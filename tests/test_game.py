"""Public API (§12.3) and integration episodes under every scripted policy
pair: terminate, metrics compute, harm states occur, both seats can be victim
and exploiter."""
import itertools

import pytest

from ledger.core.events import Action
from ledger.game import Game, IllegalAction
from ledger.policies.scripted import POLICIES, run_episode
from ledger.scenarios.admit import admit
from ledger.scenarios.generate import generate
from tests.conftest import assert_state_invariants, simple_scenario, worked_game


def test_five_method_api():
    g = worked_game(9)
    assert g.turn == 2 and not g.over
    view = g.render(g.turn)
    assert isinstance(view, bytes)
    assert isinstance(g.tools, list) and len(g.tools) == 14
    g.play(Action("WAIT"))
    assert g.ledger[-1].action.name == "WAIT"
    gr = g.grade(10)
    assert gr.bucket == "major"
    assert g.replay(10)  # exact bytes shown at tick 10
    with pytest.raises(RuntimeError):
        _ = g.result     # not over yet


def test_illegal_action_raises_with_specific_reason():
    g = Game(simple_scenario())
    with pytest.raises(IllegalAction, match="needs job 1"):
        g.play(Action("DRAW", {"amount": 20, "job": 3})) or \
            g.play(Action("EXECUTE", {"job": 3}))
    with pytest.raises(IllegalAction, match="does not exist"):
        g.play(Action("ACCEPT", {"offer_id": 9}))


def test_invalid_wait_recorded_with_flag():
    g = Game(simple_scenario())
    g.play_invalid_wait()
    ev = g.events[0]
    assert ev.action.name == "WAIT" and ev.invalid


def test_dict_actions_accepted():
    g = Game(simple_scenario())
    g.play({"name": "WAIT", "args": {}})
    assert g.state.tick == 2


@pytest.fixture(scope="session")
def integration_scenario(admitted_scenarios):
    return admitted_scenarios[0]


@pytest.mark.parametrize("p1,p2", list(itertools.product(sorted(POLICIES), repeat=2)))
def test_every_policy_pair_terminates_and_scores(integration_scenario, p1, p2):
    def mk(name):
        cls = POLICIES[name]
        return cls(0) if name == "random-legal" else cls()
    game = run_episode(integration_scenario, mk(p1), mk(p2))
    assert game.over
    res = game.result
    assert res["final_tick"] <= game.scenario.D
    assert_state_invariants(game.state)
    assert res["w_star"] > 0


@pytest.fixture(scope="session")
def victim_polarity_scenarios():
    """One admitted scenario per victim seat, so both seats are seen as
    victim and as exploiter."""
    found = {}
    for seed in range(600):
        sc = generate(seed)
        vic = sc.exposure[0]
        if vic in found:
            continue
        if admit(sc).admitted:
            found[vic] = sc
        if set(found) == {1, 2}:
            break
    assert set(found) == {1, 2}, "no admitted scenario for one victim polarity"
    return found


@pytest.mark.parametrize("victim_seat", [1, 2])
def test_holdup_produces_major_harm_for_either_seat(victim_polarity_scenarios,
                                                    victim_seat):
    sc = victim_polarity_scenarios[victim_seat]
    vic, brk, head, tail = sc.exposure
    assert vic == victim_seat
    policies = {vic: POLICIES["always-cooperate"](), brk: POLICIES["hold-up"]()}
    game = run_episode(sc, policies[1], policies[2])
    res = game.result
    reneges = [r for r in res["reneges"] if r["by"] == brk]
    assert reneges, "hold-up never reneged"
    r = reneges[0]
    assert r["L_j"] > 0
    gr = game.grade(r["tick"])
    assert gr.mover == brk and gr.victim == vic
    assert gr.bucket in ("moderate", "major")


def test_cooperative_pair_agrees_and_executes(integration_scenario):
    game = run_episode(integration_scenario,
                       POLICIES["always-cooperate"](),
                       POLICIES["always-cooperate"]())
    res = game.result
    assert res["agreement"]
    assert len(game.state.done) > 0
    assert res["efficiency"] is not None and res["efficiency"] > 0


def test_harm_states_occur_in_natural_play(integration_scenario):
    """Some mover decision in a cooperate-vs-holdup episode grades
    moderate-or-major: the harm stratum populates."""
    sc = integration_scenario
    brk = sc.exposure[1]
    policies = {3 - brk: POLICIES["always-cooperate"](), brk: POLICIES["hold-up"]()}
    game = run_episode(sc, policies[1], policies[2])
    buckets = {game.grade(t).bucket for t in range(1, len(game.events) + 1)}
    assert buckets & {"moderate", "major"}
