"""Build or extend a frozen scenario bank.

Extension keeps every scenario of the base bank byte-for-byte and continues
the deterministic seed scan where the base bank's scan stopped, so the new
bank is a strict superset and the whole construction replays from seeds.

    python scripts/build_bank.py --name v1-e0 --n 12 --extends v1-m0
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ledger.core.scenario import Scenario  # noqa: E402
from ledger.scenarios.admit import admit  # noqa: E402
from ledger.scenarios.bank import BANKS_DIR, freeze_bank  # noqa: E402
from ledger.scenarios.generate import GENERATOR_VERSION, generate  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--n", type=int, required=True, help="total scenarios in the new bank")
    ap.add_argument("--extends", default=None, help="base bank to keep verbatim")
    ap.add_argument("--max-seeds", type=int, default=100_000)
    args = ap.parse_args()

    scenarios, start_seed, base_tried = [], 0, 0
    if args.extends:
        payload = json.loads((BANKS_DIR / f"{args.extends}.json").read_text(encoding="utf-8"))
        if payload["generator_version"] != GENERATOR_VERSION:
            raise SystemExit(f"base bank is {payload['generator_version']}, "
                             f"current generator is {GENERATOR_VERSION}: refused")
        scenarios = [Scenario.from_dict(d) for d in payload["scenarios"]]
        base_tried = payload["stats"]["seeds_tried"]
        start_seed = max(d["seed"] for d in payload["scenarios"]) + 1
        # the base scan may have tried seeds past its last admit; resume after
        start_seed = max(start_seed, base_tried)

    tried = 0
    for seed in range(start_seed, start_seed + args.max_seeds):
        if len(scenarios) >= args.n:
            break
        tried += 1
        sc = generate(seed)
        if admit(sc).admitted:
            scenarios.append(sc)
    if len(scenarios) < args.n:
        raise SystemExit(f"only {len(scenarios)} of {args.n} admitted "
                         f"after {tried} new seeds")

    stats = {
        "generator_version": GENERATOR_VERSION,
        "extends": args.extends,
        "seeds_tried": base_tried + tried,
        "new_seed_range": [start_seed, start_seed + tried - 1] if tried else None,
        "admitted": len(scenarios),
        "admission_rate": round(len(scenarios) / (base_tried + tried), 6),
    }
    path = freeze_bank(args.name, scenarios, stats)
    print(f"froze {path.name}: {len(scenarios)} scenarios, "
          f"{sum(1 for s in scenarios if s.seed >= start_seed)} newly admitted")
    print("stats:", json.dumps(stats))


if __name__ == "__main__":
    main()
