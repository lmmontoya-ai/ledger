"""Contract lifecycle per ENVIRONMENT_DESIGN §5.

Stages: offered -> locked (instant at ACCEPT, atomic with reservation) -> done,
with CANCEL during the cooling-off window and RENEGE after it.  Dead statuses:
rejected, countered, expired, cancelled, reneged (reneged contracts keep the
victim's optional funded obligations alive).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Pay:
    from_: int
    to: int
    amount: int
    tick: int
    executed: bool = False
    cancelled: bool = False
    executed_tick: int | None = None

    def to_dict(self) -> dict:
        return {"from": self.from_, "to": self.to, "amount": self.amount, "tick": self.tick}


@dataclass
class Contract:
    cid: int
    proposer: int
    tick_opened: int
    assign: dict[int, int]      # job -> seat
    fund: dict[int, int]        # job -> amount reserved at ACCEPT
    pay: list[Pay]
    expires: int
    status: str = "offered"     # offered|locked|rejected|countered|expired|cancelled|reneged
    accept_tick: int | None = None
    executed_jobs: set[int] = field(default_factory=set)
    reneged_by: int | None = None
    renege_tick: int | None = None
    cancelled_by: int | None = None
    cancel_tick: int | None = None
    defaulted_by: list[int] = field(default_factory=list)

    # ---- lifecycle predicates -------------------------------------------
    def is_offer_live(self, tick: int) -> bool:
        """Offer is answerable at `tick` (lapses at the END of tick `expires`)."""
        return self.status == "offered" and tick <= self.expires

    def window_bounds(self, D: int, r: int) -> tuple[int, int]:
        assert self.accept_tick is not None
        return self.accept_tick + 1, min(self.accept_tick + r, D)

    def window_open_at(self, tick: int, D: int, r: int) -> bool:
        if self.status != "locked":
            return False
        lo, hi = self.window_bounds(D, r)
        return lo <= tick <= hi

    def window_closed_at(self, tick: int, D: int, r: int) -> bool:
        if self.status != "locked":
            return False
        _, hi = self.window_bounds(D, r)
        return tick > hi

    # ---- obligations ----------------------------------------------------
    def unexecuted_jobs(self) -> list[int]:
        return [j for j in sorted(self.assign) if j not in self.executed_jobs]

    def obligations_of(self, seat: int) -> list[int]:
        """Unexecuted binding obligations of `seat` under this contract."""
        if self.status == "locked":
            return [j for j in self.unexecuted_jobs() if self.assign[j] == seat]
        return []

    def optional_jobs_of(self, seat: int) -> list[int]:
        """After the partner reneged, `seat`'s remaining jobs are optional but
        still funded and executable."""
        if self.status == "reneged" and self.reneged_by is not None and seat != self.reneged_by:
            return [j for j in self.unexecuted_jobs() if self.assign[j] == seat]
        return []

    def executable_jobs_of(self, seat: int) -> list[int]:
        """Jobs `seat` may execute with this contract's reserved funding."""
        return self.obligations_of(seat) + self.optional_jobs_of(seat)

    def reserved_amount(self) -> int:
        """Funding still held in this contract's reserve."""
        if self.status == "locked":
            return sum(self.fund[j] for j in self.unexecuted_jobs())
        if self.status == "reneged":
            # only the victim's optional jobs keep their reserve
            victim = 3 - self.reneged_by
            return sum(self.fund[j] for j in self.unexecuted_jobs() if self.assign[j] == victim)
        return 0

    def live_pays(self) -> list[Pay]:
        return [p for p in self.pay if not p.executed and not p.cancelled]

    def cancel_unexecuted_pays(self) -> None:
        for p in self.pay:
            if not p.executed:
                p.cancelled = True


def friction_destroyed(x: int) -> int:
    """ceil(x/4): destroyed share of a cancelled allocation, rounded against
    the reneger (§5.3 step 3, phi = 1/4)."""
    return -((-x) // 4)


def friction_refund(x: int) -> int:
    return x - friction_destroyed(x)
