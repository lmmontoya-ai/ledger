"""Deterministic solver-played episodes under hidden objectives.

No model, no network.  These episodes supplied the fixed states of the
report's Contracting fixed-state gates.  The policy:

  * the mover knows its own assigned resource and maximises it;
  * it does not know the partner's, holds a uniform prior over the three,
    and mixes the belief-conditioned solver values at the level of mover
    strategy keys (a strategy the partner would refuse under a belief is
    valued at the mover's residual go-it-alone value under that belief);
  * it draws an action class from softmax(value / tau) with an RNG seeded
    per (episode, turn).

Every draw is seeded from
`f"{seed}|{scenario_id}|{opening}|{objectives}|{tau}|{tick}"`, so an episode
is a pure function of its `EpisodeSpec`.

Ported from `ledger-experiments/engine_v2/rollout_v2.py` in
self-other-prediction-smoke-tests; the arithmetic and the seeding are
unchanged.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from ...core import actions as actions_mod
from ...core import fold as fold_mod
from ...core.events import Action, Event
from .scenario import RESOURCES, ScenarioV2, score_vector
from .solver import completions, envelope_v2

DEFAULT_TAU = 6.0


@dataclass(frozen=True)
class EpisodeSpec:
    scenario: ScenarioV2
    opening: int
    objectives: tuple[str, str]          # seat 1's resource, seat 2's
    tau: float = DEFAULT_TAU
    seed: int = 0

    @property
    def episode_id(self) -> str:
        return (f"{self.scenario.scenario_id[:10]}_o{self.opening}"
                f"_{self.objectives[0][:4]}-{self.objectives[1][:4]}"
                f"_s{self.seed}")


@dataclass
class Position:
    """One decision faced by the mover, with its solver tables."""
    episode_id: str
    tick: int
    mover: int
    mover_objective: str
    partner_objective_truth: str
    scored: bool                          # tick <= scored_turns
    solo_mover: int
    n_completions: int
    # a locked deal with work left, or a live offer from the partner
    exposure_live: bool = False
    # partner objective -> per-family {"best": class, "astar": [classes],
    #                                  "q": {class: value}}
    per_belief: dict[str, dict] = field(default_factory=dict)
    chosen_class: str | None = None
    chosen_action: str | None = None


@dataclass
class EpisodeResult:
    spec: EpisodeSpec
    events: list                          # list[Event]
    positions: list[Position]
    final_scores: dict[str, tuple[int, int]]
    assigned_payoff: tuple[int, int]      # each seat's score in ITS resource
    scored_window_scores: dict[str, tuple[int, int]]
    scored_window_payoff: tuple[int, int]


def _rng(spec: EpisodeSpec, tick: int) -> random.Random:
    return random.Random(f"{spec.seed}|{spec.scenario.scenario_id}|"
                         f"{spec.opening}|{spec.objectives}|{spec.tau}|{tick}")


def _softmax(values: dict[str, float], tau: float) -> dict[str, float]:
    if not values:
        return {}
    top = max(values.values())
    w = {c: math.exp((v - top) / max(tau, 1e-6)) for c, v in values.items()}
    z = sum(w.values())
    return {c: x / z for c, x in w.items()}


def mixed_action_values(sv: ScenarioV2, state, mover_objective: str,
                        beliefs: tuple[str, ...] = RESOURCES,
                        comps=None):
    """Uniform-prior mix of the belief-conditioned solver values.

    Returns (class_values, class_reps, envelopes), with `envelopes` keyed by
    partner objective, so a position costs one enumeration."""
    if comps is None:
        comps = completions(sv, state)
    envs = {b: envelope_v2(sv, state, mover_objective, b, comps=comps)
            for b in beliefs}
    solo_m = envs[beliefs[0]].solo[0]     # mover-side, belief-independent
    keys = sorted({k for e in envs.values() for k in e.by_key},
                  key=lambda k: repr(k))
    class_values: dict[str, float] = {}
    class_reps: dict[str, Action] = {}
    for k in keys:
        vals, cls, act = [], None, None
        for b in beliefs:
            entry = envs[b].by_key.get(k)
            if entry is None:
                vals.append(float(solo_m))   # the partner refuses: go alone
            else:
                vals.append(float(entry[0]))
                cls, act = entry[1], entry[2]
        if cls is None:
            continue
        v = sum(vals) / len(vals)
        if cls not in class_values or v > class_values[cls]:
            class_values[cls] = v
            class_reps[cls] = act
    return class_values, class_reps, envs


def run_episode(sv: ScenarioV2, spec: EpisodeSpec) -> EpisodeResult:
    """One full D-turn episode; a Position is recorded at every turn."""
    base = sv.base(spec.opening)
    st = fold_mod.initial_state(base)
    events: list[Event] = []
    positions: list[Position] = []
    scored_state = None

    while not st.over:
        tick = st.tick
        mover = st.mover
        rm = spec.objectives[mover - 1]
        rp_true = spec.objectives[2 - mover]
        comps = completions(sv, st)
        cls_vals, cls_reps, envs = mixed_action_values(
            sv, st, rm, comps=comps)

        pos = Position(
            episode_id=spec.episode_id, tick=tick, mover=mover,
            mover_objective=rm, partner_objective_truth=rp_true,
            scored=tick <= sv.scored_turns,
            solo_mover=envs[RESOURCES[0]].solo[0],
            n_completions=len(comps),
            exposure_live=envs[RESOURCES[0]].exposure_live)
        for b, e in envs.items():
            pos.per_belief[b] = {
                fam: {"best": e.best[fam],
                      "astar": sorted(e.astar[fam]),
                      "q": {c: float(v) for c, v in sorted(e.q[fam].items())}}
                for fam in e.q}
            pos.per_belief[b]["_action_level"] = {
                "best_key": e.best_key,
                "eps_keys": sorted(e.eps_keys),
                "n_keys": len(e.by_key)}

        if cls_vals:
            dist = _softmax(cls_vals, spec.tau)
            classes = sorted(dist)
            cls = _rng(spec, tick).choices(
                classes, weights=[dist[c] for c in classes])[0]
            action = cls_reps[cls]
        else:
            cls, action = "WAIT", Action("WAIT")
        if actions_mod.validate(st, mover, action) is not None:
            cls, action = "WAIT", Action("WAIT")
        pos.chosen_class = cls
        pos.chosen_action = action.name
        positions.append(pos)

        ev = Event(tick, mover, action)
        st = fold_mod.apply(st, ev)
        events.append(ev)
        if tick == sv.scored_turns:
            scored_state = st

    if scored_state is None:
        scored_state = st
    final = score_vector(sv, st)
    win = score_vector(sv, scored_state)
    return EpisodeResult(
        spec=spec, events=events, positions=positions,
        final_scores=final,
        assigned_payoff=(final[spec.objectives[0]][0],
                         final[spec.objectives[1]][1]),
        scored_window_scores=win,
        scored_window_payoff=(win[spec.objectives[0]][0],
                              win[spec.objectives[1]][1]))


def episode_ledger(spec: EpisodeSpec, res: EpisodeResult) -> dict:
    """The replayable JSON record of one rollout episode."""
    return {
        "episode_id": spec.episode_id,
        "scenario_id": spec.scenario.scenario_id,
        "opening": spec.opening,
        "objectives": list(spec.objectives),
        "tau": spec.tau,
        "seed": spec.seed,
        "turns": spec.scenario.D,
        "scored_turns": spec.scenario.scored_turns,
        "final_tick": res.events[-1].tick if res.events else 0,
        "events": [{"tick": e.tick, "seat": e.seat,
                    "action": {"name": e.action.name, "args": e.action.args}}
                   for e in res.events],
        "final_scores": {k: list(v) for k, v in res.final_scores.items()},
        "scored_window_scores": {k: list(v)
                                 for k, v in res.scored_window_scores.items()},
        "assigned_payoff": list(res.assigned_payoff),
        "scored_window_payoff": list(res.scored_window_payoff),
    }


def gate_grid(bank: list[ScenarioV2], *, openings=(1, 2),
              tau: float = 1.5) -> list[EpisodeSpec]:
    """The fixed-state gates' episode grid: every bank scenario under each
    opening, the nine ordered objective assignments dealt round-robin, seeds
    1, 2, ...  With the studied bank and tau 1.5 this is the report's
    24-episode grid."""
    pairs = [(a, b) for a in RESOURCES for b in RESOURCES]
    out, i = [], 0
    for sv in bank:
        for opening in openings:
            out.append(EpisodeSpec(scenario=sv, opening=opening,
                                   objectives=pairs[i % len(pairs)],
                                   tau=tau, seed=i + 1))
            i += 1
    return out
