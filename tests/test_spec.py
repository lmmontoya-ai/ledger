"""Spec files: single definition, generated tools, registries complete."""
import json

from ledger.core.actions import PREDICATES, EFFECTS, action_spec
from ledger.core.events import ACTION_NAMES
from ledger.spec_gen import SPEC_DIR, load_actions, render_tools_json


def test_actions_spec_covers_all_fourteen():
    spec = action_spec()
    assert set(spec["actions"]) == set(ACTION_NAMES)
    assert len(spec["actions"]) == 14


def test_every_referenced_predicate_and_effect_exists():
    spec = action_spec()
    for name, a in spec["actions"].items():
        for pred in a["legality"]:
            assert pred in PREDICATES, (name, pred)
        assert a["effect"] in EFFECTS, name


def test_tools_json_is_generated_from_actions_json():
    on_disk = (SPEC_DIR / "tools.v1.json").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert on_disk == render_tools_json(), \
        "spec/tools.v1.json is stale: regenerate with python -m ledger.spec_gen"


def test_tool_schemas_match_action_args():
    tools = {t["name"]: t for t in json.loads(render_tools_json())["tools"]}
    actions = load_actions()["actions"]
    assert set(tools) == {n.lower() for n in actions}
    for name, a in actions.items():
        schema = tools[name.lower()]["input_schema"]
        assert set(schema["properties"]) == set(a["args"])
