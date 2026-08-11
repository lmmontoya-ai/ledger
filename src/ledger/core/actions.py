"""Action validation and application, driven by spec/actions.v1.json.

Each action's legality is the conjunction of named predicates listed in the
spec file; its effect is the named effect function.  Both registries live
here; the spec file is the single definition of which predicates and effects
each action uses.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from .contracts import Contract, Pay
from .events import Action, Event

if TYPE_CHECKING:
    from .fold import State

REPO_ROOT = Path(__file__).resolve().parents[3]
_SPEC_CACHE: dict | None = None


def action_spec() -> dict:
    global _SPEC_CACHE
    if _SPEC_CACHE is None:
        with open(REPO_ROOT / "spec" / "actions.v2.json", "r", encoding="utf-8") as f:
            _SPEC_CACHE = json.load(f)
        # every referenced predicate/effect must exist: one definition of everything
        for name, spec in _SPEC_CACHE["actions"].items():
            for pred in spec["legality"]:
                if pred not in PREDICATES:
                    raise RuntimeError(f"spec references unknown predicate {pred!r} for {name}")
            if spec["effect"] not in EFFECTS:
                raise RuntimeError(f"spec references unknown effect {spec['effect']!r} for {name}")
    return _SPEC_CACHE


class IllegalAction(Exception):
    """Structured legality error: .reason is the engine's specific reason."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------------------
# contract-draft parsing
# ---------------------------------------------------------------------------

def parse_contract(state: "State", args: dict) -> tuple[dict[int, int], dict[int, int], list[Pay], int]:
    c = args.get("contract")
    if not isinstance(c, dict):
        raise IllegalAction("contract must be an object")
    try:
        assign = {int(j): int(s) for j, s in dict(c.get("assign", {})).items()}
        fund = {int(j): int(a) for j, a in dict(c.get("fund", {})).items()}
        # model-facing field is "turn" (spec tools.v2.1); "tick" accepted so
        # event logs written before the rename still replay byte-for-byte
        pays = [Pay(int(p["from"]), int(p["to"]), int(p["amount"]),
                    int(p["turn"] if "turn" in p else p["tick"]))
                for p in list(c.get("pay", []))]
        expires = int(c["expires"])
    except (KeyError, TypeError, ValueError) as e:
        raise IllegalAction(f"malformed contract: {e}")
    return assign, fund, pays, expires


# ---------------------------------------------------------------------------
# legality predicates  (return None if ok, else a reason string)
# ---------------------------------------------------------------------------

def _p_episode_live(state, seat, args):
    if state.over:
        return "episode is over"
    return None


def _p_contract_wellformed(state, seat, args):
    sc = state.scenario
    try:
        assign, fund, pays, expires = parse_contract(state, args)
    except IllegalAction as e:
        return e.reason
    if not assign and not pays:
        return "contract must contain at least one assignment or payment"
    for j, s in assign.items():
        if not (1 <= j <= sc.K):
            return f"job {j} does not exist"
        if s not in (1, 2):
            return f"seat {s} is not a valid assignee"
        if j in state.done:
            return f"job {j} is already done"
    if set(fund) != set(assign):
        return "fund must cover exactly the assigned jobs"
    for j, amt in fund.items():
        if amt < sc.cost(assign[j], j):
            return f"job {j} funded {amt}, below seat {assign[j]}'s cost {sc.cost(assign[j], j)}"
    if sum(fund.values()) > sc.B:
        return "total funding exceeds the budget"
    from .welfare import w_star
    ws = max(w_star(sc), 1)
    cap = ws if sc.pay_cap is None else min(ws, sc.pay_cap)
    if pays and cap < 1:
        return "scheduled payments are disabled in this scenario"
    if sc.pay_cap is not None and sum(p.amount for p in pays) > cap:
        return f"scheduled payments exceed the per-deal total cap of {cap}"
    for p in pays:
        if p.from_ not in (1, 2) or p.to not in (1, 2) or p.from_ == p.to:
            return "payment parties must be the two seats"
        if not (1 <= p.amount <= cap):
            return f"payment amount must be between 1 and {cap}"
        if not (1 <= p.tick <= sc.D):
            return f"payment turn must be within 1..{sc.D}"
    if not (state.tick < expires <= sc.D):
        return f"expiry must be after turn {state.tick} and at most {sc.D}"
    return None


def _get_offer(state, args):
    oid = args.get("offer_id")
    try:
        oid = int(oid)
    except (TypeError, ValueError):
        return None, "offer_id must be an integer"
    c = state.contracts.get(oid)
    if c is None:
        return None, f"offer C{oid} does not exist"
    return c, None


def _p_offer_live(state, seat, args):
    c, err = _get_offer(state, args)
    if err:
        return err
    if not c.is_offer_live(state.tick):
        return f"offer C{c.cid} is not open"
    return None


def _p_is_non_proposer(state, seat, args):
    c, err = _get_offer(state, args)
    if err:
        return err
    if c.proposer == seat:
        return f"only the non-proposer may answer offer C{c.cid}"
    return None


def _p_payment_ticks_future(state, seat, args):
    c, _ = _get_offer(state, args)
    for p in c.pay:
        if p.tick <= state.tick:
            return f"scheduled payment at turn {p.tick} is not strictly after the accepting tick"
    return None


def _live_funded_jobs(state) -> dict[int, str]:
    """Jobs with live funding attached: locked obligations, reneged-optional
    reserves, and unspent draws."""
    out: dict[int, str] = {}
    for c in state.contracts.values():
        for s in (1, 2):
            for j in c.executable_jobs_of(s):
                out[j] = f"C{c.cid}"
    for j, (s, amt, spent) in state.draw_funding.items():
        if not spent:
            out[j] = f"draw by P{s}"
    return out


def _p_no_assignment_conflict(state, seat, args):
    c, _ = _get_offer(state, args)
    for j in c.assign:
        if j in state.done:
            return f"job {j} is already done"
        for other in state.contracts.values():
            if other.cid != c.cid and other.status == "locked" and j in other.unexecuted_jobs():
                return f"job {j} is already assigned under C{other.cid}"
    return None


def _p_no_funding_conflict(state, seat, args):
    c, _ = _get_offer(state, args)
    live = _live_funded_jobs(state)
    for j in c.assign:
        if j in live:
            return f"job {j} already has live funding ({live[j]})"
    return None


def _p_capacity_available(state, seat, args):
    c, _ = _get_offer(state, args)
    for s in (1, 2):
        existing = sum(len(k.obligations_of(s)) for k in state.contracts.values())
        new = sum(1 for j, a in c.assign.items() if a == s)
        if existing + new > state.scenario.kappa[s - 1] - state.caps_used[s - 1]:
            return f"seat P{s} lacks capacity for the new obligations"
    return None


def _p_pot_covers_funding(state, seat, args):
    c, _ = _get_offer(state, args)
    total = sum(c.fund.values())
    if total > state.pot_left:
        return f"pot cannot cover funding {total} on top of existing reserves"
    return None


def _p_schedule_feasible(state, seat, args):
    from .schedule import greedy_schedule_feasible
    c, _ = _get_offer(state, args)
    plan: dict[int, int] = {}
    for k in state.contracts.values():
        if k.status == "locked":
            for s in (1, 2):
                for j in k.obligations_of(s):
                    plan[j] = s
    plan.update(c.assign)
    if not greedy_schedule_feasible(state.scenario, plan, state.tick + 1,
                                    done=set(state.done)):
        return "accepting would make the combined obligations unschedulable by the deadline"
    return None


def _get_contract(state, args):
    cid = args.get("contract_id")
    try:
        cid = int(cid)
    except (TypeError, ValueError):
        return None, "contract_id must be an integer"
    c = state.contracts.get(cid)
    if c is None:
        return None, f"contract C{cid} does not exist"
    return c, None


def _p_contract_locked(state, seat, args):
    c, err = _get_contract(state, args)
    if err:
        return err
    if c.status != "locked":
        return f"contract C{c.cid} is not locked (status: {c.status})"
    return None


def _p_window_open(state, seat, args):
    c, _ = _get_contract(state, args)
    sc = state.scenario
    if not c.window_open_at(state.tick, sc.D, sc.r):
        lo, hi = c.window_bounds(sc.D, sc.r)
        return f"cooling-off window for C{c.cid} is t{lo}-t{hi}; it is not open now"
    return None


def _p_window_closed(state, seat, args):
    c, _ = _get_contract(state, args)
    sc = state.scenario
    if not c.window_closed_at(state.tick, sc.D, sc.r):
        return f"RENEGE is illegal during the cooling-off window; CANCEL is the window's exit"
    return None


def _p_job_exists(state, seat, args):
    try:
        j = int(args.get("job"))
    except (TypeError, ValueError):
        return "job must be an integer"
    if not (1 <= j <= state.scenario.K):
        return f"job {j} does not exist"
    return None


def _p_job_not_done(state, seat, args):
    j = int(args["job"])
    if j in state.done:
        return f"job {j} is already done"
    return None


def _p_amount_equals_own_cost(state, seat, args):
    j = int(args["job"])
    try:
        amt = int(args.get("amount"))
    except (TypeError, ValueError):
        return "amount must be an integer"
    cost = state.scenario.cost(seat, j)
    if amt != cost:
        return f"draw amount must equal your cost for job {j} exactly ({cost})"
    return None


def _p_within_draw_cap(state, seat, args):
    amt = int(args["amount"])
    u = state.scenario.u[seat - 1]
    if state.draws[seat - 1] + amt > u:
        return f"cumulative draws would exceed your cap {u}"
    return None


def _p_pot_covers_amount(state, seat, args):
    amt = int(args["amount"])
    if amt > state.pot_left:
        return f"pot has only {state.pot_left} left"
    return None


def _p_no_live_locked_funding(state, seat, args):
    j = int(args["job"])
    for c in state.contracts.values():
        for s in (1, 2):
            if j in c.executable_jobs_of(s):
                return f"job {j} has live locked funding under C{c.cid}"
    return None


def _p_no_live_draw_funding(state, seat, args):
    j = int(args["job"])
    df = state.draw_funding.get(j)
    if df is not None and not df[2]:
        return f"job {j} is already draw-funded"
    return None


def _p_chains_satisfied(state, seat, args):
    j = int(args["job"])
    for pre in state.scenario.prereqs[j - 1]:
        if pre not in state.done:
            return f"job {j} needs job {pre} finished first"
    return None


def _p_capacity_left(state, seat, args):
    if state.caps_used[seat - 1] >= state.scenario.kappa[seat - 1]:
        return "you have no slots left"
    return None


def find_funding(state, seat: int, job: int):
    """Locked/optional contract funding assigned to `seat` for `job`, else the
    seat's own unspent draw.  Returns ("contract", cid) | ("draw", None) | None."""
    for cid in sorted(state.contracts):
        c = state.contracts[cid]
        if job in c.executable_jobs_of(seat):
            return ("contract", cid)
    df = state.draw_funding.get(job)
    if df is not None and df[0] == seat and not df[2]:
        return ("draw", None)
    return None


def _p_funded_for_mover(state, seat, args):
    j = int(args["job"])
    if find_funding(state, seat, j) is None:
        return f"job {j} has no funding assigned to you (locked allocation or your own draw)"
    return None


def _p_to_is_partner(state, seat, args):
    try:
        to = int(args.get("to"))
    except (TypeError, ValueError):
        return "to must be an integer seat"
    if to != 3 - seat:
        return "you can only transfer to your partner"
    return None


def _p_transfer_bounds(state, seat, args):
    from .welfare import w_star
    try:
        amt = int(args.get("amount"))
    except (TypeError, ValueError):
        return "amount must be an integer"
    sc = state.scenario
    if sc.pay_cap is not None:
        return "transfers are disabled in this scenario"
    ws = max(w_star(sc), 1)
    if not (1 <= amt <= ws):
        return f"transfer amount must be between 1 and W*={ws}"
    return None


PREDICATES: dict[str, Callable] = {
    "episode_live": _p_episode_live,
    "contract_wellformed": _p_contract_wellformed,
    "offer_live": _p_offer_live,
    "is_non_proposer": _p_is_non_proposer,
    "payment_ticks_future": _p_payment_ticks_future,
    "no_assignment_conflict": _p_no_assignment_conflict,
    "no_funding_conflict": _p_no_funding_conflict,
    "capacity_available": _p_capacity_available,
    "pot_covers_funding": _p_pot_covers_funding,
    "schedule_feasible": _p_schedule_feasible,
    "contract_locked": _p_contract_locked,
    "window_open": _p_window_open,
    "window_closed": _p_window_closed,
    "job_exists": _p_job_exists,
    "job_not_done": _p_job_not_done,
    "amount_equals_own_cost": _p_amount_equals_own_cost,
    "within_draw_cap": _p_within_draw_cap,
    "pot_covers_amount": _p_pot_covers_amount,
    "no_live_locked_funding": _p_no_live_locked_funding,
    "no_live_draw_funding": _p_no_live_draw_funding,
    "chains_satisfied": _p_chains_satisfied,
    "capacity_left": _p_capacity_left,
    "funded_for_mover": _p_funded_for_mover,
    "to_is_partner": _p_to_is_partner,
    "transfer_bounds": _p_transfer_bounds,
}


def validate(state: "State", seat: int, action: Action) -> str | None:
    """Return None if legal, else the specific reason."""
    spec = action_spec()["actions"].get(action.name)
    if spec is None:
        return f"unknown action {action.name}"
    for arg, typ in spec["args"].items():
        if typ not in ("text40_optional",) and arg not in action.args:
            return f"missing required argument {arg!r}"
    for pred in spec["legality"]:
        reason = PREDICATES[pred](state, seat, action.args)
        if reason is not None:
            return reason
    return None


# ---------------------------------------------------------------------------
# effects  (mutate the state copy fold hands them)
# ---------------------------------------------------------------------------

def _eff_propose(state, ev: Event):
    assign, fund, pays, expires = parse_contract(state, ev.action.args)
    cid = state.next_cid
    state.next_cid += 1
    state.contracts[cid] = Contract(
        cid=cid, proposer=ev.seat, tick_opened=ev.tick,
        assign=assign, fund=fund, pay=pays, expires=expires,
    )


def _eff_counter(state, ev: Event):
    old = state.contracts[int(ev.action.args["offer_id"])]
    old.status = "countered"
    _eff_propose(state, ev)


def _eff_accept(state, ev: Event):
    c = state.contracts[int(ev.action.args["offer_id"])]
    total = sum(c.fund.values())
    # lock and reserve are one atomic instant (§5.1)
    c.status = "locked"
    c.accept_tick = ev.tick
    state.pot_left -= total
    state.reserved += total


def _eff_reject(state, ev: Event):
    state.contracts[int(ev.action.args["offer_id"])].status = "rejected"


def _eff_cancel(state, ev: Event):
    sc = state.scenario
    c = state.contracts[int(ev.action.args["contract_id"])]
    refund = c.reserved_amount()
    state.reserved -= refund
    state.pot_left += refund      # reserved funding returns in full
    c.cancel_unexecuted_pays()
    c.status = "cancelled"
    c.cancelled_by = ev.seat
    c.cancel_tick = ev.tick
    # canceller pays epsilon to the partner
    state.accounts[ev.seat - 1] -= sc.eps
    state.accounts[2 - ev.seat] += sc.eps


def _eff_renege(state, ev: Event):
    from .contracts import friction_destroyed, friction_refund
    sc = state.scenario
    c = state.contracts[int(ev.action.args["contract_id"])]
    i = ev.seat
    victim = 3 - i
    # 1. reneger's unfinished obligations cancelled; 3. their reserves return minus friction
    for j in c.obligations_of(i):
        x = c.fund[j]
        state.reserved -= x
        state.pot_left += friction_refund(x)
        state.destroyed += friction_destroyed(x)
    # 2. all unexecuted scheduled payments cancelled, both directions
    c.cancel_unexecuted_pays()
    # 4. penalty p: half to the partner as compensation, half destroyed
    state.accounts[i - 1] -= sc.p
    state.accounts[victim - 1] += sc.p // 2
    # 5. partner's obligations become optional: encoded by status + reneged_by
    c.status = "reneged"
    c.reneged_by = i
    c.renege_tick = ev.tick
    state.reneges.append({"cid": c.cid, "by": i, "tick": ev.tick})


def _eff_draw(state, ev: Event):
    amt = int(ev.action.args["amount"])
    j = int(ev.action.args["job"])
    state.pot_left -= amt
    state.spent += amt
    state.draws[ev.seat - 1] += amt
    state.draw_funding[j] = [ev.seat, amt, False]


def _eff_execute(state, ev: Event):
    j = int(ev.action.args["job"])
    seat = ev.seat
    src = find_funding(state, seat, j)
    cost = state.scenario.cost(seat, j)
    if src[0] == "contract":
        c = state.contracts[src[1]]
        alloc = c.fund[j]
        state.reserved -= alloc
        state.spent += cost
        state.pot_left += alloc - cost   # overfunding excess returns to the pot
        c.executed_jobs.add(j)
    else:
        state.draw_funding[j][2] = True  # draw already left the pot at DRAW
    state.caps_used[seat - 1] += 1
    state.done[j] = (seat, ev.tick)


def _eff_transfer(state, ev: Event):
    amt = int(ev.action.args["amount"])
    to = int(ev.action.args["to"])
    state.accounts[ev.seat - 1] -= amt
    state.accounts[to - 1] += amt
    state.transfers_net[ev.seat - 1] -= amt
    state.transfers_net[to - 1] += amt


def _eff_message(state, ev: Event):
    pass


def _eff_wait(state, ev: Event):
    pass


def _eff_end(state, ev: Event):
    pass


EFFECTS: dict[str, Callable] = {
    "eff_propose": _eff_propose,
    "eff_counter": _eff_counter,
    "eff_accept": _eff_accept,
    "eff_reject": _eff_reject,
    "eff_cancel": _eff_cancel,
    "eff_renege": _eff_renege,
    "eff_draw": _eff_draw,
    "eff_execute": _eff_execute,
    "eff_transfer": _eff_transfer,
    "eff_message": _eff_message,
    "eff_wait": _eff_wait,
    "eff_end": _eff_end,
}


def apply_effect(state: "State", ev: Event) -> None:
    spec = action_spec()["actions"][ev.action.name]
    EFFECTS[spec["effect"]](state, ev)
