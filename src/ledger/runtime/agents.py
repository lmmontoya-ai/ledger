"""Agents: a model behind OpenRouter, or a scripted policy, behind one
interface: act(game, seat, logger, meter) -> Action.

ModelAgent implements environment §8.3 exactly: no tool call, unknown tool,
bad arguments, and legal-shape-illegal-move each earn a re-prompt carrying
the specific reason; after three failures the turn is recorded as WAIT with
invalid=true and play moves on.  Provider errors never reach this table —
the client retries or abandons below this layer.
"""
from __future__ import annotations

from ..core import actions as actions_mod
from ..core.events import Action
from ..render.render import DEFAULT_MANDATE, render_prompt, render_user, system_block
from .config import ModelSpec
from .openrouter import CallResult
from .tools import action_from_tool_call, load_tools

MAX_BAD_OUTPUTS = 3  # §8.3: three failures, then flagged WAIT


def parse_reply(result: CallResult) -> tuple[Action | None, str | None, dict]:
    """(action, error, message).  Exactly one of action/error is set."""
    msg = result.message()
    calls = msg.get("tool_calls") or []
    if not calls:
        return None, "no tool call in reply", msg
    fn = calls[0].get("function") or {}
    try:
        return action_from_tool_call(fn.get("name", ""),
                                     fn.get("arguments", "{}")), None, msg
    except ValueError as e:
        return None, str(e), msg


class ScriptedAgent:
    """A deterministic policy from ledger.policies.scripted, run through the
    same loop as models so mixed episodes are possible."""

    def __init__(self, name: str, policy) -> None:
        self.name = name
        self.policy = policy

    def describe(self) -> dict:
        return {"kind": "scripted", "name": self.name}

    def act(self, game, seat: int, logger=None, meter=None) -> Action:
        try:
            a = self.policy(game, seat)
        except Exception:
            a = Action("WAIT", {})
        if actions_mod.validate(game.state, seat, a) is not None:
            a = Action("WAIT", {})
        return a


class ModelAgent:
    def __init__(self, spec: ModelSpec, client, *,
                 mandate: str = DEFAULT_MANDATE) -> None:
        self.spec = spec
        self.client = client
        self.mandate = mandate

    def describe(self) -> dict:
        return {"kind": "model", "mandate": self.mandate, **self.spec.describe()}

    def act(self, game, seat: int, logger=None, meter=None) -> Action:
        state, events = game.state, tuple(game.events)
        _, digest = render_prompt(state, events, seat, mandate=self.mandate)
        messages = [
            {"role": "system", "content": system_block(self.mandate).decode("utf-8")},
            {"role": "user", "content": render_user(state, events, seat)},
        ]
        tools = load_tools()
        last_error = "no attempt"
        for attempt in range(1, MAX_BAD_OUTPUTS + 1):
            result = self.client.chat(self.spec, messages, tools)
            if meter is not None:
                meter.add(result, self.spec)
            action, error, msg = parse_reply(result)
            if action is not None:
                reason = actions_mod.validate(state, seat, action)
                if reason is None:
                    if logger:
                        logger.call(tick=state.tick, seat=seat, digest=digest,
                                    model=self.describe(), attempt=attempt,
                                    purpose="act", result=result)
                    return action
                error = f"illegal action: {reason}"
            last_error = error
            if logger:
                logger.call(tick=state.tick, seat=seat, digest=digest,
                            model=self.describe(), attempt=attempt,
                            purpose="act", result=result, error=error)
            messages = messages + _corrective(msg, error)
        if logger:
            logger.call(tick=state.tick, seat=seat, digest=digest,
                        model=self.describe(), attempt=MAX_BAD_OUTPUTS,
                        purpose="act", error=last_error, invalid_wait=True)
        return Action("WAIT", {})


def _corrective(assistant_msg: dict, error: str) -> list[dict]:
    """Re-prompt per §8.3, in the shape providers expect: a tool call gets a
    tool-role rejection; prose gets a user-role reminder."""
    note = (f"That was rejected: {error}. "
            "Reply with exactly one legal action as a tool call.")
    calls = assistant_msg.get("tool_calls") or []
    if calls:
        assistant = {"role": "assistant",
                     "content": assistant_msg.get("content"),
                     "tool_calls": calls}
        rejections = [{"role": "tool", "tool_call_id": c.get("id", f"call_{i}"),
                       "content": note} for i, c in enumerate(calls)]
        return [assistant] + rejections
    return [{"role": "assistant", "content": assistant_msg.get("content") or ""},
            {"role": "user", "content": note}]
