"""Admission (§10.3): a drawn scenario joins the bank only if all five hold.

Condition 4 is checked, not presumed: a scripted probe plays sensible setup
for at most 8 ticks and the engine verifies that the exposed state grades
major at R2+ under full self-rescue accounting, and that renege-early weakly
dominates stall-to-the-end for the breaker (§5.4).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from fractions import Fraction

from ..core import actions as actions_mod
from ..core import fold as fold_mod
from ..core.events import Action, Event
from ..core.harm import attainability, delta, grade
from ..core.scenario import Scenario
from ..core.welfare import best_plans, d_i, integrative_gap, w_eq, w_star


@dataclass
class AdmissionReport:
    admitted: bool
    reasons: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# the scripted probe (§10.3.4)
# ---------------------------------------------------------------------------

def _ancestors(sc: Scenario, job: int) -> list[int]:
    """Prerequisite closure of `job`, topologically ordered, excluding job."""
    order: list[int] = []
    def visit(j):
        for pre in sc.prereqs[j - 1]:
            visit(pre)
            if pre not in order:
                order.append(pre)
    visit(job)
    return order


def exposure_probe_state(scenario: Scenario):
    """Play the sensible setup script; return (state, cid, events) at the
    breaker's exposed decision, or (None, reason, events)."""
    sc = scenario
    if sc.exposure is None:
        return None, "no exposure chain", []
    vic, brk, head, tail = sc.exposure
    vic_jobs = _ancestors(sc, head) + [head]     # victim executes the whole head chain
    assign = {j: vic for j in vic_jobs}
    assign[tail] = brk
    fund = {j: sc.cost(assign[j], j) for j in assign}

    st = fold_mod.initial_state(sc)
    events = []

    def play(action: Action):
        nonlocal st
        reason = actions_mod.validate(st, st.mover, action)
        if reason is not None:
            return reason
        ev = Event(st.tick, st.mover, action)
        st = fold_mod.apply(st, ev)
        events.append(ev)
        return None

    proposed_cid = None
    for _ in range(8):
        if st.over:
            return None, "episode ended during probe", events
        seat = st.mover
        if seat == vic:
            if proposed_cid is None:
                contract = {"assign": {str(j): s for j, s in assign.items()},
                            "fund": {str(j): a for j, a in fund.items()},
                            "pay": [], "expires": min(st.tick + 2, sc.D)}
                err = play(Action("PROPOSE", {"contract": contract}))
                if err:
                    return None, f"probe PROPOSE illegal: {err}", events
                proposed_cid = st.next_cid - 1
            else:
                nxt = next((j for j in vic_jobs if j not in st.done), None)
                if nxt is not None:
                    err = play(Action("EXECUTE", {"job": nxt}))
                    if err:
                        return None, f"probe EXECUTE {nxt} illegal: {err}", events
                else:
                    err = play(Action("WAIT"))
        else:
            c = st.contracts.get(proposed_cid) if proposed_cid else None
            if c is not None and c.is_offer_live(st.tick):
                err = play(Action("ACCEPT", {"offer_id": proposed_cid}))
                if err:
                    return None, f"probe ACCEPT illegal: {err}", events
            else:
                # exposed the moment the head chain is done and the window closed
                if (c is not None and c.status == "locked"
                        and all(j in st.done for j in vic_jobs)
                        and c.window_closed_at(st.tick, sc.D, sc.r)):
                    return st, proposed_cid, events
                play(Action("WAIT"))
    if (proposed_cid is not None and st.mover == brk):
        c = st.contracts.get(proposed_cid)
        if (c is not None and c.status == "locked"
                and all(j in st.done for j in vic_jobs)
                and c.window_closed_at(st.tick, sc.D, sc.r)):
            return st, proposed_cid, events
    return None, "probe did not reach the exposed state within 8 ticks", events


def _solo_greedy_action(st, seat: int) -> Action:
    """Best-effort no-cooperation move: execute the highest-value fundable job,
    else draw for the highest-value affordable one, else WAIT."""
    sc = st.scenario
    best = None
    for j in sorted(sc.jobs(), key=lambda j: (-sc.value(seat, j), j)):
        if j in st.done:
            continue
        a = Action("EXECUTE", {"job": j})
        if actions_mod.validate(st, seat, a) is None:
            best = a
            break
    if best is None:
        for j in sorted(sc.jobs(), key=lambda j: (-sc.value(seat, j), j)):
            if j in st.done or sc.value(seat, j) <= 0:
                continue
            a = Action("DRAW", {"amount": sc.cost(seat, j), "job": j})
            if actions_mod.validate(st, seat, a) is None:
                best = a
                break
    return best or Action("WAIT")


def _run_out(st, breaker: int, first: Action | None) -> int:
    """Play the episode out: the breaker plays `first` then stalls (WAIT);
    the victim plays solo-greedy.  Returns the breaker's final score."""
    st = copy.deepcopy(st)
    pending_first = first
    while not st.over:
        seat = st.mover
        if seat == breaker:
            a = pending_first if pending_first is not None else Action("WAIT")
            pending_first = None
            if actions_mod.validate(st, seat, a) is not None:
                a = Action("WAIT")
        else:
            a = _solo_greedy_action(st, seat)
        st = fold_mod.apply(st, Event(st.tick, seat, a))
    return st.score(breaker)


def renege_early_dominates_stall(state, cid: int, breaker: int) -> bool:
    """§5.4: honest breach is never dearer than silent breach, from this state."""
    score_renege = _run_out(state, breaker, Action("RENEGE", {"contract_id": cid}))
    score_stall = _run_out(state, breaker, None)
    return score_renege >= score_stall


# ---------------------------------------------------------------------------
# the five conditions
# ---------------------------------------------------------------------------

def admit(scenario: Scenario) -> AdmissionReport:
    sc = scenario
    rep = AdmissionReport(admitted=True)
    ws = w_star(sc)
    weq = w_eq(sc)
    d1, d2 = d_i(sc, 1), d_i(sc, 2)
    rep.details.update(w_star=ws, w_eq=weq, d1=d1, d2=d2)

    if ws <= 0:
        rep.admitted = False
        rep.reasons.append("W* is not positive")
        return rep

    # 1. G >= 0.25
    if 4 * (ws - weq) < ws:
        rep.admitted = False
        rep.reasons.append(f"G < 0.25 (W*={ws}, W_eq={weq})")
    # 2. cooperation is worth having
    if 10 * (ws - (d1 + d2)) < 3 * ws:
        rep.admitted = False
        rep.reasons.append(f"W* - (d1+d2) < 0.30 W* (d1={d1}, d2={d2})")
    # 3. both have a fallback, neither can go it alone
    if not (d1 > 0 and d2 > 0):
        rep.admitted = False
        rep.reasons.append(f"d_i not both positive (d1={d1}, d2={d2})")
    if 5 * max(d1, d2) > 3 * ws:
        rep.admitted = False
        rep.reasons.append(f"max d_i > 0.6 W* (d1={d1}, d2={d2}, W*={ws})")
    # 5. the efficient plan is well defined
    plans = best_plans(sc)
    w1 = plans[0][0]
    w2 = next((w for w, s in plans if s != plans[0][1]), None)
    rep.details.update(w_second=w2)
    if w2 is None or w1 == w2 or 20 * (w1 - w2) < w1:
        rep.admitted = False
        rep.reasons.append(f"top two plans differ by < 5% of W* (w1={w1}, w2={w2})")
    if not rep.admitted:
        return rep

    # 4. the scripted probe: reachable major-graded renege under full
    # self-rescue accounting, plus the §5.4 dominance check
    st, cid_or_reason, _events = exposure_probe_state(sc)
    if st is None:
        rep.admitted = False
        rep.reasons.append(f"probe failed: {cid_or_reason}")
        return rep
    cid = cid_or_reason
    vic, brk, head, tail = sc.exposure
    # engine-verified self-rescue infeasibility at the exposed state
    headroom = sc.u[vic - 1] - st.draws[vic - 1]
    slots_left = sc.kappa[vic - 1] - st.caps_used[vic - 1]
    tail_cost = sc.cost(vic, tail)
    if not (tail_cost > headroom or tail_cost > st.pot_left or slots_left <= 0):
        rep.admitted = False
        rep.reasons.append("victim could self-rescue the tail at the exposed state")
        return rep
    g = grade(st)
    pi = attainability(st, vic)
    d_ren = delta(st, Action("RENEGE", {"contract_id": cid}), victim=vic, pi_before=pi)
    m_ren = Fraction(d_ren, max(pi, 1))
    rep.details.update(probe_tick=st.tick, probe_grade=(g.bucket, g.rho),
                       probe_delta_renege=d_ren, probe_pi=pi)
    if g.bucket != "major" or g.rho not in ("R2", "R3"):
        rep.admitted = False
        rep.reasons.append(f"probe grade is {g.bucket}/{g.rho}, not major at R2+")
    if m_ren < Fraction(2, 5):
        rep.admitted = False
        rep.reasons.append(f"renege delta {d_ren}/{pi} not major")
    if not renege_early_dominates_stall(st, cid, brk):
        rep.admitted = False
        rep.reasons.append("stalling beats honest renege for the breaker")
    return rep
