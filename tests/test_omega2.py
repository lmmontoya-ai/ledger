"""Omega_2 refinement (EXPERIMENT_PLAN §3.3): the frozen 37-outcome
vocabulary, the division metric, beneficiary buckets, renege harm buckets,
draw headroom, the strict-highest EXECUTE rule, and legal-alphabet smoothing."""
import pytest

from ledger.analysis.omega2 import (OMEGA2_VOCABULARY, legal_omega2_alphabet,
                                    refine)
from ledger.analysis.stats import smoothed
from ledger.core import harm
from ledger.core.events import Action
from ledger.game import Game
from tests.conftest import simple_scenario, worked_game


def _offer(assign, fund, pay=None, expires=8):
    return {"assign": {str(j): s for j, s in assign.items()},
            "fund": {str(j): a for j, a in fund.items()},
            "pay": pay or [], "expires": expires}


def _propose(assign, fund, pay=None, expires=8):
    return Action("PROPOSE", {"contract": _offer(assign, fund, pay, expires)})


def test_vocabulary_counts_exactly_36():
    assert len(OMEGA2_VOCABULARY) == 36
    assert len(set(OMEGA2_VOCABULARY)) == 36
    # the §3.3 arithmetic: 5 + 10 + 3*3 + 3 + 2 + 2 + 5
    by_label = {}
    for t in OMEGA2_VOCABULARY:
        by_label.setdefault(t.split(":", 1)[0], []).append(t)
    assert len(by_label["PROPOSE"]) == 5
    assert len(by_label["COUNTER"]) == 10
    for lbl in ("ACCEPT", "REJECT", "CANCEL"):
        assert len(by_label[lbl]) == 3
    assert len(by_label["RENEGE"]) == 3
    assert len(by_label["DRAW"]) == 2
    assert len(by_label["EXECUTE"]) == 2
    for lbl in ("TRANSFER", "CHAT", "WAIT", "END", "REFUSE"):
        assert by_label[lbl] == [lbl]
    assert "QUERY" not in by_label and "INFORM" not in by_label


# ---------------------------------------------------------------------------
# division metric on known contracts (v1 = (20,5,30,0), v2 = (5,25,10,15))
# ---------------------------------------------------------------------------

def test_propose_division_buckets():
    g = Game(simple_scenario())
    st = g.state   # P1 to move
    # job1: dpi = (20, 5), s = 0.8 -> self-favoring
    assert refine(st, _propose({1: 1}, {1: 10})) == "PROPOSE:self-favoring"
    # job2: dpi = (5, 25), s = 1/6 -> other-favoring
    assert refine(st, _propose({2: 2}, {2: 10})) == "PROPOSE:other-favoring"
    # job1 plus pay 7 to the partner: dpi = (13, 12), s = 13/25 = 0.52
    assert refine(st, _propose({1: 1}, {1: 10},
                               pay=[{"from": 1, "to": 2, "amount": 7, "tick": 20}])
                  ) == "PROPOSE:balanced"
    # a pure payment draft moves money without creating value: sum = 0
    assert refine(st, Action("PROPOSE", {"contract": {
        "assign": {}, "fund": {},
        "pay": [{"from": 1, "to": 2, "amount": 5, "tick": 20}],
        "expires": 8}})) == "PROPOSE:value-destroying"


def test_propose_degenerate_buckets_in_plan_order():
    # value-destroying checked before unilateral: a job worth zero to both
    sc = simple_scenario(v=((20, 5, 30, 0), (5, 25, 10, 0)))
    g = Game(sc)
    assert refine(g.state, _propose({4: 1}, {4: 14})) == "PROPOSE:value-destroying"
    # touches only one party's payoff -> unilateral
    sc = simple_scenario(v=((20, 5, 30, 0), (0, 25, 10, 15)))
    g = Game(sc)
    assert refine(g.state, _propose({1: 1}, {1: 10})) == "PROPOSE:unilateral"


def test_counter_revision_vs_counteroffer():
    g = Game(simple_scenario())
    g.play(_propose({1: 1}, {1: 10}))           # t1: P1 proposes C1
    g.play(Action("WAIT"))                       # t2: P2 waits
    counter = Action("COUNTER", {"offer_id": 1,
                                 "contract": _offer({2: 2}, {2: 10})})
    # P1 countering its own live offer is a revision
    assert refine(g.state, counter) == "COUNTER:revision:other-favoring"
    g.play(counter)                              # t3: C1 -> C2, proposer P1
    # P2 countering the partner's offer is a counteroffer
    # the division token is the ACTOR's share of the NEW draft: job1 gives
    # the countering P2 only 5 of 25 -> other-favoring
    counter2 = Action("COUNTER", {"offer_id": 2,
                                  "contract": _offer({1: 1}, {1: 10})})
    assert refine(g.state, counter2) == "COUNTER:counteroffer:other-favoring"
    # a counteroffer draft favoring the counter-proposer reads self-favoring
    counter3 = Action("COUNTER", {"offer_id": 2,
                                  "contract": _offer({2: 2}, {2: 10})})
    assert refine(g.state, counter3) == "COUNTER:counteroffer:self-favoring"


def test_accept_reject_cancel_beneficiary_buckets():
    g = Game(simple_scenario())
    g.play(_propose({2: 2}, {2: 10}))            # C1: dpi = (5, 25)
    # P2 accepting: s_actor = 25/30 > 0.55 -> favorable
    assert refine(g.state, Action("ACCEPT", {"offer_id": 1})) == "ACCEPT:favorable"
    g.play(Action("REJECT", {"offer_id": 1}))    # t2
    g.play(_propose({1: 1}, {1: 10}))            # t3, C2: dpi = (20, 5)
    # P2 rejecting: s_actor = 5/25 < 0.45 -> unfavorable
    assert refine(g.state, Action("REJECT", {"offer_id": 2})) == "REJECT:unfavorable"
    g.play(Action("REJECT", {"offer_id": 2}))    # t4
    g.play(_propose({1: 1, 2: 2}, {1: 10, 2: 10}))   # t5, C3: dpi = (25, 30)
    # P2 accepting: s_actor = 30/55 = 0.545 -> balanced
    assert refine(g.state, Action("ACCEPT", {"offer_id": 3})) == "ACCEPT:balanced"
    g.play(Action("ACCEPT", {"offer_id": 3}))    # t6: locked, window t7-t8
    # P1 cancelling a balanced contract: balanced (s_actor = 25/55 in band)
    assert refine(g.state, Action("CANCEL", {"contract_id": 3})) == "CANCEL:balanced"


def test_degenerate_referenced_draft_classified_by_actor_sign():
    g = Game(simple_scenario())
    pay = [{"from": 1, "to": 2, "amount": 5, "tick": 20}]
    g.play(Action("PROPOSE", {"contract": {
        "assign": {}, "fund": {}, "pay": pay, "expires": 8}}))   # sum dpi = 0
    # actor P2 gains 5 -> favorable, despite the degenerate total
    assert refine(g.state, Action("ACCEPT", {"offer_id": 1})) == "ACCEPT:favorable"
    g.play(Action("ACCEPT", {"offer_id": 1}))
    # actor P1 pays 5 -> unfavorable
    assert refine(g.state, Action("CANCEL", {"contract_id": 1})) == "CANCEL:unfavorable"


# ---------------------------------------------------------------------------
# executive refinements
# ---------------------------------------------------------------------------

def test_draw_small_vs_large_headroom():
    g = Game(simple_scenario())
    st = g.state
    # headroom 25: draw 10 -> 20 <= 25 -> small
    assert refine(st, Action("DRAW", {"amount": 10, "job": 1})) == "DRAW:small"
    g.play(Action("DRAW", {"amount": 10, "job": 1}))
    g.play(Action("WAIT"))
    # headroom now 15: draw 12 -> 24 > 15 -> large
    assert refine(g.state, Action("DRAW", {"amount": 12, "job": 2})) == "DRAW:large"


def test_execute_strict_highest_including_tie():
    g = Game(simple_scenario())          # v1 = (20, 5, ...)
    g.play(Action("DRAW", {"amount": 10, "job": 1}))
    g.play(Action("WAIT"))
    g.play(Action("DRAW", {"amount": 12, "job": 2}))
    g.play(Action("WAIT"))
    st = g.state                         # t5: P1 can execute jobs 1 and 2
    assert refine(st, Action("EXECUTE", {"job": 1})) == "EXECUTE:own-priority"
    assert refine(st, Action("EXECUTE", {"job": 2})) == "EXECUTE:other-priority"
    # a tie is NOT strictly highest -> other-priority
    g2 = Game(simple_scenario(v=((20, 20, 30, 0), (5, 25, 10, 15))))
    g2.play(Action("DRAW", {"amount": 10, "job": 1}))
    g2.play(Action("WAIT"))
    g2.play(Action("DRAW", {"amount": 12, "job": 2}))
    g2.play(Action("WAIT"))
    assert refine(g2.state, Action("EXECUTE", {"job": 1})) == "EXECUTE:other-priority"
    assert refine(g2.state, Action("EXECUTE", {"job": 2})) == "EXECUTE:other-priority"
    # sole executable job is trivially strictly highest
    g3 = Game(simple_scenario())
    g3.play(Action("DRAW", {"amount": 12, "job": 2}))
    g3.play(Action("WAIT"))
    assert refine(g3.state, Action("EXECUTE", {"job": 2})) == "EXECUTE:own-priority"


def test_renege_buckets_track_harm_grade_numbers():
    # the §9.4 exposure: m = 35/77 = 0.4545 -> major, matching the grade
    g = worked_game(9)
    st = g.state
    assert refine(st, Action("RENEGE", {"contract_id": 1})) == "RENEGE:major"
    assert harm.grade(st).bucket == "major"
    # refine over the played Event agrees with refine at the decision state
    g.play(Action("RENEGE", {"contract_id": 1}))
    assert refine(g, g.events[-1]) == "RENEGE:major"

    # a renege that cancels a 9-payment against attainability 49: m = 9/49
    # = 0.18 -> moderate
    g2 = Game(simple_scenario())
    g2.play(Action("PROPOSE", {"contract": _offer(
        {2: 2}, {2: 10}, pay=[{"from": 1, "to": 2, "amount": 9, "tick": 20}],
        expires=4)}))
    g2.play(Action("ACCEPT", {"offer_id": 1}))
    g2.play(Action("WAIT")); g2.play(Action("WAIT"))
    assert refine(g2.state, Action("RENEGE", {"contract_id": 1})) == "RENEGE:moderate"

    # a renege that costs the partner nothing grades minor (zero-loss)
    g3 = Game(simple_scenario(v=((20, 5, 30, 0), (0, 25, 0, 15))))
    g3.play(Action("PROPOSE", {"contract": _offer({1: 1}, {1: 10}, expires=4)}))
    g3.play(Action("ACCEPT", {"offer_id": 1}))
    g3.play(Action("WAIT")); g3.play(Action("WAIT"))
    assert refine(g3.state, Action("RENEGE", {"contract_id": 1})) == "RENEGE:minor"


def test_label_only_actions():
    g = Game(simple_scenario())
    st = g.state
    assert refine(st, Action("WAIT")) == "WAIT"
    assert refine(st, Action("END")) == "END"
    assert refine(st, Action("CHAT", {"text": "hm?"})) == "CHAT"
    assert refine(st, Action("REFUSE", {"text": ""})) == "REFUSE"
    assert refine(st, Action("TRANSFER", {"amount": 1, "to": 2})) == "TRANSFER"


# ---------------------------------------------------------------------------
# the decision's legal alphabet
# ---------------------------------------------------------------------------

def test_legal_alphabet_opening_state():
    g = Game(simple_scenario())
    alpha = legal_omega2_alphabet(g.state, 1)
    # PROPOSE (5) + DRAW (2) + TRANSFER/CHAT/WAIT/END/REFUSE (5)
    assert len(alpha) == 12
    assert set(a.split(":", 1)[0] for a in alpha) == {
        "PROPOSE", "DRAW", "TRANSFER", "CHAT", "WAIT", "END", "REFUSE"}
    assert set(alpha) <= set(OMEGA2_VOCABULARY)
    # vocabulary order is preserved
    idx = [OMEGA2_VOCABULARY.index(a) for a in alpha]
    assert idx == sorted(idx)


def test_legal_alphabet_with_live_offer():
    g = Game(simple_scenario())
    g.play(_propose({1: 1}, {1: 10}))
    alpha = legal_omega2_alphabet(g.state, 2)   # P2 faces the offer
    labels = {a.split(":", 1)[0] for a in alpha}
    assert {"ACCEPT", "REJECT", "COUNTER"} <= labels
    assert len(alpha) == 12 + 10 + 3 + 3        # + COUNTER + ACCEPT + REJECT
    # the proposer's own view has COUNTER (revision) but not ACCEPT/REJECT
    alpha1 = legal_omega2_alphabet(g.state, 1)
    labels1 = {a.split(":", 1)[0] for a in alpha1}
    assert "COUNTER" in labels1
    assert "ACCEPT" not in labels1 and "REJECT" not in labels1


def test_legal_alphabet_final_tick_has_no_propose():
    sc = simple_scenario(D=2)
    g = Game(sc)
    g.play(Action("WAIT"))
    alpha = legal_omega2_alphabet(g.state, 2)   # tick 2 = D
    labels = {a.split(":", 1)[0] for a in alpha}
    assert "PROPOSE" not in labels and "COUNTER" not in labels
    assert g.state.tick == sc.D


def test_smoothing_accepts_omega2_legal_alphabet():
    g = Game(simple_scenario())
    g.play(_propose({1: 1}, {1: 10}))
    alpha = legal_omega2_alphabet(g.state, 2)
    counts = {"ACCEPT:favorable": 5, "REJECT:unfavorable": 3, "WAIT": 8}
    p = smoothed(counts, alpha)
    assert abs(sum(p.values()) - 1.0) < 1e-12
    assert set(p) == set(alpha)
    with pytest.raises(ValueError):
        smoothed({"RENEGE:major": 1}, alpha)    # not legal here


def test_refined_outcomes_always_in_legal_alphabet():
    """The refinement of any legal executive action lands inside the
    decision's legal alphabet (one code path for actor and predictor)."""
    g = worked_game(9)
    st = g.state
    alpha = set(legal_omega2_alphabet(st, st.mover))
    for a in harm.legal_executive_actions(st):
        assert refine(st, a) in alpha
