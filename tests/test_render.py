"""Renderer: golden bytes + digest, §7.6 token bounds, message discipline,
manifest enforcement, replay."""
import hashlib
import math
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
    assert "LEDGER · turn 9 of 24 · your move · you are P1" in board
    assert "POT shared budget: 73 of 100 left · destroyed after turn 24" in board
    assert "DRAWS taken alone: you 0 of 25 · them 0 of 25" in board
    assert "SLOTS    you 2/3 left · them 3/3 left" in board
    assert "ACCOUNT  you 0 · them 0" in board
    assert "JOB  YOUR-COST  THEIR-COST  YOUR-VALUE  NEEDS FIRST  STATUS" in board
    assert "DONE by you, turn 7" in board
    assert "<- promised to them (deal 1)" in board
    assert ("deal 1 BINDING (since turn 4)   job 3 -> you, 12 from pot"
            "  ·  job 6 -> them, 15 from pot") in board
    assert "deal 2 OFFERED by them, expires turn 11" in board
    assert "they pay you 4 at turn 14" in board
    # the v1 notation the G2 read-through failed on is gone
    for old in ("tick", "C1", "C2", "LOCKED", "CONTRACTS", "funded", "NEEDS "):
        if old == "NEEDS ":
            assert "NEEDS FIRST" in board
            continue
        assert old not in board, old
    # no timestamps, no model identities, and the partner's values are absent
    assert "THEIR-VALUE" not in board
    for banned in ("claude", "gpt", "opus", "gemini", "model"):
        assert banned not in board.lower()


def test_seat_language_flips_with_viewer():
    g = worked_game(8)
    b2 = render_board(g.state, 2)
    assert "you are P2" in b2 and "their move" in b2
    assert "job 6 -> you" in b2       # promised to P2 = "you" in P2's view
    assert "you pay them 4 at turn 14" in b2


def test_history_grammar():
    g = worked_game(8)
    hist = render_history(g.state, tuple(g.events), 1)
    lines = hist.splitlines()
    assert lines[0] == "HISTORY"
    assert len(lines) == 9            # 8 turns played
    assert 'QUERY' in lines[1] and lines[1].startswith("turn 1  you")
    assert ("PROPOSE deal 1: job 3 -> you, 12 from pot"
            " · job 6 -> them, 15 from pot") in lines[3]
    assert "[deal 1 binds; cancel window turns 5-6]" in lines[4]
    assert "[cancel window closed]" in lines[6]
    assert "EXECUTE job 3" in lines[7] and "[done]" in lines[7]
    assert "pay you 4 at turn 14" in lines[8]
    assert "tick" not in hist


def test_history_break_and_draw_grammar():
    g = worked_game(9)
    g.play(Action("RENEGE", {"contract_id": 1}))          # t10 by them
    g.play(Action("DRAW", {"amount": 25, "job": 7}))      # t11 by you
    hist = render_history(g.state, tuple(g.events), 1)
    assert "RENEGE  deal 1    [deal 1 broken; 11 back to pot; they pay you 3]" in hist
    assert "DRAW    25 from pot for job 7" in hist
    assert "[deal 2 expired]" in hist                      # offer lapsed at t11

    # a broken deal that leaves the victim optional funded jobs shows on the
    # board with the plain BROKEN/optional wording
    g2 = Game(simple_scenario())
    g2.play(Action("PROPOSE", {"contract": {
        "assign": {"1": 1, "2": 2}, "fund": {"1": 10, "2": 10},
        "pay": [], "expires": 6}}))
    g2.play(Action("ACCEPT", {"offer_id": 1}))
    g2.play(Action("WAIT")); g2.play(Action("WAIT")); g2.play(Action("WAIT"))
    g2.play(Action("RENEGE", {"contract_id": 1}))          # t6, by P2
    board = render_board(g2.state, 1)
    assert "deal 1 BROKEN by them (turn 6)" in board
    assert "job 1 -> you optional, 10 from pot" in board
    assert "<- optional for you (deal 1)" in board


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
# §7.6 token budget, measured with real tokenizers
#
# The §7.6 bounds are set on the reference o200k_base tokenizer, re-measured
# for template v2 (turn/deal/"N from pot" wording is longer than v1; the cost
# is accepted and priced).  Vendor-private tokenizers (Anthropic, xAI) are
# approximated by the two public encodings that ship with tiktoken —
# o200k_base and cl100k_base — and the cl100k bounds carry a
# ceil(1.3 x o200k-bound) headroom as the approximation allowance for
# tokenizers that segment tables and numbers less efficiently.
#
# v2 measured (o200k/cl100k): board 337/337, simple 7/7, EXECUTE 15/15,
# ACCEPT 26/26, RENEGE 32/33, 2-job proposal 33/33, +1 pay 42/42,
# maximal message line 49/49, system 616/619.
# ---------------------------------------------------------------------------

ENCODINGS = [("o200k_base", 1.0), ("cl100k_base", 1.3)]

BOARD_BOUND = 360
SIMPLE_BOUND = 8
EXECUTIVE_BOUND = 20
LIFECYCLE_BOUND = 36
CONTRACT_BASE, CONTRACT_PER_JOB, CONTRACT_PER_PAY = 12, 12, 10
MESSAGE_BOUND = 52
SYSTEM_BOUND = 1200


def _bound(base: int, scale: float) -> int:
    return math.ceil(base * scale)


def _require(enc_name: str):
    if not tok.encoding_available(enc_name):
        pytest.skip(f"tiktoken {enc_name} not available")


def _line_tokens(enc_name, state, events, viewer=1):
    hist = render_history(state, events, viewer).splitlines()[1:]
    return list(zip(events, hist,
                    [tok.token_count(l, enc_name) for l in hist]))


@pytest.mark.token_bounds
@pytest.mark.parametrize("enc_name,scale", ENCODINGS)
def test_board_token_bound(enc_name, scale):
    _require(enc_name)
    g = worked_game(8)
    board = render_board(g.state, 1)
    assert tok.token_count(board, enc_name) <= _bound(BOARD_BOUND, scale)


@pytest.mark.token_bounds
@pytest.mark.parametrize("enc_name,scale", ENCODINGS)
def test_history_line_token_bounds(enc_name, scale):
    _require(enc_name)
    g = worked_game(9)
    g.play(Action("RENEGE", {"contract_id": 1}))              # t10
    g.play(Action("DRAW", {"amount": 25, "job": 7}))          # t11 P1
    g.play(Action("TRANSFER", {"amount": 3, "to": 1}))        # t12 P2
    g.play(Action("EXECUTE", {"job": 7}))                     # t13 P1
    g.play(Action("END", {}))                                 # t14 P2
    for ev, line, n in _line_tokens(enc_name, g.state, tuple(g.events)):
        name = ev.action.name
        has_note = "[" in line
        if name in ("WAIT", "END") and not has_note:
            assert n <= _bound(SIMPLE_BOUND, scale), line
        elif name in ("DRAW", "TRANSFER") and not has_note:
            assert n <= _bound(EXECUTIVE_BOUND, scale), line
        elif name == "EXECUTE" and "; " not in line:
            assert n <= _bound(EXECUTIVE_BOUND, scale), line  # [done] is executive-class
        elif name in ("ACCEPT", "CANCEL", "RENEGE", "EXECUTE", "DRAW",
                      "TRANSFER", "WAIT", "END"):
            # any line carrying an extra consequence bracket is lifecycle-class
            assert n <= _bound(LIFECYCLE_BOUND, scale), line
        elif name in ("PROPOSE", "COUNTER"):
            ev_c = ev.action.args["contract"]
            base = (CONTRACT_BASE + CONTRACT_PER_JOB * len(ev_c["assign"])
                    + CONTRACT_PER_PAY * len(ev_c["pay"]))
            assert n <= _bound(base, scale), line
        elif name in ("QUERY", "INFORM", "REFUSE"):
            assert n <= _bound(MESSAGE_BOUND, scale), line


@pytest.mark.token_bounds
@pytest.mark.parametrize("enc_name,scale", ENCODINGS)
def test_message_line_at_cap_within_bound(enc_name, scale):
    _require(enc_name)
    g = Game(simple_scenario())
    # the engine cap is enforced with the reference o200k tokenizer;
    # other encodings measure the same rendered line against scaled bounds
    text, truncated = tok.truncate_message("negotiate " * 100)
    assert truncated and tok.token_count(text) == 40
    g.play(Action("QUERY", {"text": text}))
    line = render_history(g.state, tuple(g.events), 1).splitlines()[1]
    assert tok.token_count(line, enc_name) <= _bound(MESSAGE_BOUND, scale)


@pytest.mark.token_bounds
@pytest.mark.parametrize("enc_name,scale", ENCODINGS)
def test_system_block_token_budget(enc_name, scale):
    _require(enc_name)
    n = tok.token_count(system_block().decode("utf-8"), enc_name)
    assert n <= _bound(SYSTEM_BOUND, scale)
