"""RETUNE_PLAN §4 fixture F3: microgames with analytically known envelopes.

F3-1  dominant bargain: one plan clearly best for both, no divergence.
F3-2  the transferable-utility realignment theorem: even with two plans whose
      raw payoff vectors differ sharply, an own-optimizer extracts the
      partner's surplus down to its outside option, so own's value for every
      plan is W(plan) - solo(partner) and own ranks plans exactly as joint
      does.  Class-level trade-off divergence is impossible while transfers
      are unrestricted; the fixture pins the theorem the Gate A audit reports.
F3-3  trust divergence: an exposure-creating live offer where maximin
      (cautious) prefers the solo outside option and best-case
      (opportunistic) accepts.  Transfers do not realign this axis.
"""
from ledger.analysis.divergence import classify
from ledger.analysis.objectives import envelope
from ledger.analysis.residual import residual_solo
from ledger.core import actions as actions_mod
from ledger.core import fold as fold_mod
from ledger.core.events import Action, Event
from ledger.core.welfare import w_star
from tests.conftest import simple_scenario


def _play(st, action):
    reason = actions_mod.validate(st, st.mover, action)
    assert reason is None, reason
    return fold_mod.apply(st, Event(st.tick, st.mover, action))


def test_f3_1_dominant_bargain_is_easy():
    sc = simple_scenario(
        K=2, c=((10, 10), (99, 99)), v=((20, 15), (20, 15)),
        prereqs=((), ()), B=25, kappa=(2, 2), u=(0, 0), D=8)
    env = envelope(fold_mod.initial_state(sc))
    row = classify(env, "f3-1", sc.D)
    assert not row.tradeoff
    assert not row.trust
    assert row.mixture in ("easy", "forced")
    # both objectives settle on proposing the both-jobs bundle
    assert env.astar["own"] & env.astar["joint"]


def test_f3_2_transfer_realignment_theorem():
    # two mutually exclusive plans (the pot funds exactly one):
    # A pays seat 1 twenty points, B pays the pair (1, 30).
    sc = simple_scenario(
        K=2, c=((5, 5), (99, 99)), v=((20, 1), (0, 30)),
        prereqs=((), ()), B=5, kappa=(1, 1), u=(0, 0), D=8)
    st = fold_mod.initial_state(sc)
    env = envelope(st)
    row = classify(env, "f3-2", sc.D)
    # the raw plans differ sharply, yet own extracts B's partner surplus and
    # ranks the plans exactly as joint does: no class-level trade-off.
    assert not row.tradeoff
    own_best = max(env.q["own"].values())
    assert own_best == w_star(sc) - residual_solo(st, 2)
    assert max(env.q["joint"].values()) == w_star(sc)


def test_f3_2b_pay_cap_zero_breaks_the_realignment():
    # same board as F3-2 but transfers disabled: own can no longer extract,
    # so it strictly prefers its 20-point plan while joint prefers the
    # 31-point plan.  Class-level trade-off divergence appears.
    sc = simple_scenario(
        K=2, c=((5, 5), (99, 99)), v=((20, 1), (0, 30)),
        prereqs=((), ()), B=5, kappa=(1, 1), u=(0, 0), D=8, pay_cap=0)
    st = fold_mod.initial_state(sc)
    env = envelope(st)
    row = classify(env, "f3-2b", sc.D)
    assert row.tradeoff
    assert not (env.astar["own"] & env.astar["joint"])
    assert max(env.q["own"].values()) == 20
    assert max(env.q["joint"].values()) == 31


def test_f3_3_exposure_offer_splits_cautious_from_opportunistic():
    # seat 2 offers: seat 1 does the cheap head, seat 2 later does the tail
    # seat 1 values at 25.  Accepting burns seat 1's only slot; its outside
    # option is a solo draw worth 10.  If the partner reneges after the
    # window, seat 1 is left with the 3-point compensation.
    # the offer carries a 15-point scheduled pay toward seat 1.  Seat 1
    # cannot replicate that in a counter-proposal (the IR-compliant partner
    # would refuse a copy that pays out its own money for nothing), so
    # ACCEPT is strictly best for the best-case objective, while maximin
    # still fears the post-window renege that cancels the pay.
    sc = simple_scenario(
        K=3,
        c=((5, 99, 5), (99, 5, 99)),
        v=((0, 25, 10), (0, 0, 0)),
        prereqs=((), (1,), ()),
        B=100, kappa=(1, 2), u=(5, 0), D=10, r=1, opening=2)
    st = fold_mod.initial_state(sc)
    st = _play(st, Action("PROPOSE", {"contract": {
        "assign": {"1": 1, "2": 2}, "fund": {"1": 5, "2": 5},
        "pay": [{"from": 2, "to": 1, "amount": 15, "turn": 8}],
        "expires": 3}}))
    assert st.mover == 1
    env = envelope(st)
    row = classify(env, "f3-3", sc.D)
    assert env.exposure_live
    # opportunistic locks the offer; cautious takes the safe 10.
    assert env.astar["opportunistic"] == {"ACCEPT:favorable"}
    assert not (env.astar["cautious"] & env.astar["opportunistic"])
    assert row.trust
    # exact values: honor path 25 + 15, betrayed path 3, safe path 10
    assert env.q["opportunistic"]["ACCEPT:favorable"] == 40
    assert env.q["cautious"]["ACCEPT:favorable"] == 3
    assert max(env.q["cautious"].values()) == 10
