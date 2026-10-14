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
from ..core.events import MESSAGE_ACTIONS, Action, Event
from ..render.render import DEFAULT_MANDATE, render_prompt, render_user, system_block
from ..render.tokens import MESSAGE_TOKEN_CAP, truncate_message
from .agents import MAX_BAD_OUTPUTS, MAX_TRUNCATIONS, parse_reply, _corrective
from .config import ModelSpec
from .openrouter import EpisodeAbandoned
from .tools import load_tools


def load_events(scenario, records: list[dict]) -> list[Event]:
    """Rebuild engine events from an episode log's event records, as logged.

    `run_episode` logs the action the agent RETURNED.  `Game.play` caps CHAT
    and REFUSE text at the message cap and marks the event `truncated`, and
    both the capped text and the mark reach later prompts.  So for an episode
    with an over-cap message these raw events do not reproduce what the game
    played.  Use `played_events` to replay prompts."""
    return [Event(r["tick"], r["seat"],
                  Action(r["action"]["name"], r["action"]["args"]))
            for r in records if r.get("kind") == "event"]


def played_events(records: list[dict],
                  message_cap: int | None = None) -> list[Event]:
    """Engine events from an episode log, normalised to what the game played.

    Applies the engine's message truncation to every CHAT and REFUSE text,
    which recovers the played event exactly because `truncate_message` is a
    pure function of the logged text and the cap.  `message_cap` defaults to
    the cap in the log's meta record, else the engine default.  The result
    depends on the tokenizer: run with tiktoken installed, as live play was.
    `assert_replays_as_played` checks the claim against `Game` itself."""
    if message_cap is None:
        meta = next((r for r in records if r.get("kind") == "meta"), {})
        message_cap = int(meta.get("message_cap") or MESSAGE_TOKEN_CAP)
    out = []
    for r in records:
        if r.get("kind") != "event":
            continue
        action = Action(r["action"]["name"], r["action"]["args"])
        truncated = False
        if action.name in MESSAGE_ACTIONS and "text" in action.args:
            text, truncated = truncate_message(str(action.args["text"]),
                                               cap=message_cap)
            action = Action(action.name, {**action.args, "text": text})
        out.append(Event(r["tick"], r["seat"], action, truncated=truncated))
    return out


def assert_replays_as_played(scenario, records: list[dict],
                             message_cap: int | None = None) -> dict:
    """Re-play the logged actions through `Game` and check, field by field,
    that `played_events` returns the events the game recorded.  Raises on
    any difference; returns a small summary."""
    from ..game import Game
    if message_cap is None:
        meta = next((r for r in records if r.get("kind") == "meta"), {})
        message_cap = int(meta.get("message_cap") or MESSAGE_TOKEN_CAP)
    played = Game(scenario, message_cap=message_cap)
    for r in records:
        if r.get("kind") == "event":
            played.play(Action(r["action"]["name"], r["action"]["args"]))
    ours = played_events(records, message_cap)
    if len(played.events) != len(ours):
        raise AssertionError(
            f"event count differs: game {len(played.events)} vs "
            f"normalised {len(ours)}")
    for a, b in zip(played.events, ours):
        if ((a.tick, a.seat, a.action.name, a.action.args, a.truncated)
                != (b.tick, b.seat, b.action.name, b.action.args, b.truncated)):
            raise AssertionError(
                f"normalised event differs from the played event at tick "
                f"{a.tick}: game={a} normalised={b}")
    return {"events": len(ours),
            "truncated_messages": sum(1 for e in ours if e.truncated)}


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
                  n: int, mandate: str = DEFAULT_MANDATE,
                  message_cap: int = 40, meter=None,
                  max_bad_outputs: int = MAX_BAD_OUTPUTS,
                  max_truncations: int = MAX_TRUNCATIONS,
                  parallel_draws: int = 1,
                  extra_user_line: str | None = None) -> PolicyBatch:
    """N independent draws of the mover's policy at a frozen decision.

    The elicitation procedure — up to `max_bad_outputs` corrective
    re-prompts, then an invalid-flagged WAIT — is byte-identical to live
    play's (agents.py), which is what makes the replayed distribution the
    same measured object as the live one (plan §3.8a).  Truncation is
    configuration failure and aborts rather than polluting the batch.

    `parallel_draws` is pure scheduling, never measurement: each draw is an
    independent sample of one frozen prompt, so running them concurrently
    changes no prompt byte, no digest, and no per-draw procedure.  Results
    are assembled in draw order regardless of completion order."""
    st = state_at(scenario, events, tick)
    seat = st.mover
    prefix = tuple(ev for ev in events if ev.tick < tick)
    _, digest = render_prompt(st, prefix, seat, mandate=mandate,
                              message_cap=message_cap)
    base = [
        {"role": "system",
         "content": system_block(
             mandate, message_cap, pay_cap=scenario.pay_cap,
             settle_window=scenario.settle_window,
             arrivals=bool(scenario.available_from)
             and any(a > 1 for a in scenario.available_from),
             chat=scenario.chat_enabled).decode("utf-8")},
        {"role": "user", "content": render_user(st, prefix, seat)
         + (("\n" + extra_user_line + "\n") if extra_user_line else "")},
    ]
    # extra_user_line deliberately changes the measured object (it exists
    # for the E1 conditioning check, injected-line versus clean); None
    # keeps every byte and digest identical to live play.
    tools = load_tools(message_cap=message_cap, pay_cap=scenario.pay_cap,
                       settle_window=scenario.settle_window,
                       deadline=scenario.D, chat=scenario.chat_enabled)
    batch = PolicyBatch(tick=tick, seat=seat, digest=digest)

    def one_draw(_i: int):
        messages = list(base)
        action = None
        bad, truncs = 0, 0
        records, providers = [], []
        while bad < max_bad_outputs:
            result = (meter.call(client, spec, messages, tools)
                      if meter is not None else
                      client.chat(spec, messages, tools))
            records.append(result)
            providers.append(result.provider)
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
        invalid = action is None
        if invalid:
            action = Action("WAIT", {})
        return action, records, providers, invalid

    if parallel_draws <= 1:
        results = [one_draw(i) for i in range(n)]
    else:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=parallel_draws) as pool:
            results = list(pool.map(one_draw, range(n)))
    for action, records, providers, invalid in results:
        batch.actions.append(action)
        batch.records.extend(records)
        batch.providers.extend(providers)
        batch.invalid_draws += invalid
    served = {p for p in batch.providers if p is not None}
    batch.valid = len(served) <= 1
    return batch
