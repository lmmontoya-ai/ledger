"""The exact value calculation for the hidden-objectives variant.

Given the rules and a state, and no model, the solver computes the mover's
value of every legal Omega-2 action class in the mover's OWN assigned
resource, conditional on a belief about the partner's resource.  The report
uses it for the Contracting goal-revealing census (a decision is
goal-revealing when the best action class differs between the mover's three
possible objectives; a hedge exists when one class is within `EPS_DEFAULT`
points of best under every objective) and for the fixed-state gates.

What is reused from the core, unchanged:
  * `analysis.residual.enumerate_specs`, the completion enumerator.  It reads
    costs, capacity, chains, funding and the deadline, never a value column.
  * `core.actions.validate`, `core.fold.apply`, `core.welfare.solo_best` (run
    on a per-resource shadow scenario), `analysis.omega2.refine` and
    `analysis.objectives._mover_key`.

What is added here:
  * `realize_state`: the core realizer (`analysis.residual.realize`), line
    for line, returning the final State instead of a payoff pair.
  * `pay_variants_v2`: a fixed transfer grid, so one enumeration serves
    every belief.
  * `envelope_v2`: the belief-conditioned action-value envelope.  The
    partner's objective enters only through acceptance (the partner accepts
    a bundle iff it beats its residual go-it-alone value in its own
    resource) and breach credibility (the partner breaches only if that
    raises its own resource).
  * the pruned enumeration (`enumerate_specs_pruned`): the same enumerator
    with interchangeable locked contracts quotiented out of the breach
    product.  The report's free-play census ran under it
    (`completions(..., pruned=True)`); the fixed-state gates ran unpruned.
  * certification and classification helpers: `per_belief_at`,
    `certify_row`, `value_from_q`, `own_objective_tables`,
    `classify_tables`.

Ported from self-other-prediction-smoke-tests:
`ledger-experiments/engine_v2/solver_v2.py`, the pruned enumeration in
`ledger-experiments/ledger_episode_evidence.py`, `per_belief_at`,
`certify_row` and `value_from_q` in `ledger-experiments/ledger_v2_bridge.py`,
the stratifier in `ledger-experiments/run_ledger_v2_g1a.py`, and
`classify_tables` in `scripts/ledger_freerun_divergence_census.py`.  The
arithmetic is unchanged.
"""
from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass, field
from itertools import product
from math import comb
from typing import Any, Sequence

from ...analysis.objectives import _mover_key
from ...analysis.omega2 import legal_omega2_alphabet, refine
from ...analysis.residual import (NEW_BUNDLE, CompletionSpec,
                                  _feasible_assignments, enumerate_specs)
from ...core import actions as actions_mod
from ...core import fold as fold_mod
from ...core.events import Action, Event
from ...core.welfare import solo_best
from .scenario import RESOURCES, ScenarioV2, score_resource, score_vector, shadow

EPS_DEFAULT = 2                  # points of indifference when forming argmax sets
MAX_REALIZATIONS = 200_000       # sanity bound, never silently truncated
FAMILIES = ("best_response", "ir_only", "cautious")


# ---------------------------------------------------------------------------
# realization: spec -> legal event sequence -> final STATE
# ---------------------------------------------------------------------------

def realize_state(state, spec: CompletionSpec):
    """`analysis.residual.realize`, returning (final State, first action) or
    None when the spec cannot be realized legally."""
    sc = state.scenario
    st = copy.deepcopy(state)
    decision_seat = st.mover
    breach = dict(spec.breach)
    new_assign = dict(spec.assign)
    to_accept = set(spec.accept)
    proposal_made = spec.end_now or not (
        spec.funding == "contract" and (new_assign or spec.pay[2] > 0))
    proposal_cid: int | None = None
    drawn: set[int] = set()
    first: Action | None = None

    def obligations_now():
        out: dict[int, int] = {}
        for cid, c in st.contracts.items():
            if c.status == "locked" and cid not in breach:
                for s in (1, 2):
                    for j in c.obligations_of(s):
                        out[j] = s
            elif c.status == "locked" and cid in breach:
                victim = 3 - breach[cid]
                for j in c.unexecuted_jobs():
                    if c.assign[j] == victim:
                        out[j] = victim
            elif c.status == "reneged":
                for s in (1, 2):
                    for j in c.optional_jobs_of(s):
                        out[j] = s
        if spec.funding == "solo":
            out.update(new_assign)
        return out

    guard = 0
    while not st.over:
        guard += 1
        if guard > 4 * sc.D + 8:
            return None
        seat = st.mover
        action: Action | None = None
        for cid, s in sorted(breach.items()):
            if (s == seat and cid in st.contracts
                    and st.contracts[cid].status == "locked"):
                a = Action("RENEGE", {"contract_id": cid})
                if actions_mod.validate(st, seat, a) is None:
                    action = a
                    break
        if action is None and seat == decision_seat:
            for cid in sorted(to_accept):
                c = st.contracts.get(cid)
                if c is not None and c.is_offer_live(st.tick):
                    a = Action("ACCEPT", {"offer_id": cid})
                    if actions_mod.validate(st, seat, a) is not None:
                        return None
                    action = a
                    to_accept.discard(cid)
                    break
        if action is None and not proposal_made and seat == decision_seat:
            fund = {str(j): sc.cost(s, j) for j, s in new_assign.items()}
            pays = []
            frm, to, amt = spec.pay
            if amt > 0:
                turn = min(st.tick + 2, sc.D)
                if sc.settle_window is not None:
                    turn = max(turn, sc.D - sc.settle_window + 1)
                pays = [{"from": frm, "to": to, "amount": amt, "turn": turn}]
            contract = {"assign": {str(j): s for j, s in new_assign.items()},
                        "fund": fund, "pay": pays,
                        "expires": min(st.tick + 3, sc.D)}
            a = Action("PROPOSE", {"contract": contract})
            if actions_mod.validate(st, seat, a) is not None:
                return None
            action = a
        if action is None and seat != decision_seat and proposal_cid is not None:
            c = st.contracts.get(proposal_cid)
            if c is not None and c.is_offer_live(st.tick):
                a = Action("ACCEPT", {"offer_id": proposal_cid})
                if actions_mod.validate(st, seat, a) is not None:
                    return None
                action = a
        if action is None and spec.funding == "solo":
            for j in sorted(new_assign):
                if (new_assign[j] == seat and j not in drawn
                        and j not in st.done):
                    a = Action("DRAW", {"amount": sc.cost(seat, j), "job": j})
                    if actions_mod.validate(st, seat, a) is None:
                        action = a
                        drawn.add(j)
                        break
        if action is None:
            jobs = obligations_now()
            for j in _topo_ready(sc, jobs, seat, set(st.done)):
                a = Action("EXECUTE", {"job": j})
                if actions_mod.validate(st, seat, a) is None:
                    action = a
                    break
        if action is None:
            jobs = obligations_now()
            mine_left = [j for j, s in jobs.items()
                         if s == seat and j not in st.done]
            pending_breach = any(
                s == seat and c in st.contracts
                and st.contracts[c].status == "locked"
                for c, s in breach.items()) or (
                NEW_BUNDLE in breach and breach[NEW_BUNDLE] == seat
                and not proposal_made)
            if not mine_left and not pending_breach and proposal_made:
                action = Action("END")
            else:
                action = Action("WAIT")
        if first is None and st.mover == decision_seat:
            first = action
        ev = Event(st.tick, seat, action)
        if actions_mod.validate(st, seat, action) is not None:
            return None
        st = fold_mod.apply(st, ev)
        if action.name == "PROPOSE" and seat == decision_seat:
            proposal_made = True
            proposal_cid = st.next_cid - 1
            if NEW_BUNDLE in breach:
                breach[proposal_cid] = breach.pop(NEW_BUNDLE)

    if st.defaults:
        return None
    if to_accept:
        return None
    if proposal_cid is not None and st.contracts[proposal_cid].status in (
            "expired", "rejected"):
        return None
    if spec.funding == "solo" and any(j not in st.done for j in new_assign):
        return None
    assert first is not None
    return st, first


def _topo_ready(sc, jobs: dict[int, int], seat: int, done: set[int]):
    ready = [j for j, s in jobs.items()
             if s == seat and j not in done
             and all(p in done for p in sc.prereqs[j - 1])]
    ready.sort()
    return ready


# ---------------------------------------------------------------------------
# the pruned enumeration
# ---------------------------------------------------------------------------
#
# Two locked contracts are interchangeable at a state when they agree on
# everything the realizer, the fold and the scorer read (status, proposer,
# assignment, funding, executed jobs, live pays as (from, to, amount,
# dodgeable), the first tick a RENEGE is legal, and the seats that may
# breach them) and differ only in their id.  A breach combination and any
# permutation of it within a group of interchangeable contracts realize to
# the same final state up to contract ids, so the same scores, the same
# Omega-2 class of the first action and the same value tables.  The pruned
# enumerator keeps one representative per group multiset.

_SEATS = (1, 2)

#: The ceiling on the pruned breach-combination count at one state, derived
#: from the studied bank's knobs (`combinatorial_maximum`): at most 11 locked
#: contracts by turn 24 and at most 4 obligation-bearing ones, so
#: 3^4 * 2^7 = 10368.  Checked before anything is built.
MAX_PRUNED_BREACH_COMBOS = 10_368


class SpecBudgetExceeded(RuntimeError):
    """The pruned breach product exceeds `MAX_PRUNED_BREACH_COMBOS`."""


def _renege_ready_tick(state, contract) -> int:
    """The first tick at which RENEGE of `contract` can be legal."""
    r = int(getattr(state.scenario, "r", 0) or 0)
    if getattr(contract, "accept_tick", None) is None:
        return int(state.tick)
    return max(int(state.tick), int(contract.accept_tick) + r + 1)


def contract_class(state, contract, seats: Sequence[int]) -> tuple:
    """The interchangeability fingerprint of one contract at one state."""
    ready = _renege_ready_tick(state, contract)
    pays = tuple(sorted((int(p.from_), int(p.to), int(p.amount),
                         bool(int(p.tick) >= ready))
                        for p in contract.live_pays()))
    return (
        contract.status,
        int(getattr(contract, "proposer", 0) or 0),
        ready,
        tuple(sorted((int(j), int(s)) for j, s in contract.assign.items())),
        tuple(sorted((int(j), int(a)) for j, a in contract.fund.items())),
        tuple(sorted(int(j) for j in contract.executed_jobs)),
        pays,
        tuple(sorted(int(s) for s in seats)),
    )


def per_contract_breach_options(state, accepted: dict[int, dict[int, int]]
                                ) -> list[tuple[int, list[int]]]:
    """`(cid, breachable seats)` per contract, in the order of the core's
    `residual._breach_options`."""
    out: list[tuple[int, list[int]]] = []
    for cid, c in sorted(state.contracts.items()):
        if c.status != "locked":
            continue
        seats = [s for s in _SEATS
                 if c.obligations_of(s) or any(p.from_ == s
                                               for p in c.live_pays())]
        out.append((cid, seats))
    for cid, assign in sorted(accepted.items()):
        c = state.contracts[cid]
        seats = [s for s in _SEATS
                 if any(a == s for a in assign.values()) or c.live_pays()]
        out.append((cid, seats))
    return out


def _counts_summing_to_at_most(total: int, slots: int):
    """Every `slots`-tuple of non-negative ints summing to at most `total`."""
    if slots == 0:
        yield ()
        return
    for first in range(total + 1):
        for rest in _counts_summing_to_at_most(total - first, slots - 1):
            yield (first, *rest)


def _group_choices(cids: Sequence[int], seats: Sequence[int]
                   ) -> list[dict[int, int]]:
    """Canonical breach choices for one group of interchangeable contracts:
    one per multiset of seat assignments, dealt in sorted-cid order.  A
    singleton group gives the core's `[none, (cid, 1), (cid, 2)]` order."""
    cids = sorted(cids)
    seats = sorted(seats)
    m = len(cids)
    if not seats:
        return [{}]
    ordered = sorted(_counts_summing_to_at_most(m, len(seats)),
                     key=lambda t: (sum(t), tuple(-x for x in t)))
    out: list[dict[int, int]] = []
    for counts in ordered:
        choice: dict[int, int] = {}
        i = 0
        for seat, n in zip(seats, counts):
            for _ in range(n):
                choice[cids[i]] = seat
                i += 1
        out.append(choice)
    return out


def breach_groups(state, accepted: dict[int, dict[int, int]]
                  ) -> list[dict[str, Any]]:
    """The breachable contracts grouped by fingerprint, groups in order of
    their first member's cid."""
    order: list[tuple] = []
    members: dict[tuple, list[int]] = {}
    seats_of: dict[tuple, list[int]] = {}
    for cid, seats in per_contract_breach_options(state, accepted):
        key = contract_class(state, state.contracts[cid], seats)
        if key not in members:
            members[key] = []
            seats_of[key] = list(seats)
            order.append(key)
        members[key].append(cid)
    return [{"fingerprint": key, "cids": sorted(members[key]),
             "seats": seats_of[key]} for key in order]


def pruned_breach_options(state, accepted: dict[int, dict[int, int]]
                          ) -> list[dict[int, int]]:
    """`residual._breach_options` with one representative per equivalence
    class of breach combinations."""
    groups = breach_groups(state, accepted)
    per_group = [_group_choices(g["cids"], g["seats"]) for g in groups]
    combos: list[dict[int, int]] = []
    for combo in product(*per_group) if per_group else [()]:
        merged: dict[int, int] = {}
        for part in combo:
            merged.update(part)
        combos.append(merged)
    return combos


def pruned_breach_count(state, accepted: dict[int, dict[int, int]]) -> int:
    """The pruned breach-combination count, from the group structure alone."""
    n = 1
    for g in breach_groups(state, accepted):
        n *= comb(len(g["cids"]) + len(g["seats"]), len(g["seats"]))
    return n


def unpruned_breach_count(state, accepted: dict[int, dict[int, int]]) -> int:
    """The core enumerator's breach-combination count."""
    n = 1
    for _cid, seats in per_contract_breach_options(state, accepted):
        n *= 1 + len(seats)
    return n


def combinatorial_maximum(scenario, scored_turns: int | None = None
                          ) -> dict[str, int]:
    """The derived bound behind `MAX_PRUNED_BREACH_COMBOS`: at most one
    contract locks per two turns, at most floor(B / cheapest job) contracts
    hold live obligations (3 breach options each), the rest are pay-only (2
    options each)."""
    sv = scenario
    K = int(getattr(sv, "K", 6))
    D = int(getattr(sv, "D", 48))
    turns = int(scored_turns if scored_turns is not None
                else (getattr(sv, "scored_turns", None) or D))
    c_max = max(0, (turns - 1) // 2)
    costs = [int(sv.cost(s, j)) for s in _SEATS for j in sv.jobs()]
    min_cost = max(1, min(costs) if costs else 1)
    c_job = min(c_max, int(getattr(sv, "B", 0)) // min_cost)
    breach_max = max((3 ** a) * (2 ** (c_max - a)) for a in range(c_job + 1))
    assign_max = 1 + 2 * 3 ** K
    accept_max = 1 + c_max
    return {
        "scored_turns": turns,
        "max_locked_contracts": c_max,
        "max_obligation_bearing_contracts": c_job,
        "min_job_cost": min_cost,
        "breach_max": breach_max,
        "assign_max": assign_max,
        "accept_max": accept_max,
        "variant_max": 3,
        "specs_max": 1 + accept_max * breach_max * assign_max * 3,
        "frozen_max_specs_per_state": 20_000,
        "frozen_max_realizations": 200_000,
    }


def enumerate_specs_pruned(state):
    """`analysis.residual.enumerate_specs` with the breach product replaced
    by `pruned_breach_options`, and the post-hoc spec-count check replaced by
    the `MAX_PRUNED_BREACH_COMBOS` check taken before anything is built."""
    mover = state.mover
    live = [c for c in state.contracts.values()
            if c.is_offer_live(state.tick) and c.proposer != mover]
    accept_branches: list[tuple[tuple[int, ...], dict[int, int], int]] = [
        ((), {}, 0)]
    for c in live:
        accept_branches.append(
            ((c.cid,), dict(c.assign), sum(c.fund.values())))

    budget = 0
    for accept, _acc_assign, _acc_fund in accept_branches:
        acc_map = {cid: dict(state.contracts[cid].assign) for cid in accept}
        budget += pruned_breach_count(state, acc_map)
    if budget > MAX_PRUNED_BREACH_COMBOS:
        raise SpecBudgetExceeded(
            f"{budget} pruned breach combinations at one state exceeds the "
            f"derived maximum {MAX_PRUNED_BREACH_COMBOS}; refused before "
            "enumeration")

    specs = [CompletionSpec(breach=(), assign=(), funding="contract",
                            pay=(0, 0, 0), end_now=True)]
    for accept, acc_assign, acc_fund in accept_branches:
        acc_map = {cid: dict(state.contracts[cid].assign) for cid in accept}
        for breach in pruned_breach_options(state, acc_map):
            btup = tuple(sorted(breach.items()))
            for assign, funding in _feasible_assignments(
                    state, breach, mover, acc_assign, acc_fund):
                specs.append(CompletionSpec(breach=btup, assign=assign,
                                            funding=funding, pay=(0, 0, 0),
                                            accept=accept))
                if funding == "contract" and assign:
                    for s in _SEATS:
                        if any(a == s for _j, a in assign):
                            specs.append(CompletionSpec(
                                breach=btup + ((NEW_BUNDLE, s),),
                                assign=assign, funding=funding,
                                pay=(0, 0, 0), accept=accept))
    return specs


# ---------------------------------------------------------------------------
# belief-independent enumeration
# ---------------------------------------------------------------------------

@dataclass
class RealizedV2:
    spec: CompletionSpec
    first: Action
    scores: dict[str, tuple[int, int]]     # resource -> (seat1, seat2)
    final_tick: int
    cls: str                               # Omega_2 class of `first`


def pay_grid(sv: ScenarioV2) -> tuple[int, ...]:
    """Fixed transfer levels, belief-independent by construction."""
    cap = sv.pay_cap
    return tuple(sorted({max(1, cap // 2), cap}))


def pay_variants_v2(sv: ScenarioV2, state, spec: CompletionSpec
                    ) -> list[CompletionSpec]:
    """Transfer levels riding a newly proposed bundle, both directions, each
    with its breach family: the bundle as written, the partner reneging it,
    and, when the mover owes the pay, the mover reneging it."""
    if spec.funding != "contract" or spec.end_now:
        return []
    if not spec.assign and spec.pay == (0, 0, 0):
        return []
    mover = state.mover
    partner = 3 - mover
    out: list[CompletionSpec] = []
    partner_breaches_already = any(s == partner for _c, s in spec.breach)
    mover_breaches_already = any(s == mover for _c, s in spec.breach)
    for amt in pay_grid(sv):
        for frm, to in ((partner, mover), (mover, partner)):
            out.append(CompletionSpec(breach=spec.breach, assign=spec.assign,
                                      funding=spec.funding,
                                      pay=(frm, to, amt), accept=spec.accept))
            if not partner_breaches_already:
                out.append(CompletionSpec(
                    breach=spec.breach + ((NEW_BUNDLE, partner),),
                    assign=spec.assign, funding=spec.funding,
                    pay=(frm, to, amt), accept=spec.accept))
            if frm == mover and not mover_breaches_already:
                out.append(CompletionSpec(
                    breach=spec.breach + ((NEW_BUNDLE, mover),),
                    assign=spec.assign, funding=spec.funding,
                    pay=(frm, to, amt), accept=spec.accept))
    return out


def completions(sv: ScenarioV2, state, *, pruned: bool = False
                ) -> list[RealizedV2]:
    """Every realizable completion at `state`, scored in every resource.

    Belief-independent: one call serves every belief cell.  `pruned=True`
    uses `enumerate_specs_pruned`, as the report's free-play census did."""
    enum = enumerate_specs_pruned if pruned else enumerate_specs
    specs: list[CompletionSpec] = []
    for spec in enum(state):
        specs.append(spec)
        specs.extend(pay_variants_v2(sv, state, spec))
    if len(specs) > MAX_REALIZATIONS:
        raise RuntimeError(f"{len(specs)} completion specs at one state "
                           f"exceeds the sanity bound {MAX_REALIZATIONS}")
    out: list[RealizedV2] = []
    for spec in specs:
        got = realize_state(state, spec)
        if got is None:
            continue
        st, first = got
        out.append(RealizedV2(spec=spec, first=first,
                              scores=score_vector(sv, st),
                              final_tick=st.final_tick or sv.D,
                              cls=refine(state, first)))
    return out


# ---------------------------------------------------------------------------
# residual go-it-alone value, per resource
# ---------------------------------------------------------------------------

def residual_solo_v2(sv: ScenarioV2, state, seat: int, resource: str) -> int:
    """The seat's residual go-it-alone value in `resource`: its acceptance
    threshold.  `solo_best` runs on the shadow scenario whose value column
    is this resource's yields."""
    sc = state.scenario
    funded = set()
    for c in state.contracts.values():
        funded.update(c.executable_jobs_of(seat))
    for j, (s, _amt, spent) in state.draw_funding.items():
        if s == seat and not spent:
            funded.add(j)
    candidates = [j for j in sc.jobs() if j not in state.done]
    extra = solo_best(
        shadow(sv, resource), seat,
        budget_cap=sc.u[seat - 1] - state.draws[seat - 1],
        pot_cap=state.pot_left,
        slots=sc.kappa[seat - 1] - state.caps_used[seat - 1],
        moves=sc.moves_remaining(seat, state.tick),
        candidates=candidates,
        optional_funded=frozenset(funded),
        done=frozenset(state.done),
    )
    return score_resource(sv, state, seat, resource) + extra


# ---------------------------------------------------------------------------
# the belief-conditioned envelope
# ---------------------------------------------------------------------------

@dataclass
class EnvelopeV2:
    tick: int
    mover: int
    mover_objective: str
    partner_objective: str
    q: dict[str, dict[str, float]] = field(default_factory=dict)   # family -> class -> value
    rep: dict[str, dict[str, Action]] = field(default_factory=dict)
    astar: dict[str, set[str]] = field(default_factory=dict)
    best: dict[str, str | None] = field(default_factory=dict)      # family -> argmax class
    # best_response value per mover strategy key: key -> (value, class, action)
    by_key: dict[tuple, tuple[float, str, Action]] = field(default_factory=dict)
    # action-level (plan-level) optimum over mover strategy keys
    best_key: str | None = None
    eps_keys: set[str] = field(default_factory=set)
    solo: tuple[int, int] = (0, 0)          # (mover solo in rho_m, partner solo in rho_p)
    n_completions: int = 0
    n_accepted: int = 0
    exposure_live: bool = False


def key_id(key: tuple) -> str:
    """Stable short identifier for a mover strategy key."""
    return hashlib.sha1(repr(key).encode("utf-8")).hexdigest()[:12]


def _needs_acceptance(spec: CompletionSpec) -> bool:
    return (spec.funding == "contract" and not spec.end_now
            and (bool(spec.assign) or spec.pay[2] > 0))


def _partner_breaches(spec: CompletionSpec, mover: int) -> bool:
    return any(s != mover for _cid, s in spec.breach)


def envelope_v2(sv: ScenarioV2, state, mover_objective: str,
                partner_objective: str, *, eps: int = EPS_DEFAULT,
                comps: list[RealizedV2] | None = None) -> EnvelopeV2:
    """The mover's action-value envelope in its own resource, conditional
    on a belief about the partner's resource.

    Families: `best_response` (primary; the branch the partner prefers, with
    a partner breach credible only if it strictly beats compliance for the
    partner, ties against the mover), `ir_only` (filtered by acceptance
    alone) and `cautious` (maximin over the partner's deviations).  Pass
    `comps` to evaluate several beliefs for one enumeration."""
    assert mover_objective in RESOURCES and partner_objective in RESOURCES
    mover = state.mover
    partner = 3 - mover
    rm, rp = mover_objective, partner_objective
    if comps is None:
        comps = completions(sv, state)

    solo_m = residual_solo_v2(sv, state, mover, rm)
    solo_p = residual_solo_v2(sv, state, partner, rp)

    def mv(r: RealizedV2) -> int:      # mover's value in its own resource
        return r.scores[rm][mover - 1]

    def pv(r: RealizedV2) -> int:      # partner's value in its own resource
        return r.scores[rp][partner - 1]

    # the compliant branch of each mover strategy: what acceptance is judged on
    compliant: dict[tuple, RealizedV2] = {}
    for r in comps:
        if not _partner_breaches(r.spec, mover):
            compliant.setdefault(_mover_key(r.spec, mover), r)

    def accepted(r: RealizedV2) -> bool:
        if not _needs_acceptance(r.spec):
            return True
        base = compliant.get(_mover_key(r.spec, mover))
        if base is None:
            return False
        return pv(base) >= solo_p

    live = [r for r in comps if accepted(r)]

    branches: dict[tuple, list[RealizedV2]] = {}
    for r in live:
        branches.setdefault(_mover_key(r.spec, mover), []).append(r)

    q: dict[str, dict[str, float]] = {f: {} for f in FAMILIES}
    rep: dict[str, dict[str, Action]] = {f: {} for f in FAMILIES}
    by_key: dict[tuple, tuple[float, str, Action]] = {}

    def bump(fam: str, cls: str, val: float, action: Action) -> None:
        if cls not in q[fam] or val > q[fam][cls]:
            q[fam][cls] = val
            rep[fam][cls] = action

    for key, group in branches.items():
        base = compliant.get(key)
        if base is None or base not in group:
            continue
        cls = base.cls
        bump("ir_only", cls, mv(base), base.first)
        bump("cautious", cls, min(mv(r) for r in group), base.first)
        # A partner-breach branch is a clean counterfactual only when the
        # mover does not also breach; otherwise the key is priced at its
        # compliant value.
        mover_breaches = any(s == mover for _c, s in base.spec.breach)
        credible = [base] if mover_breaches else (
            [base] + [r for r in group
                      if _partner_breaches(r.spec, mover) and pv(r) > pv(base)])
        top = max(pv(r) for r in credible)
        val = min(mv(r) for r in credible if pv(r) == top)
        bump("best_response", cls, val, base.first)
        by_key[key] = (val, cls, base.first)

    env = EnvelopeV2(tick=state.tick, mover=mover, mover_objective=rm,
                     partner_objective=rp, q=q, rep=rep, by_key=by_key,
                     solo=(solo_m, solo_p), n_completions=len(comps),
                     n_accepted=len(live))
    for fam, table in q.items():
        if table:
            top = max(table.values())
            env.astar[fam] = {c for c, v in table.items() if v >= top - eps}
            # deterministic argmax: highest value, ties broken by class name
            env.best[fam] = max(table, key=lambda c: (table[c], c))
        else:
            env.astar[fam] = set()
            env.best[fam] = None
    if by_key:
        top_v = max(v for v, _c, _a in by_key.values())
        env.best_key = max(by_key, key=lambda k: (by_key[k][0], key_id(k)))
        env.best_key = key_id(env.best_key)
        env.eps_keys = {key_id(k) for k, (v, _c, _a) in by_key.items()
                        if v >= top_v - eps}
    env.exposure_live = any(
        (c.status == "locked" and c.unexecuted_jobs())
        or (c.is_offer_live(state.tick) and c.proposer != mover)
        for c in state.contracts.values())
    return env


# ---------------------------------------------------------------------------
# certification over partner beliefs (the fixed-state gate rows)
# ---------------------------------------------------------------------------

def per_belief_at(sv: ScenarioV2, state, mover_objective: str, *,
                  eps: int = EPS_DEFAULT, comps=None) -> dict:
    """Per partner belief: each family's best class, eps-optimal classes and
    value table, plus the action-level optimum.  The structure `rollout`
    records at every position."""
    if comps is None:
        comps = completions(sv, state)
    out = {}
    for b in RESOURCES:
        e = envelope_v2(sv, state, mover_objective, b, eps=eps, comps=comps)
        out[b] = {fam: {"best": e.best[fam],
                        "astar": sorted(e.astar[fam]),
                        "q": {c: float(v) for c, v in sorted(e.q[fam].items())}}
                  for fam in e.q}
        out[b]["_action_level"] = {"best_key": e.best_key,
                                   "eps_keys": sorted(e.eps_keys),
                                   "n_keys": len(e.by_key)}
    return out


def certify_row(per_belief: dict) -> dict:
    """Belief sensitivity of one position, per family: does the best class
    differ across partner beliefs (`differs`), and is there no class within
    eps of best under every belief (`no_common_eps_optimum`)?  The same two
    statistics at action level under `action_level`."""
    row: dict = {"families": {}}
    for fam in FAMILIES:
        bests = {b: per_belief[b][fam]["best"] for b in RESOURCES}
        astars = {b: set(per_belief[b][fam]["astar"]) for b in RESOURCES}
        n_classes = max(len(per_belief[b][fam]["q"]) for b in RESOURCES)
        live = [b for b in RESOURCES if bests[b] is not None]
        common = (set.intersection(*[astars[b] for b in live])
                  if live else set())
        regret = 0.0
        for truth in live:
            q = per_belief[truth][fam]["q"]
            if not q:
                continue
            top = max(q.values())
            for other in live:
                a = bests[other]
                if a in q:
                    regret = max(regret, top - q[a])
                else:
                    regret = max(regret, top - min(q.values()))
        row["families"][fam] = {
            "qualifies": n_classes >= 2,
            "n_classes": n_classes,
            "bests": bests,
            "differs": len({bests[b] for b in live}) > 1 if live else False,
            "no_common_eps_optimum": bool(live) and not common,
            "max_regret_points": round(regret, 3),
        }
    al = {b: per_belief[b]["_action_level"] for b in RESOURCES}
    live_a = [b for b in RESOURCES if al[b]["best_key"] is not None]
    common_a = (set.intersection(*[set(al[b]["eps_keys"]) for b in live_a])
                if live_a else set())
    row["action_level"] = {
        "qualifies": max(al[b]["n_keys"] for b in RESOURCES) >= 2,
        "n_keys": max(al[b]["n_keys"] for b in RESOURCES),
        "differs": (len({al[b]["best_key"] for b in live_a}) > 1
                    if live_a else False),
        "no_common_eps_optimum": bool(live_a) and not common_a,
    }
    return row


def value_from_q(q: dict, cls: str) -> float | None:
    """The value of one action class in one value table; a class absent from
    the table is priced at the table's floor."""
    if not q:
        return None
    return float(q.get(cls, min(q.values())))


# ---------------------------------------------------------------------------
# sensitivity to the mover's own objective (goal-revealing decisions)
# ---------------------------------------------------------------------------

def own_objective_tables(sv: ScenarioV2, state, *, pruned: bool = False,
                         comps=None) -> dict | None:
    """Per mover objective: the `best_response` class values averaged over
    the three partner beliefs (uniform prior), the best class (ties broken
    by class name), and the stratum: "divergent" when the best class differs
    across the mover's objectives, else "flat".

    Returns None where the stratifier declines: the state is over, its
    value table is empty, or the mover has fewer than two legal Omega-2
    classes."""
    if state.over:
        return None
    if comps is None:
        comps = completions(sv, state, pruned=pruned)
    tables: dict[str, dict[str, float]] = {}
    bests: dict[str, str] = {}
    for arm in RESOURCES:
        vals: dict[str, float] = {}
        for b in RESOURCES:
            e = envelope_v2(sv, state, arm, b, comps=comps)
            for c, v in e.q["best_response"].items():
                vals[c] = vals.get(c, 0.0) + v / len(RESOURCES)
        if not vals:
            return None
        tables[arm] = dict(vals)
        bests[arm] = max(vals, key=lambda c: (vals[c], c))
    if len(legal_omega2_alphabet(state, state.mover)) < 2:
        return None
    return {"stratum": ("divergent" if len(set(bests.values())) > 1
                        else "flat"),
            "bests": bests, "tables": tables,
            "n_completions": len(comps)}


def classify_tables(tables: dict[str, dict[str, float]],
                    eps: float = EPS_DEFAULT) -> dict[str, Any]:
    """Flip and hedge of one state from its per-objective class tables.

    flip: the best class differs across objectives.  hedge margin: for each
    class present in every table, the worst shortfall from that table's top;
    the state's margin is the best such class.  Hedged iff the margin is at
    least -eps."""
    bests = {arm: max(t, key=lambda c: (t[c], c)) for arm, t in tables.items()}
    flip = len(set(bests.values())) > 1
    tops = {arm: max(t.values()) for arm, t in tables.items()}
    common = set.intersection(*[set(t) for t in tables.values()])
    margins = {c: min(tables[a][c] - tops[a] for a in tables) for c in common}
    hedge_margin = max(margins.values()) if margins else None
    hedged = hedge_margin is not None and hedge_margin >= -eps
    hedge_classes = sorted(c for c, m in margins.items() if m >= -eps)
    return {"flip": flip, "stratum": "divergent" if flip else "flat",
            "best_by_arm": bests,
            "hedge_margin": (None if hedge_margin is None
                             else round(hedge_margin, 6)),
            "hedged": hedged, "hedge_classes": hedge_classes}
