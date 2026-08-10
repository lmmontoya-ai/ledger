"""Run one LEDGER episode: models via OpenRouter, scripted policies, or both.

    # zero-cost smoke test, no key needed:
    python scripts/run_episode.py --bank v1-e0 --index 0 \
        --p1 scripted:cooperator --p2 scripted:tit_for_tat --out data/runs/smoke

    # a real game (needs OPENROUTER_API_KEY and a models file):
    python scripts/run_episode.py --bank v1-e0 --index 0 \
        --models models.json --p1 model:sonnet --p2 model:gpt \
        --mandate principal --cap-usd 2 --out data/runs/pilot
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ledger.policies.scripted import POLICIES  # noqa: E402
from ledger.runtime import (CostMeter, ModelAgent, OpenRouterClient,  # noqa: E402
                            ScriptedAgent, load_models, run_episode)
from ledger.scenarios.bank import load_bank  # noqa: E402


def make_agent(spec_str, models, client, mandate):
    kind, _, name = spec_str.partition(":")
    if kind == "scripted":
        if name not in POLICIES:
            raise SystemExit(f"unknown policy {name!r}; have {sorted(POLICIES)}")
        return ScriptedAgent(name, POLICIES[name]())
    if kind == "model":
        if models is None or name not in models:
            raise SystemExit(f"unknown model {name!r}; pass --models with it defined")
        return ModelAgent(models[name], client, mandate=mandate)
    raise SystemExit(f"agent must be scripted:<name> or model:<name>, got {spec_str!r}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", default="v1-e0")
    ap.add_argument("--index", type=int, default=0, help="template index in the bank")
    ap.add_argument("--p1", required=True)
    ap.add_argument("--p2", required=True)
    ap.add_argument("--models", default=None, help="model registry JSON")
    ap.add_argument("--mandate", default="principal")
    ap.add_argument("--message-cap", type=int, default=None,
                    help="override the 40-token CHAT cap (exploration only)")
    ap.add_argument("--cap-usd", type=float, default=1.0)
    ap.add_argument("--out", default="data/runs/adhoc")
    args = ap.parse_args()

    bank = load_bank(args.bank)
    scenario = bank[args.index]
    models = load_models(args.models) if args.models else None
    needs_client = "model:" in args.p1 or "model:" in args.p2
    client = OpenRouterClient() if needs_client else None
    meter = CostMeter(cap_usd=args.cap_usd)
    agents = {1: make_agent(args.p1, models, client, args.mandate),
              2: make_agent(args.p2, models, client, args.mandate)}

    r = run_episode(scenario, agents, args.out, bank=args.bank,
                    mandate=args.mandate, message_cap=args.message_cap,
                    meter=meter)
    if r is None:
        print("episode ABANDONED (see log); spent "
              f"${meter.spent_usd:.2f} over {meter.calls} calls")
        raise SystemExit(2)
    print(f"scores {tuple(r['pi'])} | W* {r['w_star']} | "
          f"efficiency {r['efficiency']} | agreement {r['agreement']} | "
          f"reneges {len(r['reneges'])} | ${meter.spent_usd:.4f} "
          f"over {meter.calls} calls")


if __name__ == "__main__":
    main()
