"""Playing, scoring and replaying hidden-objectives episodes.

Play runs on the core runtime unchanged.  `ModelAgentV2` is the core
`ModelAgent` with `_payload` overridden to render this variant's acting
prompt; the elicitation loop, the corrective budget, truncation handling,
legality validation, the episode logger and the event fold are all the
core's.  The dynamics do not depend on which resource anyone maximises
(see scenario.py), so `run_episode` on `sv.base(opening)` is the whole
environment, and scripted agents play it without change.

Scoring follows the variant's rules: each seat's score in its assigned
resource, read at the end of the episode and at the end of the scored
window (turn `scored_turns`, or the final turn if play ended earlier).

Ported from `ledger-experiments/ledger_v2_bridge.py` (`ModelAgentV2`,
`play_episode_v2`, `state_and_prefix`, `load_episode`) and the scoring in
`ledger-experiments/engine_v2/rollout_v2.py` in
self-other-prediction-smoke-tests.
"""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from ...core import fold as fold_mod
from ...render.render import DEFAULT_MANDATE
from ...render.tokens import MESSAGE_TOKEN_CAP
from ...runtime.agents import ModelAgent
from ...runtime.episode import run_episode
from ...runtime.log import read_records
from ...runtime.replay import played_events
from .render import messages_v2, render_prompt_v2
from .scenario import RESOURCES, ScenarioV2, score_vector

VARIANT = "hidden_objectives"


class ModelAgentV2(ModelAgent):
    """The core ModelAgent, rendering the hidden-objectives acting prompt.

    Holds the seat's ASSIGNED RESOURCE.  Nothing this agent renders is ever
    shown to its partner, so the assignment stays private by construction.
    """

    def __init__(self, spec, client, sv: ScenarioV2, objective: str, *,
                 mandate: str = DEFAULT_MANDATE, **kw) -> None:
        super().__init__(spec, client, mandate=mandate, **kw)
        if objective not in RESOURCES:
            raise ValueError(f"unknown assigned resource {objective!r}")
        self.sv = sv
        self.objective = objective

    def describe(self) -> dict:
        d = super().describe()
        d.update(kind="model_v2", assigned_objective=self.objective)
        return d

    def _payload(self, game, seat: int) -> tuple[str, str, str]:
        cap = getattr(game, "message_cap", None) or MESSAGE_TOKEN_CAP
        msgs = messages_v2(self.sv, game.state, tuple(game.events), seat,
                           self.objective, mandate=self.mandate,
                           message_cap=cap)
        system, user = msgs[0]["content"], msgs[1]["content"]
        digest = hashlib.sha256(
            (system + "\n" + user).encode("utf-8")).hexdigest()
        return system, user, digest


def _check_objectives(objectives) -> tuple[str, str]:
    objectives = tuple(objectives)
    if len(objectives) != 2 or any(o not in RESOURCES for o in objectives):
        raise ValueError(f"objectives must be two of {RESOURCES}, "
                         f"got {objectives!r}")
    return objectives


def outcome(sv: ScenarioV2, opening: int, events,
            objectives: tuple[str, str]) -> dict:
    """Resource scores at the end of play and at the end of the scored
    window, and each seat's payoff in its assigned resource."""
    objectives = _check_objectives(objectives)
    base = sv.base(opening)
    events = list(events)
    final = score_vector(sv, fold_mod.fold(base, events))
    window = score_vector(sv, fold_mod.fold(
        base, [e for e in events if e.tick <= sv.scored_turns]))
    return {
        "objectives": objectives,
        "scores": final,
        "assigned_payoff": (final[objectives[0]][0],
                            final[objectives[1]][1]),
        "scored_window_scores": window,
        "scored_window_payoff": (window[objectives[0]][0],
                                 window[objectives[1]][1]),
    }


def play_episode(sv: ScenarioV2, opening: int, objectives: tuple[str, str],
                 agents: dict, out_dir, *, episode_id: str | None = None,
                 bank: str | None = None, message_cap: int = 40,
                 mandate: str = DEFAULT_MANDATE, meter=None) -> dict | None:
    """Play one episode under hidden objectives and score it.

    `agents` is {1: agent, 2: agent}: `ModelAgentV2` for model seats (its
    objective must match `objectives`), or any core agent such as
    `ScriptedAgent`.  The log is the core runtime's JSONL, with the variant's
    settings added to the meta record.  Returns None if the episode was
    abandoned (the log records why); otherwise the core engine result under
    "engine_result" (computed on the reference value column), the variant
    outcome from `outcome`, and the log path.

    `message_cap` defaults to 40, the cap the paper's campaign used.
    """
    objectives = _check_objectives(objectives)
    for seat, agent in agents.items():
        own = getattr(agent, "objective", None)
        if own is not None and own != objectives[seat - 1]:
            raise ValueError(f"seat {seat} agent holds {own!r} but the "
                             f"assignment is {objectives[seat - 1]!r}")
    episode_id = episode_id or uuid.uuid4().hex[:12]
    result = run_episode(
        sv.base(opening), agents, out_dir,
        bank=bank or sv.generator_version, mandate=mandate,
        message_cap=message_cap, meter=meter, episode_id=episode_id,
        extra_meta={"variant": VARIANT,
                    "variant_generator_version": sv.generator_version,
                    "objectives": {"1": objectives[0], "2": objectives[1]},
                    "scored_turns": sv.scored_turns})
    if result is None:
        return None
    path = Path(out_dir) / f"{episode_id}.jsonl"
    events = played_events(read_records(path), message_cap)
    return {"engine_result": result,
            **outcome(sv, opening, events, objectives),
            "log": str(path)}


# ---------------------------------------------------------------------------
# replay
# ---------------------------------------------------------------------------

def state_and_prefix(sv: ScenarioV2, opening: int, events, tick: int):
    """(state at `tick`, the events strictly before it) from an event list."""
    st = fold_mod.initial_state(sv.base(opening))
    prefix = []
    for ev in events:
        if ev.tick >= tick:
            break
        st = fold_mod.apply(st, ev)
        prefix.append(ev)
    return st, tuple(prefix)


def acting_prompt(sv: ScenarioV2, opening: int, events, tick: int,
                  objective: str, *, mandate: str = DEFAULT_MANDATE,
                  message_cap: int = 40) -> tuple[bytes, str]:
    """The exact prompt bytes and digest the mover saw at `tick`, given its
    assigned objective.  The digest equals the `digest` field of that turn's
    call records in the episode log."""
    st, prefix = state_and_prefix(sv, opening, events, tick)
    return render_prompt_v2(sv, st, prefix, st.mover, objective,
                            mandate=mandate, message_cap=message_cap)


def load_episode(path) -> tuple[dict, list]:
    """(meta record, played events) from an episode log.  The message cap
    is the one recorded in the log's meta: an episode replays under the cap
    it was played under."""
    recs = read_records(path)
    meta = recs[0]
    cap = int(meta.get("message_cap") or MESSAGE_TOKEN_CAP)
    return meta, played_events(recs, cap)
