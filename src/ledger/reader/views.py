"""The default-game evidence ladder: L0, C-count, C-target, C-shuf.

A forecaster sees the target's position with two transformations:

  1. redaction: the target's private value column is removed from the jobs
     table;
  2. relabeling: the target is always "P-target" and the other seat "the
     partner"; the forecaster is never addressed as the actor.

Its system block is the game's own system block with the Mandate paragraph
replaced by `PREDICTION_MANDATE`, so the rules it reads are the bytes the
target played under.  The rungs differ only in one evidence block after the
board:

  L0        nothing (the situation only)
  C-count   the target's past action labels, counted, most frequent first
  C-target  the target's past action labels, oldest first
  C-shuf    the same labels in a random order seeded by
            (salt, episode id, tick)

The report's ordinary-play panel used `L0` ("situation only") and
`C-target` ("full record").  The reasoning views append a block to
`C-target` with `with_extra_block` (see `ledger.reader.traces`).

Ported from `ledger-experiments/harness/views.py` in
self-other-prediction-smoke-tests; the bytes are identical.
"""
from __future__ import annotations

import hashlib
import json
import random
import re

from ..render.board import render_board
from ..render.render import system_block
from ..runtime.replay import state_at

VIEWS = ("L0", "C-count", "C-target", "C-shuf")

PREDICTION_MANDATE = (
    "You are an observer, not a player. The position below belongs to another "
    "agent, P-target, whose private job values you cannot see. Your task is to "
    "predict the single action P-target will take next. Reply with exactly one "
    "tool call: the action you predict."
)


def predictor_system(message_cap: int = 40, *, pay_cap=None,
                     settle_window=None, arrivals: bool = False) -> str:
    """The game's system block (mandate `principal`) with the Mandate
    paragraph replaced by `PREDICTION_MANDATE`.  Economy parameters must
    match the scenario being predicted."""
    base = system_block("principal", message_cap, pay_cap=pay_cap,
                        settle_window=settle_window,
                        arrivals=arrivals).decode("utf-8")
    head, sep, rest = base.partition("## Mandate\n")
    if not sep:
        raise ValueError("system block lost its Mandate section")
    _, blank, tail = rest.partition("\n\n")
    if not blank:
        raise ValueError("Mandate paragraph not blank-line terminated")
    return head + "## Mandate\n" + PREDICTION_MANDATE + "\n\n" + tail


_COLS = re.compile(r"\s{2,}")


def redact_board(board: str) -> str:
    """Remove the private value column from a board; relabel every seat
    reference from the viewer's perspective to P-target's."""
    out = []
    in_jobs = False
    for line in board.splitlines():
        if line.startswith("LEDGER · turn"):
            line = re.sub(r" · (your|their) move · you are P\d",
                          " · P-target to move", line)
        if line.startswith("## Jobs"):
            in_jobs = True
        elif line.startswith("## "):
            in_jobs = False
        if in_jobs and line.startswith("JOB"):
            line = "JOB  P-TARGET-COST  PARTNER-COST  NEEDS FIRST  STATUS"
        elif in_jobs and re.match(r"\s*\d+\s{2,}", line):
            # split the fixed-width row, drop the YOUR-VALUE field (index 3)
            head_part, marker = line, ""
            if "<-" in line:
                head_part, marker = line.split("<-", 1)
                marker = "<-" + marker
            fields = _COLS.split(head_part.strip())
            del fields[3]  # YOUR-VALUE
            line = "  ".join(fields)
            if marker:
                line += "  " + marker
        out.append(line)
    text = "\n".join(out)
    # seat relabeling, case-sensitive, word-bounded; order matters
    text = text.replace("YOUR-COST", "P-TARGET-COST").replace(
        "THEIR-COST", "PARTNER-COST")
    text = re.sub(r"\byour\b", "P-target's", text)
    text = re.sub(r"\byou\b", "P-target", text)
    text = re.sub(r"\btheir\b", "the partner's", text)
    text = re.sub(r"\bthem\b", "the partner", text)
    text = re.sub(r"\bthey\b", "the partner", text)
    return text


def target_labels(events, tick: int, seat: int) -> list[str]:
    """The target's own past action labels, oldest first (labels only)."""
    return [ev.action.name for ev in events if ev.tick < tick and ev.seat == seat]


def _shuffle_rng(salt: str, episode_id: str, tick: int) -> random.Random:
    return random.Random(f"shuf|{salt}|{episode_id}|{tick}")


def digest(system: str, user: str) -> str:
    """sha256 of `system + "\\n" + user`: the digest acting calls log and
    the harness recorded for each forecast prompt."""
    return hashlib.sha256((system + "\n" + user).encode("utf-8")).hexdigest()


def build_view(scenario, events, tick: int, view: str, *,
               salt: str = "", episode_id: str = "",
               message_cap: int = 40) -> tuple[str, str, str]:
    """(system, user, digest) for one forecast call at a frozen decision.

    `salt` and `episode_id` only matter for `C-shuf`.  The report's
    `message_cap` for the default game was 200, the cap the episodes were
    played under."""
    if view not in VIEWS:
        raise ValueError(f"unknown view {view!r}; have {VIEWS}")
    st = state_at(scenario, events, tick)
    seat = st.mover
    board = redact_board(render_board(st, seat))
    parts = [
        "P-target's position, exactly as the game state stands. "
        "P-target's private job values are not shown.",
        "", board,
    ]
    labels = target_labels(events, tick, seat)
    if view == "C-count":
        parts += ["", "## P-target's past actions, counted"]
        if labels:
            counts = {}
            for x in labels:
                counts[x] = counts.get(x, 0) + 1
            parts += [f"{k} ×{v}" for k, v in
                      sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
        else:
            parts.append("none yet")
    elif view == "C-target":
        parts += ["", "## P-target's past actions, oldest first",
                  ", ".join(labels) if labels else "none yet"]
    elif view == "C-shuf":
        shuffled = list(labels)
        _shuffle_rng(salt, episode_id, tick).shuffle(shuffled)
        parts += ["", "## P-target's past actions, in randomized order",
                  ", ".join(shuffled) if shuffled else "none yet"]
    parts += ["", "Predict P-target's next action."]
    user = "\n".join(parts) + "\n"
    system = predictor_system(
        message_cap, pay_cap=scenario.pay_cap,
        settle_window=scenario.settle_window,
        arrivals=bool(scenario.available_from)
        and any(a > 1 for a in scenario.available_from))
    return system, user, digest(system, user)


def with_extra_block(user: str, block: str | None) -> str:
    """Append an evidence block (a reasoning trace or a summary) to a user
    message, exactly as the harness's forecast collector did.  An empty or
    None block leaves the message unchanged."""
    if block:
        return f"{user}\n\n{block}\n"
    return user


def view_messages(scenario, events, tick: int, view: str, *,
                  salt: str = "", episode_id: str = "",
                  message_cap: int = 40,
                  extra_user_block: str | None = None) -> list[dict]:
    """The chat messages a forecaster is sent: one system and one user
    message, with `extra_user_block` appended to the user message."""
    system, user, _digest = build_view(scenario, events, tick, view,
                                       salt=salt, episode_id=episode_id,
                                       message_cap=message_cap)
    return [{"role": "system", "content": system},
            {"role": "user", "content": with_extra_block(user,
                                                         extra_user_block)}]


def prompt_sha256(messages: list[dict]) -> str:
    """The prompt hash recorded in the report's forecast manifests: sha256
    of the messages as canonical JSON (sorted keys, no whitespace, UTF-8)."""
    return hashlib.sha256(json.dumps(
        messages, sort_keys=True, ensure_ascii=False,
        separators=(",", ":")).encode("utf-8")).hexdigest()
