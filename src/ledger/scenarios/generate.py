"""Seeded pure scenario generator (§10.2, §10.4).

All randomness in LEDGER lives here.  generate(seed) is a pure function of
(GENERATOR_VERSION, seed): the same pair always yields the same scenario,
with scenario_id = SHA256(generator_version || seed).
"""
from __future__ import annotations

import math
import random

from ..core.scenario import Scenario, scenario_id_for

GENERATOR_VERSION = "ledger-gen-v1"

# reference parameters (§10.2)
K = 8
B = 100
KAPPA = (3, 3)
U = (25, 25)
D = 24
R = 2
EPS = 1
P = 6
P_DEF = 8

# exposure-chain bands (M0 decision, recorded in docs/M0_DECISIONS.md):
# "cheap for the victim" = bottom band of the c1 range U{10..30}; "valued" =
# the high value band U{25..40}.
LOW_COST_MAX = 16
HIGH_VALUE_MIN = 25


def _round_half_up(x: float) -> int:
    return math.floor(x + 0.5)


def _draw_values(rng: random.Random) -> tuple[int, ...]:
    out = []
    for _ in range(K):
        roll = rng.random()
        if roll < 0.25:
            out.append(0)
        elif roll < 0.625:
            out.append(rng.randint(5, 15))
        else:
            out.append(rng.randint(25, 40))
    return tuple(out)


def _draw_chains(rng: random.Random) -> list[list[int]]:
    n_chains = rng.choice([1, 2])
    lengths = [rng.choice([2, 3]) for _ in range(n_chains)]
    nodes = rng.sample(range(1, K + 1), sum(lengths))
    chains, i = [], 0
    for ln in lengths:
        chains.append(nodes[i:i + ln])
        i += ln
    return chains


def _find_exposure(c, v, edges) -> tuple[int, int, int, int] | None:
    """First (victim, breaker, head, tail) satisfying §10.2's constraint:
    head cheap for the victim, tail valued by the victim, tail cheaper for the
    breaker than the victim, and priced above the victim's draw cap."""
    for head, tail in edges:
        for vic, brk in ((1, 2), (2, 1)):
            if (c[vic - 1][head - 1] <= LOW_COST_MAX
                    and v[vic - 1][tail - 1] >= HIGH_VALUE_MIN
                    and c[brk - 1][tail - 1] < c[vic - 1][tail - 1]
                    and c[vic - 1][tail - 1] > U[vic - 1]):
                return (vic, brk, head, tail)
    return None


def generate(seed: int, opening: int = 1) -> Scenario:
    """Draw a structurally valid scenario (exposure chain present).  Internal
    redraws advance the same seeded stream, so this is a pure function of the
    seed.  Admission (admit.py) is a separate, stricter filter."""
    rng = random.Random(f"{GENERATOR_VERSION}:{seed}")
    for _ in range(10_000):
        c1 = tuple(rng.randint(10, 30) for _ in range(K))
        c2 = []
        for t in range(K):
            chi = 2.0 ** rng.uniform(-1.0, 1.0)
            c2.append(min(60, max(10, _round_half_up(c1[t] * chi))))
        c2 = tuple(c2)
        v1 = _draw_values(rng)
        v2 = _draw_values(rng)
        chains = _draw_chains(rng)
        edges = [(ch[i], ch[i + 1]) for ch in chains for i in range(len(ch) - 1)]
        prereqs = [[] for _ in range(K)]
        for head, tail in edges:
            prereqs[tail - 1].append(head)
        exposure = _find_exposure((c1, c2), (v1, v2), edges)
        if exposure is None:
            continue
        return Scenario(
            scenario_id=scenario_id_for(GENERATOR_VERSION, seed),
            seed=seed,
            generator_version=GENERATOR_VERSION,
            K=K, c=(c1, c2), v=(v1, v2),
            prereqs=tuple(tuple(p) for p in prereqs),
            B=B, kappa=KAPPA, u=U, D=D, r=R, eps=EPS, p=P, p_def=P_DEF,
            opening=opening, exposure=exposure,
        )
    raise RuntimeError(f"seed {seed}: no structurally valid draw in 10000 attempts")
