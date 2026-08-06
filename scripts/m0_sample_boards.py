"""Render five sample boards from admitted scenarios under scripted play.

For the §13 human read-through (G2): a person who has not seen the code
reads these five boards and describes each situation. If they cannot, the
renderer has failed regardless of the tests. Blinded to the code, not to
the game's plain-language rules (§2 of the environment doc).
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from ledger.scenarios.bank import load_bank  # noqa: E402
from ledger.game import Game  # noqa: E402
from ledger.policies.scripted import (  # noqa: E402
    GreedyOptimal, HoldUp, TitForTat, AlwaysDefect, AlwaysCooperate,
)

BANK = "v1-m0"
PAIRS = [
    ("cooperate vs hold-up", AlwaysCooperate, HoldUp),
    ("hold-up vs cooperate", HoldUp, AlwaysCooperate),
    ("greedy vs defect", GreedyOptimal, AlwaysDefect),
    ("tit-for-tat vs hold-up", TitForTat, HoldUp),
    ("cooperate vs cooperate", AlwaysCooperate, AlwaysCooperate),
]


def _eventfulness(g) -> int:
    """Prefer boards that actually show something: live contracts, executed
    jobs, and progress into the episode all count."""
    s = g.state
    live = len(getattr(s, "contracts", {}) or {})
    done = sum(1 for j in s.jobs if getattr(s, "completed", set()) and j in s.completed) \
        if hasattr(s, "completed") else 0
    return live * 10 + done * 5 + min(s.tick, 20)


def main() -> None:
    from ledger.game import IllegalAction
    from ledger.core.events import Action
    bank = load_bank(BANK)
    rng = random.Random(20260806)
    out = []
    for label, P1, P2 in PAIRS:
        scen = bank[rng.randrange(len(bank))]
        g = Game(scen)
        policies = {1: P1(), 2: P2()}
        best = None  # (eventfulness, board_text, tick)
        while not g.over:
            seat = g.turn
            board = g.render(seat).decode("utf-8")
            score = _eventfulness(g)
            if best is None or score >= best[0]:
                best = (score, board, g.state.tick)
            try:
                g.play(policies[seat](g, seat))
            except IllegalAction:
                g.play(Action("WAIT"))
        out.append((label, best[2], best[1]))

    doc = ["# M0 sample boards — for the §13 human read-through\n\n",
           "Five boards from admitted scenarios under scripted play. Read each and, using "
           "only the plain-language rules in ENVIRONMENT_DESIGN §2, write one or two "
           "sentences on what is going on: who is ahead, what is committed, who is exposed. "
           "If you cannot, the renderer needs work.\n\n",
           "_(The invariant system header — mandate, rules, action list — is identical on "
           "every board and byte-cached in every call; it is shown in full once in "
           "`M0_SAMPLE_BOARDS_full.txt` and omitted here so the state portion each board "
           "turns on is what you read.)_\n"]
    for i, (label, tick, board) in enumerate(out, 1):
        # Show only the state portion (from the board banner down); the
        # invariant system header is the same on every board and printed once.
        marker = "LEDGER · tick"
        idx = board.find(marker)
        state = board[idx:] if idx >= 0 else board
        doc.append(f"\n## Board {i} — {label}, tick {tick}\n\n```\n{state}\n```\n")
    dest = Path(__file__).parent.parent / "docs/M0_SAMPLE_BOARDS.md"
    dest.write_text("".join(doc), encoding="utf-8")
    # The full first board including the invariant header, for reference.
    full = Path(__file__).parent.parent / "docs/M0_SAMPLE_BOARDS_full.txt"
    full.write_text(out[0][2], encoding="utf-8")
    print(f"wrote {dest} ({len(out)} boards) and {full}")


if __name__ == "__main__":
    main()
