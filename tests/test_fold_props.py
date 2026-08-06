"""Property tests over random legal play: money conservation, caps,
fold/step commutation, reservation integrity, payment self-enforcement."""
from hypothesis import given, settings, strategies as st

from ledger.core import fold as fold_mod
from ledger.core.events import deserialize_events, serialize_events
from ledger.game import Game
from ledger.policies.scripted import RandomLegal, run_episode
from ledger.scenarios.generate import generate
from tests.conftest import assert_state_invariants


def _random_episode(scenario_seed: int, policy_seed: int) -> Game:
    sc = generate(scenario_seed % 4)
    return run_episode(sc, RandomLegal(policy_seed), RandomLegal(policy_seed + 1))


@given(st.integers(0, 3), st.integers(0, 10_000))
@settings(max_examples=20, deadline=None)
def test_invariants_hold_at_every_reachable_state(scenario_seed, policy_seed):
    sc = generate(scenario_seed)
    game = _random_episode(scenario_seed, policy_seed)
    # replay the episode state by state, checking every invariant row
    st_ = fold_mod.initial_state(sc)
    assert_state_invariants(st_)
    for ev in game.events:
        st_ = fold_mod.apply(st_, ev)
        assert_state_invariants(st_)
    assert st_.over == game.over


@given(st.integers(0, 3), st.integers(0, 10_000))
@settings(max_examples=15, deadline=None)
def test_fold_step_commute(scenario_seed, policy_seed):
    """fold(step(L, a)) == apply(fold(L), a) at every prefix."""
    game = _random_episode(scenario_seed, policy_seed)
    sc = game.scenario
    for k in range(len(game.events)):
        assert (fold_mod.fold(sc, game.events[: k + 1])
                == fold_mod.apply(fold_mod.fold(sc, game.events[:k]),
                                  game.events[k]))


@given(st.integers(0, 3), st.integers(0, 10_000))
@settings(max_examples=10, deadline=None)
def test_canonical_serialization_roundtrip(scenario_seed, policy_seed):
    game = _random_episode(scenario_seed, policy_seed)
    s = serialize_events(game.events)
    events2 = deserialize_events(s)
    assert tuple(game.events) == events2
    assert fold_mod.fold(game.scenario, events2) == game.state


@given(st.integers(0, 3), st.integers(0, 10_000))
@settings(max_examples=15, deadline=None)
def test_scheduled_payments_always_execute_or_die_with_their_contract(
        scenario_seed, policy_seed):
    """§6.1: the only breach in the world is RENEGE.  At episode end every
    scheduled payment is either executed, or cancelled by an explicit
    renege/cancel/default of its contract — never silently skipped."""
    game = _random_episode(scenario_seed, policy_seed)
    st_ = game.state
    defaulted = {d["cid"] for d in st_.defaults}
    for c in st_.contracts.values():
        if c.accept_tick is None:
            continue   # never locked: pays never bound
        for p in c.pay:
            assert p.executed or p.cancelled
            if p.cancelled:
                assert (c.status in ("cancelled", "reneged")
                        or c.cid in defaulted)
            if c.status == "locked" and c.cid not in defaulted:
                assert p.executed


@given(st.integers(0, 3), st.integers(0, 10_000))
@settings(max_examples=8, deadline=None)
def test_episode_always_terminates_and_result_computes(scenario_seed, policy_seed):
    game = _random_episode(scenario_seed, policy_seed)
    assert game.over
    res = game.result
    assert res["final_tick"] <= game.scenario.D
    assert isinstance(res["pi"], tuple)
