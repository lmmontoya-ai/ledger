"""Freeze a decision, re-sample the policy (plan §3.2, §3.8).

The world side replays from the event log alone; the model side re-answers
the byte-identical prompt N times.  The single-provider validity rule is
enforced here: a batch whose calls report more than one serving provider is
marked invalid and must be re-collected, because a mixture of hosts is a
mixture of policies, not a policy.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..core import fold as fold_mod
from ..core import actions as actions_mod
from ..core.events import Action, Event
from ..render.render import DEFAULT_MANDATE, render_prompt, render_user, system_block
from .agents import MAX_BAD_OUTPUTS, MAX_TRUNCATIONS, parse_reply, _corrective
from .config import ModelSpec
from .openrouter import EpisodeAbandoned
from .tools import load_tools


def load_events(scenario, records: list[dict]) -> list[Event]:
    """Rebuild engine events from an episode log's event records."""
    return [Event(r["tick"], r["seat"],
                  Action(r["action"]["name"], r["action"]["args"]))
            for r in records if r.get("kind") == "event"]


def state_at(scenario, events: list[Event], tick: int):
    """The state a mover saw at `tick`: all events strictly before it applied."""
    st = fold_mod.initial_state(scenario)
    for ev in events:
        if ev.tick >= tick:
            break
        st = fold_mod.apply(st, ev)
    return st


@dataclass
class PolicyBatch:
    tick: int
    seat: int
    digest: str
    actions: list = field(default_factory=list)      # Action per draw (WAIT if invalid)
    invalid_draws: int = 0                            # forced WAITs (behavior, §3.8)
    providers: list = field(default_factory=list)     # served provider per draw
    valid: bool = True                                # single-provider rule
    records: list = field(default_factory=list)       # raw CallResults, in order


def sample_policy(client, spec: ModelSpec, scenario, events, tick: int, *,
                  n: int, mandate: str = DEFAULT_MANDATE, meter=None,
                  max_bad_outputs: int = MAX_BAD_OUTPUTS,
                  max_truncations: int = MAX_TRUNCATIONS) -> PolicyBatch:
    """N independent draws of the mover's policy at a frozen decision.

    The elicitation procedure — up to `max_bad_outputs` corrective
    re-prompts, then an invalid-flagged WAIT — is byte-identical to live
    play's (agents.py), which is what makes the replayed distribution the
    same measured object as the live one (plan §3.8a).  Truncation is
    configuration failure and aborts rather than polluting the batch."""
    st = state_at(scenario, events, tick)
    seat = st.mover
    prefix = tuple(ev for ev in events if ev.tick < tick)
    _, digest = render_prompt(st, prefix, seat, mandate=mandate)
    base = [
        {"role": "system", "content": system_block(mandate).decode("utf-8")},
        {"role": "user", "content": render_user(st, prefix, seat)},
    ]
    tools = load_tools()
    batch = PolicyBatch(tick=tick, seat=seat, digest=digest)
    for _ in range(n):
        messages = list(base)
        action = None
        bad, truncs = 0, 0
        while bad < max_bad_outputs:
            result = client.chat(spec, messages, tools)
            if meter is not None:
                meter.add(result, spec)
            batch.records.append(result)
            batch.providers.append(result.provider)
            if result.finish_reason() == "length":
                truncs += 1
                if truncs > max_truncations:
                    raise EpisodeAbandoned(
                        f"{spec.slug}: replay draw truncated {truncs}x; "
                        f"raise max_tokens ({spec.max_tokens}) and re-collect")
                continue
            candidate, error, msg = parse_reply(result)
            if candidate is not None:
                reason = actions_mod.validate(st, seat, candidate)
                if reason is None:
                    action = candidate
                    break
                error = f"illegal action: {reason}"
            bad += 1
            messages = messages + _corrective(msg, error)
        if action is None:
            action = Action("WAIT", {})
            batch.invalid_draws += 1
        batch.actions.append(action)
    served = {p for p in batch.providers if p is not None}
    batch.valid = len(served) <= 1
    return batch
