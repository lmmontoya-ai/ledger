"""Full prompt assembly: system block + board + history, bytes + digest.

Pure functions of the ledger.  The system block is byte-identical in every
call, ever (§7.5); the digest is SHA256 of the rendered bytes (§11.1).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from .board import render_board, TEMPLATES_DIR
from .history import render_history

_system_cache: bytes | None = None


def system_block() -> bytes:
    global _system_cache
    if _system_cache is None:
        _system_cache = (TEMPLATES_DIR / "system.txt").read_bytes().replace(b"\r\n", b"\n")
    return _system_cache


def render_user(state, events, viewer: int) -> str:
    board = render_board(state, viewer)
    hist = render_history(state, events, viewer)
    return f"{board}\n\n{hist}\n"


def render_prompt(state, events, viewer: int) -> tuple[bytes, str]:
    """Returns (bytes, sha256 hex digest) of the full prompt shown to `viewer`."""
    data = system_block() + b"\n" + render_user(state, events, viewer).encode("utf-8")
    return data, hashlib.sha256(data).hexdigest()
