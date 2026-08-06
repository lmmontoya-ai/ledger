"""Board renderer (§7.2).  Pure: state -> str.

Every rendered value passes through the field-manifest guard; rendering a
field outside spec/templates.v1/board.manifest.json raises rather than
emitting.  The partner's private value column is not in the manifest, so it
is structurally impossible to render it.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATES_DIR = REPO_ROOT / "spec" / "templates.v1"

_manifests: dict[str, set] = {}


class RenderFieldError(Exception):
    pass


def manifest_fields(template: str) -> set:
    if template not in _manifests:
        with open(TEMPLATES_DIR / f"{template}.manifest.json", "r", encoding="utf-8") as f:
            _manifests[template] = set(json.load(f)["fields"])
    return _manifests[template]


def _guard(template: str):
    allowed = manifest_fields(template)

    def F(name, value):
        if name not in allowed:
            raise RenderFieldError(f"field {name!r} is outside the {template} manifest")
        return value
    return F


def render_board(state, viewer: int) -> str:
    sc = state.scenario
    F = _guard("board")
    you = F("viewer_seat", viewer)
    them = 3 - you

    def rel(seat: int) -> str:
        return "you" if seat == you else "them"

    tick = F("tick", min(state.tick, sc.D))
    D = F("deadline", sc.D)
    if F("over", state.over):
        move = "episode over"
    else:
        move = "your move" if F("mover_seat", state.mover) == you else "their move"
    lines = [f"LEDGER · tick {tick}/{D} · {move} · you are P{you}", ""]

    spent = F("pot_spent_display", sc.B - state.pot_left)
    lines.append(
        f"POT {F('budget_total', sc.B)}: spent {spent}"
        f" · your draws {F('draws_you', state.draws[you-1])}/{F('draw_cap_you', sc.u[you-1])}"
        f" · their draws {F('draws_them', state.draws[them-1])}/{F('draw_cap_them', sc.u[them-1])}"
        f" · left {F('pot_left', state.pot_left)}")
    lines.append(f"         everything left at tick {D} is destroyed")
    lines.append(
        f"SLOTS    you {F('slots_left_you', sc.kappa[you-1]-state.caps_used[you-1])}"
        f"/{F('slots_total_you', sc.kappa[you-1])} left"
        f" · them {F('slots_left_them', sc.kappa[them-1]-state.caps_used[them-1])}"
        f"/{F('slots_total_them', sc.kappa[them-1])} left")
    lines.append(
        f"ACCOUNT  you {F('account_you', state.accounts[you-1])}"
        f" · them {F('account_them', state.accounts[them-1])}")
    lines.append("")
    lines.append("JOB  YOUR-COST  THEIR-COST  YOUR-VALUE  NEEDS  STATUS")

    locked_to: dict[int, int] = {}
    optional_for: dict[int, int] = {}
    for c in state.contracts.values():
        if c.status == "locked":
            for j in c.unexecuted_jobs():
                locked_to[j] = c.assign[j]
        for s in (1, 2):
            for j in c.optional_jobs_of(s):
                optional_for[j] = s

    for j in F("job_numbers", list(sc.jobs())):
        needs = ",".join(str(p) for p in F("job_needs", sc.prereqs[j - 1])) or "-"
        if j in state.done:
            seat, t = state.done[j]
            status = f"DONE by {rel(F('job_done_by', seat))}, tick {F('job_done_tick', t)}"
        else:
            status = "open"
        marker = ""
        if j in locked_to:
            marker = f"<- locked to {rel(F('job_locked_to', locked_to[j]))}"
        elif j in optional_for:
            marker = f"<- optional for {rel(F('job_optional_for', optional_for[j]))}"
        elif j in state.draw_funding and not state.draw_funding[j][2] and j not in state.done:
            marker = f"<- drawn by {rel(F('job_drawn_by', state.draw_funding[j][0]))}"
        row = (f"{j:>2}  {F('job_cost_you', sc.cost(you, j)):>7}"
               f"  {F('job_cost_them', sc.cost(them, j)):>9}"
               f"  {F('job_value_you', sc.value(you, j)):>10}"
               f"  {needs:>5}  {status}")
        if marker:
            row = f"{row:<58} {marker}" if len(row) < 58 else f"{row}  {marker}"
        lines.append(row)

    lines.append("")
    lines.append("CONTRACTS")
    shown = 0
    for cid in sorted(state.contracts):
        c = state.contracts[cid]
        cid_s = F("contract_id", c.cid)
        status = F("contract_status", c.status)

        def terms(jobs, optional=False):
            opt = " optional" if optional else ""
            return "  ·  ".join(
                f"job {j} -> {rel(F('contract_assign', c.assign[j]))}{opt},"
                f" funded {F('contract_fund', c.fund[j])}" for j in jobs)

        def pay_lines():
            out = []
            for p in c.pay:
                if p.executed or p.cancelled:
                    continue
                pp = F("contract_pay", p)
                subj = "you pay them" if pp.from_ == you else "they pay you"
                out.append(f"      {subj} {pp.amount} at tick {pp.tick}")
            return out

        if status == "locked":
            head = f" C{cid_s} LOCKED (tick {F('contract_accept_tick', c.accept_tick)})"
            body = terms(sorted(c.assign))
            lo, hi = F("contract_window", c.window_bounds(sc.D, sc.r))
            if not state.over and lo <= state.tick <= hi:
                body += f"  ·  cancel window t{lo}-t{hi}"
            lines.append(f"{head}   {body}")
            lines.extend(pay_lines())
            shown += 1
        elif c.is_offer_live(state.tick) and not state.over:
            lines.append(f" C{cid_s} OFFERED by {rel(F('contract_proposer', c.proposer))},"
                         f" expires tick {F('contract_expires', c.expires)}")
            lines.append(f"      {terms(sorted(c.assign))}")
            lines.extend(pay_lines())
            shown += 1
        elif status == "reneged":
            opt = c.optional_jobs_of(3 - c.reneged_by)
            if opt:
                head = (f" C{cid_s} RENEGED by {rel(F('contract_reneged_by', c.reneged_by))}"
                        f" (tick {F('contract_renege_tick', c.renege_tick)})")
                lines.append(f"{head}   {terms(opt, optional=True)}")
                shown += 1
    if shown == 0:
        lines.append(" none")
    return "\n".join(lines)
