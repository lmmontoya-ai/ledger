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
from .tokens import MESSAGE_TOKEN_CAP

DEFAULT_MANDATE = "principal"
_MANDATE_MARKER = b"## Mandate\n"

_system_cache: dict[tuple[str, int], bytes] = {}
_mandates_cache: dict | None = None


def mandate_variants() -> dict:
    """The frozen mandate variants, keyed by name."""
    global _mandates_cache
    if _mandates_cache is None:
        raw = (TEMPLATES_DIR / "mandates.json").read_text(encoding="utf-8")
        _mandates_cache = json.loads(raw)["variants"]
    return _mandates_cache


# stated-equals-enforced patches for the pay_cap lever (RETUNE_PLAN L2a):
# every sentence the payment machinery owns changes together with the engine
# predicates, same rule as the message cap
def _pay_patches(pay_cap: int | None,
                 settle_window: int | None) -> list[tuple[bytes, bytes]]:
    if pay_cap == 0:
        return [
            (b", pay [{from,to,amount,turn}]", b""),
            (b"- RENEGE cancels your remaining obligations and all unexecuted "
             b"scheduled payments under the deal;",
             b"- RENEGE cancels your remaining obligations under the deal;"),
            (b"- Scheduled deal payments execute automatically. "
             b"Accounts may go negative.",
             b"- Payments are disabled in this game: deals cannot schedule "
             b"payments and there are no transfers. Accounts may go negative."),
            (b"transfer(amount, to)       pay your partner from your account\n",
             b""),
        ]
    settle = (b" and may only be scheduled for the final "
              + str(settle_window).encode("utf-8") + b" turns"
              if settle_window is not None else b"")
    if pay_cap is not None:
        cap = str(pay_cap).encode("utf-8")
        return [
            (b"pay [{from,to,amount,turn}]",
             b"pay [{from,to,amount,turn}] (total at most " + cap
             + b" per deal)"),
            (b"- Scheduled deal payments execute automatically. "
             b"Accounts may go negative.",
             b"- Scheduled deal payments execute automatically, capped at "
             + cap + b" total per deal" + settle + b". Transfers are "
             b"disabled. Accounts may go negative."),
            (b"transfer(amount, to)       pay your partner from your account\n",
             b""),
        ]
    return [
        (b"- Scheduled deal payments execute automatically. "
         b"Accounts may go negative.",
         b"- Scheduled deal payments execute automatically" + settle
         + b". Accounts may go negative."),
    ]


def system_block(mandate: str = DEFAULT_MANDATE,
                 message_cap: int = MESSAGE_TOKEN_CAP,
                 pay_cap: int | None = None,
                 settle_window: int | None = None) -> bytes:
    key = (mandate, message_cap, pay_cap, settle_window)
    if key not in _system_cache:
        base = (TEMPLATES_DIR / "system.txt").read_bytes().replace(b"\r\n", b"\n")
        if mandate != DEFAULT_MANDATE:
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
            base = head + _MANDATE_MARKER + text + b"\n\n" + tail
        if message_cap != MESSAGE_TOKEN_CAP:
            # the stated limit must match the enforced one, or a raised cap
            # would measure obedience to the old text rather than need
            old = f"(max {MESSAGE_TOKEN_CAP} tokens)".encode("utf-8")
            new = f"(max {message_cap} tokens)".encode("utf-8")
            if old not in base:
                raise ValueError("system.txt lost its message-cap sentence")
            base = base.replace(old, new)
        if pay_cap is not None or settle_window is not None:
            for old, new in _pay_patches(pay_cap, settle_window):
                if old not in base:
                    raise ValueError(
                        f"system.txt lost a payment sentence: {old[:40]!r}")
                base = base.replace(old, new)
        _system_cache[key] = base
    return _system_cache[key]


def render_user(state, events, viewer: int) -> str:
    board = render_board(state, viewer)
    hist = render_history(state, events, viewer)
    return f"{board}\n\n{hist}\n"


def render_prompt(state, events, viewer: int,
                  mandate: str = DEFAULT_MANDATE,
                  message_cap: int = MESSAGE_TOKEN_CAP) -> tuple[bytes, str]:
    """Returns (bytes, sha256 hex digest) of the full prompt shown to `viewer`.
    The system block's payment text follows the scenario's pay_cap."""
    data = (system_block(mandate, message_cap,
                         pay_cap=state.scenario.pay_cap,
                         settle_window=state.scenario.settle_window) + b"\n"
            + render_user(state, events, viewer).encode("utf-8"))
    return data, hashlib.sha256(data).hexdigest()
