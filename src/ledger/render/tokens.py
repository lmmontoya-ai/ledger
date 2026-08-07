"""Token counting and the 40-token message cap.

Uses tiktoken o200k_base when importable; otherwise a whitespace
approximation, with token-bound tests skipped via a pytest marker.
"""
from __future__ import annotations

MESSAGE_TOKEN_CAP = 40
DEFAULT_ENCODING = "o200k_base"

_encs: dict[str, object] = {}


def encoding_named(name: str):
    """A tiktoken encoding by name, cached; None if unavailable."""
    if name not in _encs:
        try:
            import tiktoken
            _encs[name] = tiktoken.get_encoding(name)
        except Exception:
            _encs[name] = None
    return _encs[name]


def encoding_available(name: str) -> bool:
    return encoding_named(name) is not None


def _encoding():
    return encoding_named(DEFAULT_ENCODING)


def tokenizer_available() -> bool:
    return _encoding() is not None


def tokenizer_name() -> str:
    return DEFAULT_ENCODING if tokenizer_available() else "whitespace-approx"


def token_count(text: str, encoding: str | None = None) -> int:
    """Token count under the named encoding (default: the reference
    o200k_base of §7.6); whitespace approximation if unavailable."""
    enc = encoding_named(encoding) if encoding else _encoding()
    if enc is not None:
        return len(enc.encode(text))
    return len(text.split())


def truncate_message(text: str, cap: int = MESSAGE_TOKEN_CAP) -> tuple[str, bool]:
    """Truncate to `cap` tokens at the engine boundary; returns (text, truncated)."""
    enc = _encoding()
    if enc is not None:
        toks = enc.encode(text)
        if len(toks) <= cap:
            return text, False
        return enc.decode(toks[:cap]), True
    words = text.split()
    if len(words) <= cap:
        return text, False
    return " ".join(words[:cap]), True
