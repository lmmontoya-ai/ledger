"""pay_cap=0 stated-equals-enforced: system text, tool schema, and engine
predicates must agree that payments do not exist."""
from ledger.core import actions as actions_mod
from ledger.core import fold as fold_mod
from ledger.core.events import Action
from ledger.render.render import system_block
from ledger.runtime.tools import load_tools
from tests.conftest import simple_scenario


def test_system_block_drops_payment_text():
    base = system_block().decode()
    patched = system_block(pay_cap=0).decode()
    assert "transfer(" in base and "transfer(" not in patched
    assert "pay [{from,to,amount,turn}]" not in patched
    assert "Payments are disabled" in patched
    assert "scheduled payments" not in patched


def test_tools_drop_transfer_and_pay_field():
    base = load_tools()
    patched = load_tools(pay_cap=0)
    names = {t["function"]["name"] for t in patched}
    assert "transfer" not in names
    assert {t["function"]["name"] for t in base} - names == {"transfer"}
    propose = next(t for t in patched if t["function"]["name"] == "propose")
    contract = propose["function"]["parameters"]["properties"]["contract"]
    assert "pay" not in contract.get("properties", {})


def test_arrivals_gate_work_but_not_deals():
    sc = simple_scenario(available_from=(1, 14, 1, 1))
    st = fold_mod.initial_state(sc)
    # drawing for or executing an unopened job is illegal, with the turn named
    reason = actions_mod.validate(st, 1, Action("DRAW",
                                                {"amount": 12, "job": 2}))
    assert reason and "until turn 14" in reason
    # proposing a deal about it now is legal: forward contracts are the point
    contract = {"assign": {"2": 2}, "fund": {"2": 10}, "pay": [],
                "expires": 4}
    assert actions_mod.validate(st, 1, Action("PROPOSE",
                                              {"contract": contract})) is None
    # the stated text moves with the mechanism
    assert "Openings" in system_block(arrivals=True).decode()
    assert "Openings" not in system_block().decode()


def test_engine_rejects_payments_under_cap_zero():
    sc = simple_scenario(pay_cap=0)
    st = fold_mod.initial_state(sc)
    reason = actions_mod.validate(st, 1, Action("TRANSFER",
                                                {"amount": 5, "to": 2}))
    assert reason and "disabled" in reason
    contract = {"assign": {"1": 1}, "fund": {"1": 10},
                "pay": [{"from": 2, "to": 1, "amount": 5, "turn": 6}],
                "expires": 4}
    reason = actions_mod.validate(st, 1, Action("PROPOSE",
                                                {"contract": contract}))
    assert reason and "disabled" in reason
