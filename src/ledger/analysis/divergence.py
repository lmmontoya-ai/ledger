"""State harvesting, mixture classification, and the divergence report
(RETUNE_PLAN §3, §5).  Consumes Envelope results; owns no game semantics.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from ..core import fold as fold_mod
from ..core.events import Event
from .objectives import Envelope, envelope

NON_CONSEQUENTIAL = {"WAIT", "CHAT", "REFUSE"}


def consequential(classes) -> set[str]:
    return {c for c in classes if c.split(":", 1)[0] not in NON_CONSEQUENTIAL}


def phase_of(tick: int, D: int) -> str:
    if tick <= D // 3:
        return "negotiation"
    if tick > D - D // 3:
        return "endgame"
    return "execution"


@dataclass
class StateRow:
    scenario_id: str
    tick: int
    phase: str
    mover: int
    n_completions: int
    options: int                       # consequential classes reachable
    tradeoff: bool                     # own vs joint argmax disjoint
    trust: bool                        # cautious vs opportunistic disjoint
    forced: bool
    mixture: str                       # forced | easy | trade-off | trust
    breach_premium: int | None
    frontier_n: int
    frontier_spread: int               # max seat-payoff gap on the frontier
    astar_own: list[str] = field(default_factory=list)
    astar_joint: list[str] = field(default_factory=list)


def classify(env: Envelope, scenario_id: str, D: int) -> StateRow:
    opts = consequential(set(env.q["own"]) | set(env.q["joint"]))
    a_own = consequential(env.astar["own"])
    a_joint = consequential(env.astar["joint"])
    a_caut = consequential(env.astar["cautious"])
    a_opp = consequential(env.astar["opportunistic"])
    forced = len(opts) <= 1
    tradeoff = (not forced and bool(a_own) and bool(a_joint)
                and not (a_own & a_joint))
    trust = (not forced and env.exposure_live and bool(a_caut) and bool(a_opp)
             and not (a_caut & a_opp))
    if forced:
        mixture = "forced"
    elif tradeoff:
        mixture = "trade-off"
    elif trust:
        mixture = "trust"
    else:
        mixture = "easy"
    spread = 0
    if env.frontier:
        spread = max(abs(a - b) for a, b in env.frontier)
    return StateRow(
        scenario_id=scenario_id, tick=env.state_tick,
        phase=phase_of(env.state_tick, D), mover=env.mover,
        n_completions=env.n_completions, options=len(opts),
        tradeoff=tradeoff, trust=trust, forced=forced, mixture=mixture,
        breach_premium=env.breach_premium,
        frontier_n=len(env.frontier), frontier_spread=spread,
        astar_own=sorted(a_own), astar_joint=sorted(a_joint))


# ---------------------------------------------------------------------------
# state harvesting
# ---------------------------------------------------------------------------

def states_from_events(scenario, events: list[Event]):
    """The mover state before every played tick: the real decisions."""
    st = fold_mod.initial_state(scenario)
    out = [st]
    for ev in events:
        st = fold_mod.apply(st, ev)
        if not st.over:
            out.append(st)
    return out


def states_from_policies(scenario, policy1, policy2):
    """Visited states of one scripted interaction episode."""
    from ..policies.scripted import run_episode
    game = run_episode(scenario, policy1, policy2)
    return states_from_events(scenario, game.events)


# ---------------------------------------------------------------------------
# the report
# ---------------------------------------------------------------------------

def audit_states(states, scenario_id: str, D: int,
                 eps: int = 2) -> list[StateRow]:
    rows = []
    for st in states:
        if st.over:
            continue
        rows.append(classify(envelope(st, eps=eps), scenario_id, D))
    return rows


def aggregate(rows: list[StateRow]) -> dict:
    def share(pred, sub) -> float:
        sub = list(sub)
        return round(sum(1 for r in sub if pred(r)) / len(sub), 4) if sub else 0.0

    by_phase = defaultdict(list)
    for r in rows:
        by_phase[r.phase].append(r)
    premiums = [r.breach_premium for r in rows if r.breach_premium is not None]
    return {
        "n_states": len(rows),
        "mixture": dict(Counter(r.mixture for r in rows)),
        "tradeoff_share": share(lambda r: r.tradeoff, rows),
        "trust_share": share(lambda r: r.trust, rows),
        "optionality_share": share(lambda r: r.options >= 2, rows),
        "by_phase": {
            ph: {
                "n": len(sub),
                "tradeoff_share": share(lambda r: r.tradeoff, sub),
                "trust_share": share(lambda r: r.trust, sub),
                "optionality_share": share(lambda r: r.options >= 2, sub),
                "mean_options": round(sum(r.options for r in sub)
                                      / len(sub), 2) if sub else 0.0,
            } for ph, sub in sorted(by_phase.items())},
        "frontier": {
            "mean_n": round(sum(r.frontier_n for r in rows)
                            / len(rows), 2) if rows else 0.0,
            "mean_spread": round(sum(r.frontier_spread for r in rows)
                                 / len(rows), 2) if rows else 0.0,
        },
        "breach_premiums": {
            "n_states": len(premiums),
            "n_profitable": sum(1 for x in premiums if x > 0),
            "max": max(premiums, default=None),
        },
    }
