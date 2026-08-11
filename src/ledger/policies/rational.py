"""Objective-conditioned rational policies (RETUNE_PLAN §6).

RationalPolicy(objective, tau, seed) evaluates every legal continuation
family through the envelope analyzer and samples an action class from
softmax(Q/tau), playing that class's representative action.  The policies
differ ONLY in the objective scoring the same completion set, which is
exactly the acceptance test's requirement: rational play, different values.

Objectives: own, joint, cautious (maximin over partner breach),
opportunistic (best case), loyal (own, but never breaching).

Temperature is in points: tau -> 0 is argmax play, larger tau mixes.
solve_tau() calibrates tau against a target mean entropy on a state set
(Gate C freezes an entropy-defined grid, never a fitted value).
"""
from __future__ import annotations

import math
import random

from ..analysis.objectives import envelope
from ..core.events import Action

OBJECTIVES = ("own", "joint", "cautious", "opportunistic", "loyal")


def class_distribution(env, objective: str, tau: float) -> dict[str, float]:
    table = env.q[objective]
    if not table:
        return {}
    best = max(table.values())
    weights = {c: math.exp((v - best) / max(tau, 1e-6))
               for c, v in table.items()}
    z = sum(weights.values())
    return {c: w / z for c, w in weights.items()}


def entropy_bits(dist: dict[str, float]) -> float:
    return -sum(p * math.log2(p) for p in dist.values() if p > 0)


class RationalPolicy:
    def __init__(self, objective: str, tau: float = 2.0, seed: int = 0):
        assert objective in OBJECTIVES, objective
        self.objective = objective
        self.tau = tau
        self.rng = random.Random(f"{objective}|{tau}|{seed}")

    def __call__(self, game, seat) -> Action:
        env = envelope(game.state)
        dist = class_distribution(env, self.objective, self.tau)
        if not dist:
            return Action("WAIT")
        classes = sorted(dist)
        cls = self.rng.choices(classes, weights=[dist[c] for c in classes])[0]
        return env.rep[self.objective][cls]


def solve_tau(envs, objective: str, target_bits: float,
              lo: float = 0.05, hi: float = 60.0, iters: int = 28) -> float:
    """Binary-search tau so the mean class-entropy over `envs` hits the
    target.  Entropy grows monotonically in tau."""
    def mean_h(tau: float) -> float:
        hs = [entropy_bits(class_distribution(e, objective, tau))
              for e in envs]
        hs = [h for h in hs if h == h]
        return sum(hs) / len(hs) if hs else 0.0

    if mean_h(hi) < target_bits:
        return hi
    for _ in range(iters):
        mid = math.sqrt(lo * hi)
        if mean_h(mid) < target_bits:
            lo = mid
        else:
            hi = mid
    return math.sqrt(lo * hi)
