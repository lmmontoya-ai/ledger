"""Scenario: the immutable parameter vector theta of ENVIRONMENT_DESIGN §10.1.

All quantities are integers.  Jobs are numbered 1..K.  Seats are 1 and 2.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    seed: int
    generator_version: str
    K: int
    # c[0] is seat 1's cost column, c[1] seat 2's; index job-1.
    c: tuple[tuple[int, ...], tuple[int, ...]]
    # v[0] is seat 1's private value column, v[1] seat 2's.
    v: tuple[tuple[int, ...], tuple[int, ...]]
    # prereqs[job-1] = tuple of job numbers that must be done first.
    prereqs: tuple[tuple[int, ...], ...]
    B: int
    kappa: tuple[int, int]
    u: tuple[int, int]
    D: int
    r: int
    eps: int
    p: int
    p_def: int
    opening: int  # seat that moves at tick 1
    # exposure metadata from the generator: victim/breaker seats, head/tail jobs.
    exposure: tuple[int, int, int, int] | None = None  # (victim, breaker, head, tail)
    # L2a transfer-friction lever (RETUNE_PLAN 7).  None = the original v1
    # rule (each payment bounded by W*, TRANSFER free).  An integer caps the
    # TOTAL of scheduled payments per contract and disables TRANSFER, so
    # surplus extraction is bounded (own-vs-joint realignment breaks above
    # the cap) while dodgeable pays keep the deferred-pay temptation alive.
    # 0 disables money movement entirely.  Default None: v1 banks unchanged.
    pay_cap: int | None = None
    # L2a companion (loop 5): scheduled payments may only fall in the final
    # `settle_window` turns (end-of-period net settlement), so every payment
    # is an IOU that outlives the cooling-off window and can be reneged on.
    # Trust exposure becomes a property of ordinary deals rather than a
    # special contract type nobody rationally proposes.  None = v1 rule.
    settle_window: int | None = None
    # loop 6 (FORGE-informed): per-job earliest workable turn.  Jobs are on
    # the board from turn 1 but cannot be drawn for or executed before their
    # arrival, so late arrivals reopen negotiation mid-game and deals struck
    # early about them are forward contracts whose payments (under the
    # settlement window) are IOUs by construction.  Empty = all jobs
    # available from turn 1 (v1 banks unchanged).
    available_from: tuple[int, ...] = ()
    # communication switch: when False, CHAT is illegal, the action is
    # removed from the tool schema, and the rules text says so.  Values
    # then have to be inferred from actions rather than told.
    chat_enabled: bool = True

    def arrive(self, job: int) -> int:
        return self.available_from[job - 1] if self.available_from else 1

    def cost(self, seat: int, job: int) -> int:
        return self.c[seat - 1][job - 1]

    def value(self, seat: int, job: int) -> int:
        return self.v[seat - 1][job - 1]

    def jobs(self) -> range:
        return range(1, self.K + 1)

    def mover_at(self, tick: int) -> int:
        """Seat that moves at 1-based tick; agents strictly alternate."""
        return self.opening if tick % 2 == 1 else 3 - self.opening

    def moves_remaining(self, seat: int, next_tick: int) -> int:
        """Number of ticks in [next_tick, D] at which `seat` moves."""
        return sum(1 for t in range(next_tick, self.D + 1) if self.mover_at(t) == seat)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @staticmethod
    def from_dict(d: dict) -> "Scenario":
        return Scenario(
            scenario_id=d["scenario_id"],
            seed=d["seed"],
            generator_version=d["generator_version"],
            K=d["K"],
            c=tuple(tuple(col) for col in d["c"]),
            v=tuple(tuple(col) for col in d["v"]),
            prereqs=tuple(tuple(p) for p in d["prereqs"]),
            B=d["B"],
            kappa=tuple(d["kappa"]),
            u=tuple(d["u"]),
            D=d["D"],
            r=d["r"],
            eps=d["eps"],
            p=d["p"],
            p_def=d["p_def"],
            opening=d["opening"],
            exposure=tuple(d["exposure"]) if d.get("exposure") else None,
            pay_cap=d.get("pay_cap"),
            settle_window=d.get("settle_window"),
            available_from=tuple(d.get("available_from") or ()),
            chat_enabled=bool(d.get("chat_enabled", True)),
        )

    def with_opening(self, opening: int) -> "Scenario":
        d = self.to_dict()
        d["opening"] = opening
        return Scenario.from_dict(d)


def scenario_id_for(generator_version: str, seed: int) -> str:
    return hashlib.sha256(f"{generator_version}||{seed}".encode("utf-8")).hexdigest()
