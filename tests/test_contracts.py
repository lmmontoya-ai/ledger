"""Contract lifecycle per §5: instant lock with atomic reservation, the
cooling-off window, reneging, offer expiry, payment-tick validation,
funding-rights exclusivity, and overfunding."""
import pytest

from ledger.core.events import Action
from ledger.game import Game, IllegalAction
from tests.conftest import assert_state_invariants, simple_scenario


def _offer(assign, fund, pay=None, expires=6):
    return {"assign": {str(j): s for j, s in assign.items()},
            "fund": {str(j): a for j, a in fund.items()},
            "pay": pay or [], "expires": expires}


def _locked_game(fund_1=10, fund_2=10, pay=None, expires=6):
    """t1: P1 proposes job1->P1, job2->P2; t2: P2 accepts."""
    g = Game(simple_scenario())
    g.play(Action("PROPOSE", {"contract": _offer({1: 1, 2: 2},
                                                 {1: fund_1, 2: fund_2},
                                                 pay=pay, expires=expires)}))
    g.play(Action("ACCEPT", {"offer_id": 1}))
    return g


def test_accept_locks_and_reserves_atomically():
    g = _locked_game()
    st = g.state
    c = st.contracts[1]
    assert c.status == "locked" and c.accept_tick == 2
    assert st.reserved == 20 and st.pot_left == 80
    assert_state_invariants(st)


def test_cancel_only_in_window_and_pays_epsilon():
    g = _locked_game()
    # window is t3-t4; cancel at t3 by P1
    g.play(Action("CANCEL", {"contract_id": 1}))
    st = g.state
    assert st.contracts[1].status == "cancelled"
    assert st.pot_left == 100 and st.reserved == 0     # full refund
    assert st.accounts == [-1, 1]                       # epsilon to the partner
    assert_state_invariants(st)


def test_cancel_after_window_is_illegal_and_double_cancel_is_illegal():
    g = _locked_game()
    g.play(Action("WAIT"))   # t3
    g.play(Action("WAIT"))   # t4, window closes at end of t4
    with pytest.raises(IllegalAction):
        g.play(Action("CANCEL", {"contract_id": 1}))   # t5
    g.play(Action("RENEGE", {"contract_id": 1}))       # t5: legal now
    with pytest.raises(IllegalAction):                  # t6: not locked any more
        g.play(Action("CANCEL", {"contract_id": 1}))


def test_renege_is_illegal_during_the_window():
    g = _locked_game()
    with pytest.raises(IllegalAction):
        g.play(Action("RENEGE", {"contract_id": 1}))   # t3, window open


def test_renege_friction_and_penalty_arithmetic():
    # P2 reneges at t5: its own job2 allocation 10 -> refund 10 - ceil(10/4) = 7
    g = _locked_game()
    g.play(Action("WAIT"))   # t3 P1
    g.play(Action("WAIT"))   # t4 P2
    g.play(Action("WAIT"))   # t5 P1
    g.play(Action("RENEGE", {"contract_id": 1}))       # t6 P2
    st = g.state
    c = st.contracts[1]
    assert c.status == "reneged" and c.reneged_by == 2
    assert st.destroyed == 3                        # ceil(10/4)
    assert st.pot_left == 80 + 7                    # refund minus friction
    assert st.reserved == 10                        # P1's optional job1 stays funded
    assert st.accounts == [3, -6]                   # p=6: half to the victim
    assert_state_invariants(st)
    # victim may still execute its optional funded job
    g.play(Action("EXECUTE", {"job": 1}))           # t7 P1
    assert 1 in g.state.done
    # the reneger's cancelled obligation cannot be executed
    with pytest.raises(IllegalAction):
        g.play(Action("EXECUTE", {"job": 2}))       # t8 P2


def test_renege_cancels_scheduled_payments_both_directions():
    pay = [{"from": 1, "to": 2, "amount": 5, "tick": 20},
           {"from": 2, "to": 1, "amount": 3, "tick": 21}]
    g = _locked_game(pay=pay)
    g.play(Action("WAIT")); g.play(Action("WAIT")); g.play(Action("WAIT"))
    g.play(Action("RENEGE", {"contract_id": 1}))
    c = g.state.contracts[1]
    assert all(p.cancelled for p in c.pay)
    # run to the end: cancelled payments never execute
    while not g.over:
        g.play(Action("WAIT"))
    assert all(not p.executed for p in c.pay)


def test_scheduled_payment_executes_at_its_tick():
    pay = [{"from": 1, "to": 2, "amount": 5, "tick": 6}]
    g = _locked_game(pay=pay)
    g.play(Action("WAIT"))  # t3
    g.play(Action("WAIT"))  # t4
    g.play(Action("WAIT"))  # t5
    assert not g.state.contracts[1].pay[0].executed
    g.play(Action("WAIT"))  # t6: due now
    p = g.state.contracts[1].pay[0]
    assert p.executed and p.executed_tick == 6
    assert g.state.accounts == [-5, 5]


def test_accept_illegal_if_payment_tick_not_strictly_future():
    g = Game(simple_scenario())
    pay = [{"from": 1, "to": 2, "amount": 5, "tick": 2}]
    g.play(Action("PROPOSE", {"contract": _offer({1: 1}, {1: 10}, pay=pay)}))
    with pytest.raises(IllegalAction, match="strictly after"):
        g.play(Action("ACCEPT", {"offer_id": 1}))   # t2: pay tick 2 not > 2


def test_propose_validates_expiry_and_payment_ticks():
    g = Game(simple_scenario())
    with pytest.raises(IllegalAction, match="expiry"):
        g.play(Action("PROPOSE", {"contract": _offer({1: 1}, {1: 10}, expires=1)}))
    with pytest.raises(IllegalAction, match="expiry"):
        g.play(Action("PROPOSE", {"contract": _offer({1: 1}, {1: 10}, expires=25)}))
    with pytest.raises(IllegalAction, match="payment turn"):
        g.play(Action("PROPOSE", {"contract": _offer(
            {1: 1}, {1: 10}, pay=[{"from": 1, "to": 2, "amount": 5, "tick": 25}])}))
    with pytest.raises(IllegalAction, match="below seat"):
        g.play(Action("PROPOSE", {"contract": _offer({1: 1}, {1: 9})}))


def test_offer_expires_at_end_of_its_tick():
    g = Game(simple_scenario())
    g.play(Action("PROPOSE", {"contract": _offer({1: 1}, {1: 10}, expires=3)}))
    g.play(Action("WAIT"))  # t2
    g.play(Action("WAIT"))  # t3: lapses at the END of t3
    assert g.state.contracts[1].status == "expired"
    with pytest.raises(IllegalAction):
        g.play(Action("ACCEPT", {"offer_id": 1}))


def test_accept_at_expiry_tick_is_still_legal():
    g = Game(simple_scenario())
    g.play(Action("PROPOSE", {"contract": _offer({1: 1}, {1: 10}, expires=2)}))
    g.play(Action("ACCEPT", {"offer_id": 1}))
    assert g.state.contracts[1].status == "locked"


def test_reject_and_counter_party_rules():
    g = Game(simple_scenario())
    g.play(Action("PROPOSE", {"contract": _offer({1: 1}, {1: 10})}))
    # proposer cannot accept or reject its own offer
    g.play(Action("WAIT"))  # t2 P2
    with pytest.raises(IllegalAction):
        g.play(Action("ACCEPT", {"offer_id": 1}))   # t3 P1 = proposer
    with pytest.raises(IllegalAction):
        g.play(Action("REJECT", {"offer_id": 1}))
    # proposer CAN counter its own live offer (revision)
    g.play(Action("COUNTER", {"offer_id": 1,
                              "contract": _offer({1: 1}, {1: 12}, expires=8)}))
    assert g.state.contracts[1].status == "countered"
    assert g.state.contracts[2].fund[1] == 12
    # respondent rejects the revision
    g.play(Action("REJECT", {"offer_id": 2}))
    assert g.state.contracts[2].status == "rejected"


def test_funding_rights_are_exclusive():
    g = _locked_game()
    # job 2 is locked to P2: P1 cannot execute it with P2's allocation
    with pytest.raises(IllegalAction):
        g.play(Action("EXECUTE", {"job": 2}))   # t3 P1
    # and nobody can DRAW on a job with live locked funding
    with pytest.raises(IllegalAction, match="live locked funding"):
        g.play(Action("DRAW", {"amount": 10, "job": 1}))


def test_no_double_draw_and_draw_must_equal_cost():
    g = Game(simple_scenario())
    g.play(Action("DRAW", {"amount": 10, "job": 1}))   # t1 P1, c1(1)=10
    g.play(Action("WAIT"))
    with pytest.raises(IllegalAction, match="exactly"):
        g.play(Action("DRAW", {"amount": 9, "job": 2}))
    with pytest.raises(IllegalAction, match="draw-funded"):
        g.play(Action("DRAW", {"amount": 10, "job": 1}))
    # partner cannot execute a job draw-funded by the other seat
    g.play(Action("WAIT"))  # move to P2? t3 is P1 (the failed plays did not advance)
    with pytest.raises(IllegalAction):
        g.play(Action("EXECUTE", {"job": 1}))   # t4 P2: P1's draw, not P2's


def test_draw_cap_binds():
    g = Game(simple_scenario())
    g.play(Action("DRAW", {"amount": 10, "job": 1}))   # draws 10/25
    g.play(Action("WAIT"))
    g.play(Action("DRAW", {"amount": 12, "job": 2}))   # draws 22/25
    g.play(Action("WAIT"))
    with pytest.raises(IllegalAction, match="cap"):
        g.play(Action("DRAW", {"amount": 20, "job": 3}))  # 42 > 25


def test_overfunding_excess_returns_at_execution_and_locks_meanwhile():
    g = _locked_game(fund_1=18, fund_2=10)     # job1 cost 10, funded 18
    st = g.state
    assert st.pot_left == 72                    # excess locked while live
    g.play(Action("EXECUTE", {"job": 1}))       # t3 P1
    st = g.state
    assert st.pot_left == 80                    # excess 8 returned to the pot
    assert st.spent == 10 and st.reserved == 10
    assert st.destroyed == 0                    # overfunding never burns
    assert_state_invariants(st)


def test_double_spend_impossible():
    g = _locked_game()
    g.play(Action("EXECUTE", {"job": 1}))
    g.play(Action("WAIT"))
    with pytest.raises(IllegalAction, match="already done"):
        g.play(Action("EXECUTE", {"job": 1}))


def test_accept_conflict_checks():
    g = Game(simple_scenario())
    g.play(Action("PROPOSE", {"contract": _offer({1: 1}, {1: 10})}))
    g.play(Action("ACCEPT", {"offer_id": 1}))
    g.play(Action("PROPOSE", {"contract": _offer({1: 2}, {1: 11}, expires=8)}))
    with pytest.raises(IllegalAction, match="already assigned"):
        g.play(Action("ACCEPT", {"offer_id": 2}))   # job1 already under C1


def test_accept_schedule_simulation_gates_late_overload():
    # near the deadline one seat cannot execute two jobs in one remaining move
    sc = simple_scenario(D=6)
    g = Game(sc)
    for _ in range(2):
        g.play(Action("WAIT"))
    g.play(Action("PROPOSE", {"contract": _offer({1: 1, 2: 1}, {1: 10, 2: 12},
                                                 expires=5)}))   # t3
    with pytest.raises(IllegalAction, match="unschedulable"):
        g.play(Action("ACCEPT", {"offer_id": 1}))   # t4: P1 moves only at t5
    # accepting at the final tick leaves no tick to execute: the sim rejects it
    g.play(Action("WAIT"))                           # t4
    g.play(Action("PROPOSE", {"contract": _offer({1: 1}, {1: 10}, expires=6)}))  # t5
    with pytest.raises(IllegalAction, match="unschedulable"):
        g.play(Action("ACCEPT", {"offer_id": 2}))    # t6 = D


def test_chain_prereq_enforced():
    g = Game(simple_scenario())
    g.play(Action("DRAW", {"amount": 20, "job": 3}))   # job3 needs job1
    g.play(Action("WAIT"))
    with pytest.raises(IllegalAction, match="needs job 1"):
        g.play(Action("EXECUTE", {"job": 3}))
