from __future__ import annotations

import pytest

from ledger.core.events import Action
from ledger.core.scenario import Scenario
from ledger.game import Game
from ledger.scenarios.admit import admit
from ledger.scenarios.generate import generate


def simple_scenario(**overrides) -> Scenario:
    """A small controllable scenario for targeted lifecycle tests."""
    base = dict(
        scenario_id="test-simple", seed=0, generator_version="manual",
        K=4,
        c=((10, 12, 20, 14), (11, 10, 15, 18)),
        v=((20, 5, 30, 0), (5, 25, 10, 15)),
        prereqs=((), (), (1,), ()),
        B=100, kappa=(3, 3), u=(25, 25), D=24, r=2, eps=1, p=6, p_def=8,
        opening=1, exposure=None,
    )
    base.update(overrides)
    return Scenario(**base)


def worked_scenario() -> Scenario:
    """The §7.2 / §9.4 board configuration."""
    return Scenario(
        scenario_id="worked-9-4", seed=0, generator_version="manual",
        K=8,
        c=((14, 27, 12, 19, 27, 28, 25, 16), (21, 13, 22, 19, 14, 15, 16, 28)),
        v=((0, 30, 30, 8, 0, 35, 12, 5), (0, 0, 0, 0, 0, 20, 0, 0)),
        prereqs=((), (), (), (), (3,), (3,), (), (7,)),
        B=100, kappa=(3, 3), u=(25, 25), D=24, r=2, eps=1, p=6, p_def=8,
        opening=1, exposure=(1, 2, 3, 6),
    )


WORKED_PLAYS = [
    Action("QUERY", {"text": "which jobs carry your value? I care about 3 and 6."}),
    Action("INFORM", {"text": "6 is my biggest. 3 is worth nothing to me."}),
    Action("PROPOSE", {"contract": {"assign": {"3": 1, "6": 2},
                                    "fund": {"3": 12, "6": 15},
                                    "pay": [], "expires": 5}}),
    Action("ACCEPT", {"offer_id": 1}),
    Action("WAIT"),
    Action("WAIT"),
    Action("EXECUTE", {"job": 3}),
    Action("PROPOSE", {"contract": {"assign": {"2": 2, "7": 1},
                                    "fund": {"2": 13, "7": 25},
                                    "pay": [{"from": 2, "to": 1, "amount": 4, "tick": 14}],
                                    "expires": 11}}),
    Action("WAIT"),
]


def worked_game(n_plays: int = 9) -> Game:
    g = Game(worked_scenario())
    for a in WORKED_PLAYS[:n_plays]:
        g.play(a)
    return g


@pytest.fixture(scope="session")
def admitted_scenarios():
    """First three admitted scenarios of the reference generator."""
    out = []
    seed = 0
    while len(out) < 3 and seed < 500:
        sc = generate(seed)
        if admit(sc).admitted:
            out.append(sc)
        seed += 1
    assert out, "no admitted scenario in 500 seeds"
    return out


@pytest.fixture(scope="session")
def generated_scenarios():
    return [generate(seed) for seed in range(6)]


def assert_state_invariants(st):
    """The always-true §13 rows checked at every state."""
    sc = st.scenario
    # money conservation: reserved + spent + left + destroyed == B
    lhs, B = st.money_identity()
    assert lhs == B, f"money not conserved: {lhs} != {B}"
    assert st.pot_left >= 0 and st.reserved >= 0
    # reservation integrity: the reserve counter equals the sum of live
    # contract reserves — no state has a live contract without its funding.
    # After settlement the pot, reserves and all, is destroyed (§5.6).
    if st.settled:
        assert st.reserved == 0 and st.pot_left == 0
    else:
        assert st.reserved == sum(c.reserved_amount() for c in st.contracts.values())
    for i in (0, 1):
        assert st.caps_used[i] <= sc.kappa[i], "capacity cap violated"
        assert st.draws[i] <= sc.u[i], "draw cap violated"
    # a job is done at most once, and executed contract jobs are done
    for c in st.contracts.values():
        for j in c.executed_jobs:
            assert j in st.done
