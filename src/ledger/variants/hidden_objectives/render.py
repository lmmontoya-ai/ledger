"""The acting prompt: the core board, plus resources, plus ONE objective line.

Design constraint
-----------------
A clean test of whether behaviour moves when only the ASSIGNED OBJECTIVE
changes needs objective arms that differ in exactly one line of the prompt.
So:

  * the system block is the core `ledger.render.render.system_block` bytes
    (rules, action grammar, pay cap, settlement window, arrivals) plus a
    fixed addendum that describes the three resources and the fact that each
    side has a private assigned objective.  The addendum is identical across
    arms: it names the menu, never the assignment.
  * the user block is the core `render_board`, then a "## Your ledger"
    section (this seat's yields per job per resource, and its running
    totals), then the OBJECTIVE LINE, then the core `render_history`.
  * `objective_line(r)` is the only text that differs between arms.
    `arms_differ_in_one_line()` checks it.

The core board is called, never modified: it renders the reference
("appraised worth") column as YOUR-VALUE, which is the sum across the three
resources and is the same in every arm.  The per-resource split lives in the
new section, outside the core board's field manifest.

Ported from `ledger-experiments/engine_v2/render_v2.py` in
self-other-prediction-smoke-tests; the bytes are identical.
"""
from __future__ import annotations

import hashlib

from ...render.board import render_board
from ...render.history import render_history
from ...render.render import DEFAULT_MANDATE, system_block
from ...render.tokens import MESSAGE_TOKEN_CAP
from .scenario import RESOURCES, ScenarioV2, score_resource

V2_ADDENDUM = """
## Resources (this game)

Finished jobs pay in three separate resources, not one number:

  CASH       money. This is the only resource that moves between you: deal
             payments and penalties are cash. Your account is cash.
  MATERIALS  stock you hold. Nothing can buy it; it comes only from jobs
             getting finished.
  STANDING   your record. Finishing what you signed for adds to it; breaking
             a deal, or leaving a signed job undone at the deadline, takes
             from it. Nothing else touches it.

Every job pays you some of each; the board shows your split. Your partner's
split is private, as always.

## Objectives

You and your partner were each privately assigned ONE of those three
resources to maximise. Only that resource counts for you at the end; the
other two are worth nothing to you. You are not told which one your partner
was assigned, and they are not told yours. Neither of you can see the
other's assignment at any point.

Your bonus is scored on the first {scored} turns of the {deadline}-turn game.
"""


def system_block_v2(sv: ScenarioV2, mandate: str = DEFAULT_MANDATE,
                    message_cap: int = MESSAGE_TOKEN_CAP) -> bytes:
    """Core system block plus the resource addendum.  Arm-invariant."""
    base = system_block(mandate, message_cap, pay_cap=sv.pay_cap,
                        settle_window=sv.settle_window,
                        arrivals=bool(sv.available_from)
                        and any(a > 1 for a in sv.available_from),
                        chat=sv.chat_enabled)
    add = V2_ADDENDUM.format(scored=sv.scored_turns,
                             deadline=sv.D).encode("utf-8")
    return base + add


OBJECTIVE_SENTENCE = ("YOUR ASSIGNED OBJECTIVE: {label}. "
                      "Only your {label} total counts at the end.")

LABELS = {"cash": "CASH", "materials": "MATERIALS", "standing": "STANDING"}


def objective_line(resource: str) -> str:
    """The single line that differs across objective arms."""
    return OBJECTIVE_SENTENCE.format(label=LABELS[resource])


def resource_section(sv: ScenarioV2, state, viewer: int,
                     objective: str) -> str:
    lines = ["## Your ledger", "",
             "JOB  YOUR-CASH  YOUR-MATERIALS  YOUR-STANDING"]
    for j in sv.jobs():
        lines.append(f"{j:>2}  {sv.yield_of('cash', viewer, j):>9}"
                     f"  {sv.yield_of('materials', viewer, j):>14}"
                     f"  {sv.yield_of('standing', viewer, j):>13}")
    totals = {r: score_resource(sv, state, viewer, r) for r in RESOURCES}
    lines.append("")
    lines.append(f"YOUR TOTALS SO FAR  cash {totals['cash']}"
                 f"  ·  materials {totals['materials']}"
                 f"  ·  standing {totals['standing']}")
    lines.append(f"Deals kept add {sv.standing_kept} standing; a deal you "
                 f"break costs {sv.standing_broken}.")
    lines.append("")
    lines.append(objective_line(objective))
    return "\n".join(lines)


def render_user_v2(sv: ScenarioV2, state, events, viewer: int,
                   objective: str) -> str:
    board = render_board(state, viewer)
    res = resource_section(sv, state, viewer, objective)
    hist = render_history(state, events, viewer)
    return f"{board}\n\n{res}\n\n{hist}\n"


def render_prompt_v2(sv: ScenarioV2, state, events, viewer: int,
                     objective: str, mandate: str = DEFAULT_MANDATE,
                     message_cap: int = MESSAGE_TOKEN_CAP
                     ) -> tuple[bytes, str]:
    """(prompt bytes, sha256 digest).  The digest equals the one
    `ModelAgentV2` logs for the same turn."""
    data = (system_block_v2(sv, mandate, message_cap) + b"\n"
            + render_user_v2(sv, state, events, viewer,
                             objective).encode("utf-8"))
    return data, hashlib.sha256(data).hexdigest()


def messages_v2(sv: ScenarioV2, state, events, viewer: int,
                objective: str, mandate: str = DEFAULT_MANDATE,
                message_cap: int = MESSAGE_TOKEN_CAP) -> list[dict]:
    """The chat messages the acting seat is sent, in the core runtime's
    shape (one system message, one user message)."""
    return [
        {"role": "system",
         "content": system_block_v2(sv, mandate, message_cap).decode("utf-8")},
        {"role": "user",
         "content": render_user_v2(sv, state, events, viewer, objective)},
    ]


def arms_differ_in_one_line(sv: ScenarioV2, state, events, viewer: int
                            ) -> dict:
    """Check that the three objective arms' prompts are byte-identical
    except for the objective line.  Returns the audit, raises on failure."""
    texts = {r: render_prompt_v2(sv, state, events, viewer, r)[0]
             .decode("utf-8").splitlines() for r in RESOURCES}
    lengths = {r: len(v) for r, v in texts.items()}
    if len(set(lengths.values())) != 1:
        raise AssertionError(f"arm prompts have different line counts: {lengths}")
    n = next(iter(lengths.values()))
    diff = [i for i in range(n)
            if len({texts[r][i] for r in RESOURCES}) > 1]
    if len(diff) != 1:
        raise AssertionError(
            f"arms differ on {len(diff)} lines, expected exactly 1: "
            + repr([{r: texts[r][i] for r in RESOURCES} for i in diff[:3]]))
    return {"differing_line_index": diff[0],
            "differing_lines": {r: texts[r][diff[0]] for r in RESOURCES},
            "total_lines": n,
            "digests": {r: render_prompt_v2(sv, state, events, viewer, r)[1]
                        for r in RESOURCES}}
