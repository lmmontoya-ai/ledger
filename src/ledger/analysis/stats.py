"""Statistical instrument pieces (EXPERIMENT_PLAN §3.4, §3.6): JSD in bits
with Dirichlet smoothing over the decision's legal alphabet only, the
floor-corrected excess score X, and the distinctness gate.

This is analysis tooling, not engine: floats are fine here.
"""
from __future__ import annotations

import math
from collections import Counter


def smoothed(counts: dict[str, int], legal: list[str]) -> dict[str, float]:
    """Dirichlet-smoothed empirical distribution, alpha = 1/|legal|, over the
    legal alphabet ONLY.  Outcomes outside the legal set are an error, never
    silently absorbed."""
    if not legal:
        raise ValueError("legal alphabet is empty")
    for o in counts:
        if o not in legal:
            raise ValueError(f"outcome {o!r} is not in the legal alphabet")
    alpha = 1.0 / len(legal)
    n = sum(counts.values())
    denom = n + alpha * len(legal)
    return {o: (counts.get(o, 0) + alpha) / denom for o in legal}


def _kl_bits(p: dict, q: dict) -> float:
    out = 0.0
    for o, po in p.items():
        if po > 0:
            out += po * math.log2(po / q[o])
    return out


def jsd_bits(p: dict, q: dict) -> float:
    keys = set(p) | set(q)
    m = {o: 0.5 * (p.get(o, 0.0) + q.get(o, 0.0)) for o in keys}
    return 0.5 * _kl_bits(p, m) + 0.5 * _kl_bits(q, m)


def entropy_bits(p: dict) -> float:
    return -sum(x * math.log2(x) for x in p.values() if x > 0)


def excess_score(pred: dict[str, int], t1: dict[str, int], t2: dict[str, int],
                 legal: list[str]) -> float:
    """X = 1/2 [JSD(P,T1) + JSD(P,T2)] - JSD(T1,T2): zero means the predictor
    is indistinguishable from another sample of the target itself."""
    P = smoothed(pred, legal)
    T1 = smoothed(t1, legal)
    T2 = smoothed(t2, legal)
    return 0.5 * (jsd_bits(P, T1) + jsd_bits(P, T2)) - jsd_bits(T1, T2)


def distinctness_pass(a1: dict, a2: dict, b1: dict, b2: dict,
                      legal: list[str], delta: float) -> bool:
    """§3.6 margin gate: both cross-pairings must exceed both floors by delta."""
    A1, A2 = smoothed(a1, legal), smoothed(a2, legal)
    B1, B2 = smoothed(b1, legal), smoothed(b2, legal)
    cross = min(jsd_bits(A1, B2), jsd_bits(A2, B1))
    floor = max(jsd_bits(A1, A2), jsd_bits(B1, B2))
    return cross > floor + delta


def sample_counts(rng, dist: dict[str, float], n: int) -> dict[str, int]:
    outcomes = list(dist)
    weights = [dist[o] for o in outcomes]
    return dict(Counter(rng.choices(outcomes, weights=weights, k=n)))


def calibrate_delta(rng, dist: dict[str, float], legal: list[str],
                    n: int, reps: int = 200, percentile: float = 0.90) -> float:
    """Provisional margin: the 90th percentile of same-model cross-half JSD."""
    floors = []
    for _ in range(reps):
        h1 = smoothed(sample_counts(rng, dist, n), legal)
        h2 = smoothed(sample_counts(rng, dist, n), legal)
        floors.append(jsd_bits(h1, h2))
    floors.sort()
    idx = min(len(floors) - 1, int(percentile * len(floors)))
    return floors[idx]
