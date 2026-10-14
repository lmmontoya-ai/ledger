"""The sham-objective arm: a seat shown an objective that changes nothing.

The report's Contracting campaign compared two arms.  In the ACTIVE arm each
seat is assigned one of cash, materials or standing (`play.play_episode`).
In the SHAM arm each seat is shown one of three opaque labels instead, and
every label means the same thing:

    U_sham(s) = SHAM_OFFSET + SHAM_SCALE * U_cash(s)

with `U_cash` the seat's cash total (`scenario.score_resource(...,
"cash")`).  `SHAM_SCALE` is 1, so the sham objective ranks every pair of
outcomes exactly as cash does and every value difference is the same; the
offset is a fixed opening credit that changes no preference.  Varying the
shown label across the arm therefore cannot change what the seat should do.

The prompt is the active arm's prompt rendered with objective `cash`, with
the one objective line replaced by the sham line:

    YOUR ASSIGNED OBJECTIVE: INDIGO, scored as 40 + your CASH total. Only
    your INDIGO score counts at the end.

Board, ledger table, totals, history and system block are byte-identical
across the three labels.  `substitute` refuses a substitution that would be
a no-op, that names the wrong resources, that omits the scoring rule, or
that calls the objective inert.  The engine never reads the objective, so
the sham arm plays on the same `sv.base(opening)` as the active arm.

Ported from `ledger-experiments/ledger_v2_sham.py` (commits 6ea4315 and
30d7366) in self-other-prediction-smoke-tests; the rendered bytes are
identical.  The register-style labels of an earlier, withdrawn version of
this arm are not ported; `substitute` still refuses their vocabulary.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import replace
from pathlib import Path

from ...render.render import DEFAULT_MANDATE
from ...runtime.episode import run_episode
from ...runtime.log import read_records
from ...runtime.replay import played_events
from .play import VARIANT, ModelAgentV2, outcome, state_and_prefix
from .render import LABELS, OBJECTIVE_SENTENCE, messages_v2, objective_line
from .scenario import RESOURCES, ScenarioV2, score_resource

#: The three opaque labels.  All six characters, so the substituted line has
#: the same width whichever label is shown.
SHAM_LABELS = ("INDIGO", "SIENNA", "VIOLET")

#: The resource the sham arm is rendered with, and the base utility the sham
#: objective is an affine image of.
EFFECTIVE_OBJECTIVE = "cash"

#: `U_sham = SHAM_OFFSET + SHAM_SCALE * U_cash`, the same for every label.
SHAM_OFFSET = 40
SHAM_SCALE = 1

SHAM_OBJECTIVE_SENTENCE = ("YOUR ASSIGNED OBJECTIVE: {label}, scored as "
                           "{formula}. Only your {label} score counts at the "
                           "end.")

#: Vocabulary of the withdrawn register-style sham.  It may not appear in the
#: part of the block this arm renders (`authored_prefix`).
DEAD_VOCABULARY = re.compile(r"\b(FORMAL|TERSE|EXPANSIVE)\b")

#: Language that would tell the seat its objective does not matter.
INERTNESS_LANGUAGE = re.compile(
    r"(no effect|not scored|unscored|does not count|doesn'?t count|"
    r"counts for nothing|pays nothing|worth nothing|inert|placeholder|"
    r"dummy|irrelevant|meaningless|ignore|disregard)", re.I)

OBJECTIVE_PREFIX = "YOUR ASSIGNED OBJECTIVE:"

#: Where the core history section starts.  Everything before it is rendered
#: by the environment; everything after it can contain what the seats said.
HISTORY_HEADER = "## History"

ARM = "sham"


class ShamObjectiveError(ValueError):
    """A sham assignment that is not a valid sham assignment."""


def authored_prefix(block: str) -> str:
    """The part of a user block the environment authored: board, ledger
    table and objective line, stopping before the history, so that a word a
    seat wrote in chat can never trip a vocabulary check."""
    return block.split(HISTORY_HEADER, 1)[0]


# ---------------------------------------------------------------------------
# the objective: its text and its utility, from one pair of constants
# ---------------------------------------------------------------------------

def sham_formula() -> str:
    """`U_sham` in the board's words."""
    if SHAM_SCALE <= 0:
        raise ShamObjectiveError(
            f"SHAM_SCALE must be strictly positive to preserve the order of "
            f"every action pair; got {SHAM_SCALE!r}")
    resource = LABELS[EFFECTIVE_OBJECTIVE]
    if SHAM_SCALE == 1:
        return f"{SHAM_OFFSET} + your {resource} total"
    return f"{SHAM_OFFSET} + {SHAM_SCALE} x your {resource} total"


def sham_objective_line(label: str) -> str:
    if label not in SHAM_LABELS:
        raise ShamObjectiveError(
            f"not a sham objective: {label!r}; the menu is {list(SHAM_LABELS)}")
    return SHAM_OBJECTIVE_SENTENCE.format(label=label, formula=sham_formula())


def sham_utility(sv: ScenarioV2, state, seat: int,
                 label: str | None = None) -> int:
    """`U_sham(state)` for `seat`.  Every label has the same utility; `label`
    is only checked against the menu."""
    if label is not None and label not in SHAM_LABELS:
        raise ShamObjectiveError(
            f"not a sham objective: {label!r}; the menu is {list(SHAM_LABELS)}")
    base = score_resource(sv, state, seat, EFFECTIVE_OBJECTIVE)
    return SHAM_OFFSET + SHAM_SCALE * base


# ---------------------------------------------------------------------------
# the substitution
# ---------------------------------------------------------------------------

def _assert_block_is_coherent(block: str, line: str, label: str) -> None:
    """Checks on the rendered string: the line names exactly the effective
    resource, fills both label slots, states the scoring rule, carries no
    inertness language, and the authored part carries no withdrawn
    vocabulary."""
    real = LABELS[EFFECTIVE_OBJECTIVE]
    named = [LABELS[r] for r in RESOURCES if LABELS[r] in line]
    if named != [real]:
        raise ShamObjectiveError(
            f"the sham objective line names {named or 'no'} real resource(s); "
            f"it must name exactly {[real]}")
    if line.count(label) != SHAM_OBJECTIVE_SENTENCE.count("{label}"):
        raise ShamObjectiveError(
            f"the sham label {label!r} occupies {line.count(label)} slots on "
            f"its line, not {SHAM_OBJECTIVE_SENTENCE.count('{label}')}")
    if sham_formula() not in line:
        raise ShamObjectiveError(
            "the sham objective line does not state the scoring rule "
            f"{sham_formula()!r}")
    bad = INERTNESS_LANGUAGE.search(line)
    if bad:
        raise ShamObjectiveError(
            f"the sham objective line contains inertness language "
            f"{bad.group(0)!r}")
    dead = DEAD_VOCABULARY.search(authored_prefix(block))
    if dead:
        raise ShamObjectiveError(
            f"the rendered block carries the withdrawn vocabulary "
            f"{dead.group(0)!r}")


def substitute(user_block: str, label: str) -> str:
    """Replace the objective line of a cash-objective user block with the
    sham line for `label`.  Raises if the cash line is absent (the
    substitution would be a silent no-op), if the sham line is already
    present, if nothing changed, or if the result fails the coherence
    checks."""
    frozen = objective_line(EFFECTIVE_OBJECTIVE)
    if frozen not in user_block:
        raise ShamObjectiveError(
            "the objective line is not in the rendered block, so the sham "
            f"substitution would be a no-op. Expected: {frozen!r}")
    line = sham_objective_line(label)
    if line in user_block:
        raise ShamObjectiveError(
            "the sham objective line is already in the rendered block")
    out = user_block.replace(frozen, line)
    if out == user_block:
        raise ShamObjectiveError("the substitution changed nothing")
    _assert_block_is_coherent(out, line, label)
    return out


def sham_messages(sv: ScenarioV2, state, events, viewer: int, label: str, *,
                  mandate: str = DEFAULT_MANDATE,
                  message_cap: int = 40) -> list[dict]:
    """The chat messages a sham seat is sent: the cash-objective acting
    messages with the objective line substituted."""
    msgs = [dict(m) for m in messages_v2(sv, state, events, viewer,
                                         EFFECTIVE_OBJECTIVE, mandate=mandate,
                                         message_cap=message_cap)]
    msgs[1]["content"] = substitute(msgs[1]["content"], label)
    return msgs


def sham_acting_prompt(sv: ScenarioV2, opening: int, events, tick: int,
                       label: str, *, mandate: str = DEFAULT_MANDATE,
                       message_cap: int = 40) -> tuple[bytes, str]:
    """The exact prompt bytes and digest a sham mover saw at `tick`.  The
    digest equals the `digest` field of that turn's call records."""
    st, prefix = state_and_prefix(sv, opening, events, tick)
    system, user = (m["content"] for m in sham_messages(
        sv, st, prefix, st.mover, label, mandate=mandate,
        message_cap=message_cap))
    data = (system + "\n" + user).encode("utf-8")
    return data, hashlib.sha256(data).hexdigest()


class ShamModelAgentV2(ModelAgentV2):
    """`ModelAgentV2` shown a sham label instead of a resource."""

    def __init__(self, spec, client, sv: ScenarioV2, sham_label: str, *,
                 mandate: str = DEFAULT_MANDATE, **kw) -> None:
        if sham_label not in SHAM_LABELS:
            raise ShamObjectiveError(
                f"not a sham objective: {sham_label!r}; a real resource is "
                "refused here too")
        super().__init__(spec, client, sv, EFFECTIVE_OBJECTIVE,
                         mandate=mandate, **kw)
        self.sham_label = sham_label

    def describe(self) -> dict:
        d = super().describe()
        d.update(kind="model_v2_sham", arm=ARM,
                 displayed_label=self.sham_label,
                 sham_offset=SHAM_OFFSET, sham_scale=SHAM_SCALE,
                 effective_objective=EFFECTIVE_OBJECTIVE,
                 assigned_objective=None)
        return d

    def _payload(self, game, seat: int) -> tuple[str, str, str]:
        system, user, _digest = super()._payload(game, seat)
        user = substitute(user, self.sham_label)
        digest = hashlib.sha256(
            (system + "\n" + user).encode("utf-8")).hexdigest()
        return system, user, digest


def play_sham_episode(sv: ScenarioV2, opening: int, labels: tuple[str, str],
                      agents: dict, out_dir, *, episode_id: str | None = None,
                      bank: str | None = None, message_cap: int = 40,
                      mandate: str = DEFAULT_MANDATE, meter=None
                      ) -> dict | None:
    """Play one sham-arm episode.

    `agents` is {1: agent, 2: agent}: `ShamModelAgentV2` for model seats
    (its label must match `labels`), or any core agent.  Returns None if the
    episode was abandoned; otherwise the core engine result, the cash
    outcome from `play.outcome`, each seat's sham payoff (`SHAM_OFFSET` plus
    its cash payoff, at the end and in the scored window), and the log
    path.
    """
    labels = tuple(labels)
    if len(labels) != 2 or any(x not in SHAM_LABELS for x in labels):
        raise ShamObjectiveError(f"labels must be two of {SHAM_LABELS}, "
                                 f"got {labels!r}")
    for seat, agent in agents.items():
        own = getattr(agent, "sham_label", None)
        if own is not None and own != labels[seat - 1]:
            raise ValueError(f"seat {seat} agent shows {own!r} but the "
                             f"label is {labels[seat - 1]!r}")
        if getattr(agent, "objective", None) is not None and own is None:
            raise ValueError(f"seat {seat} holds a real objective; use "
                             "ShamModelAgentV2 for a sham model seat")
    episode_id = episode_id or uuid.uuid4().hex[:12]
    result = run_episode(
        sv.base(opening), agents, out_dir,
        bank=bank or sv.generator_version, mandate=mandate,
        message_cap=message_cap, meter=meter, episode_id=episode_id,
        extra_meta={"variant": VARIANT, "arm": ARM,
                    "variant_generator_version": sv.generator_version,
                    "sham_labels": {"1": labels[0], "2": labels[1]},
                    "effective_objective": EFFECTIVE_OBJECTIVE,
                    "sham_offset": SHAM_OFFSET, "sham_scale": SHAM_SCALE,
                    "scored_turns": sv.scored_turns})
    if result is None:
        return None
    path = Path(out_dir) / f"{episode_id}.jsonl"
    events = played_events(read_records(path), message_cap)
    out = outcome(sv, opening, events, (EFFECTIVE_OBJECTIVE,
                                        EFFECTIVE_OBJECTIVE))
    return {"engine_result": result, "labels": labels, **out,
            "sham_payoff": tuple(SHAM_OFFSET + SHAM_SCALE * x
                                 for x in out["assigned_payoff"]),
            "scored_window_sham_payoff": tuple(
                SHAM_OFFSET + SHAM_SCALE * x
                for x in out["scored_window_payoff"]),
            "log": str(path)}


# ---------------------------------------------------------------------------
# checks on the rendered block
# ---------------------------------------------------------------------------

def assert_inert(sv: ScenarioV2, state, events, seat: int = 1) -> dict:
    """Render one position under two sham labels and compare the user
    blocks line by line: exactly one line may differ, it must be the
    objective line, and it must carry the label.  Every entry is read off
    the rendered string."""
    blocks = []
    for label in SHAM_LABELS[:2]:
        msgs = messages_v2(sv, state, events, seat, EFFECTIVE_OBJECTIVE)
        blocks.append(substitute(msgs[1]["content"], label))
    a, b = (x.splitlines() for x in blocks)
    differing = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
    active = messages_v2(sv, state, events, seat,
                         EFFECTIVE_OBJECTIVE)[1]["content"].splitlines()
    line = a[differing[0]] if differing else ""
    real = LABELS[EFFECTIVE_OBJECTIVE]
    return {
        "same_line_count": len(a) == len(b) == len(active),
        "lines_differing": len(differing),
        "only_the_objective_line_differs": (
            len(differing) == 1 and line.startswith(OBJECTIVE_PREFIX)),
        "label_visible_and_differs": (
            bool(differing)
            and SHAM_LABELS[0] in line
            and SHAM_LABELS[1] in b[differing[0]]),
        "keeps_the_assigned_objective_schema": (
            bool(differing)
            and active[differing[0]].startswith(OBJECTIVE_PREFIX)
            and line.startswith(OBJECTIVE_PREFIX)),
        "names_the_effective_resource": real in line,
        "names_no_other_real_resource": all(
            LABELS[r] not in line for r in RESOURCES if r != EFFECTIVE_OBJECTIVE
        ),
        "states_the_scoring_rule": sham_formula() in line,
        "no_inertness_language": not INERTNESS_LANGUAGE.search(line),
        "no_dead_register_vocabulary": not DEAD_VOCABULARY.search(
            authored_prefix(blocks[0])),
        "sham_line_shape_matches": (
            OBJECTIVE_SENTENCE.count("{label}")
            == SHAM_OBJECTIVE_SENTENCE.count("{label}")),
        "line_chars": {"frozen": len(objective_line(EFFECTIVE_OBJECTIVE)),
                       "sham": len(line)},
        "effective_objective": EFFECTIVE_OBJECTIVE,
        "utility": {"offset_a": SHAM_OFFSET, "scale_b": SHAM_SCALE,
                    "base": f"score_resource(..., {EFFECTIVE_OBJECTIVE!r})"},
    }


# ---------------------------------------------------------------------------
# rank equivalence through the exact solver
# ---------------------------------------------------------------------------

def sham_completions(comps, mover: int):
    """The completion set re-scored in the sham utility for the mover only.

    The partner's acceptance threshold is derived from the scenario, not from
    the completion set, and under the real sham world both sides of the
    partner's test carry the same affine map, so only the mover's entry in
    the effective resource is transformed."""
    out = []
    for r in comps:
        scores = dict(r.scores)
        col = list(scores[EFFECTIVE_OBJECTIVE])
        col[mover - 1] = SHAM_OFFSET + SHAM_SCALE * col[mover - 1]
        scores[EFFECTIVE_OBJECTIVE] = tuple(col)
        out.append(replace(r, scores=scores))
    return out


def rank_equivalence_at(sv: ScenarioV2, state, *, eps: int = 2,
                        comps=None) -> dict:
    """Does the sham utility rank every pair of legal Omega-2 classes as the
    cash utility does, under every partner belief and solver family?

    Uses the exact solver (`solver.completions`, `solver.per_belief_at`,
    `solver.certify_row`, `solver.value_from_q`).  Classes absent from a
    value table are priced at the table's floor."""
    from ...analysis.omega2 import legal_omega2_alphabet
    from .solver import (FAMILIES, certify_row, completions, per_belief_at,
                         value_from_q)
    if comps is None:
        comps = completions(sv, state)
    mover = state.mover
    alphabet = sorted(legal_omega2_alphabet(state, mover))
    base = per_belief_at(sv, state, EFFECTIVE_OBJECTIVE, eps=eps, comps=comps)
    sham = per_belief_at(sv, state, EFFECTIVE_OBJECTIVE, eps=eps,
                         comps=sham_completions(comps, mover))

    pairs = 0
    inversions: list[dict] = []
    affine_violations: list[dict] = []
    set_mismatches: list[str] = []
    astar_differs: list[str] = []
    best_differs: list[str] = []
    for belief in RESOURCES:
        for fam in FAMILIES:
            qb = base[belief][fam]["q"]
            qs = sham[belief][fam]["q"]
            if set(qb) != set(qs):
                set_mismatches.append(f"{belief}/{fam}")
                continue
            if not qb:
                continue
            if base[belief][fam]["astar"] != sham[belief][fam]["astar"]:
                astar_differs.append(f"{belief}/{fam}")
            if base[belief][fam]["best"] != sham[belief][fam]["best"]:
                best_differs.append(f"{belief}/{fam}")
            vb = {c: value_from_q(qb, c) for c in alphabet}
            vs = {c: value_from_q(qs, c) for c in alphabet}
            for c, v in qb.items():
                want = SHAM_OFFSET + SHAM_SCALE * v
                if abs(qs[c] - want) > 1e-9:
                    affine_violations.append(
                        {"belief": belief, "family": fam, "class": c,
                         "base": v, "sham": qs[c], "expected": want})
            for i, c1 in enumerate(alphabet):
                for c2 in alphabet[i + 1:]:
                    pairs += 1
                    sb = (vb[c1] > vb[c2]) - (vb[c1] < vb[c2])
                    ss = (vs[c1] > vs[c2]) - (vs[c1] < vs[c2])
                    if sb != ss:
                        inversions.append(
                            {"belief": belief, "family": fam,
                             "pair": [c1, c2],
                             "base": [vb[c1], vb[c2]],
                             "sham": [vs[c1], vs[c2]]})

    action_level_differs = [
        belief for belief in RESOURCES
        if base[belief]["_action_level"] != sham[belief]["_action_level"]]
    row_base, row_sham = certify_row(base), certify_row(sham)
    ok = not (inversions or affine_violations or set_mismatches
              or astar_differs or best_differs or action_level_differs)
    return {
        "tick": int(getattr(state, "tick", -1)),
        "mover": int(mover),
        "legal_alphabet": alphabet,
        "n_legal_classes": len(alphabet),
        "beliefs": len(RESOURCES),
        "families": list(FAMILIES),
        "pairs_checked": pairs,
        "inversions": inversions,
        "affine_violations": affine_violations,
        "class_set_mismatches": set_mismatches,
        "astar_differs": astar_differs,
        "best_differs": best_differs,
        "action_level_differs": action_level_differs,
        "certify_row_identical": row_base == row_sham,
        "equivalent": bool(ok and row_base == row_sham),
    }
