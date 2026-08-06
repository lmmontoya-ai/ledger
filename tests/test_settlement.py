"""End settlement per §5.4/§5.6: snapshot-batched simultaneous defaults at
p_def = 8, payment cancellation ordering, order-independence, destruction."""
import copy
import itertools

import pytest

from ledger.core import fold as fold_mod
from ledger.core.events import Action, Event
from ledger.game import Game
from tests.conftest import assert_state_invariants, simple_scenario


def _offer(assign, fund, pay=None, expires=6):
    return {"assign": {str(j): s for j, s in assign.items()},
            "fund": {str(j): a for j, a in fund.items()},
            "pay": pay or [], "expires": expires}


def _stalled_game(pay=None):
    """Locked contract job1->P1 (f10), job2->P2 (f10); nobody executes; both
    stall to mutual END."""
    g = Game(simple_scenario())
    g.play(Action("PROPOSE", {"contract": _offer({1: 1, 2: 2}, {1: 10, 2: 10},
                                                 pay=pay)}))
    g.play(Action("ACCEPT", {"offer_id": 1}))
    g.play(Action("WAIT"))
    g.play(Action("WAIT"))
    g.play(Action("END"))
    g.play(Action("END"))
    return g


def test_mutual_default_fires_simultaneously_with_p_def():
    g = _stalled_game()
    st = g.state
    assert st.over and st.settled and st.ended_by_mutual
    assert len(st.defaults) == 2
    assert {d["by"] for d in st.defaults} == {1, 2}
    # each pays 8, each receives 8//2 = 4: net -4 each
    assert st.accounts == [-4, -4]
    # friction on each cancelled allocation of 10: ceil(10/4) = 3 destroyed
    # then the whole pot is destroyed
    assert st.pot_left == 0 and st.reserved == 0
    assert st.destroyed == 100
    assert_state_invariants(st)
    assert g.result["pi"] == (-4, -4)


def test_default_penalty_exceeds_renege_penalty():
    sc = simple_scenario()
    assert sc.p_def == sc.p + 2


def test_defaulted_contract_payments_cancel_but_survivors_execute():
    # C1 will default (job never executed) and carries a final-tick payment;
    # C2 is fully executed and carries a final-tick payment: only C2's fires.
    g = Game(simple_scenario())
    g.play(Action("PROPOSE", {"contract": _offer(
        {1: 1}, {1: 10}, pay=[{"from": 2, "to": 1, "amount": 7, "tick": 24}])}))
    g.play(Action("ACCEPT", {"offer_id": 1}))
    g.play(Action("PROPOSE", {"contract": _offer(
        {2: 2}, {2: 10}, pay=[{"from": 1, "to": 2, "amount": 3, "tick": 24}],
        expires=8)}))
    g.play(Action("ACCEPT", {"offer_id": 2}))     # t4 P2... offer_id 2 proposed by P1 at t3
    g.play(Action("WAIT"))                        # t5
    g.play(Action("EXECUTE", {"job": 2}))         # t6 P2 completes C2
    while not g.over:
        g.play(Action("WAIT"))
    st = g.state
    c1, c2 = st.contracts[1], st.contracts[2]
    assert not c1.pay[0].executed and c1.pay[0].cancelled
    assert c2.pay[0].executed and not c2.pay[0].cancelled
    assert len(st.defaults) == 1 and st.defaults[0]["by"] == 1
    # P1: -8 penalty, -3 payment; P2: +4 compensation, +3 payment
    assert st.accounts == [-11, 7]
    assert_state_invariants(st)


def test_settlement_is_order_independent():
    """Permuting the settlement processing order never changes who defaults
    or what anyone is paid (§13)."""
    g = Game(simple_scenario())
    g.play(Action("PROPOSE", {"contract": _offer(
        {1: 1}, {1: 12}, pay=[{"from": 1, "to": 2, "amount": 2, "tick": 20}])}))
    g.play(Action("ACCEPT", {"offer_id": 1}))
    g.play(Action("PROPOSE", {"contract": _offer(
        {2: 2, 3: 1}, {2: 10, 3: 21},
        pay=[{"from": 2, "to": 1, "amount": 5, "tick": 24}], expires=8)}))
    g.play(Action("ACCEPT", {"offer_id": 2}))
    for _ in range(19):
        g.play(Action("WAIT"))
    pre = fold_mod.fold(g.scenario, g.events)      # state at tick 24
    assert pre.tick == 24 and not pre.over
    final_ev = Event(24, pre.mover, Action("WAIT"))

    outcomes = []
    orders = [None,
              (lambda x: tuple(reversed(str(x)))),
              (lambda x: hash((str(x), 1))),
              (lambda x: hash((str(x), 2)))]
    for key in orders:
        st = fold_mod.apply(copy.deepcopy(pre), final_ev, _settle_order_key=key)
        outcomes.append((tuple(st.accounts), st.destroyed, st.spent,
                         tuple(sorted((d["cid"], d["by"]) for d in st.defaults)),
                         tuple(sorted((c.cid, p.amount, p.executed, p.cancelled)
                                      for c in st.contracts.values() for p in c.pay))))
    assert len(set(outcomes)) == 1
    assert_state_invariants(st)


def test_early_mutual_end_settles_everything():
    # a live locked contract with a payment scheduled after the early end:
    # the §6.1 invariant says a scheduled payment under a live contract
    # always executes — at settlement if the episode ends first.
    g = Game(simple_scenario())
    g.play(Action("PROPOSE", {"contract": _offer(
        {1: 1}, {1: 10}, pay=[{"from": 2, "to": 1, "amount": 4, "tick": 20}])}))
    g.play(Action("ACCEPT", {"offer_id": 1}))
    g.play(Action("EXECUTE", {"job": 1}))          # t3: contract complete
    g.play(Action("END"))                          # t4 P2
    g.play(Action("END"))                          # t5 P1 -> mutual end
    st = g.state
    assert st.over and st.final_tick == 5
    p = st.contracts[1].pay[0]
    assert p.executed                              # survived, executed at settlement
    assert st.accounts == [4, -4]
    assert st.defaults == []
    assert st.destroyed == 90                      # unspent pot destroyed
    assert_state_invariants(st)


def test_deadline_destroys_pot_and_reserves():
    g = Game(simple_scenario())
    while not g.over:
        g.play(Action("WAIT"))
    st = g.state
    assert st.destroyed == 100 and st.pot_left == 0
    assert_state_invariants(st)
