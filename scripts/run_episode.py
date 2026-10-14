"""Run one LEDGER episode: models via OpenRouter, scripted policies, or both.

    # zero-cost smoke test, no key needed:
    python scripts/run_episode.py --bank v1-e0 --index 0 \
        --p1 scripted:always-cooperate --p2 scripted:tit-for-tat --out data/runs/smoke

    # the hidden-objectives variant studied in the paper ("Contracting"),
    # zero cost with scripted players:
    python scripts/run_episode.py --variant hidden-objectives --index 0 \
        --opening 1 --objectives cash,standing \
        --p1 scripted:greedy-optimal --p2 scripted:tit-for-tat --out data/runs/smoke

    # a real game (needs OPENROUTER_API_KEY, a models file, and tiktoken):
    python scripts/run_episode.py --variant hidden-objectives --index 0 \
        --opening 1 --objectives cash,materials \
        --models models.json --p1 model:sonnet --p2 model:gpt \
        --cap-usd 2 --out data/runs/pilot

Scripted policies: always-cooperate, always-defect, hold-up, greedy-optimal,
tit-for-tat, random-legal.  Scripted players do not read their assigned
objective; the objective scores are still computed and reported.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ledger.policies.scripted import POLICIES  # noqa: E402
from ledger.render.tokens import tokenizer_available  # noqa: E402
from ledger.runtime import (CostMeter, ModelAgent, OpenRouterClient,  # noqa: E402
                            ScriptedAgent, load_models, run_episode)
from ledger.scenarios.bank import load_bank  # noqa: E402
from ledger.variants import hidden_objectives as ho  # noqa: E402

VARIANTS = ("none", "hidden-objectives")


def make_agent(spec_str, models, client, mandate, sv=None, objective=None):
    kind, _, name = spec_str.partition(":")
    if kind == "scripted":
        if name not in POLICIES:
            raise SystemExit(f"unknown policy {name!r}; have {sorted(POLICIES)}")
        return ScriptedAgent(name, POLICIES[name]())
    if kind == "model":
        if models is None or name not in models:
            raise SystemExit(f"unknown model {name!r}; pass --models with it defined")
        if sv is not None:
            return ho.ModelAgentV2(models[name], client, sv, objective,
                                   mandate=mandate)
        return ModelAgent(models[name], client, mandate=mandate)
    raise SystemExit(f"agent must be scripted:<name> or model:<name>, got {spec_str!r}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=VARIANTS, default="none",
                    help="hidden-objectives = the paper's Contracting environment")
    ap.add_argument("--bank", default=None,
                    help=f"bank name (default v1-e0, or {ho.PAPER_BANK_ID} "
                         "with --variant hidden-objectives)")
    ap.add_argument("--index", type=int, default=0, help="template index in the bank")
    ap.add_argument("--opening", type=int, choices=(1, 2), default=1,
                    help="seat that moves first (hidden-objectives only; v1 "
                         "banks already list both seat orders as templates)")
    ap.add_argument("--objectives", default="cash,materials",
                    help="seat 1 and seat 2 assigned resources, comma-separated "
                         "(hidden-objectives only)")
    ap.add_argument("--p1", required=True)
    ap.add_argument("--p2", required=True)
    ap.add_argument("--models", default=None, help="model registry JSON")
    ap.add_argument("--mandate", default="principal")
    ap.add_argument("--message-cap", type=int, default=None,
                    help="CHAT token cap (engine default 40; the paper used 40)")
    ap.add_argument("--cap-usd", type=float, default=1.0)
    ap.add_argument("--out", default="data/runs/adhoc")
    args = ap.parse_args()

    models = load_models(args.models) if args.models else None
    needs_client = "model:" in args.p1 or "model:" in args.p2
    if needs_client and not tokenizer_available():
        raise SystemExit(
            "model seats need tiktoken with the o200k_base encoding: without "
            "it CHAT truncation falls back to a whitespace approximation and "
            "the game differs from the studied one. pip install -e '.[runtime]'")
    client = OpenRouterClient() if needs_client else None
    meter = CostMeter(cap_usd=args.cap_usd)

    if args.variant == "hidden-objectives":
        bank_id = args.bank or ho.PAPER_BANK_ID
        sv = ho.load_bank(bank_id)[args.index]
        objectives = tuple(args.objectives.split(","))
        if len(objectives) != 2 or any(o not in ho.RESOURCES for o in objectives):
            raise SystemExit(f"--objectives must be two of {ho.RESOURCES}")
        agents = {seat: make_agent(spec, models, client, args.mandate, sv,
                                   objectives[seat - 1])
                  for seat, spec in ((1, args.p1), (2, args.p2))}
        cap = 40 if args.message_cap is None else args.message_cap
        out = ho.play_episode(sv, args.opening, objectives, agents, args.out,
                              bank=bank_id, message_cap=cap,
                              mandate=args.mandate, meter=meter)
        if out is None:
            print("episode ABANDONED (see log); spent "
                  f"${meter.spent_usd:.2f} over {meter.calls} calls")
            raise SystemExit(2)
        r = out["engine_result"]
        print(f"objectives {objectives} | assigned payoff "
              f"{out['assigned_payoff']} | scored window (turns 1..{sv.scored_turns}) "
              f"{out['scored_window_payoff']} | final tick {r['final_tick']} | "
              f"agreement {r['agreement']} | reneges {len(r['reneges'])} | "
              f"${meter.spent_usd:.4f} over {meter.calls} calls")
        print("resource scores (seat 1, seat 2):",
              {k: tuple(v) for k, v in out["scores"].items()})
        print("log:", out["log"])
        return

    bank_id = args.bank or "v1-e0"
    scenario = load_bank(bank_id)[args.index]
    agents = {1: make_agent(args.p1, models, client, args.mandate),
              2: make_agent(args.p2, models, client, args.mandate)}
    r = run_episode(scenario, agents, args.out, bank=bank_id,
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
