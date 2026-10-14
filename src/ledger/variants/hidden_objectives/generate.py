"""Hidden-objectives scenario generation, admission, and frozen banks.

Pure and seeded.  `generate(seed, knobs)` is a function of
(GENERATOR_VERSION, knobs, seed) only: no wall clock, no global RNG.

The value model
---------------
Each job is given a DOMINANT resource: it pays well in that resource and
little in the others.  Capacity (`kappa`) is smaller than the job count, so
the seats cannot do everything and must choose, and which jobs are worth
choosing depends on which resource you are maximising.  Cross-seat
anticorrelation (`anti`) means a job that is rich for one seat is often
worthless to the other, so plan choice moves value between seats rather than
just scaling it.

Admission condition 3 is the load-bearing one: playing another resource's
optimal plan must cost you at least `wrong_plan_frac` of your own optimum,
in every ordered pair of resources.  If optimising the wrong resource were
free, no belief about the partner could change the best action.

The studied bank
----------------
`PAPER_KNOBS`, `PAPER_PROFILE` and `PAPER_BANK_SIZE` are the third admission
iteration ("iteration 3") of the research harness's config
`config/ledger_v2_g1.json`.  `paper_bank()` rebuilds that 12-scenario bank
deterministically, and `banks/hidden-objectives-iter3.json` is the same bank
frozen to JSON.  Every Contracting episode in the paper was played on one of
these scenarios.

Ported from `ledger-experiments/engine_v2/generate_v2res.py` in
self-other-prediction-smoke-tests; output is identical.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass
from pathlib import Path

from ...core.welfare import best_plan_assignment, d_i, w_eq, w_star
from ...scenarios.bank import BANKS_DIR
from .scenario import RESOURCES, ScenarioV2, scenario_id_v2, shadow

GENERATOR_VERSION = "ledger-gen-v2res-1"

# default admission bands (changing one selects a different bank)
G_BAND = (0.10, 0.50)          # integrative gap, per resource
FALLBACK_MAX = 0.60            # no seat may nearly go it alone, per resource
PAY_TEMPTATION_MIN = 4         # pay_cap - p: what dodging a full pay nets

# The cost of optimising the WRONG resource, as a fraction of your own
# optimum.  Changing this constant selects a different subset of the same
# seeded scenario stream; it does not change any scenario.
WRONG_PLAN_FRAC = 0.25


@dataclass(frozen=True)
class AdmissionProfile:
    """One admission rule, declaratively.

    The last three fields default to None, meaning NOT APPLIED, so earlier
    iterations' banks stay reproducible from the same seeded stream.
    """
    wrong_plan_frac: float = WRONG_PLAN_FRAC
    g_band: tuple[float, float] = G_BAND
    fallback_max: float = FALLBACK_MAX
    pay_temptation_min: int = PAY_TEMPTATION_MIN
    # Thin cooperation surplus, per resource: W*_r - (d1_r + d2_r) must fall
    # in this band as a fraction of W*_r.  A thin surplus makes acceptance
    # marginal, so WHICH resource the partner holds decides whether a deal
    # clears its threshold at all.
    surplus_band: tuple[float, float] | None = None
    # The three resource-optimal plans may share at most this many jobs.
    # Combined with a tight pot, satisfying two resources at once becomes
    # unaffordable.
    max_shared_plan_jobs: int | None = None
    # The payment cap must be small relative to the cash W*, so cash cannot
    # buy acceptance on its own and a cash partner has to be paid in
    # cash-yielding jobs.
    pay_cap_max_frac_of_cash_w_star: float | None = None

    @staticmethod
    def from_dict(d: dict | None) -> "AdmissionProfile":
        if not d:
            return AdmissionProfile()
        f = dict(d)
        for k in ("g_band", "surplus_band"):
            if f.get(k) is not None:
                f[k] = tuple(f[k])
        return AdmissionProfile(**f)


@dataclass(frozen=True)
class Knobs:
    K: int = 6
    B: int = 60
    kappa: tuple[int, int] = (3, 3)
    u: tuple[int, int] = (25, 25)
    D: int = 48                    # 48 turns ...
    scored_turns: int = 24         # ... scored on the first 24
    r: int = 2
    eps: int = 1
    p: int = 6
    p_def: int = 8
    pay_cap: int = 14
    settle_window: int = 16        # pays land in turns 33..48, past the window
    n_arrivals: int = 2            # jobs that open mid-game ...
    arrive_turn: int = 28          # ... after the scored window closes
    standing_kept: int = 6
    standing_broken: int = 14
    # value model
    p_zero: float = 0.15           # P(a seat's dominant yield is zero)
    dom_hi: tuple[int, int] = (22, 36)
    dom_mid: tuple[int, int] = (10, 20)
    p_dom_hi: float = 0.5
    off_max: int = 3               # non-dominant resources pay 0..off_max
    anti: float = 0.55             # P(partner's dominant yield zeroed)
    # cost model (core generator family)
    cost_lo: int = 10
    cost_hi: int = 30
    chi_spread: float = 1.0
    # chains
    n_chains: tuple[int, ...] = (1,)
    chain_len: tuple[int, ...] = (2,)
    # exposure bands
    low_cost_max: int = 18
    high_value_min: int = 22

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True)
                              .encode()).hexdigest()[:12]


# The studied configuration: iteration 3 of the research harness's
# config/ledger_v2_g1.json ("knobs" with "knobs_override", and "admission").
PAPER_KNOBS = Knobs(B=45, pay_cap=6, p=2, p_def=3)
PAPER_PROFILE = AdmissionProfile(
    wrong_plan_frac=0.25,
    g_band=(0.1, 0.95),
    fallback_max=0.55,
    pay_temptation_min=4,
    surplus_band=(0.25, 0.9),
    max_shared_plan_jobs=1,
    pay_cap_max_frac_of_cash_w_star=0.15,
)
PAPER_BANK_SIZE = 12
PAPER_BANK_ID = "hidden-objectives-iter3"


def _round_half_up(x: float) -> int:
    return math.floor(x + 0.5)


def _dominance(rng: random.Random, k: Knobs) -> list[str]:
    """Which resource each job is rich in.  Balanced by construction: every
    resource dominates the same number of jobs (up to the remainder), so no
    resource's column is pure noise."""
    base = [RESOURCES[i % len(RESOURCES)] for i in range(k.K)]
    rng.shuffle(base)
    return base


def _yields(rng: random.Random, k: Knobs):
    """Per resource, a (seat1 column, seat2 column) pair."""
    cols = {r: ([], []) for r in RESOURCES}
    dominants = _dominance(rng, k)
    for _j in range(k.K):
        dom = dominants[_j]
        pair = []
        for _seat in (1, 2):
            roll = rng.random()
            if roll < k.p_zero:
                pair.append(0)
            elif roll < k.p_zero + (1 - k.p_zero) * (1 - k.p_dom_hi):
                pair.append(rng.randint(*k.dom_mid))
            else:
                pair.append(rng.randint(*k.dom_hi))
        # anticorrelation: a job rich for one seat is often worthless to the
        # other, so which plan runs decides who gets paid, not just how much
        if pair[0] >= k.dom_hi[0] and rng.random() < k.anti:
            pair[1] = 0
        elif pair[1] >= k.dom_hi[0] and rng.random() < k.anti:
            pair[0] = 0
        for r in RESOURCES:
            if r == dom:
                cols[r][0].append(pair[0])
                cols[r][1].append(pair[1])
            else:
                cols[r][0].append(rng.randint(0, k.off_max))
                cols[r][1].append(rng.randint(0, k.off_max))
    return (tuple((tuple(cols[r][0]), tuple(cols[r][1])) for r in RESOURCES),
            tuple(dominants))


def _chains(rng: random.Random, k: Knobs) -> list[list[int]]:
    n = rng.choice(list(k.n_chains))
    lengths = [rng.choice(list(k.chain_len)) for _ in range(n)]
    total = min(sum(lengths), k.K)
    nodes = rng.sample(range(1, k.K + 1), total)
    chains, i = [], 0
    for ln in lengths:
        if i >= total:
            break
        chains.append(nodes[i:i + ln])
        i += ln
    return [c for c in chains if len(c) >= 2]


def _exposure(c, ref, k: Knobs):
    """The deferred-pay trap, on the reference column: a job the BREAKER
    values highly that the VICTIM can execute cheaply."""
    for job in range(1, k.K + 1):
        for vic, brk in ((1, 2), (2, 1)):
            if (c[vic - 1][job - 1] <= k.low_cost_max
                    and ref[brk - 1][job - 1] >= k.high_value_min):
                return (vic, brk, job, job)
    return None


def generate(seed: int, knobs: Knobs = Knobs(),
             opening: int = 1) -> ScenarioV2 | None:
    """One structurally valid draw, or None if the seeded stream cannot make
    one within its redraw budget.  Admission is a separate, later filter."""
    k = knobs
    rng = random.Random(f"{GENERATOR_VERSION}:{k.digest()}:{seed}")
    for _ in range(4000):
        c1 = tuple(rng.randint(k.cost_lo, k.cost_hi) for _ in range(k.K))
        c2 = tuple(min(60, max(k.cost_lo,
                               _round_half_up(c1[t] * 2.0 ** rng.uniform(
                                   -k.chi_spread, k.chi_spread))))
                   for t in range(k.K))
        yields, _dominants = _yields(rng, k)
        ref = tuple(tuple(sum(yields[i][s][j] for i in range(len(RESOURCES)))
                          for j in range(k.K)) for s in (0, 1))
        chains = _chains(rng, k)
        prereqs = [[] for _ in range(k.K)]
        for ch in chains:
            for i in range(len(ch) - 1):
                prereqs[ch[i + 1] - 1].append(ch[i])
        exposure = _exposure((c1, c2), ref, k)
        if exposure is None:
            continue
        available = ()
        if k.n_arrivals > 0:
            is_prereq = {p for pre in prereqs for p in pre}
            leaves = [j for j in range(1, k.K + 1)
                      if j not in is_prereq and j != exposure[2]]
            leaves.sort(key=lambda j: -(ref[0][j - 1] + ref[1][j - 1]))
            late = set(leaves[:k.n_arrivals])
            if len(late) < k.n_arrivals:
                continue
            available = tuple(k.arrive_turn if j in late else 1
                              for j in range(1, k.K + 1))
        return ScenarioV2(
            scenario_id=scenario_id_v2(GENERATOR_VERSION, k.digest(), seed),
            seed=seed, generator_version=GENERATOR_VERSION, K=k.K,
            c=(c1, c2), prereqs=tuple(tuple(p) for p in prereqs),
            B=k.B, kappa=k.kappa, u=k.u, D=k.D, r=k.r, eps=k.eps, p=k.p,
            p_def=k.p_def, opening=opening, exposure=exposure,
            pay_cap=k.pay_cap, settle_window=k.settle_window,
            available_from=available, chat_enabled=True, yields=yields,
            scored_turns=k.scored_turns, standing_kept=k.standing_kept,
            standing_broken=k.standing_broken)
    return None


# ---------------------------------------------------------------------------
# admission
# ---------------------------------------------------------------------------

def plan_value(sv: ScenarioV2, resource: str, assign: dict[int, int],
               seat: int | None = None) -> int:
    """Joint (or one seat's) yield in `resource` if exactly `assign` runs."""
    seats = (1, 2) if seat is None else (seat,)
    return sum(sv.yield_of(resource, s, j) for j in assign for s in seats)


def admit(sv: ScenarioV2, wrong_plan_frac: float | None = None,
          profile: AdmissionProfile | None = None) -> dict:
    """Returns {'admitted': bool, 'reasons': [...], 'details': {...}}.

    `profile` selects an admission rule; `wrong_plan_frac` overrides just
    that one field.
    """
    prof = profile or AdmissionProfile()
    wpf = prof.wrong_plan_frac if wrong_plan_frac is None else wrong_plan_frac
    reasons: list[str] = []
    details: dict = {"per_resource": {}, "wrong_plan_loss": {},
                     "wrong_plan_frac": wpf,
                     "surplus_band": prof.surplus_band,
                     "max_shared_plan_jobs": prof.max_shared_plan_jobs}

    # 0. the payment ceiling must be pay_cap, not W*, so the dynamics do not
    #    depend on any value column (see scenario.py)
    ws_ref = w_star(sv.base())
    details["w_star_reference"] = ws_ref
    if not (1 <= sv.pay_cap <= ws_ref):
        reasons.append(f"pay_cap {sv.pay_cap} does not bind under "
                       f"W*(reference)={ws_ref}")
    if sv.pay_cap - sv.p < prof.pay_temptation_min:
        reasons.append(f"dodging a full pay nets {sv.pay_cap - sv.p}, under "
                       f"the temptation floor {prof.pay_temptation_min}")

    plans: dict[str, dict[int, int]] = {}
    for r in RESOURCES:
        sh = shadow(sv, r)
        ws = w_star(sh)
        weq = w_eq(sh)
        d1, d2 = d_i(sh, 1), d_i(sh, 2)
        plans[r] = best_plan_assignment(sh)
        details["per_resource"][r] = {"w_star": ws, "w_eq": weq,
                                      "d": [d1, d2],
                                      "best_plan": dict(sorted(plans[r].items()))}
        if ws <= 0:
            reasons.append(f"{r}: W* is not positive")
            continue
        lo, hi = prof.g_band
        if not (lo * ws <= ws - weq <= hi * ws):
            reasons.append(f"{r}: integrative gap outside band "
                           f"(W*={ws}, W_eq={weq})")
        if not (d1 > 0 and d2 > 0):
            reasons.append(f"{r}: a seat's go-it-alone value is zero")
        if max(d1, d2) > prof.fallback_max * ws:
            reasons.append(f"{r}: one seat can nearly go it alone "
                           f"(d={d1},{d2} vs W*={ws})")
        # a thin cooperation surplus makes acceptance marginal
        surplus = ws - (d1 + d2)
        details["per_resource"][r]["surplus"] = surplus
        details["per_resource"][r]["surplus_frac"] = (
            round(surplus / ws, 3) if ws else None)
        if prof.surplus_band is not None:
            slo, shi = prof.surplus_band
            if not (slo * ws <= surplus <= shi * ws):
                reasons.append(
                    f"{r}: cooperation surplus {surplus} outside the thin "
                    f"band [{slo:.0%},{shi:.0%}] of W*={ws}")

    # 3. objective distinguishability: optimising the wrong resource must hurt
    for r in RESOURCES:
        ws = details["per_resource"][r]["w_star"]
        own = plan_value(sv, r, plans[r])
        for r2 in RESOURCES:
            if r2 == r:
                continue
            loss = own - plan_value(sv, r, plans[r2])
            details["wrong_plan_loss"][f"{r}|plan_{r2}"] = loss
            if ws > 0 and loss < wpf * ws:
                reasons.append(
                    f"{r}: playing the {r2}-optimal plan costs only {loss} "
                    f"({wpf:.0%} of W*={ws} required)")

    # 4. the resources' preferred plans must be near-disjoint, so that with a
    #    tight pot you cannot fund two resources' sets at once
    shared = {}
    for i, r in enumerate(RESOURCES):
        for r2 in RESOURCES[i + 1:]:
            n = len(set(plans[r]) & set(plans[r2]))
            shared[f"{r}|{r2}"] = n
    details["shared_plan_jobs"] = shared
    if prof.max_shared_plan_jobs is not None:
        worst = max(shared.values()) if shared else 0
        if worst > prof.max_shared_plan_jobs:
            reasons.append(
                f"resource-optimal plans share {worst} jobs, over the "
                f"disjointness limit {prof.max_shared_plan_jobs}")

    # 5. cash must not be able to buy acceptance on its own
    if prof.pay_cap_max_frac_of_cash_w_star is not None:
        cash_ws = details["per_resource"]["cash"]["w_star"]
        cap_frac = sv.pay_cap / cash_ws if cash_ws else 1.0
        details["pay_cap_frac_of_cash_w_star"] = round(cap_frac, 3)
        if cap_frac > prof.pay_cap_max_frac_of_cash_w_star:
            reasons.append(
                f"pay_cap {sv.pay_cap} is {cap_frac:.0%} of the cash W* "
                f"({cash_ws}); over {prof.pay_cap_max_frac_of_cash_w_star:.0%} "
                "a cash transfer can buy acceptance on its own")

    return {"admitted": not reasons, "reasons": reasons, "details": details}


def build_bank(n: int, knobs: Knobs = Knobs(), start_seed: int = 1,
               max_seed: int = 8000,
               wrong_plan_frac: float | None = None,
               profile: AdmissionProfile | None = None) -> list[ScenarioV2]:
    """The first `n` admitted scenarios in seed order.  Deterministic.

    Running out of seeds is an error rather than a short bank, because a
    short bank would silently change every per-bank denominator.
    """
    out: list[ScenarioV2] = []
    seed = start_seed
    while len(out) < n and seed <= max_seed:
        sv = generate(seed, knobs)
        if sv is not None and admit(sv, wrong_plan_frac, profile)["admitted"]:
            out.append(sv)
        seed += 1
    if len(out) < n:
        raise RuntimeError(
            f"only {len(out)}/{n} scenarios admitted at "
            f"wrong_plan_frac={wrong_plan_frac if wrong_plan_frac is not None else WRONG_PLAN_FRAC} "
            f"within seeds {start_seed}..{max_seed}; raise max_seed or relax "
            "the band rather than running a short bank")
    return out


def paper_bank() -> list[ScenarioV2]:
    """The 12-scenario bank the paper's Contracting episodes were played on,
    rebuilt from seeds.  Equal to `load_bank(PAPER_BANK_ID)`."""
    return build_bank(PAPER_BANK_SIZE, PAPER_KNOBS, profile=PAPER_PROFILE)


# ---------------------------------------------------------------------------
# frozen banks
# ---------------------------------------------------------------------------

def freeze_bank(name: str, scenarios: list[ScenarioV2], knobs: Knobs,
                profile: AdmissionProfile, banks_dir: Path = BANKS_DIR) -> Path:
    """Write a bank to `banks/<name>.json` with the knobs and admission rule
    that produced it, so the file is self-describing."""
    banks_dir.mkdir(exist_ok=True)
    path = banks_dir / f"{name}.json"
    payload = {
        "bank_id": name,
        "generator_version": GENERATOR_VERSION,
        "knobs": asdict(knobs),
        "knobs_digest": knobs.digest(),
        "admission": asdict(profile),
        "seeds": [sv.seed for sv in scenarios],
        "scenarios": [sv.to_dict() for sv in scenarios],
    }
    path.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")
    return path


def load_bank(name: str = PAPER_BANK_ID,
              banks_dir: Path = BANKS_DIR) -> list[ScenarioV2]:
    """Load a frozen hidden-objectives bank.  Every scenario is stored with
    opening seat 1; pass `opening` to `ScenarioV2.base` (or use
    `with_opening`) to play the other seat order."""
    path = banks_dir / f"{name}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload["generator_version"] != GENERATOR_VERSION:
        raise ValueError(
            f"bank {name} was generated by {payload['generator_version']}, "
            f"current is {GENERATOR_VERSION}: refused, not coerced")
    return [ScenarioV2.from_dict(d) for d in payload["scenarios"]]
