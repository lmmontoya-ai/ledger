"""Reasoning views: the target's own reasoning from earlier turns.

Two blocks, both appended to the `C-target` view with
`views.with_extra_block`:

  trace     the target's reasoning text from its PAST turns, oldest first,
            at most `MAX_TURNS` turns of at most `MAX_CHARS_PER_TURN`
            characters each.  Redacted (the information-matched rung) or
            not (the monitoring condition, which is not information-matched).
            The trace of the decision being predicted is never included.
  summary   a summary of the redacted trace, under the same header.

Redaction is deliberately blunt: any sentence with a value-revealing phrase
is replaced, and any bare integer equal to one of the target's private job
values is replaced by "[n]".  Over-redaction weakens the rung; a leak would
break the information match.

These functions take the reasoning text (or the episode log it is stored
in) as input.  No reasoning text or summary is shipped with this package.

Ported from `ledger-experiments/harness/reason_view.py` and
`ledger-experiments/run_s1.py` in self-other-prediction-smoke-tests; the
bytes are identical.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..runtime.log import read_records

MAX_CHARS_PER_TURN = 1200
MAX_TURNS = 6                  # the most recent past turns of the target

_VALUE_WORDS = re.compile(
    r"\b(my|our)\s+(value|values|worth|payoff)\b|\bworth\s+\d+\s+to\s+me\b"
    r"|\bI\s+value\b|\bmy\s+private\b", re.I)

SUMMARY_HEADER = ("P-target's own reasoning at its previous turns, with its "
                  "private values removed:\n\n[earlier turns, summarized] ")


def redact_trace(text: str, private_values: list[int]) -> str:
    """Remove the target's private values and the sentences that state them."""
    out = []
    for sentence in re.split(r"(?<=[.!?\n])\s+", text):
        if _VALUE_WORDS.search(sentence):
            out.append("[redacted: private values]")
            continue
        red = sentence
        for v in sorted({abs(int(v)) for v in private_values if v}, reverse=True):
            red = re.sub(rf"(?<!\d){v}(?!\d)", "[n]", red)
        out.append(red)
    return " ".join(out).strip()


def reasoning_chunks(records: list[dict], tick: int, seat: int
                     ) -> list[tuple[int, str]]:
    """(tick, reasoning text) for every call `seat` made before `tick`, in
    log order, read from the provider's `reasoning` and `reasoning_details`
    fields of the logged raw responses.  Calls with no reasoning text are
    skipped."""
    chunks = []
    for r in records:
        if r.get("kind") != "call" or r.get("seat") != seat:
            continue
        if r.get("tick", 0) >= tick:
            continue
        msg = (r.get("raw", {}).get("choices") or [{}])[0].get("message") or {}
        text = msg.get("reasoning") or ""
        for d in (msg.get("reasoning_details") or []):
            text += str(d.get("text", ""))
        text = text.strip()
        if text:
            chunks.append((r["tick"], text))
    return chunks


def trace_block(chunks: list[tuple[int, str]], *, redacted: bool,
                private_values: list[int] | None = None) -> str:
    """The trace block from (tick, text) chunks, or "" when there are none.

    With `redacted=True` each chunk is redacted against `private_values`
    before it is cut to `MAX_CHARS_PER_TURN`; then the last `MAX_TURNS`
    chunks are kept.  Labels carry no turn numbers, so that a digit in a
    label can never look like a leaked value."""
    private = list(private_values or []) if redacted else []
    cut = []
    for t, text in chunks:
        if redacted:
            text = redact_trace(text, private)
        cut.append((t, text[:MAX_CHARS_PER_TURN]))
    cut = cut[-MAX_TURNS:]
    if not cut:
        return ""
    lines = [f"[earlier turn] {x}" for _t, x in cut]
    head = ("P-target's own reasoning at its previous turns"
            + (", with its private values removed" if redacted else "")
            + ":")
    return head + "\n\n" + "\n\n".join(lines)


def trace_text(scenario, episode, tick: int, seat: int, *,
               redacted: bool) -> str:
    """The trace block for `seat` at `tick` from an episode log (a path or
    its list of records), redacted against `scenario.v[seat - 1]`."""
    records = (read_records(episode) if isinstance(episode, (str, Path))
               else episode)
    private = list(scenario.v[seat - 1]) if redacted else []
    return trace_block(reasoning_chunks(records, tick, seat),
                       redacted=redacted, private_values=private)


def summary_block(summary: str) -> str:
    """The summary view's block: the trace header, then the summary."""
    return SUMMARY_HEADER + summary


def audit_leaks(text: str, private_values: list[int]) -> list[int]:
    """Private values still present in a redacted text: must be empty."""
    found = []
    for v in {abs(int(v)) for v in private_values if v}:
        if re.search(rf"(?<!\d){v}(?!\d)", text):
            found.append(v)
    return sorted(found)
