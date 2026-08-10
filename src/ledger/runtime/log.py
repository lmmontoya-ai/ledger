"""Episode trace registration (plan §3.8): one append-only JSONL per episode.

Records, in order: one meta record; per ledger event, one event record; per
provider call, one call record carrying the prompt digest, sampling
parameters, attempt context, served provider, usage, and the raw response
body verbatim; and one result (or abandonment) record.  The event log alone
reconstructs the world byte-for-byte; call records preserve the one thing
reconstruction cannot — what the model actually sampled.
"""
from __future__ import annotations

import json
import time
from fractions import Fraction
from pathlib import Path


def jsonable(x):
    """JSON-safe with exactness kept: Fractions become [num, den]."""
    if isinstance(x, Fraction):
        return {"num": x.numerator, "den": x.denominator}
    if isinstance(x, dict):
        return {str(k): jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    if isinstance(x, (set, frozenset)):
        return sorted(jsonable(v) for v in x)
    return x


class EpisodeLogger:
    def __init__(self, path: str | Path, meta: dict):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a", encoding="utf-8", newline="\n")
        self.write({"kind": "meta", **meta})

    def write(self, record: dict) -> None:
        record.setdefault("utc", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        self._fh.write(json.dumps(jsonable(record), ensure_ascii=False) + "\n")
        self._fh.flush()

    def event(self, tick: int, seat: int, action) -> None:
        self.write({"kind": "event", "tick": tick, "seat": seat,
                    "action": {"name": action.name, "args": action.args}})

    def call(self, *, tick: int, seat: int, digest: str, model: dict,
             attempt: int, purpose: str, result=None, error: str | None = None,
             invalid_wait: bool = False) -> None:
        rec = {"kind": "call", "tick": tick, "seat": seat, "digest": digest,
               "model": model, "attempt": attempt, "purpose": purpose,
               "invalid_wait": invalid_wait}
        if result is not None:
            rec.update(provider=result.provider, served_model=result.model,
                       usage=result.usage, cost_usd=result.cost_usd,
                       latency_s=result.latency_s,
                       transport_attempts=result.attempts, raw=result.raw)
        if error:
            rec["error"] = error
        self.write(rec)

    def result(self, r: dict) -> None:
        self.write({"kind": "result", **{k: v for k, v in r.items()}})

    def abandon(self, reason: str) -> None:
        self.write({"kind": "abandoned", "reason": reason})

    def close(self) -> None:
        self._fh.close()


def read_records(path: str | Path) -> list[dict]:
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out
