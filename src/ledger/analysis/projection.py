"""Minimal E8-style projection machinery (EXPERIMENT_PLAN §6.8): landing
zones over a per-decision bank of candidate policies plus their uniform
centroid, and the permutation null that shuffles predictor labels within
decision.

The centroid zone is essential: regression toward a generic mode is the
default failure of a bad prediction, and without it any predictor whose
habits sit near the population mode is miscounted as projecting.
"""
from __future__ import annotations

import random

from .stats import jsd_bits, smoothed

CENTROID = "centroid"


def centroid_of(bank: dict[str, dict[str, float]]) -> dict[str, float]:
    """Uniform mixture of all bank entries at a decision."""
    keys = set()
    for d in bank.values():
        keys |= set(d)
    n = len(bank)
    return {o: sum(d.get(o, 0.0) for d in bank.values()) / n for o in keys}


def landing_zone(miss: dict[str, int], bank: dict[str, dict[str, int]],
                 legal: list[str]) -> str:
    """Argmin JSD from the miss distribution to every bank entry plus the
    population centroid.  Ties resolve to the centroid first (conservative:
    never over-counts a named landing), then lexicographically."""
    p = smoothed(miss, legal)
    dists = {name: jsd_bits(p, smoothed(counts, legal))
             for name, counts in bank.items()}
    smoothed_bank = {name: smoothed(counts, legal) for name, counts in bank.items()}
    dists[CENTROID] = jsd_bits(p, centroid_of(smoothed_bank))
    best = min(dists.values())
    winners = sorted(name for name, d in dists.items() if d == best)
    return CENTROID if CENTROID in winners else winners[0]


def self_landing_rate(landings: dict, predictors: list[str],
                      relabel: dict | None = None) -> float:
    """landings: {decision: {predictor: zone}}.  Rate at which a predictor's
    miss lands on its own bank entry.  `relabel` optionally permutes
    predictor labels per decision: {decision: {predictor: permuted}}."""
    hits = total = 0
    for d, per_pred in landings.items():
        for p in predictors:
            zone = per_pred[relabel[d][p]] if relabel else per_pred[p]
            hits += zone == p
            total += 1
    return hits / total if total else 0.0


def permutation_null(landings: dict, predictors: list[str], rng: random.Random,
                     n_perm: int = 200) -> tuple[float, list[float]]:
    """Observed self-landing rate and its permutation null: predictor labels
    shuffled within each decision, conditioning on the real geometry of
    policies there (§6.8)."""
    observed = self_landing_rate(landings, predictors)
    null = []
    for _ in range(n_perm):
        relabel = {}
        for d in landings:
            perm = predictors[:]
            rng.shuffle(perm)
            relabel[d] = dict(zip(predictors, perm))
        null.append(self_landing_rate(landings, predictors, relabel))
    return observed, null


def exceeds_null(observed: float, null: list[float],
                 percentile: float = 0.95) -> bool:
    s = sorted(null)
    idx = min(len(s) - 1, int(percentile * len(s)))
    return observed > s[idx]
