"""Residual completion enumeration and fold-backed realization (RETUNE_PLAN §3).

A *completion* is one deterministic joint continuation from a mid-game state:
which standing contracts get breached and by whom, which remaining jobs get
done by whom under which funding channel, and what transfer rides on the new
contract.  Every completion is realized as a legal event sequence replayed
through fold.apply, so payoffs are read from State.score() and are
engine-exact by construction; nothing here reimplements scoring.

Epistemic status: this is the optimistic action-value envelope.  Both seats
are steered by one plan (the declared partner-response model is
individually-rational compliance, checked against the partner's residual solo
optimum).  Silent-default branches are excluded: admission §5.4 guarantees
honest renege weakly dominates stalling, so stall completions are dominated.
CANCEL branches (window exits) are not enumerated in v1; RENEGE fires at the
first legal tick of its branch.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from itertools import product

from ..core import actions as actions_mod
from ..core import fold as fold_mod
from ..core.events import Action, Event
from ..core.schedule import greedy_schedule_feasible
from ..core.welfare import solo_best, w_star

MAX_SPECS_PER_STATE = 20_000     # hard sanity bound, never silently truncated


@dataclass(frozen=True)
class CompletionSpec:
    breach: tuple[tuple[int, int], ...]   # (cid, breaching seat), renege ASAP
    assign: tuple[tuple[int, int], ...]   # new job -> seat
    funding: str                          # "contract" | "solo"
    pay: tuple[int, int, int]             # (from, to, amount); amount 0 = none
    accept: tuple[int, ...] = ()          # live partner offers the mover locks
    end_now: bool = False


@dataclass
class Realized:
    spec: CompletionSpec
    first: Action          # the decision seat's first action
    pi: tuple[int, int]    # final scores, engine-exact
    final_tick: int


# ---------------------------------------------------------------------------
# residual capacities
# ---------------------------------------------------------------------------

def honored_obligations(state, breach: dict[int, int]) -> dict[int, int]:
    """job -> seat still owed under locked contracts that this completion does
    not breach.  A breached contract keeps the victim's jobs alive as
    *optional*; those are handled as free executes, not obligations."""
    out: dict[int, int] = {}
    for cid, c in state.contracts.items():
        if c.status != "locked" or cid in breach:
            continue
        for s in (1, 2):
            for j in c.obligations_of(s):
                out[j] = s
    return out


def optional_jobs(state, breach: dict[int, int]) -> dict[int, int]:
    """Victim-side funded jobs that remain executable: already-reneged
    contracts, plus victim jobs of contracts this completion breaches."""
    out: dict[int, int] = {}
    for cid, c in state.contracts.items():
        if c.status == "reneged":
            for s in (1, 2):
                for j in c.optional_jobs_of(s):
                    out[j] = s
        if c.status == "locked" and cid in breach:
            victim = 3 - breach[cid]
            for j in c.unexecuted_jobs():
                if c.assign[j] == victim:
                    out[j] = victim
    return out


def residual_solo(state, seat: int) -> int:
    """The seat's residual go-it-alone value (partner-IR threshold): §6.3
    machinery on what is left, funded by draws and already-assigned funding."""
    sc = state.scenario
    funded = set()
    for c in state.contracts.values():
        funded.update(c.executable_jobs_of(seat))
    for j, (s, _amt, spent) in state.draw_funding.items():
        if s == seat and not spent:
            funded.add(j)
    candidates = [j for j in sc.jobs() if j not in state.done]
    extra = solo_best(
        sc, seat,
        budget_cap=sc.u[seat - 1] - state.draws[seat - 1],
        pot_cap=state.pot_left,
        slots=sc.kappa[seat - 1] - state.caps_used[seat - 1],
        moves=sc.moves_remaining(seat, state.tick),
        candidates=candidates,
        optional_funded=frozenset(funded),
        done=frozenset(state.done),
    )
    return state.score(seat) + extra


# ---------------------------------------------------------------------------
# spec enumeration
# ---------------------------------------------------------------------------

NEW_BUNDLE = -1   # sentinel cid: the completion's own proposed bundle


def _breach_options(state, accepted: dict[int, dict[int, int]]) -> list[dict[int, int]]:
    """Breach combinations over contracts that are locked at the state or
    become locked in this branch (accepted live offers).  The new bundle's
    breach variants are added per assignment in enumerate_specs."""
    per_contract = []
    for cid, c in sorted(state.contracts.items()):
        if c.status != "locked":
            continue
        opts: list[tuple[int, int] | None] = [None]
        for s in (1, 2):
            # a seat may breach to void its job obligations OR to dodge a
            # scheduled pay it owes (the deferred-pay trap, live in E0 ep14)
            if c.obligations_of(s) or any(p.from_ == s for p in c.live_pays()):
                opts.append((cid, s))
        per_contract.append(opts)
    for cid, assign in sorted(accepted.items()):
        c = state.contracts[cid]
        opts = [None]
        for s in (1, 2):
            if any(a == s for a in assign.values()) or c.live_pays():
                opts.append((cid, s))
        per_contract.append(opts)
    combos = []
    for combo in product(*per_contract) if per_contract else [()]:
        combos.append({cid: s for item in combo if item for cid, s in [item]})
    return combos


def _feasible_assignments(state, breach: dict[int, int], mover: int,
                          accepted: dict[int, int],
                          accepted_fund: int):
    """(assign, funding) pairs passing the cheap integer prefilter.  The
    realizer is ground truth; this only bounds enumeration.  `accepted` are
    job -> seat obligations of live offers this branch locks; their funding
    leaves the pot at ACCEPT."""
    sc = state.scenario
    obligations = honored_obligations(state, breach)
    obligations.update(accepted)
    opts = optional_jobs(state, breach)
    candidates = [j for j in sc.jobs()
                  if j not in state.done and j not in obligations
                  and j not in opts
                  and not (j in state.draw_funding
                           and not state.draw_funding[j][2])]
    slots_left = {s: sc.kappa[s - 1] - state.caps_used[s - 1]
                  - sum(1 for j, o in obligations.items() if o == s)
                  - sum(1 for j, o in opts.items() if o == s)
                  for s in (1, 2)}
    pot = state.pot_left - accepted_fund
    out = [((), "contract")]
    n = len(candidates)
    for mask_sigma in product((0, 1, 2), repeat=n):
        assign = {candidates[i]: mask_sigma[i] for i in range(n)
                  if mask_sigma[i] != 0}
        if not assign:
            continue
        if any(sum(1 for s in assign.values() if s == seat)
               > max(0, slots_left[seat]) for seat in (1, 2)):
            continue
        full = dict(obligations)
        full.update(assign)
        closure = set(state.done) | set(full) | set(opts)
        if any(pre not in closure for j in assign
               for pre in sc.prereqs[j - 1]):
            continue
        # contract family: pot must cover new funding
        cost_total = sum(sc.cost(s, j) for j, s in assign.items())
        if cost_total <= pot and state.tick + 2 <= sc.D:
            if greedy_schedule_feasible(sc, full, state.tick + 2,
                                        done=set(state.done)):
                out.append((tuple(sorted(assign.items())), "contract"))
        # solo family: mover-only, draw-funded
        if all(s == mover for s in assign.values()):
            draw_cost = sum(sc.cost(mover, j) for j in assign)
            if (draw_cost <= sc.u[mover - 1] - state.draws[mover - 1]
                    and draw_cost <= pot
                    and greedy_schedule_feasible(
                        sc, full, state.tick, done=set(state.done),
                        self_funded=frozenset(assign))):
                out.append((tuple(sorted(assign.items())), "solo"))
    return out


def enumerate_specs(state) -> list[CompletionSpec]:
    """All completion specs at a state, pay grid deferred to objectives.py
    (pay levels depend on realized surpluses).  Live partner offers branch
    over {ignore, accept}; renege-after-accept of a just-locked offer is not
    modeled at this state (it surfaces at later states of the same episode)."""
    mover = state.mover
    live = [c for c in state.contracts.values()
            if c.is_offer_live(state.tick) and c.proposer != mover]
    accept_branches: list[tuple[tuple[int, ...], dict[int, int], int]] = [
        ((), {}, 0)]
    for c in live:
        accept_branches.append(
            ((c.cid,), dict(c.assign), sum(c.fund.values())))
    specs = [CompletionSpec(breach=(), assign=(), funding="contract",
                            pay=(0, 0, 0), end_now=True)]
    for accept, acc_assign, acc_fund in accept_branches:
        acc_map = {cid: dict(state.contracts[cid].assign) for cid in accept}
        for breach in _breach_options(state, acc_map):
            btup = tuple(sorted(breach.items()))
            for assign, funding in _feasible_assignments(
                    state, breach, mover, acc_assign, acc_fund):
                specs.append(CompletionSpec(breach=btup, assign=assign,
                                            funding=funding, pay=(0, 0, 0),
                                            accept=accept))
                # breach variants of the completion's own bundle: either
                # party may renege it once locked (post-window)
                if funding == "contract" and assign:
                    for s in (1, 2):
                        if any(a == s for _j, a in assign):
                            specs.append(CompletionSpec(
                                breach=btup + ((NEW_BUNDLE, s),),
                                assign=assign, funding=funding,
                                pay=(0, 0, 0), accept=accept))
    if len(specs) > MAX_SPECS_PER_STATE:
        raise RuntimeError(f"{len(specs)} specs at one state exceeds the "
                           f"sanity bound; shrink the scenario")
    return specs


# ---------------------------------------------------------------------------
# realization: spec -> legal event sequence -> final state
# ---------------------------------------------------------------------------

def _topo_ready(sc, jobs: dict[int, int], seat: int, done: set[int]):
    ready = [j for j, s in jobs.items()
             if s == seat and j not in done
             and all(p in done for p in sc.prereqs[j - 1])]
    ready.sort()
    return ready


def realize(state, spec: CompletionSpec) -> Realized | None:
    """Drive both seats along the spec via validate + fold.apply.  Returns
    None when the spec is not realizable as legal play (the prefilter is
    optimistic by design)."""
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
        """Owed work per the CURRENT contracts: locked-and-honored plus the
        breach victims' optional funded jobs, plus solo-planned jobs."""
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
        # 1. renege the designated contracts at first legal moment
        for cid, s in sorted(breach.items()):
            if (s == seat and cid in st.contracts
                    and st.contracts[cid].status == "locked"):
                a = Action("RENEGE", {"contract_id": cid})
                if actions_mod.validate(st, seat, a) is None:
                    action = a
                    break
        # 2a. the decision seat locks the offers its plan accepts
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
        # 2b. propose the cooperative bundle
        if action is None and not proposal_made and seat == decision_seat:
            fund = {str(j): sc.cost(s, j) for j, s in new_assign.items()}
            pays = []
            frm, to, amt = spec.pay
            if amt > 0:
                turn = min(st.tick + 2, sc.D)
                if sc.settle_window is not None:
                    turn = max(turn, sc.D - sc.settle_window + 1)
                pays = [{"from": frm, "to": to, "amount": amt,
                         "turn": turn}]
            contract = {"assign": {str(j): s for j, s in new_assign.items()},
                        "fund": fund, "pay": pays,
                        "expires": min(st.tick + 3, sc.D)}
            a = Action("PROPOSE", {"contract": contract})
            if actions_mod.validate(st, seat, a) is not None:
                return None
            action = a
        # 3. the partner accepts exactly the plan's new bundle, nothing else
        if action is None and seat != decision_seat and proposal_cid is not None:
            c = st.contracts.get(proposal_cid)
            if c is not None and c.is_offer_live(st.tick):
                a = Action("ACCEPT", {"offer_id": proposal_cid})
                if actions_mod.validate(st, seat, a) is not None:
                    return None
                action = a
        # 4. draw for solo-funded jobs
        if action is None and spec.funding == "solo":
            for j in sorted(new_assign):
                if (new_assign[j] == seat and j not in drawn
                        and j not in st.done):
                    a = Action("DRAW", {"amount": sc.cost(seat, j), "job": j})
                    if actions_mod.validate(st, seat, a) is None:
                        action = a
                        drawn.add(j)
                        break
        # 5. execute ready funded work
        if action is None:
            jobs = obligations_now()
            for j in _topo_ready(sc, jobs, seat, set(st.done)):
                a = Action("EXECUTE", {"job": j})
                if actions_mod.validate(st, seat, a) is None:
                    action = a
                    break
        # 6. done with the plan: END; otherwise WAIT for the board to move
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

    # completions must not leave planned work undone: settlement defaults are
    # dominated by honest renege (§5.4) and excluded from the envelope
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
    return Realized(spec=spec, first=first,
                    pi=(st.score(1), st.score(2)),
                    final_tick=st.final_tick or sc.D)


def w_star_residual(state) -> int:
    """Best joint completion value reachable from here (for frontier width)."""
    best = None
    for spec in enumerate_specs(state):
        r = realize(state, spec)
        if r is not None:
            tot = r.pi[0] + r.pi[1]
            best = tot if best is None else max(best, tot)
    return best if best is not None else state.score(1) + state.score(2)
