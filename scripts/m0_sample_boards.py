"""Render five sample boards from admitted scenarios under scripted play.

For the §13 human read-through (G2): a person who has not seen the code
reads these five boards and describes each situation. If they cannot, the
renderer has failed regardless of the tests. Blinded to the code, not to
the game's plain-language rules (§2 of the environment doc).

The five boards come from five DISTINCT bank scenarios (distinct
scenario_ids, iterated — never rng-drawn with replacement, which once made
two boards byte-identical), and the script asserts all five rendered state
blocks are pairwise distinct before writing anything.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from ledger.scenarios.bank import load_bank  # noqa: E402
from ledger.game import Game  # noqa: E402
from ledger.policies.scripted import (  # noqa: E402
    GreedyOptimal, HoldUp, RandomLegal, AlwaysDefect, AlwaysCooperate,
)

BANK = "v1-m0"
# label, P1 factory, P2 factory.  random-legal (seeded) vs hold-up diverges
# from the cooperate-vs-hold-up arc from the very first tick.
PAIRS = [
    ("cooperate vs hold-up", AlwaysCooperate, HoldUp),
    ("hold-up vs cooperate", HoldUp, AlwaysCooperate),
    ("greedy vs defect", GreedyOptimal, AlwaysDefect),
    ("random-legal vs hold-up", lambda: RandomLegal(20260806), HoldUp),
    ("cooperate vs cooperate", AlwaysCooperate, AlwaysCooperate),
]

MARKER = "LEDGER · tick"


def _eventfulness(g) -> int:
    """Prefer boards that actually show something: live contracts (offers,
    locked, reneged-with-optional), executed jobs, and progress into the
    episode all count."""
    s = g.state
    live = sum(1 for c in s.contracts.values()
               if c.status == "locked"
               or c.is_offer_live(s.tick)
               or (c.status == "reneged" and c.optional_jobs_of(3 - c.reneged_by)))
    return live * 10 + len(s.done) * 5 + min(s.tick, 20)


def _state_block(board_text: str) -> str:
    idx = board_text.find(MARKER)
    return board_text[idx:] if idx >= 0 else board_text


def main() -> None:
    from ledger.game import IllegalAction
    from ledger.core.events import Action
    bank = load_bank(BANK)
    # five DISTINCT scenarios: first bank entry per scenario_id, in bank order
    distinct, seen = [], set()
    for scen in bank:
        if scen.scenario_id not in seen:
            seen.add(scen.scenario_id)
            distinct.append(scen)
    assert len(distinct) >= len(PAIRS), \
        f"bank {BANK} holds {len(distinct)} distinct scenarios, need {len(PAIRS)}"

    out = []
    for (label, P1, P2), scen in zip(PAIRS, distinct):
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

    # the whole point of distinct scenarios: no two boards may coincide
    blocks = [_state_block(board) for _, _, board in out]
    for i in range(len(blocks)):
        for j in range(i + 1, len(blocks)):
            assert blocks[i] != blocks[j], \
                f"boards {i + 1} and {j + 1} are byte-identical"

    doc = ["# M0 sample boards — for the §13 human read-through\n\n",
           "Five boards from five distinct admitted scenarios under scripted play. Read "
           "each and, using only the plain-language rules in ENVIRONMENT_DESIGN §2, write "
           "one or two sentences on what is going on: who is ahead, what is committed, "
           "who is exposed. If you cannot, the renderer needs work.\n\n",
           "_(The invariant system header — mandate, rules, action list — is identical on "
           "every board and byte-cached in every call; it is shown in full once in "
           "`M0_SAMPLE_BOARDS_full.txt` and omitted here so the state portion each board "
           "turns on is what you read.)_\n"]
    for i, ((label, tick, board), block) in enumerate(zip(out, blocks), 1):
        doc.append(f"\n## Board {i} — {label}, tick {tick}\n\n```\n{block}\n```\n")
    dest = Path(__file__).parent.parent / "docs/M0_SAMPLE_BOARDS.md"
    dest.write_text("".join(doc), encoding="utf-8")
    # The full first board including the invariant header, for reference.
    full = Path(__file__).parent.parent / "docs/M0_SAMPLE_BOARDS_full.txt"
    full.write_text(out[0][2], encoding="utf-8")
    print(f"wrote {dest} ({len(out)} boards, all pairwise distinct) and {full}")


if __name__ == "__main__":
    main()
