"""chat_enabled=False: the engine, the rules text and the tool schema all
agree that talking does not exist."""
from ledger.core import actions as actions_mod
from ledger.core import fold as fold_mod
from ledger.core.events import Action
from ledger.render.render import system_block
from ledger.runtime.tools import load_tools
from tests.conftest import simple_scenario


def test_engine_rejects_chat_when_disabled():
    on = fold_mod.initial_state(simple_scenario())
    off = fold_mod.initial_state(simple_scenario(chat_enabled=False))
    msg = Action("CHAT", {"text": "which jobs matter to you?"})
    assert actions_mod.validate(on, 1, msg) is None
    reason = actions_mod.validate(off, 1, msg)
    assert reason and "disabled" in reason
    # everything else still works
    assert actions_mod.validate(off, 1, Action("WAIT", {})) is None


def test_rules_text_drops_talking():
    base = system_block().decode()
    quiet = system_block(chat=False).decode()
    assert "chat(text)" in base and "chat(text)" not in quiet
    assert "no talking in this game" in quiet
    assert "no talking" not in base


def test_tool_schema_drops_chat():
    names = {t["function"]["name"] for t in load_tools(chat=False)}
    base = {t["function"]["name"] for t in load_tools()}
    assert "chat" in base and "chat" not in names
    assert base - names == {"chat"}
