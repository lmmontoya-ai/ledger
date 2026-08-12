"""Ledger -> derived state.

state(L) = fold(empty, L).  `apply` is the single-step pure transition; `fold`
is its iteration from the initial state.  fold(step(L, a)) == apply(fold(L), a)
by construction, and the property test pins it.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from .contracts import Contract, friction_destroyed, friction_refund
from .events import Event
from .scenario import Scenario


@dataclass
class State:
    scenario: Scenario
    tick: int = 1                 # next tick to be played
    over: bool = False
    settled: bool = False
    ended_by_mutual: bool = False
    final_tick: int | None = None
    pot_left: int = 0
    reserved: int = 0
    spent: int = 0                # pot outflow: draws taken + execution costs paid
    destroyed: int = 0            # friction + end-of-episode destruction
    draws: list[int] = field(default_factory=lambda: [0, 0])
    caps_used: list[int] = field(default_factory=lambda: [0, 0])
    accounts: list[int] = field(default_factory=lambda: [0, 0])
    # net voluntary transfers + executed scheduled payments, excluding
    # penalties/compensation/cancel fees (used by attainability, §9.1/§9.4)
    transfers_net: list[int] = field(default_factory=lambda: [0, 0])
    done: dict[int, tuple[int, int]] = field(default_factory=dict)   # job -> (seat, tick)
    draw_funding: dict[int, list] = field(default_factory=dict)      # job -> [seat, amount, spent]
    contracts: dict[int, Contract] = field(default_factory=dict)
    next_cid: int = 1
    last_nonwait: list = field(default_factory=lambda: [None, None])
    reneges: list[dict] = field(default_factory=list)
    defaults: list[dict] = field(default_factory=list)

    # ------------------------------------------------------------------
    def __deepcopy__(self, memo) -> "State":
        """Explicit field-wise clone, semantically identical to the generic
        deepcopy and ~5-10x faster.  The scenario is a frozen dataclass of
        tuples and is shared, not copied; every mutable container is copied
        to exactly the depth the effect functions mutate it (the §13
        property suite pins purity, so any divergence here fails tests)."""
        return State(
            scenario=self.scenario,
            tick=self.tick, over=self.over, settled=self.settled,
            ended_by_mutual=self.ended_by_mutual, final_tick=self.final_tick,
            pot_left=self.pot_left, reserved=self.reserved, spent=self.spent,
            destroyed=self.destroyed,
            draws=list(self.draws), caps_used=list(self.caps_used),
            accounts=list(self.accounts),
            transfers_net=list(self.transfers_net),
            done=dict(self.done),
            draw_funding={j: list(v) for j, v in self.draw_funding.items()},
            contracts={cid: c.__deepcopy__(memo)
                       for cid, c in self.contracts.items()},
            next_cid=self.next_cid,
            last_nonwait=list(self.last_nonwait),
            reneges=[{k: (list(v) if isinstance(v, list) else v)
                      for k, v in r.items()} for r in self.reneges],
            defaults=[{k: (list(v) if isinstance(v, list) else v)
                       for k, v in r.items()} for r in self.defaults],
        )

    @property
    def mover(self) -> int:
        return self.scenario.mover_at(self.tick)

    def score(self, seat: int) -> int:
        sc = self.scenario
        return sum(sc.value(seat, j) for j in self.done) + self.accounts[seat - 1]

    def money_identity(self) -> tuple[int, int]:
        """(lhs, B): pot conservation — reserved + spent + left + destroyed == B."""
        return (self.pot_left + self.reserved + self.spent + self.destroyed,
                self.scenario.B)

    def live_offers(self) -> list[Contract]:
        return [c for c in self.contracts.values() if c.is_offer_live(self.tick)]

    def locked_contracts(self) -> list[Contract]:
        return [c for c in self.contracts.values() if c.status == "locked"]


def initial_state(scenario: Scenario) -> State:
    return State(scenario=scenario, pot_left=scenario.B)


def apply(state: State, ev: Event, _settle_order_key=None) -> State:
    """Pure single-step transition: returns a new state, never mutates.

    `_settle_order_key` exists only for the §13 order-independence property
    test: it permutes the settlement processing order, which must never
    change the outcome."""
    from . import actions as actions_mod
    if state.over:
        raise ValueError("cannot apply an event to a finished episode")
    if ev.tick != state.tick:
        raise ValueError(f"event tick {ev.tick} != expected tick {state.tick}")
    if ev.seat != state.mover:
        raise ValueError(f"event seat {ev.seat} is not the mover at tick {ev.tick}")

    st = copy.deepcopy(state)
    actions_mod.apply_effect(st, ev)

    # last non-WAIT action per seat (invalid events are recorded WAITs)
    if not ev.invalid and ev.action.name != "WAIT":
        st.last_nonwait[ev.seat - 1] = ev.action.name

    # offer expiry: an offer with expires = t lapses at the end of tick t
    for c in st.contracts.values():
        if c.status == "offered" and c.expires <= ev.tick:
            c.status = "expired"

    # episode end: tick D, or both agents' most recent non-WAIT actions are END
    mutual = st.last_nonwait[0] == "END" and st.last_nonwait[1] == "END"
    if mutual:
        st.ended_by_mutual = True
    if ev.tick >= st.scenario.D or mutual:
        st.over = True
        st.final_tick = ev.tick
        _settle(st, order_key=_settle_order_key)
    else:
        _run_due_payments(st, ev.tick)

    st.tick = ev.tick + 1
    return st


def fold(scenario: Scenario, events) -> State:
    st = initial_state(scenario)
    for ev in events:
        st = apply(st, ev)
    return st


# ---------------------------------------------------------------------------
# scheduled payments (§6.1: self-enforcing; the only breach is RENEGE)
# ---------------------------------------------------------------------------

def _execute_pay(st: State, pay, tick: int) -> None:
    pay.executed = True
    pay.executed_tick = tick
    st.accounts[pay.from_ - 1] -= pay.amount
    st.accounts[pay.to - 1] += pay.amount
    st.transfers_net[pay.from_ - 1] -= pay.amount
    st.transfers_net[pay.to - 1] += pay.amount


def _run_due_payments(st: State, tick: int) -> None:
    for cid in sorted(st.contracts):
        c = st.contracts[cid]
        if c.status != "locked":
            continue
        for pay in c.pay:
            if not pay.executed and not pay.cancelled and pay.tick <= tick:
                _execute_pay(st, pay, tick)


# ---------------------------------------------------------------------------
# end settlement (§5.4): one snapshot, simultaneous defaults, then payments,
# then the pot — reserves and all — is destroyed
# ---------------------------------------------------------------------------

def _settle(st: State, order_key=None) -> None:
    sc = st.scenario
    # 1. snapshot the locked, unexecuted obligations
    snapshot = []
    for cid in sorted(st.contracts):
        c = st.contracts[cid]
        if c.status == "locked":
            for j in c.unexecuted_jobs():
                snapshot.append((cid, j, c.assign[j]))
    if order_key is not None:
        snapshot = sorted(snapshot, key=order_key)
    # 2-3. every snapshot obligation is a default by its assignee; all fire
    # simultaneously from the snapshot with p_def, cancelling those contracts'
    # unexecuted scheduled payments both directions
    defaulters = sorted({(cid, s) for cid, _, s in snapshot})
    if order_key is not None:
        defaulters = sorted(defaulters, key=order_key)
    for cid, s in defaulters:
        partner = 3 - s
        st.accounts[s - 1] -= sc.p_def
        st.accounts[partner - 1] += sc.p_def // 2
        st.defaults.append({"cid": cid, "by": s,
                            "jobs": [j for c2, j, s2 in snapshot if c2 == cid and s2 == s]})
    for cid, j, s in snapshot:
        c = st.contracts[cid]
        x = c.fund[j]
        st.reserved -= x
        st.pot_left += friction_refund(x)
        st.destroyed += friction_destroyed(x)
    for cid in sorted({cid for cid, _, _ in snapshot}):
        st.contracts[cid].cancel_unexecuted_pays()
        st.contracts[cid].defaulted_by = sorted({s for c2, _, s in snapshot if c2 == cid})
    # 4. remaining scheduled payments execute; accounts settle
    for cid in sorted(st.contracts):
        c = st.contracts[cid]
        if c.status not in ("locked", "reneged"):
            continue
        for pay in c.pay:
            if not pay.executed and not pay.cancelled:
                _execute_pay(st, pay, st.final_tick or sc.D)
    # open offers lapse, free
    for c in st.contracts.values():
        if c.status == "offered":
            c.status = "expired"
    # the pot — reserves and all — is destroyed
    st.destroyed += st.pot_left + st.reserved
    st.pot_left = 0
    st.reserved = 0
    st.settled = True
