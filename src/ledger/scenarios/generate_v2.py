"""Development generator for the retune search (RETUNE_PLAN §7, L0 + L2a).

Same structural family as ledger-gen-v1 (chains, exposure pair, integer
costs/values) with the search knobs exposed and two additions:

  - pay_cap: the transfer ceiling (L2a).  0 disables scheduled pays and
    TRANSFER, which breaks the transferable-utility realignment (fixture
    F3-2b) and makes own-vs-joint divergence structurally possible.
  - cross-seat value anticorrelation: with probability `anti`, a job that is
    valuable to one seat is worthless to the other, which widens the payoff
    frontier that admit_v2 condition 5 requires.

Pure and seeded: generate_v2(seed, knobs) is a function of
(GENERATOR_VERSION, knobs, seed) only.  Everything else (admission,
divergence) is downstream filtering.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass, field

from ..core.scenario import Scenario

GENERATOR_VERSION = "ledger-gen-v2-dev"


@dataclass(frozen=True)
class Knobs:
    K: int = 8
    B: int = 100
    kappa: tuple[int, int] = (3, 3)
    u: tuple[int, int] = (25, 25)
    D: int = 24
    r: int = 2
    eps: int = 1
    p: int = 6
    p_def: int = 8
    pay_cap: int | None = 12
    settle_window: int | None = 8    # pays fall in the final third (D=24)
    # value model
    p_zero: float = 0.25
    mid: tuple[int, int] = (5, 15)
    hi: tuple[int, int] = (25, 40)
    p_hi: float = 0.375
    anti: float = 0.6          # P(partner value zeroed | own value high)
    # cost model
    cost_lo: int = 10
    cost_hi: int = 30
    chi_spread: float = 1.0    # log2 range of the cross-seat cost ratio
    # chains
    n_chains: tuple[int, ...] = (1, 2)
    chain_len: tuple[int, ...] = (2, 3)
    # exposure bands
    low_cost_max: int = 16
    high_value_min: int = 25

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True)
                              .encode()).hexdigest()[:12]


def _values(rng: random.Random, k: Knobs) -> tuple[tuple[int, ...], tuple[int, ...]]:
    v1, v2 = [], []
    for _ in range(k.K):
        pair = []
        for _seat in (1, 2):
            roll = rng.random()
            if roll < k.p_zero:
                pair.append(0)
            elif roll < 1 - k.p_hi:
                pair.append(rng.randint(*k.mid))
            else:
                pair.append(rng.randint(*k.hi))
        # anticorrelation: a high-value job for one seat is often worthless
        # to the other, so plan choice moves real value between seats
        if pair[0] >= k.hi[0] and rng.random() < k.anti:
            pair[1] = 0
        elif pair[1] >= k.hi[0] and rng.random() < k.anti:
            pair[0] = 0
        v1.append(pair[0])
        v2.append(pair[1])
    return tuple(v1), tuple(v2)


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


def _round_half_up(x: float) -> int:
    return math.floor(x + 0.5)


def _exposure(c, v, edges, k: Knobs):
    """v2 temptation pattern (deferred pay): a job the BREAKER values highly
    that the VICTIM can execute cheaply.  The victim works early against a
    scheduled payment the breaker can later renege on.  (head == tail: the
    chain machinery is orthogonal to this trap.)"""
    for job in range(1, k.K + 1):
        for vic, brk in ((1, 2), (2, 1)):
            if (c[vic - 1][job - 1] <= k.low_cost_max
                    and v[brk - 1][job - 1] >= k.high_value_min):
                return (vic, brk, job, job)
    return None


def scenario_id_v2(knobs: Knobs, seed: int) -> str:
    return hashlib.sha256(
        f"{GENERATOR_VERSION}|{knobs.digest()}|{seed}".encode()).hexdigest()


def generate_v2(seed: int, knobs: Knobs = Knobs(),
                opening: int = 1) -> Scenario | None:
    """One structurally valid draw, or None if the seeded stream cannot
    produce an exposure chain within its redraw budget."""
    k = knobs
    rng = random.Random(f"{GENERATOR_VERSION}:{k.digest()}:{seed}")
    for _ in range(10_000):
        c1 = tuple(rng.randint(k.cost_lo, k.cost_hi) for _ in range(k.K))
        c2 = []
        for t in range(k.K):
            chi = 2.0 ** rng.uniform(-k.chi_spread, k.chi_spread)
            c2.append(min(60, max(k.cost_lo,
                                  _round_half_up(c1[t] * chi))))
        c2 = tuple(c2)
        v1, v2 = _values(rng, k)
        chains = _chains(rng, k)
        edges = [(ch[i], ch[i + 1]) for ch in chains
                 for i in range(len(ch) - 1)]
        prereqs = [[] for _ in range(k.K)]
        for head, tail in edges:
            prereqs[tail - 1].append(head)
        exposure = _exposure((c1, c2), (v1, v2), edges, k)
        if exposure is None:
            continue
        return Scenario(
            scenario_id=scenario_id_v2(k, seed),
            seed=seed,
            generator_version=GENERATOR_VERSION,
            K=k.K, c=(c1, c2), v=(v1, v2),
            prereqs=tuple(tuple(p) for p in prereqs),
            B=k.B, kappa=k.kappa, u=k.u, D=k.D, r=k.r, eps=k.eps,
            p=k.p, p_def=k.p_def, opening=opening, exposure=exposure,
            pay_cap=k.pay_cap, settle_window=k.settle_window,
        )
    return None
