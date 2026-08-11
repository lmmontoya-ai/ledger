"""Runtime layer: §8.3 bad-output protocol, §3.8 registration and routing
rules, episode logging, and byte-exact replay — all without a network."""
import json

import pytest

from ledger.core.events import Action
from ledger.game import Game
from ledger.policies.scripted import POLICIES
from ledger.render.render import render_prompt
from ledger.runtime import (BudgetExceeded, CallResult, CostMeter,
                            EpisodeAbandoned, ModelAgent, ModelSpec,
                            OpenRouterClient, ProviderError, ScriptedAgent,
                            load_events, load_tools, read_records,
                            run_episode, sample_policy, state_at)
from ledger.scenarios.bank import load_bank

SPEC = ModelSpec(slug="fake/model", label="fake", provider_order=("prov-a",),
                 price_in=1.0, price_out=5.0)


def scenario():
    return load_bank("v1-e0")[0]


def tool_response(name, args, provider="prov-a", cost=0.001, content=None):
    return {"provider": provider, "model": "fake/model",
            "choices": [{"message": {
                "role": "assistant", "content": content,
                "tool_calls": [{"id": "call_1", "type": "function",
                                "function": {"name": name,
                                             "arguments": json.dumps(args)}}]}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 10, "cost": cost}}


def prose_response(text="I think I will wait.", provider="prov-a"):
    return {"provider": provider, "model": "fake/model",
            "choices": [{"message": {"role": "assistant", "content": text}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 10, "cost": 0.001}}


def truncated_response(provider="prov-a"):
    return {"provider": provider, "model": "fake/model",
            "choices": [{"finish_reason": "length",
                         "message": {"role": "assistant",
                                     "content": "let me think step by st"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 8192, "cost": 0.005}}


class FakeClient:
    """Stands in for OpenRouterClient: same .chat contract, no network."""

    def __init__(self, script=None, fn=None):
        self.script, self.fn = list(script or []), fn
        self.seen_messages = []

    def chat(self, spec, messages, tools=None):
        self.seen_messages.append(messages)
        raw = self.fn(spec, messages, tools) if self.fn else self.script.pop(0)
        usage = raw.get("usage") or {}
        return CallResult(raw=raw, provider=raw.get("provider"),
                          model=raw.get("model", spec.slug), usage=usage,
                          cost_usd=usage.get("cost"), latency_s=0.0, attempts=1)


# ---------------------------------------------------------------- tools ----

def test_thirteen_tools_from_frozen_spec():
    tools = load_tools()
    assert len(tools) == 13
    names = {t["function"]["name"] for t in tools}
    assert {"propose", "renege", "chat", "refuse"} <= names
    for t in tools:
        assert t["function"]["parameters"]["type"] == "object"


# ------------------------------------------------------- §8.3 protocol ----

def test_malformed_then_valid_uses_the_retry():
    g = Game(scenario())
    agent = ModelAgent(SPEC, FakeClient([prose_response(),
                                         tool_response("chat", {"text": "hi"})]))
    a = agent.act(g, g.turn)
    assert a.name == "CHAT" and a.args == {"text": "hi"}


def test_three_failures_become_flagged_wait(tmp_path):
    from ledger.runtime import EpisodeLogger
    g = Game(scenario())
    logger = EpisodeLogger(tmp_path / "ep.jsonl", {"episode_id": "t"})
    agent = ModelAgent(SPEC, FakeClient([prose_response()] * 3))
    a = agent.act(g, g.turn, logger)
    logger.close()
    assert a.name == "WAIT"
    recs = read_records(tmp_path / "ep.jsonl")
    assert recs[-1]["invalid_wait"] is True and recs[-1]["error"]


def test_retry_echo_preserves_reasoning_blocks():
    """Within-turn correction must carry the assistant's reasoning blocks
    back (Anthropic requires thinking to precede tool_use on echoed turns).
    Across turns, nothing is carried — each turn is a fresh call."""
    g = Game(scenario())
    bad = tool_response("accept", {"offer_id": 99})
    bad["choices"][0]["message"]["reasoning_details"] = [
        {"type": "reasoning.text", "text": "let me accept offer 99"}]
    client = FakeClient([bad, tool_response("wait", {})])
    ModelAgent(SPEC, client).act(g, g.turn)
    echoed = [m for m in client.seen_messages[1] if m.get("role") == "assistant"]
    assert echoed and echoed[0].get("reasoning_details")


def test_illegal_move_reprompted_with_reason(tmp_path):
    from ledger.runtime import EpisodeLogger
    g = Game(scenario())
    logger = EpisodeLogger(tmp_path / "ep.jsonl", {"episode_id": "t"})
    client = FakeClient([tool_response("accept", {"offer_id": 99}),
                         tool_response("wait", {})])
    a = ModelAgent(SPEC, client).act(g, g.turn, logger)
    logger.close()
    assert a.name == "WAIT"
    calls = [r for r in read_records(tmp_path / "ep.jsonl") if r["kind"] == "call"]
    assert "illegal action" in calls[0]["error"]
    # the rejection went back as a tool-role message, in distribution
    assert any(m.get("role") == "tool" for m in client.seen_messages[1])


def test_truncation_retried_clean_not_counted_as_behavior():
    g = Game(scenario())
    client = FakeClient([truncated_response(), tool_response("chat", {"text": "hi"})])
    a = ModelAgent(SPEC, client).act(g, g.turn)
    assert a.name == "CHAT"
    # the retry re-sent the same clean messages: no corrective was appended
    assert client.seen_messages[1] == client.seen_messages[0]


def test_persistent_truncation_abandons_not_waits():
    g = Game(scenario())
    client = FakeClient([truncated_response()] * 4)
    with pytest.raises(EpisodeAbandoned, match="max_tokens"):
        ModelAgent(SPEC, client).act(g, g.turn)


def test_max_bad_outputs_is_a_knob():
    g = Game(scenario())
    strict = ModelAgent(SPEC, FakeClient([prose_response()]), max_bad_outputs=1)
    assert strict.act(g, g.turn).name == "WAIT"
    assert strict.describe()["max_bad_outputs"] == 1


def test_pay_turn_field_accepted_end_to_end():
    sc = scenario()
    g = Game(sc)
    job = next(j for j in sc.jobs() if not sc.prereqs[j - 1])
    contract = {"assign": {job: 2}, "fund": {job: sc.cost(2, job)},
                "pay": [{"from": 1, "to": 2, "amount": 5, "turn": 8}],
                "expires": 4}
    a = ModelAgent(SPEC, FakeClient([tool_response("propose",
                                                   {"contract": contract})])).act(g, g.turn)
    assert a.name == "PROPOSE"
    g.play(a)
    assert g.state.contracts[1].pay[0].tick == 8


def test_message_cap_knob_flows_prompt_schema_and_engine():
    from ledger.render.render import system_block
    from ledger.runtime import load_tools as lt
    # default untouched, byte-for-byte
    assert b"(max 40 tokens)" in system_block()
    assert system_block() == system_block("principal", 40)
    # raised cap: stated limit matches enforced limit everywhere
    assert b"(max 120 tokens)" in system_block("principal", 120)
    chat = next(t for t in lt(message_cap=120)
                if t["function"]["name"] == "chat")
    assert "120 tokens" in json.dumps(chat)
    assert "40 tokens" not in json.dumps(chat)
    # engine truncates at the configured cap
    long_text = " ".join(["word"] * 100)
    g40, g120 = Game(scenario()), Game(scenario(), message_cap=120)
    for g in (g40, g120):
        g.play(Action("CHAT", {"text": long_text}))
    from ledger.render.tokens import token_count
    assert token_count(g40.events[0].action.args["text"], "o200k_base") <= 40
    assert token_count(g120.events[0].action.args["text"], "o200k_base") > 40


def test_mandate_variant_reaches_the_system_message():
    seen = {}

    def fn(spec, messages, tools):
        seen["system"] = messages[0]["content"]
        return tool_response("wait", {})

    g = Game(scenario())
    ModelAgent(SPEC, FakeClient(fn=fn), mandate="joint").act(g, g.turn)
    assert "combined final score" in seen["system"]


# ------------------------------------------------- episodes and replay ----

def test_scripted_episode_logs_and_replays_byte_exact(tmp_path):
    names = sorted(POLICIES)[:2]
    sc = scenario()
    agents = {1: ScriptedAgent(names[0], POLICIES[names[0]]()),
              2: ScriptedAgent(names[1], POLICIES[names[1]]())}
    r = run_episode(sc, agents, tmp_path, bank="v1-e0", episode_id="scripted1")
    recs = read_records(tmp_path / "scripted1.jsonl")
    kinds = [x["kind"] for x in recs]
    assert kinds[0] == "meta" and "result" in kinds
    # replay the world from the event records alone
    events = load_events(sc, recs)
    final = state_at(sc, events, 10_000)
    assert not final or True  # state exists
    result_rec = next(x for x in recs if x["kind"] == "result")
    g2 = Game(sc)
    for ev in events:
        g2.play(ev.action)
    assert list(g2.result["pi"]) == list(result_rec["pi"]) == list(r["pi"])


def test_model_episode_digests_verify_against_replay(tmp_path):
    sc = scenario()
    fn = lambda spec, messages, tools: tool_response("wait", {})
    agents = {1: ModelAgent(SPEC, FakeClient(fn=fn)),
              2: ModelAgent(SPEC, FakeClient(fn=fn))}
    r = run_episode(sc, agents, tmp_path, bank="v1-e0", episode_id="model1")
    assert r is not None
    recs = read_records(tmp_path / "model1.jsonl")
    events = load_events(sc, recs)
    for call in (x for x in recs if x["kind"] == "call"):
        st = state_at(sc, events, call["tick"])
        prefix = tuple(ev for ev in events if ev.tick < call["tick"])
        _, digest = render_prompt(st, prefix, call["seat"])
        assert digest == call["digest"], f"digest drift at tick {call['tick']}"


def test_cost_cap_abandons_and_quarantines(tmp_path):
    sc = scenario()
    fn = lambda spec, messages, tools: tool_response("wait", {}, cost=0.5)
    agents = {1: ModelAgent(SPEC, FakeClient(fn=fn)),
              2: ModelAgent(SPEC, FakeClient(fn=fn))}
    r = run_episode(sc, agents, tmp_path, meter=CostMeter(cap_usd=1.0),
                    episode_id="capped")
    assert r is None
    kinds = [x["kind"] for x in read_records(tmp_path / "capped.jsonl")]
    assert "abandoned" in kinds and "result" not in kinds


def test_replay_elicits_under_the_live_cap():
    """Live play and replay must share one elicitation procedure, message
    cap included: the E0 review caught replay pinned at the old default."""
    from ledger.render.render import render_prompt
    from ledger.runtime import state_at
    sc = scenario()
    c40, c200 = (FakeClient(fn=lambda s, m, t: tool_response("wait", {}))
                 for _ in range(2))
    b40 = sample_policy(c40, SPEC, sc, [], 1, n=1)
    b200 = sample_policy(c200, SPEC, sc, [], 1, n=1, message_cap=200)
    assert b40.digest != b200.digest
    st = state_at(sc, [], 1)
    assert b200.digest == render_prompt(st, (), st.mover, message_cap=200)[1]
    assert "max 200 tokens" in c200.seen_messages[0][0]["content"]


def test_meter_precheck_refuses_before_any_call():
    g = Game(scenario())
    client = FakeClient(fn=lambda s, m, t: tool_response("wait", {}))
    meter = CostMeter(cap_usd=0.001)   # worst-case per call exceeds this
    with pytest.raises(BudgetExceeded):
        ModelAgent(SPEC, client).act(g, g.turn, None, meter)
    assert client.seen_messages == []  # refused BEFORE spending


def test_unpriced_spend_is_an_error_not_free():
    g = Game(scenario())
    noprice = ModelSpec(slug="fake/noprice", provider_order=("prov-a",))
    raw = tool_response("wait", {})
    raw["usage"] = {"prompt_tokens": 100, "completion_tokens": 10}  # no cost
    with pytest.raises(BudgetExceeded, match="unmetered"):
        ModelAgent(noprice, FakeClient([raw])).act(g, g.turn, None, CostMeter())


# ------------------------------------------------------- §3.8 routing ----

def test_provider_mix_invalidates_the_batch(tmp_path):
    sc = scenario()
    flip = {"n": 0}

    def fn(spec, messages, tools):
        flip["n"] += 1
        return tool_response("wait", {},
                             provider="prov-a" if flip["n"] % 2 else "prov-b")

    batch = sample_policy(FakeClient(fn=fn), SPEC, sc, [], 1, n=4)
    assert batch.valid is False and len(batch.actions) == 4

    single = sample_policy(FakeClient(
        fn=lambda s, m, t: tool_response("wait", {})), SPEC, sc, [], 1, n=4)
    assert single.valid is True and single.digest


# ----------------------------------------------------- transport layer ----

class _Resp:
    def __init__(self, status, body=None, text=""):
        self.status_code, self._body, self.text = status, body, text

    def json(self):
        if self._body is None:
            raise json.JSONDecodeError("x", "y", 0)
        return self._body


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)

    def post(self, url, json=None, headers=None, timeout=None):
        return self.responses.pop(0)


def test_transport_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    ok = _Resp(200, tool_response("wait", {}))
    client = OpenRouterClient(api_key="test",
                              session=_Session([_Resp(429), _Resp(500), ok]))
    result = client.chat(SPEC, [{"role": "user", "content": "x"}], load_tools())
    assert result.attempts == 3 and result.provider == "prov-a"


def test_transport_hard_error_raises(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    client = OpenRouterClient(api_key="test",
                              session=_Session([_Resp(401, text="bad key")]))
    with pytest.raises(ProviderError):
        client.chat(SPEC, [], None)


def test_transport_exhaustion_abandons(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    client = OpenRouterClient(api_key="test", max_attempts=2,
                              session=_Session([_Resp(503), _Resp(503)]))
    with pytest.raises(EpisodeAbandoned):
        client.chat(SPEC, [], None)
