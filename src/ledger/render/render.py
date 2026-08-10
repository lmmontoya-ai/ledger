"""Full prompt assembly: system block + board + history, bytes + digest.

Pure functions of the ledger.  The system block is byte-identical in every
call within a condition (§7.5); across registered mandate variants
(spec/templates.v2/mandates.json) only the Mandate paragraph differs, and
each variant's block is itself byte-frozen.  The digest is SHA256 of the
rendered bytes (§11.1).
"""
from __future__ import annotations

import hashlib
import json

from .board import render_board, TEMPLATES_DIR
from .history import render_history

DEFAULT_MANDATE = "principal"
_MANDATE_MARKER = b"## Mandate\n"

_system_cache: dict[str, bytes] = {}
_mandates_cache: dict | None = None


def mandate_variants() -> dict:
    """The frozen mandate variants, keyed by name."""
    global _mandates_cache
    if _mandates_cache is None:
        raw = (TEMPLATES_DIR / "mandates.json").read_text(encoding="utf-8")
        _mandates_cache = json.loads(raw)["variants"]
    return _mandates_cache


def system_block(mandate: str = DEFAULT_MANDATE) -> bytes:
    if mandate not in _system_cache:
        base = (TEMPLATES_DIR / "system.txt").read_bytes().replace(b"\r\n", b"\n")
        if mandate == DEFAULT_MANDATE:
            _system_cache[mandate] = base
        else:
            variants = mandate_variants()
            if mandate not in variants:
                raise KeyError(
                    f"unknown mandate variant {mandate!r}; "
                    f"registered: {sorted(variants)}")
            head, sep, rest = base.partition(_MANDATE_MARKER)
            if not sep:
                raise ValueError("system.txt has no '## Mandate' section")
            _, blank, tail = rest.partition(b"\n\n")
            if not blank:
                raise ValueError("Mandate paragraph is not blank-line terminated")
            text = variants[mandate]["text"].encode("utf-8")
            _system_cache[mandate] = head + _MANDATE_MARKER + text + b"\n\n" + tail
    return _system_cache[mandate]


def render_user(state, events, viewer: int) -> str:
    board = render_board(state, viewer)
    hist = render_history(state, events, viewer)
    return f"{board}\n\n{hist}\n"


def render_prompt(state, events, viewer: int,
                  mandate: str = DEFAULT_MANDATE) -> tuple[bytes, str]:
    """Returns (bytes, sha256 hex digest) of the full prompt shown to `viewer`."""
    data = system_block(mandate) + b"\n" + render_user(state, events, viewer).encode("utf-8")
    return data, hashlib.sha256(data).hexdigest()
