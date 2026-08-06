"""Exact welfare quantities: W*, d_i, W_eq, G (§6.2-6.4).

Everything here is exact by enumeration — K=8 gives at most 3^8 assignment
vectors for W* and 2^8 subsets for the solo optima.  All arithmetic is
integer; G is returned as an integer pair (numerator, denominator).
"""
from __future__ import annotations

from itertools import product

from .scenario import Scenario
from .schedule import greedy_schedule_feasible

_CACHE: dict = {}


def _plans(scenario: Scenario):
    """All feasible (welfare, sigma) plans: sigma[t-1] in {0,1,2}."""
    sc = scenario
    key = ("plans", sc)
    if key in _CACHE:
        return _CACHE[key]
    out = []
    jobs = list(sc.jobs())
    for sigma in product((0, 1, 2), repeat=sc.K):
        S = [j for j in jobs if sigma[j - 1] != 0]
        if not S:
            out.append((0, sigma))
            continue
        # capacity
        if sum(1 for j in S if sigma[j - 1] == 1) > sc.kappa[0]:
            continue
        if sum(1 for j in S if sigma[j - 1] == 2) > sc.kappa[1]:
            continue
        # budget
        if sum(sc.cost(sigma[j - 1], j) for j in S) > sc.B:
            continue
        # chain closure
        if any(pre not in S for j in S for pre in sc.prereqs[j - 1]):
            continue
        # schedule feasibility: joint plans are contract-funded, one move per job
        assign = {j: sigma[j - 1] for j in S}
        if not greedy_schedule_feasible(sc, assign, 1):
            continue
        w = sum(sc.value(1, j) + sc.value(2, j) for j in S)
        out.append((w, sigma))
    _CACHE[key] = out
    return out


def w_star(scenario: Scenario) -> int:
    key = ("w_star", scenario)
    if key not in _CACHE:
        _CACHE[key] = max(w for w, _ in _plans(scenario))
    return _CACHE[key]


def best_plans(scenario: Scenario) -> list[tuple[int, tuple]]:
    """Feasible plans sorted lexicographically by (welfare, sigma), best first."""
    return sorted(_plans(scenario), key=lambda ws: (ws[0], ws[1]), reverse=True)


def best_plan_assignment(scenario: Scenario) -> dict[int, int]:
    """The efficient plan's assignment map job -> seat (jobs actually done)."""
    w, sigma = best_plans(scenario)[0]
    return {j: sigma[j - 1] for j in scenario.jobs() if sigma[j - 1] != 0}


def solo_best(
    scenario: Scenario,
    seat: int,
    budget_cap: int,
    pot_cap: int,
    slots: int,
    moves: int,
    candidates: list[int],
    optional_funded: frozenset[int] | set[int] = frozenset(),
    done: frozenset[int] | set[int] = frozenset(),
    prereq_ok: frozenset[int] | set[int] = frozenset(),
) -> int:
    """Best value `seat` can guarantee alone (§6.3, recomputed on what is left
    for §9.1).  Draw-funded jobs cost budget and TWO moves; optional-funded
    jobs (reserved funding already assigned to the seat) cost zero budget and
    ONE move.  Chain closure: every prerequisite must be done, assumed-secure,
    or inside the chosen set."""
    sc = scenario
    cands = [j for j in candidates]
    n = len(cands)
    best = 0
    eff_budget = min(budget_cap, pot_cap)
    for mask in range(1 << n):
        S = [cands[i] for i in range(n) if mask >> i & 1]
        if len(S) > slots:
            continue
        draw_jobs = [j for j in S if j not in optional_funded]
        if 2 * len(draw_jobs) + (len(S) - len(draw_jobs)) > moves:
            continue
        if sum(sc.cost(seat, j) for j in draw_jobs) > eff_budget:
            continue
        sset = set(S)
        if any(pre not in done and pre not in prereq_ok and pre not in sset
               for j in S for pre in sc.prereqs[j - 1]):
            continue
        val = sum(sc.value(seat, j) for j in S)
        if val > best:
            best = val
    return best


def d_i(scenario: Scenario, seat: int, budget_cap: int | None = None) -> int:
    """§6.3 alone-value from the episode start; budget_cap overrides u_i (used
    with B/2 for W_eq)."""
    sc = scenario
    cap = sc.u[seat - 1] if budget_cap is None else budget_cap
    key = ("d_i", sc, seat, cap)
    if key not in _CACHE:
        _CACHE[key] = solo_best(
            sc, seat,
            budget_cap=cap, pot_cap=sc.B,
            slots=sc.kappa[seat - 1],
            moves=sc.moves_remaining(seat, 1),
            candidates=list(sc.jobs()),
        )
    return _CACHE[key]


def w_eq(scenario: Scenario) -> int:
    """Value of split-the-pot-and-work-alone: d_1^{B/2} + d_2^{B/2}."""
    half = scenario.B // 2
    return d_i(scenario, 1, half) + d_i(scenario, 2, half)


def integrative_gap(scenario: Scenario) -> tuple[int, int]:
    """G = (W* - W_eq) / W* as an exact integer pair (num, den)."""
    ws = w_star(scenario)
    return ws - w_eq(scenario), ws
