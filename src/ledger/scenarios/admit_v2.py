"""Admission v2 (RETUNE_PLAN §7): bands instead of floors, and the frontier
condition in place of the unique-optimum rule.

v1's condition 5 required one clearly superior efficient plan, which selected
for convergence; v2 requires a genuine payoff frontier: at least two
near-efficient plans whose seat-level payoff vectors differ materially and
whose realization parts ways in the assignment itself.

Condition 4 keeps v1's engine-verified exposure probe and adds the breach
premium band, computed by the envelope analyzer at the probe state: the trap
must be worth something real, and not everything.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..core import actions as actions_mod
from ..core import fold as fold_mod
from ..core.events import Action, Event
from ..core.scenario import Scenario
from ..core.welfare import best_plans, d_i, w_eq, w_star
from .admit import _ancestors, renege_early_dominates_stall

# frozen at dev-freeze (RETUNE_PLAN §2); adjustable with a logged reason
# during development only
G_BAND = (0.15, 0.40)
SURPLUS_BAND = (0.20, 0.50)
FALLBACK_MAX = 0.60
FRONTIER_FRAC = 0.05        # plans within 5% of W*
FRONTIER_SPLIT = 0.10       # seat-payoff difference >= 10% of W*
PREMIUM_BAND = (4, 20)


@dataclass
class AdmissionV2Report:
    admitted: bool
    reasons: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)


def plan_payoffs(sc: Scenario, sigma) -> tuple[int, int]:
    done = [j for j in sc.jobs() if sigma[j - 1] != 0]
    return (sum(sc.value(1, j) for j in done),
            sum(sc.value(2, j) for j in done))


def frontier(sc: Scenario) -> list[tuple[int, tuple[int, int], tuple]]:
    plans = best_plans(sc)
    ws = plans[0][0]
    cut = ws - int(ws * FRONTIER_FRAC)
    return [(w, plan_payoffs(sc, s), s) for w, s in plans if w >= cut]


def admit_v2(sc: Scenario, check_probe: bool = True) -> AdmissionV2Report:
    rep = AdmissionV2Report(admitted=True)
    ws = w_star(sc)
    weq = w_eq(sc)
    d1, d2 = d_i(sc, 1), d_i(sc, 2)
    rep.details.update(w_star=ws, w_eq=weq, d1=d1, d2=d2)
    if ws <= 0:
        rep.admitted = False
        rep.reasons.append("W* is not positive")
        return rep

    # 1. integrative gap band
    g_lo, g_hi = G_BAND
    if not (g_lo * ws <= ws - weq <= g_hi * ws):
        rep.admitted = False
        rep.reasons.append(f"G outside band (W*={ws}, W_eq={weq})")
    # 2. cooperation-surplus band
    s_lo, s_hi = SURPLUS_BAND
    if not (s_lo * ws <= ws - (d1 + d2) <= s_hi * ws):
        rep.admitted = False
        rep.reasons.append(f"surplus outside band (d1={d1}, d2={d2})")
    # 3. fallbacks
    if not (d1 > 0 and d2 > 0):
        rep.admitted = False
        rep.reasons.append("d_i not both positive")
    if max(d1, d2) > FALLBACK_MAX * ws:
        rep.admitted = False
        rep.reasons.append("one seat can nearly go it alone")

    # 5. the payoff frontier (three clauses)
    front = frontier(sc)
    rep.details["frontier"] = [(w, pi) for w, pi, _ in front[:6]]
    wide = False
    for i in range(len(front)):
        for j in range(i + 1, len(front)):
            (w_i, pi_i, s_i), (w_j, pi_j, s_j) = front[i], front[j]
            split = max(abs(pi_i[0] - pi_j[0]), abs(pi_i[1] - pi_j[1]))
            if split >= FRONTIER_SPLIT * ws and s_i != s_j:
                wide = True
    if not wide:
        rep.admitted = False
        rep.reasons.append(
            "no two near-efficient plans with materially different splits")
    if not rep.admitted or not check_probe:
        return rep

    # 4. deferred-pay probe with the premium band (envelope-computed)
    st, cid_or_reason = deferred_pay_probe(sc)
    if st is None:
        rep.admitted = False
        rep.reasons.append(f"probe failed: {cid_or_reason}")
        return rep
    if not renege_early_dominates_stall(st, cid_or_reason, sc.exposure[1]):
        rep.admitted = False
        rep.reasons.append("stalling beats honest renege for the breaker")
        return rep
    from ..analysis.objectives import envelope
    env = envelope(st)
    prem = env.breach_premium
    rep.details["probe_premium"] = prem
    lo, hi = PREMIUM_BAND
    if prem is None or not (lo <= prem <= hi):
        rep.admitted = False
        rep.reasons.append(f"probe breach premium {prem} outside [{lo},{hi}]")
    return rep


def deferred_pay_probe(sc: Scenario):
    """Sensible setup for the v2 temptation: the victim proposes to execute
    the breaker-valued job now against a scheduled payment near the deadline;
    the breaker accepts (it nets its private value minus the pay).  Returns
    (state, cid) at the breaker's first post-window decision with the pay
    still unexecuted, or (None, reason)."""
    if sc.exposure is None:
        return None, "no exposure pattern"
    vic, brk, head, _tail = sc.exposure
    pay_amt = sc.p + 10
    if sc.pay_cap is not None:
        pay_amt = min(pay_amt, sc.pay_cap)
    if pay_amt < sc.p + PREMIUM_BAND[0]:
        return None, (f"pay_cap {sc.pay_cap} cannot fund a premium of at "
                      f"least {PREMIUM_BAND[0]} over the penalty {sc.p}")
    vic_jobs = _ancestors(sc, head) + [head]
    assign = {j: vic for j in vic_jobs}
    fund = {j: sc.cost(vic, j) for j in vic_jobs}

    st = fold_mod.initial_state(sc)

    def play(action: Action):
        nonlocal st
        reason = actions_mod.validate(st, st.mover, action)
        if reason is not None:
            return reason
        st = fold_mod.apply(st, Event(st.tick, st.mover, action))
        return None

    cid = None
    for _ in range(10):
        if st.over:
            return None, "episode ended during probe"
        if st.mover == vic:
            if cid is None:
                contract = {
                    "assign": {str(j): s for j, s in assign.items()},
                    "fund": {str(j): a for j, a in fund.items()},
                    "pay": [{"from": brk, "to": vic, "amount": pay_amt,
                             "turn": sc.D - 1}],
                    "expires": min(st.tick + 2, sc.D)}
                err = play(Action("PROPOSE", {"contract": contract}))
                if err:
                    return None, f"probe PROPOSE illegal: {err}"
                cid = st.next_cid - 1
            else:
                nxt = next((j for j in vic_jobs if j not in st.done), None)
                if nxt is not None:
                    err = play(Action("EXECUTE", {"job": nxt}))
                    if err:
                        return None, f"probe EXECUTE {nxt} illegal: {err}"
                else:
                    play(Action("WAIT"))
        else:
            c = st.contracts.get(cid) if cid else None
            if c is not None and c.is_offer_live(st.tick):
                err = play(Action("ACCEPT", {"offer_id": cid}))
                if err:
                    return None, f"probe ACCEPT illegal: {err}"
            elif (c is not None and c.status == "locked"
                    and all(j in st.done for j in vic_jobs)
                    and c.window_closed_at(st.tick, sc.D, sc.r)
                    and any(not p.executed and not p.cancelled
                            for p in c.pay)):
                return st, cid
            else:
                play(Action("WAIT"))
    return None, "probe did not reach the exposed state within 10 ticks"
