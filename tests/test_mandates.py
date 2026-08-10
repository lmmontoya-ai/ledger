"""Mandate variants (spec/templates.v2/mandates.json): the frozen default is
byte-identical to system.txt, variants change only the Mandate paragraph, and
the registered texts cannot drift from the template."""
import json

import pytest

from ledger.render.board import TEMPLATES_DIR
from ledger.render.render import (DEFAULT_MANDATE, mandate_variants,
                                  render_prompt, system_block)


def _raw_system() -> bytes:
    return (TEMPLATES_DIR / "system.txt").read_bytes().replace(b"\r\n", b"\n")


def _mandate_paragraph(block: bytes) -> bytes:
    rest = block.split(b"## Mandate\n", 1)[1]
    return rest.split(b"\n\n", 1)[0]


def test_default_is_byte_identical_to_template():
    assert system_block() == _raw_system()
    assert system_block(DEFAULT_MANDATE) == _raw_system()


def test_principal_text_matches_template_verbatim():
    """Single source: the JSON's principal text IS the system.txt paragraph."""
    registered = mandate_variants()["principal"]["text"].encode("utf-8")
    assert registered == _mandate_paragraph(_raw_system())


@pytest.mark.parametrize("name", ["open", "own", "joint"])
def test_variant_changes_only_the_mandate_paragraph(name):
    base, var = system_block(), system_block(name)
    assert var != base
    assert _mandate_paragraph(var) == mandate_variants()[name]["text"].encode("utf-8")
    strip = lambda b: b.replace(_mandate_paragraph(b), b"")
    assert strip(var) == strip(base)


def test_shared_instrument_sentence_held_constant():
    """Variants vary the objective, never the permission framing."""
    shared = b"legitimate instruments available to you within the rules"
    for name in mandate_variants():
        assert shared in _mandate_paragraph(system_block(name))


def test_unknown_variant_rejected():
    with pytest.raises(KeyError):
        system_block("maximize-chaos")


def test_render_prompt_carries_the_variant(worked_game_factory=None):
    from conftest import worked_game
    g = worked_game(4)
    d0 = render_prompt(g.state, tuple(g.events), 1)[1]
    dj = render_prompt(g.state, tuple(g.events), 1, mandate="joint")[1]
    assert d0 != dj
    assert render_prompt(g.state, tuple(g.events), 1)[1] == d0


@pytest.mark.token_bounds
def test_variant_blocks_within_system_budget():
    from ledger.render import tokens as tok
    if not tok.encoding_available("o200k_base"):
        pytest.skip("tokenizer unavailable")
    for name in mandate_variants():
        n = tok.token_count(system_block(name).decode("utf-8"), "o200k_base")
        assert n <= 640, f"{name} system block measures {n} tokens"
