"""Token counting and the 40-token message cap.

Uses tiktoken o200k_base when importable; otherwise a whitespace
approximation, with token-bound tests skipped via a pytest marker.
"""
from __future__ import annotations

MESSAGE_TOKEN_CAP = 40

_enc = None
_tried = False


def _encoding():
    global _enc, _tried
    if not _tried:
        _tried = True
        try:
            import tiktoken
            _enc = tiktoken.get_encoding("o200k_base")
        except Exception:
            _enc = None
    return _enc


def tokenizer_available() -> bool:
    return _encoding() is not None


def tokenizer_name() -> str:
    return "o200k_base" if tokenizer_available() else "whitespace-approx"


def token_count(text: str) -> int:
    enc = _encoding()
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
