"""Model registry: what a 'model' is for this study.

Per plan §3.8, a model is the pair (slug, pinned serving provider): requests
set an explicit provider order with fallbacks disabled, and the provider that
actually served each call is recorded from the response.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ModelSpec:
    slug: str                              # OpenRouter model slug
    label: str = ""                        # short name used in logs
    provider_order: tuple[str, ...] = ()   # pinned providers; empty = unpinned (exploration only)
    temperature: float = 1.0
    max_tokens: int = 1024
    reasoning: dict | None = None          # OpenRouter reasoning config, or None
    tool_choice: str = "required"          # the most forcing mode the model supports (§3.8)
    price_in: float | None = None          # USD per 1M input tokens, for the cost cap
    price_out: float | None = None         # USD per 1M output tokens

    def describe(self) -> dict:
        return {
            "slug": self.slug, "label": self.label or self.slug,
            "provider_order": list(self.provider_order),
            "temperature": self.temperature, "max_tokens": self.max_tokens,
            "reasoning": self.reasoning, "tool_choice": self.tool_choice,
        }


def load_models(path: str | Path) -> dict[str, ModelSpec]:
    """Load a registry file: {"models": {name: {slug, provider_order, ...}}}."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for name, m in payload["models"].items():
        out[name] = ModelSpec(
            slug=m["slug"], label=m.get("label", name),
            provider_order=tuple(m.get("provider_order", [])),
            temperature=m.get("temperature", 1.0),
            max_tokens=m.get("max_tokens", 1024),
            reasoning=m.get("reasoning"),
            tool_choice=m.get("tool_choice", "required"),
            price_in=m.get("price_in"), price_out=m.get("price_out"),
        )
    return out
