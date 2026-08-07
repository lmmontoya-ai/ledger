"""M0 validation measurements: admission rate over >= 200 seeds, token counts
per render class, and branching entropy under scripted mixed play.

Run:  .venv/Scripts/python scripts/m0_report.py
"""
from __future__ import annotations

import itertools
import math
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from conftest import worked_game
from ledger.core.events import Action
from ledger.policies.scripted import POLICIES, run_episode
from ledger.render import tokens as tok
from ledger.render.board import render_board
from ledger.render.history import render_history
from ledger.render.render import system_block
from ledger.scenarios.admit import admit
from ledger.scenarios.generate import generate


def admission(n_seeds: int = 250):
    t0 = time.time()
    admitted = 0
    reject_reasons = Counter()
    victims = Counter()
    for seed in range(n_seeds):
        rep = admit(generate(seed))
        if rep.admitted:
            admitted += 1
            victims[generate(seed).exposure[0]] += 1
        else:
            reject_reasons[rep.reasons[0].split("(")[0].strip()] += 1
    dt = time.time() - t0
    print(f"ADMISSION: {admitted}/{n_seeds} = {admitted/n_seeds:.3f}  ({dt:.0f}s)")
    print(f"  victim seat among admitted: {dict(victims)}")
    for reason, n in reject_reasons.most_common():
        print(f"  reject: {n:4d}  {reason}")


def token_report():
    """Measured under both public encodings: o200k_base carries the §7.6
    bounds; cl100k_base is asserted against ceil(1.3 x o200k bound) as the
    approximation allowance for vendor-private tokenizers."""
    encodings = [e for e in ("o200k_base", "cl100k_base")
                 if tok.encoding_available(e)]
    print(f"\nTOKENS (encodings: {', '.join(encodings) or 'whitespace-approx'})")

    def counts(text):
        return " / ".join(f"{tok.token_count(text, e)}" for e in encodings)

    print(f"  system block: {counts(system_block().decode('utf-8'))}")
    g = worked_game(8)
    board = render_board(g.state, 1)
    print(f"  board (K=8, 2 live contracts): {counts(board)}  (o200k bound 340)")
    g = worked_game(9)
    g.play(Action("RENEGE", {"contract_id": 1}))
    g.play(Action("DRAW", {"amount": 25, "job": 7}))
    g.play(Action("TRANSFER", {"amount": 3, "to": 1}))
    g.play(Action("EXECUTE", {"job": 7}))
    g.play(Action("END", {}))
    hist = render_history(g.state, tuple(g.events), 1).splitlines()[1:]
    for ev, line in zip(g.events, hist):
        print(f"  {counts(line):>9}  {line}")
    full = g.render(1)
    print(f"  full prompt at tick 15: {counts(full.decode('utf-8'))}")


def branching_entropy(n_scenarios: int = 4):
    """Omega_1 label entropy of the pooled action distribution under scripted
    mixed play (every policy pair, both random-legal seeds varied)."""
    labels = Counter()
    names = sorted(POLICIES)
    scenarios = []
    seed = 0
    while len(scenarios) < n_scenarios:
        sc = generate(seed)
        if admit(sc).admitted:
            scenarios.append(sc)
        seed += 1
    for sc in scenarios:
        for i, (a, b) in enumerate(itertools.product(names, repeat=2)):
            def mk(name, s):
                cls = POLICIES[name]
                return cls(s) if name == "random-legal" else cls()
            game = run_episode(sc, mk(a, i), mk(b, i + 100))
            for ev in game.events:
                labels[ev.action.name] += 1
    total = sum(labels.values())
    ent = -sum((n / total) * math.log2(n / total) for n in labels.values())
    print(f"\nBRANCHING under scripted mixed play "
          f"({n_scenarios} scenarios x {len(names)**2} pairs, {total} ticks)")
    print(f"  pooled Omega_1 label entropy: {ent:.2f} bits")
    for name, n in labels.most_common():
        print(f"  {name:<9} {n:5d}  {n/total:.3f}")


if __name__ == "__main__":
    admission(250)
    token_report()
    branching_entropy()
