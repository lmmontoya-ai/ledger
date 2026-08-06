"""Generate spec/tools.v1.json from spec/actions.v1.json.

One definition of everything: the tool schemas are derived mechanically from
the action spec so the two cannot disagree.  Run as a script to regenerate;
the golden test asserts the file on disk equals the generated content.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_DIR = REPO_ROOT / "spec"

CONTRACT_SCHEMA = {
    "type": "object",
    "description": "Contract draft: assignments, funding, scheduled payments, expiry.",
    "properties": {
        "assign": {
            "type": "object",
            "description": "Map job number -> seat (1 or 2): who does what.",
            "additionalProperties": {"type": "integer", "enum": [1, 2]},
        },
        "fund": {
            "type": "object",
            "description": "Map job number -> amount reserved at ACCEPT; must be >= that seat's cost.",
            "additionalProperties": {"type": "integer", "minimum": 1},
        },
        "pay": {
            "type": "array",
            "description": "Scheduled side payments.",
            "items": {
                "type": "object",
                "properties": {
                    "from": {"type": "integer", "enum": [1, 2]},
                    "to": {"type": "integer", "enum": [1, 2]},
                    "amount": {"type": "integer", "minimum": 1},
                    "tick": {"type": "integer", "minimum": 1},
                },
                "required": ["from", "to", "amount", "tick"],
            },
        },
        "expires": {
            "type": "integer",
            "description": "Tick at whose end the offer lapses if unanswered.",
        },
    },
    "required": ["assign", "fund", "pay", "expires"],
}

TYPE_MAP = {
    "int": {"type": "integer"},
    "text40": {"type": "string", "description": "Free text, capped at 40 tokens (truncated beyond)."},
    "text40_optional": {"type": "string", "description": "Optional free text, capped at 40 tokens."},
    "contract": CONTRACT_SCHEMA,
}

OPTIONAL_TYPES = {"text40_optional"}


def load_actions() -> dict:
    with open(SPEC_DIR / "actions.v1.json", "r", encoding="utf-8") as f:
        return json.load(f)


def generate_tools(actions_spec: dict) -> dict:
    tools = []
    for name, spec in actions_spec["actions"].items():
        properties = {}
        required = []
        for arg, typ in spec["args"].items():
            properties[arg] = TYPE_MAP[typ]
            if typ not in OPTIONAL_TYPES:
                required.append(arg)
        tools.append(
            {
                "name": name.lower(),
                "description": spec["description"],
                "input_schema": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            }
        )
    return {
        "spec_version": "tools.v1",
        "generated_from": actions_spec["spec_version"],
        "tools": tools,
    }


def render_tools_json(actions_spec: dict | None = None) -> str:
    if actions_spec is None:
        actions_spec = load_actions()
    return json.dumps(generate_tools(actions_spec), indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    out = SPEC_DIR / "tools.v1.json"
    out.write_text(render_tools_json(), encoding="utf-8", newline="\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
