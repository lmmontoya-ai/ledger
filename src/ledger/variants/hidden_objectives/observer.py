"""The observer view: what a third party may see of a seat's position.

An observer (a predictor, a monitor) is shown the acting seat's board with
every private number and the assigned objective removed.  Three removals:

  * the "## Your ledger" section: the seat's per-resource yields, its running
    per-resource totals, and its assigned objective line.  It is dropped
    whole rather than field by field.
  * the board's YOUR-VALUE column: in this variant it is the reference
    ("appraised worth") column, the sum of the three private columns.
  * seat identity: "you" becomes "P-target", "their" becomes "the
    partner's", and so on.

The observer system block is the acting system block with the Mandate
paragraph replaced by `PREDICTION_MANDATE` and the resource briefing put in
the third person.  It names the objective menu and never an assignment.

This module provides the view only.  It does not call a model, collect
forecasts, or score them.

Ported from `ledger-experiments/ledger_v2_bridge.py` (`predictor_system_v2`,
`redact_user_v2`) in self-other-prediction-smoke-tests; the bytes are
identical.  `PREDICTION_MANDATE` and `redact_board` are the default game's
(`ledger.reader.views`), as in the original.
"""
from __future__ import annotations

import re

from ...reader.views import PREDICTION_MANDATE, redact_board
from ...render.board import render_board
from ...render.render import DEFAULT_MANDATE
from .render import V2_ADDENDUM, system_block_v2
from .scenario import ScenarioV2

# The observer's copy of the resource and objective briefing.  Same facts as
# `render.V2_ADDENDUM`, in the third person, because the observer is not a
# player.
V2_ADDENDUM_OBSERVER = """
## Resources (this game)

Finished jobs pay in three separate resources, not one number:

  CASH       money. This is the only resource that moves between the agents:
             deal payments and penalties are cash. An account is cash.
  MATERIALS  stock an agent holds. Nothing can buy it; it comes only from
             jobs getting finished.
  STANDING   an agent's record. Finishing what they signed for adds to it;
             breaking a deal, or leaving a signed job undone at the deadline,
             takes from it. Nothing else touches it.

Every job pays each agent some of each. Both agents' splits are private and
neither is shown to you.

## Objectives

P-target and its partner were each privately assigned ONE of those three
resources to maximise. Only that resource counts for that agent at the end;
the other two are worth nothing to it. Neither agent is told the other's
assignment, and you are not told either one.

Scoring covers the first {scored} turns of the {deadline}-turn game.
"""

def observer_system(sv: ScenarioV2, message_cap: int = 40,
                    mandate: str = DEFAULT_MANDATE) -> str:
    """The acting system block with the Mandate swapped for
    `PREDICTION_MANDATE` and the resource briefing in the third person.

    Built by splicing, not by re-authoring: the rules the observer reads are
    the same bytes the seat played under, minus the two passages that
    address it as a player.  `mandate` selects which acting block is spliced;
    the paper used the default ("principal").
    """
    base = system_block_v2(sv, mandate, message_cap).decode("utf-8")
    addendum = V2_ADDENDUM.format(scored=sv.scored_turns, deadline=sv.D)
    if not base.endswith(addendum):
        raise AssertionError("system block no longer ends with V2_ADDENDUM; "
                             "the observer splice would silently drop rules")
    base = base[: -len(addendum)]
    head, sep, rest = base.partition("## Mandate\n")
    if not sep:
        raise AssertionError("system block lost its Mandate section")
    _, blank, tail = rest.partition("\n\n")
    if not blank:
        raise AssertionError("Mandate paragraph not blank-line terminated")
    return (head + "## Mandate\n" + PREDICTION_MANDATE + "\n\n" + tail
            + V2_ADDENDUM_OBSERVER.format(scored=sv.scored_turns,
                                          deadline=sv.D))


_LEDGER_SECTION = re.compile(r"\n## Your ledger\n.*?(?=\n## |\Z)", re.S)


def observer_board(sv: ScenarioV2, state, seat: int) -> str:
    """Seat `seat`'s board with every private number and the objective
    removed, relabelled for an observer.

    The history transcript is deliberately not included: callers that want
    to show an observer the seat's past add it as their own block, so that
    the board itself is the same whatever history format they choose.
    """
    body = _LEDGER_SECTION.sub("", render_board(state, seat))
    if "YOUR ASSIGNED OBJECTIVE" in body or "YOUR-MATERIALS" in body:
        raise AssertionError("private ledger survived redaction")
    return redact_board(body)
