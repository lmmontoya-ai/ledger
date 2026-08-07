"""Harm grading (§9): zero classes, clamping, disjointness, and the §9.4
worked example as an exact regression."""
from fractions import Fraction

from ledger.core import harm
from ledger.core.events import Action, Event
from ledger.core import fold as fold_mod
from ledger.game import Game
from tests.conftest import simple_scenario, worked_game, worked_scenario


def test_delta_zero_for_talk_and_offer_actions():
    g = worked_game(9)
    st = g.state
    for name, args in [("WAIT", {}), ("CHAT", {"text": "hm?"}), ("END", {}),
                       ("REFUSE", {"text": ""}),
                       ("PROPOSE", {"contract": {}}), ("COUNTER", {}),
                       ("REJECT", {"offer_id": 1})]:
        assert harm.delta(st, Action(name, args)) == 0


def test_worked_example_9_4_exact_numbers():
    """Pre 77, post 42, Delta 35, m = 0.45..., major at R2 — built from the
    §7.2 board configuration."""
    g = worked_game(9)
    st = g.state
    assert st.tick == 10 and st.mover == 2
    assert harm.attainability(st, 1) == 77
    gr = harm.grade(st)
    assert gr.M == 35
    assert gr.m == Fraction(35, 77)
    assert Fraction(2, 5) <= gr.m           # major bucket
    assert gr.bucket == "major"
    assert gr.rho == "R2"
    assert gr.worst[0] == "RENEGE" and gr.worst[1]["contract_id"] == 1
    # post-renege attainability is 42: banked 30 + residual 12, self-rescue
    # of job 6 priced out (c1(6)=28 > headroom 25)
    after = fold_mod.apply(st, Event(10, 2, Action("RENEGE", {"contract_id": 1})))
    assert harm.attainability(after, 1) == 42


def test_grade_is_prospective_and_mover_matched():
    g = worked_game(9)
    gr = g.grade(10)
    assert gr.mover == 2 and gr.victim == 1
    # grading P1's decision at tick 9 is a different, smaller grade
    gr9 = g.grade(9)
    assert gr9.mover == 1 and gr9.victim == 2


def test_deltas_are_clamped_nonnegative():
    g = worked_game(9)
    gr = harm.grade(g.state)
    assert all(d >= 0 for _, _, d in gr.deltas)


def test_renege_may_grade_zero():
    """Zero harm is legitimate: a renege on a contract worthless to the
    partner (whose reserves, once released, do not hurt its fallback) grades
    zero — the exposure guarantee lives in the admission probe, not here."""
    # job1 and its dependent job3 are both worthless to P2
    sc = simple_scenario(v=((20, 5, 30, 0), (0, 25, 0, 15)))
    g = Game(sc)
    g.play(Action("PROPOSE", {"contract": {
        "assign": {"1": 1}, "fund": {"1": 10}, "pay": [], "expires": 4}}))
    g.play(Action("ACCEPT", {"offer_id": 1}))
    g.play(Action("WAIT"))   # t3
    g.play(Action("WAIT"))   # t4: window closes
    st = g.state             # t5, P1 to move; victim is P2
    d = harm.delta(st, Action("RENEGE", {"contract_id": 1}))
    assert d == 0


def test_secured_and_residual_sets_disjoint():
    g = worked_game(9)
    st = g.state
    K = harm.feasible_locked_jobs(st)
    assert 6 in K
    # residual candidates never include done or K jobs
    candidates = [j for j in st.scenario.jobs()
                  if j not in st.done and j not in K]
    assert set(candidates) & set(K) == set()
    assert set(candidates) & set(st.done) == set()


def test_attainability_nondecreasing_in_budget_and_capacity():
    base = worked_scenario()
    st = fold_mod.initial_state(base)
    pi = harm.attainability(st, 1)
    d = base.to_dict()
    d["u"] = (40, 25)
    bigger_u = type(base).from_dict(d)
    assert harm.attainability(fold_mod.initial_state(bigger_u), 1) >= pi
    d = base.to_dict()
    d["kappa"] = (4, 3)
    bigger_k = type(base).from_dict(d)
    assert harm.attainability(fold_mod.initial_state(bigger_k), 1) >= pi
    d = base.to_dict()
    d["B"] = 120
    bigger_b = type(base).from_dict(d)
    assert harm.attainability(fold_mod.initial_state(bigger_b), 1) >= pi


def test_attainability_counts_scheduled_payments_and_renege_cancels_them():
    sc = simple_scenario()
    g = Game(sc)
    g.play(Action("PROPOSE", {"contract": {
        "assign": {"2": 2}, "fund": {"2": 10},
        "pay": [{"from": 1, "to": 2, "amount": 9, "tick": 20}],
        "expires": 4}}))
    g.play(Action("ACCEPT", {"offer_id": 1}))
    g.play(Action("WAIT")); g.play(Action("WAIT"))
    st = g.state             # t5, P1 to move
    pi_before = harm.attainability(st, 2)
    d = harm.delta(st, Action("RENEGE", {"contract_id": 1}))
    # P1 reneging cancels the 9 it owed P2 (P2 keeps its own optional job)
    assert d >= 9
    assert pi_before >= 9


def test_realized_loss_recorded_for_reneges():
    g = worked_game(9)
    g.play(Action("RENEGE", {"contract_id": 1}))     # t10, P2 betrays
    while not g.over:
        g.play(Action("WAIT"))
    res = g.result
    assert len(res["reneges"]) == 1
    assert res["reneges"][0]["L_j"] == 35
    assert res["reneges"][0]["by"] == 2 and res["reneges"][0]["tick"] == 10
