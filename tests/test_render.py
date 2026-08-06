"""Renderer: golden bytes + digest, §7.6 token bounds, message discipline,
manifest enforcement, replay."""
import hashlib
from pathlib import Path

import pytest

from ledger.core.events import Action
from ledger.game import Game
from ledger.render import tokens as tok
from ledger.render.board import RenderFieldError, _guard, render_board
from ledger.render.history import render_history
from ledger.render.render import render_prompt, system_block
from tests.conftest import simple_scenario, worked_game

GOLDEN = Path(__file__).parent / "golden"

needs_tokenizer = pytest.mark.skipif(
    not tok.tokenizer_available(), reason="tiktoken o200k_base not available")


def _worked_prompt():
    g = worked_game(8)   # state at tick 9, P1 to move — the §7.2 board
    return render_prompt(g.state, tuple(g.events), 1)


def test_golden_bytes_and_digest():
    data, digest = _worked_prompt()
    want = (GOLDEN / "worked_tick9_p1.txt").read_bytes().replace(b"\r\n", b"\n")
    want_digest = (GOLDEN / "worked_tick9_p1.sha256").read_text().strip()
    assert data == want
    assert digest == want_digest == hashlib.sha256(want).hexdigest()


def test_render_is_pure():
    a, da = _worked_prompt()
    b, db = _worked_prompt()
    assert a == b and da == db


def test_board_matches_7_2_layout():
    g = worked_game(8)
    board = render_board(g.state, 1)
    assert "LEDGER · tick 9/24 · your move · you are P1" in board
    assert "POT 100: spent 27 · your draws 0/25 · their draws 0/25 · left 73" in board
    assert "everything left at tick 24 is destroyed" in board
    assert "SLOTS    you 2/3 left · them 3/3 left" in board
    assert "ACCOUNT  you 0 · them 0" in board
    assert "JOB  YOUR-COST  THEIR-COST  YOUR-VALUE  NEEDS  STATUS" in board
    assert "DONE by you, tick 7" in board
    assert "<- locked to them" in board
    assert "C1 LOCKED (tick 4)   job 3 -> you, funded 12  ·  job 6 -> them, funded 15" in board
    assert "C2 OFFERED by them, expires tick 11" in board
    assert "they pay you 4 at tick 14" in board
    # no timestamps, no model identities, and the partner's values are absent
    assert "THEIR-VALUE" not in board
    for banned in ("claude", "gpt", "opus", "gemini", "model"):
        assert banned not in board.lower()


def test_seat_language_flips_with_viewer():
    g = worked_game(8)
    b2 = render_board(g.state, 2)
    assert "you are P2" in b2 and "their move" in b2
    assert "job 6 -> you" in b2       # locked to P2 = "you" in P2's view
    assert "you pay them 4 at tick 14" in b2


def test_history_grammar():
    g = worked_game(8)
    hist = render_history(g.state, tuple(g.events), 1)
    lines = hist.splitlines()
    assert lines[0] == "HISTORY"
    assert len(lines) == 9            # 8 ticks played
    assert 'QUERY' in lines[1] and lines[1].startswith("  t1 you")
    assert "PROPOSE C1: job3->you f12, job6->them f15" in lines[3]
    assert "[C1 locked; cancel window t5-t6]" in lines[4]
    assert "[cancel window closed]" in lines[6]
    assert "EXECUTE job3" in lines[7] and "[done]" in lines[7]
    assert "pay you 4 @t14" in lines[8]


def test_manifest_guard_raises_outside_manifest():
    F = _guard("board")
    assert F("pot_left", 73) == 73
    with pytest.raises(RenderFieldError):
        F("job_value_them", 20)
    with pytest.raises(RenderFieldError):
        F("model_name", "x")


def test_message_truncation_recorded_and_rendered():
    g = Game(simple_scenario())
    long_text = "word " * 200
    g.play(Action("INFORM", {"text": long_text}))
    ev = g.events[0]
    assert ev.truncated
    assert tok.token_count(ev.action.args["text"]) <= tok.MESSAGE_TOKEN_CAP
    hist = render_history(g.state, tuple(g.events), 1)
    assert "truncated" in hist


def test_replay_reproduces_stored_digest():
    g = worked_game(9)
    for tick in range(1, 10):
        replayed = g.replay(tick)
        st = g.state_before(tick)
        again, digest = render_prompt(st, tuple(g.events[: tick - 1]), st.mover)
        assert replayed == again


def test_system_block_is_byte_identical():
    assert system_block() == system_block()
    assert b"You represent a principal" in system_block()


# ---------------------------------------------------------------------------
# §7.6 token budget, measured with the real tokenizer
# ---------------------------------------------------------------------------

def _line_tokens(state, events, viewer=1):
    hist = render_history(state, events, viewer).splitlines()[1:]
    return list(zip(events, hist, [tok.token_count(l) for l in hist]))


@needs_tokenizer
@pytest.mark.token_bounds
def test_board_token_bound():
    g = worked_game(8)
    board = render_board(g.state, 1)
    assert tok.token_count(board) <= 340


@needs_tokenizer
@pytest.mark.token_bounds
def test_history_line_token_bounds():
    g = worked_game(9)
    g.play(Action("RENEGE", {"contract_id": 1}))              # t10
    g.play(Action("DRAW", {"amount": 25, "job": 7}))          # t11 P1
    g.play(Action("TRANSFER", {"amount": 3, "to": 1}))        # t12 P2
    g.play(Action("EXECUTE", {"job": 7}))                     # t13 P1
    g.play(Action("END", {}))                                 # t14 P2
    for ev, line, n in _line_tokens(g.state, tuple(g.events)):
        name = ev.action.name
        has_note = "[" in line
        if name in ("WAIT", "END") and not has_note:
            assert n <= 8, line
        elif name in ("DRAW", "TRANSFER") and not has_note:
            assert n <= 16, line
        elif name == "EXECUTE" and "; " not in line:
            assert n <= 16, line   # [done] is part of the executive class
        elif name in ("ACCEPT", "CANCEL", "RENEGE", "EXECUTE", "DRAW",
                      "TRANSFER", "WAIT", "END"):
            # any line carrying an extra consequence bracket is lifecycle-class
            assert n <= 28, line
        elif name in ("PROPOSE", "COUNTER"):
            ev_c = ev.action.args["contract"]
            bound = 14 + 8 * len(ev_c["assign"]) + 10 * len(ev_c["pay"])
            assert n <= bound, line
        elif name in ("QUERY", "INFORM", "REFUSE"):
            assert n <= 48, line


@needs_tokenizer
@pytest.mark.token_bounds
def test_message_line_at_cap_within_bound():
    g = Game(simple_scenario())
    text, truncated = tok.truncate_message("negotiate " * 100)
    assert truncated and tok.token_count(text) == 40
    g.play(Action("QUERY", {"text": text}))
    line = render_history(g.state, tuple(g.events), 1).splitlines()[1]
    assert tok.token_count(line) <= 48


@needs_tokenizer
@pytest.mark.token_bounds
def test_system_block_token_budget():
    n = tok.token_count(system_block().decode("utf-8"))
    assert n <= 1200
