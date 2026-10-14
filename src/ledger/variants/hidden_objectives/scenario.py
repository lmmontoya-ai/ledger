"""ScenarioV2: the multi-resource parameter vector, and the resource scorer.

The structural idea
-------------------
A hidden-objectives scenario is an ordinary `Scenario` (the DYNAMICS
scenario) plus one yield column per resource per seat (the PAYOFF table).
This split is what lets the core engine run unmodified:

  * Legality, capacity, chains, funding, the schedule simulator and
    settlement read `c` (costs), `kappa`, `prereqs`, `B`, `u`, `D` and
    `available_from`.  They read `v` in exactly two places, both of which are
    the payment ceiling `min(w_star(sc), pay_cap)`
    (`actions._p_contract_wellformed`, `actions._p_transfer_bounds`).  The
    variant always sets `pay_cap` below every resource column's W*, so the
    ceiling is `pay_cap` and the dynamics do not depend on which resource
    anyone is maximising.  `tests/test_hidden_objectives.py` pins this.
  * The Omega_2 refinement reads `v` too.  The variant gives the base
    scenario a REFERENCE value column (the per-seat sum across resources,
    "appraised worth"), so the action-class alphabet is the same for every
    objective assignment.  If the class label moved with the hidden
    objective, a behavioural comparison across objectives would be
    contaminated by relabelling.

Resources
---------
cash        transferable.  The only resource money moves in: scheduled pays,
            TRANSFER, renege penalties, default penalties and cancel fees all
            land in `accounts`, and `accounts` enters the cash score only.
materials   non-transferable and purely productive.  A materials maximiser
            cannot be bought with money; it must be paid in work assignment.
standing    non-transferable, and the only resource sensitive to conduct:
            keeping a contract adds `standing_kept`, reneging or defaulting
            costs `standing_broken`.  A standing maximiser loses by breaching.

The three objectives therefore differ in three independent channels: which
jobs you want done, whether money is worth anything to you, and whether your
promises bind.

Ported from the research harness (`ledger-experiments/engine_v2/
scenario_v2.py` in self-other-prediction-smoke-tests).  Behaviour is
byte-identical; `scripts/check_hidden_objectives_equivalence.py` proves it.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass

from ...core.scenario import Scenario

RESOURCES: tuple[str, ...] = ("cash", "materials", "standing")

# The transferable resource.  `accounts` (pays, transfers, penalties,
# compensation, cancel fees) is added to this resource's score and no other.
TRANSFERABLE = "cash"

Column = tuple[int, ...]
Pair = tuple[Column, Column]


def objective_menu() -> tuple[str, ...]:
    """The hidden-objective menu: one assigned resource to maximise."""
    return RESOURCES


@dataclass(frozen=True)
class ScenarioV2:
    """Immutable; hashable (every field is a scalar or a tuple)."""

    scenario_id: str
    seed: int
    generator_version: str
    K: int
    # fields shared with the core Scenario
    c: Pair                                    # cost columns, per seat
    prereqs: tuple[tuple[int, ...], ...]
    B: int
    kappa: tuple[int, int]
    u: tuple[int, int]
    D: int                                     # 48 in the studied bank
    r: int
    eps: int
    p: int
    p_def: int
    opening: int
    exposure: tuple[int, int, int, int] | None
    pay_cap: int
    settle_window: int
    available_from: tuple[int, ...]
    chat_enabled: bool
    # one yield column pair per resource, in RESOURCES order
    yields: tuple[Pair, ...]
    # The episode runs D turns; the objective bonus is scored on turns
    # 1..scored_turns.
    scored_turns: int = 24
    # conduct effects on standing
    standing_kept: int = 6
    standing_broken: int = 14

    # accessors ----------------------------------------------------------
    def jobs(self) -> range:
        return range(1, self.K + 1)

    def cost(self, seat: int, job: int) -> int:
        return self.c[seat - 1][job - 1]

    def yield_of(self, resource: str, seat: int, job: int) -> int:
        return self.yields[RESOURCES.index(resource)][seat - 1][job - 1]

    def column(self, resource: str) -> Pair:
        return self.yields[RESOURCES.index(resource)]

    def reference_column(self) -> Pair:
        """Appraised worth: the sum across resources, per seat per job.

        Used only by core machinery that needs a single value column: the
        Omega_2 division and priority tokens, the harm model, and `w_star`
        (which never binds, because `pay_cap` is smaller).  It is the same
        for every objective assignment by construction.
        """
        return tuple(
            tuple(sum(self.yields[k][s][j] for k in range(len(RESOURCES)))
                  for j in range(self.K))
            for s in (0, 1))

    # the core view --------------------------------------------------------
    def base(self, opening: int | None = None) -> Scenario:
        """The core Scenario the engine actually runs."""
        return Scenario(
            scenario_id=self.scenario_id,
            seed=self.seed,
            generator_version=self.generator_version,
            K=self.K,
            c=self.c,
            v=self.reference_column(),
            prereqs=self.prereqs,
            B=self.B, kappa=self.kappa, u=self.u, D=self.D, r=self.r,
            eps=self.eps, p=self.p, p_def=self.p_def,
            opening=self.opening if opening is None else opening,
            exposure=self.exposure,
            pay_cap=self.pay_cap,
            settle_window=self.settle_window,
            available_from=self.available_from,
            chat_enabled=self.chat_enabled,
        )

    def with_opening(self, opening: int) -> "ScenarioV2":
        d = self.to_dict()
        d["opening"] = opening
        return ScenarioV2.from_dict(d)

    # serialisation ----------------------------------------------------------
    def to_dict(self) -> dict:
        d = asdict(self)
        d["yields"] = {r: [list(self.column(r)[0]), list(self.column(r)[1])]
                       for r in RESOURCES}
        return d

    @staticmethod
    def from_dict(d: dict) -> "ScenarioV2":
        ys = d["yields"]
        if isinstance(ys, dict):
            yields = tuple(
                (tuple(ys[r][0]), tuple(ys[r][1])) for r in RESOURCES)
        else:                                       # already positional
            yields = tuple((tuple(a), tuple(b)) for a, b in ys)
        return ScenarioV2(
            scenario_id=d["scenario_id"], seed=d["seed"],
            generator_version=d["generator_version"], K=d["K"],
            c=(tuple(d["c"][0]), tuple(d["c"][1])),
            prereqs=tuple(tuple(p) for p in d["prereqs"]),
            B=d["B"], kappa=tuple(d["kappa"]), u=tuple(d["u"]),
            D=d["D"], r=d["r"], eps=d["eps"], p=d["p"], p_def=d["p_def"],
            opening=d["opening"],
            exposure=tuple(d["exposure"]) if d.get("exposure") else None,
            pay_cap=d["pay_cap"], settle_window=d["settle_window"],
            available_from=tuple(d.get("available_from") or ()),
            chat_enabled=bool(d.get("chat_enabled", True)),
            yields=yields,
            scored_turns=d.get("scored_turns", 24),
            standing_kept=d.get("standing_kept", 6),
            standing_broken=d.get("standing_broken", 14),
        )


def scenario_id_v2(generator_version: str, knob_digest: str, seed: int) -> str:
    return hashlib.sha256(
        f"{generator_version}|{knob_digest}|{seed}".encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# shadow scenarios: a core Scenario whose value column is ONE resource.
# Used to reuse `ledger.core.welfare` (w_star, d_i, best_plan_assignment)
# verbatim per resource.
# ---------------------------------------------------------------------------

def shadow(sv: ScenarioV2, resource: str, opening: int | None = None) -> Scenario:
    b = sv.base(opening)
    return Scenario(
        scenario_id=f"{b.scenario_id}#{resource}", seed=b.seed,
        generator_version=b.generator_version, K=b.K, c=b.c,
        v=sv.column(resource), prereqs=b.prereqs, B=b.B, kappa=b.kappa,
        u=b.u, D=b.D, r=b.r, eps=b.eps, p=b.p, p_def=b.p_def,
        opening=b.opening, exposure=b.exposure, pay_cap=b.pay_cap,
        settle_window=b.settle_window, available_from=b.available_from,
        chat_enabled=b.chat_enabled)


# ---------------------------------------------------------------------------
# the resource scorer
# ---------------------------------------------------------------------------

def _contracts_performed(state, seat: int) -> int:
    """Locked contracts under which `seat` owed at least one job and executed
    every one of them, with no renege or default recorded against it."""
    n = 0
    for c in state.contracts.values():
        if c.status != "locked" or c.defaulted_by:
            continue
        owed = [j for j, s in c.assign.items() if s == seat]
        if owed and all(j in c.executed_jobs for j in owed):
            n += 1
    return n


def _contracts_broken(state, seat: int) -> int:
    """Reneges by `seat` plus settlement defaults by `seat`."""
    return (sum(1 for r in state.reneges if r["by"] == seat)
            + sum(1 for d in state.defaults if d["by"] == seat))


def score_resource(sv: ScenarioV2, state, seat: int, resource: str) -> int:
    """Seat `seat`'s score in `resource` at `state`.

    A finished job pays each seat its own yield, whoever executed it (the
    core rule, generalised per resource).  Money enters the cash score only.
    Conduct enters the standing score only.
    """
    total = sum(sv.yield_of(resource, seat, j) for j in state.done)
    if resource == TRANSFERABLE:
        total += state.accounts[seat - 1]
    if resource == "standing":
        total += sv.standing_kept * _contracts_performed(state, seat)
        total -= sv.standing_broken * _contracts_broken(state, seat)
    return total


def score_vector(sv: ScenarioV2, state) -> dict[str, tuple[int, int]]:
    """resource -> (seat 1 score, seat 2 score)."""
    return {r: (score_resource(sv, state, 1, r),
                score_resource(sv, state, 2, r)) for r in RESOURCES}
