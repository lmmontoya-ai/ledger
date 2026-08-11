"""Provider tool schemas, straight from the frozen spec (spec/tools.v2.json).

The runtime never authors a schema: it reformats the generated spec into the
OpenAI-style shape OpenRouter forwards, so the tools a model sees cannot
drift from the actions the engine accepts.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..core.events import Action

REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC_PATH = REPO_ROOT / "spec" / "tools.v2.json"

_cache: list[dict] | None = None


def load_tools(message_cap: int | None = None,
               pay_cap: int | None = None) -> list[dict]:
    global _cache
    if _cache is None:
        spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        _cache = [
            {"type": "function",
             "function": {"name": t["name"],
                          "description": t["description"],
                          "parameters": t["input_schema"]}}
            for t in spec["tools"]
        ]
    tools = _cache
    if message_cap is not None and message_cap != 40:
        # non-default cap: the stated limit in the schema must match the
        # enforced one (same rule as the system block)
        tools = json.loads(json.dumps(tools).replace(
            "40 tokens", f"{message_cap} tokens"))
    if pay_cap is not None:
        # capped payments: no transfer tool; at 0 the pay field disappears,
        # above 0 the schema states the per-deal total cap (engine
        # predicates enforce both; the schema must agree)
        tools = json.loads(json.dumps(tools))
        tools = [t for t in tools if t["function"]["name"] != "transfer"]
        for t in tools:
            if t["function"]["name"] == "propose":
                params = t["function"]["parameters"]
                c = params.get("properties", {}).get("contract", {})
                if pay_cap == 0:
                    c.get("properties", {}).pop("pay", None)
                    if "pay" in c.get("required", []):
                        c["required"] = [x for x in c["required"]
                                         if x != "pay"]
                else:
                    pay = c.get("properties", {}).get("pay")
                    if pay is not None:
                        pay["description"] = (
                            pay.get("description", "").rstrip(". ")
                            + f". Total across all payments in one deal is "
                              f"capped at {pay_cap}.").lstrip(". ")
    return tools


def action_names() -> set[str]:
    return {t["function"]["name"].upper() for t in load_tools()}


def action_from_tool_call(name: str, arguments: str | dict) -> Action:
    """Parse a provider tool call into an engine Action.

    Raises ValueError with a model-readable reason on anything malformed;
    the caller turns that into a re-prompt per environment §8.3.
    """
    upper = (name or "").upper()
    if upper not in action_names():
        raise ValueError(f"unknown tool {name!r}")
    if isinstance(arguments, str):
        try:
            args = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError as e:
            raise ValueError(f"arguments are not valid JSON: {e}")
    else:
        args = dict(arguments or {})
    if not isinstance(args, dict):
        raise ValueError("arguments must be a JSON object")
    return Action(upper, args)
