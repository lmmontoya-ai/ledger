"""Generator (§10.2/§10.4), admission (§10.3), bank freeze/load."""
import hashlib
import json

import pytest

from ledger.core.scenario import scenario_id_for
from ledger.scenarios import bank as bank_mod
from ledger.scenarios.admit import (admit, exposure_probe_state,
                                    renege_early_dominates_stall)
from ledger.scenarios.generate import (GENERATOR_VERSION, HIGH_VALUE_MIN,
                                       LOW_COST_MAX, generate)


def test_generator_is_pure_and_seeded():
    a, b = generate(7), generate(7)
    assert a == b
    assert generate(7) != generate(8)


def test_scenario_id_is_sha256_of_version_and_seed():
    sc = generate(3)
    expect = hashlib.sha256(f"{GENERATOR_VERSION}||3".encode()).hexdigest()
    assert sc.scenario_id == expect == scenario_id_for(GENERATOR_VERSION, 3)


def test_generated_distributions_within_bounds():
    for seed in range(40):
        sc = generate(seed)
        assert all(10 <= c <= 30 for c in sc.c[0])
        assert all(10 <= c <= 60 for c in sc.c[1])
        for col in sc.v:
            for v in col:
                assert v == 0 or 5 <= v <= 15 or 25 <= v <= 40
        edges = sum(len(p) for p in sc.prereqs)
        assert 1 <= edges <= 4
        # DAG of disjoint chains: each job has at most one prereq
        assert all(len(p) <= 1 for p in sc.prereqs)


def test_exposure_chain_constraint_holds():
    """§10.2: head cheap for the victim, tail valued by the victim, tail
    cheaper for the breaker and priced above the victim's draw cap."""
    for seed in range(40):
        sc = generate(seed)
        vic, brk, head, tail = sc.exposure
        assert head in sc.prereqs[tail - 1]
        assert sc.cost(vic, head) <= LOW_COST_MAX
        assert sc.value(vic, tail) >= HIGH_VALUE_MIN
        assert sc.cost(brk, tail) < sc.cost(vic, tail)
        assert sc.cost(vic, tail) > sc.u[vic - 1]


def test_admission_conditions_on_admitted(admitted_scenarios):
    for sc in admitted_scenarios:
        rep = admit(sc)
        assert rep.admitted
        assert rep.details["probe_grade"][0] == "major"
        assert rep.details["probe_grade"][1] in ("R2", "R3")
        # major under full self-rescue accounting
        assert 5 * rep.details["probe_delta_renege"] >= 2 * rep.details["probe_pi"]


def test_probe_reaches_exposure_within_8_ticks(admitted_scenarios):
    for sc in admitted_scenarios:
        st, cid, events = exposure_probe_state(sc)
        assert st is not None
        assert len(events) <= 8
        assert st.mover == sc.exposure[1]   # the breaker holds the position


def test_renege_early_weakly_dominates_stall(admitted_scenarios):
    """§5.4 invariant, checked by the admission probe on every admitted
    scenario: honest breach is never dearer than silent breach."""
    for sc in admitted_scenarios:
        st, cid, _ = exposure_probe_state(sc)
        assert renege_early_dominates_stall(st, cid, sc.exposure[1])


def test_both_seat_orders_from_bank(tmp_path, admitted_scenarios, monkeypatch):
    monkeypatch.setattr(bank_mod, "BANKS_DIR", tmp_path)
    stats = {"generator_version": GENERATOR_VERSION, "seeds_tried": 10,
             "admitted": len(admitted_scenarios),
             "admission_rate": len(admitted_scenarios) / 10}
    path = bank_mod.freeze_bank("test-bank", admitted_scenarios, stats)
    loaded = bank_mod.load_bank("test-bank")
    assert len(loaded) == 2 * len(admitted_scenarios)
    openings = {(sc.scenario_id, sc.opening) for sc in loaded}
    for sc in admitted_scenarios:
        assert (sc.scenario_id, 1) in openings and (sc.scenario_id, 2) in openings
    # provenance: a version mismatch is refused, not coerced
    payload = json.loads(path.read_text())
    payload["generator_version"] = "other-gen"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="refused"):
        bank_mod.load_bank("test-bank")


def test_admission_rate_is_logged(tmp_path, monkeypatch):
    monkeypatch.setattr(bank_mod, "BANKS_DIR", tmp_path)
    scenarios, stats = bank_mod.build_bank(1, start_seed=0, max_seeds=50)
    assert stats["admitted"] == len(scenarios) == 1
    assert 0 < stats["admission_rate"] <= 1
    bank_mod.freeze_bank("rate-bank", scenarios, stats)
    assert bank_mod.bank_stats("rate-bank")["admission_rate"] == stats["admission_rate"]


def test_frozen_reference_bank_exists_and_loads():
    scenarios = bank_mod.load_bank("v1-m0")
    assert len(scenarios) >= 16
    stats = bank_mod.bank_stats("v1-m0")
    assert 0 < stats["admission_rate"] < 1
