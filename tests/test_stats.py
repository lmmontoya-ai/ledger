"""Statistical validation on synthetic agents: the §3.4 floor/excess
estimator recovers known divergences, the §3.6 distinctness gate has a low
false-positive rate under identical policies, and smoothing is over the
legal alphabet only."""
import random

import pytest

from ledger.analysis.stats import (calibrate_delta, distinctness_pass,
                                   entropy_bits, excess_score, jsd_bits,
                                   sample_counts, smoothed)

LEGAL = ["ACCEPT", "COUNTER", "REJECT", "WAIT"]
N = 16   # draws per half, as in the experiment plan


def test_smoothing_over_legal_alphabet_only():
    with pytest.raises(ValueError, match="not in the legal alphabet"):
        smoothed({"RENEGE": 3}, LEGAL)
    p = smoothed({"ACCEPT": 10}, LEGAL)
    assert set(p) == set(LEGAL)
    assert abs(sum(p.values()) - 1.0) < 1e-12
    assert p["WAIT"] > 0    # prior mass on unobserved legal outcomes


def test_jsd_basics():
    p = {"a": 0.5, "b": 0.5}
    assert jsd_bits(p, p) == pytest.approx(0.0)
    q = {"a": 1.0, "b": 0.0}
    assert 0 < jsd_bits(p, q) <= 1.0
    assert jsd_bits({"a": 1.0}, {"b": 1.0}) == pytest.approx(1.0)
    assert entropy_bits(p) == pytest.approx(1.0)


def test_excess_estimator_recovers_known_divergences():
    rng = random.Random(42)
    target = {"ACCEPT": 0.6, "COUNTER": 0.2, "REJECT": 0.1, "WAIT": 0.1}
    other = {"ACCEPT": 0.1, "COUNTER": 0.1, "REJECT": 0.2, "WAIT": 0.6}
    true_jsd = jsd_bits(target, other)
    reps = 300
    x_same, x_diff = 0.0, 0.0
    for _ in range(reps):
        t1 = sample_counts(rng, target, N)
        t2 = sample_counts(rng, target, N)
        pred_same = sample_counts(rng, target, N)
        pred_diff = sample_counts(rng, other, N)
        x_same += excess_score(pred_same, t1, t2, LEGAL)
        x_diff += excess_score(pred_diff, t1, t2, LEGAL)
    x_same /= reps
    x_diff /= reps
    # a predictor matching the target is indistinguishable from another
    # sample of the target: X ~ 0
    assert abs(x_same) < 0.05
    # a mismatched predictor recovers the true divergence within tolerance
    assert x_diff > 0.10
    assert abs(x_diff - true_jsd) < 0.12


def test_distinctness_gate_false_positive_rate_under_identical_policies():
    rng = random.Random(7)
    policy = {"ACCEPT": 0.5, "COUNTER": 0.25, "REJECT": 0.15, "WAIT": 0.10}
    delta = calibrate_delta(rng, policy, LEGAL, N, reps=300)
    trials, fp = 400, 0
    for _ in range(trials):
        a1 = sample_counts(rng, policy, N)
        a2 = sample_counts(rng, policy, N)
        b1 = sample_counts(rng, policy, N)
        b2 = sample_counts(rng, policy, N)
        if distinctness_pass(a1, a2, b1, b2, LEGAL, delta):
            fp += 1
    assert fp / trials < 0.15


def test_distinctness_gate_separates_genuinely_different_policies():
    rng = random.Random(11)
    a = {"ACCEPT": 0.7, "COUNTER": 0.1, "REJECT": 0.1, "WAIT": 0.1}
    b = {"ACCEPT": 0.1, "COUNTER": 0.1, "REJECT": 0.1, "WAIT": 0.7}
    delta = calibrate_delta(rng, a, LEGAL, N, reps=300)
    trials, hits = 200, 0
    for _ in range(trials):
        if distinctness_pass(sample_counts(rng, a, N), sample_counts(rng, a, N),
                             sample_counts(rng, b, N), sample_counts(rng, b, N),
                             LEGAL, delta):
            hits += 1
    assert hits / trials > 0.80


def test_gate_passes_matched_scripted_agents_and_rejects_on_margin():
    """§18.1-style margin behavior: a bare inequality would admit noise; the
    calibrated margin keeps one lucky split from admitting a pair."""
    rng = random.Random(23)
    policy = {"ACCEPT": 1.0, "COUNTER": 0.0, "REJECT": 0.0, "WAIT": 0.0}
    # near-deterministic identical policies: floors approach zero; without a
    # margin a stray draw would pass the gate
    delta = calibrate_delta(rng, policy, LEGAL, N, reps=200)
    noisy = {"ACCEPT": 0.94, "COUNTER": 0.02, "REJECT": 0.02, "WAIT": 0.02}
    fp = sum(
        distinctness_pass(sample_counts(rng, policy, N), sample_counts(rng, policy, N),
                          sample_counts(rng, noisy, N), sample_counts(rng, noisy, N),
                          LEGAL, delta)
        for _ in range(200))
    assert fp / 200 < 0.5   # mostly held out despite tiny floors
