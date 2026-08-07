"""History renderer v2 (§7.3): one line per past turn, fixed grammar
(spec/templates.v2/history.grammar.txt).  Action labels are frozen (they
match the tool names); everything around them is plain language.  Engine
consequences render in square brackets on the line that caused them.
Pure: (final state, events, viewer) -> str.
"""
from __future__ import annotations

from ..core.contracts import friction_refund
from .board import _guard


def _contract_terms(c, viewer: int, F) -> str:
    def rel(seat):
        return "you" if seat == viewer else "them"
    # "you do job 3 (16 from pot)", never "job 3 -> you": the arrow read as
    # RECEIVING the job and the money, when an assignment is an obligation to
    # spend a slot doing the work, funded from the shared budget.
    parts = [f"{rel(F('contract_assign', c.assign[j]))} do job {j}"
             f" ({F('contract_fund', c.fund[j])} from pot)"
             for j in sorted(c.assign)]
    for p in c.pay:
        pp = F("contract_pay", p)
        if pp.from_ == c.proposer:
            parts.append(f"pay {rel(pp.to)} {pp.amount} at turn {pp.tick}")
        else:
            parts.append(f"{rel(pp.from_)} pay {pp.amount} at turn {pp.tick}")
    return " · ".join(parts)


def render_history(state, events, viewer: int) -> str:
    """`state` is the fold of `events` (the current position)."""
    sc = state.scenario
    F = _guard("history")
    F("viewer_seat", viewer)

    def rel(seat):
        return "you" if seat == viewer else "them"

    def pays_phrase(payer: int, amount: int) -> str:
        return (f"you pay them {amount}" if payer == viewer
                else f"they pay you {amount}")

    # contracts created per turn (for PROPOSE/COUNTER lines)
    opened_at = {}
    for cid in sorted(state.contracts):
        opened_at[state.contracts[cid].tick_opened] = state.contracts[cid]

    lines = ["HISTORY"]
    for ev in events:
        t = F("tick", ev.tick)
        who = rel(F("actor_seat", ev.seat))
        name = F("action_name", ev.action.name)
        rest = ""
        notes = []
        args = ev.action.args
        if name in ("PROPOSE", "COUNTER"):
            c = opened_at[ev.tick]
            if name == "COUNTER":
                rest = (f"deal {F('offer_id', int(args['offer_id']))}"
                        f" -> deal {F('contract_id', c.cid)}: ")
            else:
                rest = f"deal {F('contract_id', c.cid)}: "
            rest += _contract_terms(c, viewer, F)
        elif name in ("ACCEPT", "REJECT"):
            cid = F("offer_id", int(args["offer_id"]))
            rest = f"deal {cid}"
            if name == "ACCEPT":
                lo, hi = F("window_bounds", (ev.tick + 1, min(ev.tick + sc.r, sc.D)))
                if lo <= hi:
                    notes.append(f"deal {cid} binds; cancel window turns {lo}-{hi}")
                else:
                    notes.append(f"deal {cid} binds")
        elif name in ("CANCEL", "RENEGE"):
            cid = F("contract_id", int(args["contract_id"]))
            c = state.contracts[cid]
            rest = f"deal {cid}"
            if name == "CANCEL":
                refund = F("cancel_refund",
                           sum(c.fund[j] for j in c.assign if j not in c.executed_jobs))
                notes.append(f"deal {cid} cancelled; {refund} back to pot;"
                             f" {pays_phrase(ev.seat, F('cancel_fee', sc.eps))}")
            else:
                refund = F("renege_refund",
                           sum(friction_refund(c.fund[j]) for j in c.assign
                               if c.assign[j] == ev.seat and j not in c.executed_jobs))
                notes.append(f"deal {cid} broken; {refund} back to pot;"
                             f" {pays_phrase(ev.seat, F('renege_compensation', sc.p // 2))}")
        elif name == "DRAW":
            rest = (f"{F('draw_amount', int(args['amount']))} from pot"
                    f" for job {F('draw_job', int(args['job']))}")
        elif name == "EXECUTE":
            rest = f"job {F('execute_job', int(args['job']))}"
            notes.append("done")
        elif name == "TRANSFER":
            rest = (f"{F('transfer_amount', int(args['amount']))} to "
                    f"{rel(F('transfer_to', int(args['to'])))}")
        elif name in ("CHAT", "REFUSE"):
            text = F("message_text", args.get("text", ""))
            rest = f'"{text}"'

        # engine consequences at this turn
        for cid in sorted(state.contracts):
            c = state.contracts[cid]
            for p in c.pay:
                if F("pay_executed", p.executed) and p.executed_tick == ev.tick \
                        and not (state.over and ev.tick == state.final_tick):
                    notes.append(f"deal {cid} paid {rel(p.to)} {p.amount}")
            if c.status == "expired" and c.expires == ev.tick and F("offer_expired", True):
                notes.append(f"deal {cid} expired")
            if (c.accept_tick is not None and c.status in ("locked", "reneged")
                    and min(c.accept_tick + sc.r, sc.D) == ev.tick
                    and c.accept_tick < ev.tick and F("window_closed", True)):
                notes.append("cancel window closed")
        if F("invalid_flag", ev.invalid):
            notes.append("invalid")
        if F("truncated_flag", ev.truncated):
            notes.append("truncated")

        if name in ("CHAT", "REFUSE"):
            # single-space separator keeps a maximal message line inside the
            # §7.6 token bound; alignment padding costs real tokens
            base = f"turn {t}  {who:<6}{name} {rest}".rstrip()
        else:
            name_field = name.ljust(8) if len(name) < 8 else name + " "
            base = f"turn {t}  {who:<6}{name_field}{rest}".rstrip()
        if notes:
            base = f"{base}    [{'; '.join(notes)}]"
        lines.append(base)
    return "\n".join(lines)
