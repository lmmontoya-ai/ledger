"""Event types and canonical serialization.

The ledger is an append-only sequence of Events, one per tick.  Everything
else is a pure fold over it (fold.py).  Canonical serialization is stable
JSON with sorted keys, so a ledger has one byte representation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping

ACTION_NAMES = (
    "PROPOSE", "COUNTER", "ACCEPT", "REJECT", "CANCEL", "RENEGE", "DRAW",
    "EXECUTE", "TRANSFER", "QUERY", "INFORM", "WAIT", "END", "REFUSE",
)

MESSAGE_ACTIONS = ("QUERY", "INFORM", "REFUSE")


def _freeze(obj: Any) -> Any:
    """Recursively convert to canonical, hashable-friendly plain structures."""
    if isinstance(obj, Mapping):
        return {str(k): _freeze(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_freeze(x) for x in obj]
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, int):
        return int(obj)
    if isinstance(obj, str):
        return obj
    raise TypeError(f"non-canonical value in action args: {obj!r}")


@dataclass(frozen=True)
class Action:
    name: str
    args: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.name not in ACTION_NAMES:
            raise ValueError(f"unknown action name {self.name!r}")
        object.__setattr__(self, "args", _freeze(self.args))

    def to_dict(self) -> dict:
        return {"name": self.name, "args": _freeze(self.args)}

    @staticmethod
    def from_dict(d: dict) -> "Action":
        return Action(d["name"], d.get("args", {}))


@dataclass(frozen=True)
class Event:
    tick: int
    seat: int
    action: Action
    invalid: bool = False      # WAIT recorded after exhausted retries
    truncated: bool = False    # message text was truncated at the 40-token cap

    def to_dict(self) -> dict:
        return {
            "tick": self.tick,
            "seat": self.seat,
            "action": self.action.to_dict(),
            "invalid": self.invalid,
            "truncated": self.truncated,
        }

    @staticmethod
    def from_dict(d: dict) -> "Event":
        return Event(
            tick=d["tick"],
            seat=d["seat"],
            action=Action.from_dict(d["action"]),
            invalid=d.get("invalid", False),
            truncated=d.get("truncated", False),
        )


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def serialize_events(events) -> str:
    return canonical_json([e.to_dict() for e in events])


def deserialize_events(s: str) -> tuple[Event, ...]:
    return tuple(Event.from_dict(d) for d in json.loads(s))
