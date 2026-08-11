"""The only code that talks to a provider (via the OpenRouter aggregator).

Environment §8.3, last row: provider errors, timeouts, and filter failures
are infrastructure, never behavior.  They are retried with backoff; past the
wall-clock cap the episode is abandoned and quarantined.  Nothing here ever
converts an infrastructure failure into a WAIT.

Plan §3.8: requests pin an explicit provider order with fallbacks disabled,
and the provider that actually served each call is recorded from the
response.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

from .config import ModelSpec

BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
RETRYABLE = {408, 429, 500, 502, 503, 504}


class ProviderError(RuntimeError):
    """A non-retryable provider response."""


class EpisodeAbandoned(RuntimeError):
    """Provider stayed down past the wall-clock cap (§8.3): quarantine."""


class BudgetExceeded(RuntimeError):
    """The hard cost cap tripped; the episode is abandoned, not truncated."""


@dataclass
class CallResult:
    raw: dict                    # the full response body, verbatim
    provider: str | None         # who actually served it (plan §3.8)
    model: str                   # the served model id per the response
    usage: dict
    cost_usd: float | None
    latency_s: float
    attempts: int                # transport attempts (1 = clean)

    def message(self) -> dict:
        return (self.raw.get("choices") or [{}])[0].get("message") or {}

    def finish_reason(self) -> str | None:
        return (self.raw.get("choices") or [{}])[0].get("finish_reason")


class CostMeter:
    """Cumulative spend with a HARD cap: thread-safe, checked before a call
    is placed (worst-case estimate) as well as after, and a call whose price
    cannot be determined is an error, never $0.  `on_add` is invoked (under
    the lock) after every accounted call so callers can persist spend at
    call granularity rather than stage granularity."""

    EST_PROMPT_TOKENS = 4_000   # generous worst-case prompt for the precheck

    def __init__(self, cap_usd: float | None = None, *,
                 strict_pricing: bool = True, on_add=None):
        import threading
        self.cap_usd = cap_usd
        self.spent_usd = 0.0
        self.calls = 0
        self.unpriced_calls = 0
        self.strict_pricing = strict_pricing
        self.on_add = on_add
        self._lock = threading.Lock()

    def precheck(self, spec: ModelSpec) -> None:
        """Refuse to place a call whose worst case could breach the cap."""
        if self.cap_usd is None:
            return
        if spec.price_in is None or spec.price_out is None:
            if self.strict_pricing:
                raise BudgetExceeded(
                    f"{spec.slug} has no price entry; refusing to spend "
                    "unmetered money (set price_in/price_out)")
            return
        worst = (self.EST_PROMPT_TOKENS * spec.price_in
                 + spec.max_tokens * spec.price_out) / 1e6
        with self._lock:
            if self.spent_usd + worst > self.cap_usd:
                raise BudgetExceeded(
                    f"next call could cost ${worst:.2f}; "
                    f"${self.spent_usd:.2f} of ${self.cap_usd:.2f} spent")

    def add(self, result: CallResult, spec: ModelSpec) -> None:
        cost = result.cost_usd
        if cost is None and spec.price_in is not None and spec.price_out is not None:
            u = result.usage or {}
            cost = (u.get("prompt_tokens", 0) * spec.price_in
                    + u.get("completion_tokens", 0) * spec.price_out) / 1e6
        with self._lock:
            self.calls += 1
            if cost is None:
                self.unpriced_calls += 1
                if self.strict_pricing:
                    raise BudgetExceeded(
                        f"call to {spec.slug} returned no usage cost and the "
                        "registry has no prices; unmetered spend refused")
                cost = 0.0
            self.spent_usd += cost
            if self.on_add is not None:
                self.on_add(self)
            if self.cap_usd is not None and self.spent_usd > self.cap_usd:
                raise BudgetExceeded(
                    f"spent ${self.spent_usd:.2f} > cap ${self.cap_usd:.2f} "
                    f"after {self.calls} calls")


class OpenRouterClient:
    def __init__(self, api_key: str | None = None, *, session=None,
                 timeout_s: float = 180.0, max_attempts: int = 6,
                 wall_clock_cap_s: float = 900.0, app_name: str = "ledger"):
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not self.api_key:
            raise ProviderError(
                "no API key: pass api_key or set OPENROUTER_API_KEY")
        if session is None:
            import requests
            session = requests.Session()
        self.session = session
        self.timeout_s = timeout_s
        self.max_attempts = max_attempts
        self.wall_clock_cap_s = wall_clock_cap_s
        self.app_name = app_name

    def _body(self, spec: ModelSpec, messages: list[dict],
              tools: list[dict] | None) -> dict:
        body = {
            "model": spec.slug,
            "messages": messages,
            "temperature": spec.temperature,
            "max_tokens": spec.max_tokens,
            "usage": {"include": True},
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = spec.tool_choice
        if spec.provider_order:
            body["provider"] = {"order": list(spec.provider_order),
                                "allow_fallbacks": False}
        if spec.reasoning is not None:
            body["reasoning"] = spec.reasoning
        return body

    def chat(self, spec: ModelSpec, messages: list[dict],
             tools: list[dict] | None = None) -> CallResult:
        import requests
        body = self._body(spec, messages, tools)
        headers = {"Authorization": f"Bearer {self.api_key}",
                   "X-Title": self.app_name}
        started = time.monotonic()
        last_err = "no attempt made"
        for attempt in range(1, self.max_attempts + 1):
            if time.monotonic() - started > self.wall_clock_cap_s:
                break
            t0 = time.monotonic()
            try:
                resp = self.session.post(BASE_URL, json=body, headers=headers,
                                         timeout=self.timeout_s)
            except requests.RequestException as e:
                last_err = f"transport: {e}"
                time.sleep(min(2 ** attempt, 30))
                continue
            latency = time.monotonic() - t0
            if resp.status_code in RETRYABLE:
                last_err = f"HTTP {resp.status_code}"
                time.sleep(min(2 ** attempt, 30))
                continue
            if resp.status_code != 200:
                raise ProviderError(
                    f"HTTP {resp.status_code}: {resp.text[:500]}")
            try:
                raw = resp.json()
            except json.JSONDecodeError:
                last_err = "unparseable 200 body"
                time.sleep(min(2 ** attempt, 30))
                continue
            err = raw.get("error")
            if err:
                code = err.get("code")
                if isinstance(code, int) and code in RETRYABLE:
                    last_err = f"provider error {code}: {err.get('message')}"
                    time.sleep(min(2 ** attempt, 30))
                    continue
                raise ProviderError(f"provider error: {err}")
            usage = raw.get("usage") or {}
            return CallResult(
                raw=raw,
                provider=raw.get("provider"),
                model=raw.get("model", spec.slug),
                usage=usage,
                cost_usd=usage.get("cost"),
                latency_s=round(latency, 3),
                attempts=attempt,
            )
        raise EpisodeAbandoned(
            f"provider unavailable past caps ({last_err}); "
            "episode abandoned and quarantined per environment §8.3")
