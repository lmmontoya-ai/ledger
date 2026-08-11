"""Quick envelope sanity: one bank scenario, opening state + a mid state."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ledger.analysis.divergence import (aggregate, audit_states,
                                        states_from_policies)
from ledger.analysis.objectives import envelope
from ledger.core import fold as fold_mod
from ledger.policies.scripted import POLICIES
from ledger.scenarios.bank import load_bank

bank = load_bank("v1-e0")
sc = list(bank)[0]
print("scenario", sc.scenario_id[:12], "K", sc.K, "D", sc.D)

t0 = time.time()
st = fold_mod.initial_state(sc)
env = envelope(st)
print(f"opening state: {time.time()-t0:.2f}s, {env.n_completions} completions")
for obj in ("own", "joint", "cautious", "opportunistic"):
    best = max(env.q[obj].values()) if env.q[obj] else None
    print(f"  {obj:14} best={best} astar={sorted(env.astar[obj])}")
print("  frontier:", env.frontier[:6], "solo:", env.solo)

t0 = time.time()
states = states_from_policies(sc, POLICIES["always-cooperate"](),
                              POLICIES["always-cooperate"]())
rows = audit_states(states, sc.scenario_id[:12], sc.D)
print(f"\ncoop self-play: {len(states)} states audited in {time.time()-t0:.1f}s")
import json
print(json.dumps(aggregate(rows), indent=1))
