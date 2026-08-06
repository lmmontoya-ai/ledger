"""Welfare: exact enumeration, tick accounting, welfare ordering."""
from hypothesis import given, settings, strategies as st

from ledger.core.scenario import Scenario
from ledger.core.welfare import d_i, integrative_gap, solo_best, w_eq, w_star
from ledger.scenarios.generate import generate
from tests.conftest import simple_scenario, worked_scenario


def test_w_star_exact_on_hand_scenario():
    # two jobs, one agent much better at each, generous budget
    sc = simple_scenario(
        K=2, c=((10, 30), (30, 10)), v=((20, 20), (20, 20)),
        prereqs=((), ()), B=20, kappa=(1, 1), u=(10, 10))
    # best: job1 -> P1 (10), job2 -> P2 (10), total value 80
    assert w_star(sc) == 80


def test_w_star_respects_budget_and_capacity():
    sc = simple_scenario(
        K=3, c=((10, 10, 10), (10, 10, 10)), v=((30, 30, 30), (0, 0, 0)),
        prereqs=((), (), ()), B=20, kappa=(1, 1), u=(10, 10))
    # budget 20 funds two jobs; capacity 1+1 allows two: 60, not 90
    assert w_star(sc) == 60


def test_w_star_chain_closure():
    sc = simple_scenario(
        K=2, c=((10, 10), (10, 10)), v=((0, 40), (0, 0)),
        prereqs=((), (1,)), B=15, kappa=(2, 2), u=(15, 15))
    # job2 needs job1; budget only funds one job: neither 2-alone nor both fit
    assert w_star(sc) == 0


def test_welfare_ordering_w_star_ge_w_eq(generated_scenarios):
    for sc in generated_scenarios:
        assert w_star(sc) >= w_eq(sc)


def test_d_i_monotone_in_budget(generated_scenarios):
    for sc in generated_scenarios:
        for seat in (1, 2):
            caps = [10, 25, 50, 100]
            vals = [d_i(sc, seat, c) for c in caps]
            assert vals == sorted(vals), "d_i must be nondecreasing in budget"


def test_tick_accounting_binds_self_funded_jobs():
    """A residual plan with k self-funded jobs is infeasible with fewer than
    2k remaining moves (§6.3, §13)."""
    sc = simple_scenario(K=2, c=((10, 10), (10, 10)), v=((30, 30), (0, 0)),
                         prereqs=((), ()), B=100, kappa=(2, 2), u=(100, 100))
    both = solo_best(sc, 1, budget_cap=100, pot_cap=100, slots=2, moves=4,
                     candidates=[1, 2])
    one = solo_best(sc, 1, budget_cap=100, pot_cap=100, slots=2, moves=3,
                    candidates=[1, 2])
    zero = solo_best(sc, 1, budget_cap=100, pot_cap=100, slots=2, moves=1,
                     candidates=[1, 2])
    assert both == 60      # 2 self-funded jobs need 4 moves
    assert one == 30       # 3 moves allow only one draw+execute
    assert zero == 0       # 1 move allows none


@given(st.integers(min_value=1, max_value=4), st.integers(min_value=0, max_value=8))
@settings(max_examples=30, deadline=None)
def test_tick_accounting_property(k, moves):
    """k identical self-funded jobs are feasible iff moves >= 2k (slots and
    budget permitting)."""
    sc = simple_scenario(
        K=4, c=((10,) * 4, (10,) * 4), v=((10,) * 4, (0,) * 4),
        prereqs=((), (), (), ()), B=100, kappa=(4, 4), u=(100, 100))
    best = solo_best(sc, 1, budget_cap=100, pot_cap=100, slots=k, moves=moves,
                     candidates=[1, 2, 3, 4])
    assert best == 10 * min(k, moves // 2, 4)


def test_locked_funded_jobs_cost_one_move():
    sc = simple_scenario(K=2, c=((10, 10), (10, 10)), v=((30, 30), (0, 0)),
                         prereqs=((), ()), B=100, kappa=(2, 2), u=(100, 100))
    # optional-funded jobs cost one move each: 2 moves suffice for both
    both = solo_best(sc, 1, budget_cap=0, pot_cap=0, slots=2, moves=2,
                     candidates=[1, 2], optional_funded={1, 2})
    assert both == 60


def test_integrative_gap_admitted(admitted_scenarios):
    for sc in admitted_scenarios:
        num, den = integrative_gap(sc)
        assert 4 * num >= den   # G >= 0.25 on every admitted scenario


def test_worked_scenario_welfare_sane():
    sc = worked_scenario()
    assert w_star(sc) > 0
    assert w_star(sc) >= w_eq(sc)
