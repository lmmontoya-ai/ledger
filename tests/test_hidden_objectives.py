"""The hidden-objectives variant (the paper's Contracting environment).

Three groups:
  * equivalence with the research harness it was ported from, through the
    frozen digests in tests/golden/hidden_objectives_equivalence.json
    (computed by the ORIGINAL implementation; see
    scripts/check_hidden_objectives_equivalence.py);
  * the variant's environment properties: resource flows, the payment
    ceiling, objective-independent dynamics, one-line objective arms, the
    observer redaction;
  * play and replay on the core runtime with scripted agents and a fake
    model client.  No network.
"""
import hashlib
import json
from pathlib import Path

import pytest

from ledger.core import actions as actions_mod
from ledger.core import fold as fold_mod
from ledger.core.events import Action, Event
from ledger.core.welfare import w_star
from ledger.policies.scripted import POLICIES
from ledger.render import tokens as tok
from ledger.runtime import (CallResult, ModelSpec, ScriptedAgent,
                            assert_replays_as_played, load_events,
                            played_events, read_records, run_episode)
from ledger.variants import hidden_objectives as ho
from ledger.variants.hidden_objectives import (RESOURCES, ScenarioV2,
                                               score_vector)

FIXTURE = Path(__file__).parent / "golden" / "hidden_objectives_equivalence.json"


def sha(data) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(scope="module")
def bank() -> list[ScenarioV2]:
    return ho.load_bank()


@pytest.fixture(scope="module")
def sv(bank) -> ScenarioV2:
    return bank[0]


def _play(st, action: Action):
    reason = actions_mod.validate(st, st.mover, action)
    assert reason is None, reason
    return fold_mod.apply(st, Event(st.tick, st.mover, action))


# ---------------------------------------------------------------------------
# equivalence with the original implementation
# ---------------------------------------------------------------------------

def test_frozen_bank_is_the_rebuilt_bank(bank):
    """The shipped bank file is exactly what the seeded generator and the
    studied admission rule produce."""
    assert [s.to_dict() for s in ho.paper_bank()] == [s.to_dict() for s in bank]
    assert len(bank) == ho.PAPER_BANK_SIZE == 12
    assert [s.seed for s in bank] == [17, 23, 26, 50, 83, 87, 95, 98, 104,
                                      121, 127, 134]
    # the first campaign episode of the paper was played on this scenario
    assert bank[0].scenario_id == (
        "1f1f46fb777e02dd2468d771509cc2e40bff54cbf7fffb868624a290fd9f3300")
    for s in bank:
        assert ho.admit(s, profile=ho.PAPER_PROFILE)["admitted"]


def test_system_blocks_match_the_original(bank):
    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert set(fx["system_blocks"]) == {s.scenario_id for s in bank}
    for s in bank:
        want = fx["system_blocks"][s.scenario_id]
        assert sha(ho.system_block_v2(s, message_cap=40)) == want["system_block_sha256"]
        assert sha(ho.observer_system(s, 40)) == want["observer_system_sha256"]


def test_prompts_and_outcomes_match_the_original(bank):
    """Every acting prompt (all three objective arms at every tick), every
    observer board, and every outcome of 25 frozen episodes reproduces the
    digests the original harness code computed."""
    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    by_id = {s.scenario_id: s for s in bank}
    assert len(fx["episodes"]) == 25
    for ep in fx["episodes"]:
        s = by_id[ep["scenario_id"]]
        events = [Event(t, seat, Action(name, args), truncated=trunc)
                  for t, seat, name, args, trunc in ep["events"]]
        acting, observer = [], []
        for ev in events:
            st, prefix = ho.state_and_prefix(s, ep["opening"], events, ev.tick)
            for r in RESOURCES:
                acting.append(ho.render_prompt_v2(
                    s, st, prefix, st.mover, r,
                    message_cap=ep["message_cap"])[1])
            observer.append(sha(ho.observer_board(s, st, st.mover)))
        assert len(acting) == ep["n_prompts"]
        assert sha("\n".join(acting)) == ep["acting_digests_sha256"], ep["policies"]
        assert sha("\n".join(observer)) == ep["observer_board_digests_sha256"]
        got = ho.outcome(s, ep["opening"], events, tuple(ep["objectives"]))
        assert {r: list(v) for r, v in got["scores"].items()} == ep["outcome"]["scores"]
        assert list(got["assigned_payoff"]) == ep["outcome"]["assigned_payoff"]
        assert ({r: list(v) for r, v in got["scored_window_scores"].items()}
                == ep["outcome"]["scored_window_scores"])
        assert list(got["scored_window_payoff"]) == ep["outcome"]["scored_window_payoff"]


def test_fixture_covers_message_truncation():
    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert any(e[4] for ep in fx["episodes"] for e in ep["events"])


# ---------------------------------------------------------------------------
# resource flows
# ---------------------------------------------------------------------------

def test_job_pays_a_resource_mix(sv):
    """A finished job pays both seats a vector, and at least one job pays
    materially in more than one resource."""
    st = fold_mod.initial_state(sv.base())
    assert score_vector(sv, st) == {r: (0, 0) for r in RESOURCES}
    seat = st.mover
    job = next(j for j in sv.jobs()
               if sv.base().arrive(j) == 1 and not sv.prereqs[j - 1]
               and sv.cost(seat, j) <= sv.u[seat - 1])
    st = _play(st, Action("DRAW", {"amount": sv.cost(seat, job), "job": job}))
    st = _play(st, Action("WAIT"))
    st = _play(st, Action("EXECUTE", {"job": job}))
    after = score_vector(sv, st)
    for r in RESOURCES:
        for s in (1, 2):
            assert after[r][s - 1] == sv.yield_of(r, s, job)
    mixes = [sum(1 for r in RESOURCES if sv.yield_of(r, 1, j) > 0)
             for j in sv.jobs()]
    assert max(mixes) >= 2


def test_pay_moves_cash_only(sv):
    st = fold_mod.initial_state(sv.base())
    mover = st.mover
    contract = {"assign": {}, "fund": {},
                "pay": [{"from": mover, "to": 3 - mover, "amount": sv.pay_cap,
                         "turn": sv.D - sv.settle_window + 1}],
                "expires": st.tick + 2}
    st = _play(st, Action("PROPOSE", {"contract": contract}))
    st = _play(st, Action("ACCEPT", {"offer_id": 1}))
    while not st.over:
        st = _play(st, Action("WAIT"))
    got = score_vector(sv, st)
    assert got["cash"][mover - 1] == -sv.pay_cap
    assert got["cash"][2 - mover] == sv.pay_cap
    assert got["materials"] == (0, 0)
    assert got["standing"] == (0, 0)


def test_conduct_moves_standing_only(sv):
    st = fold_mod.initial_state(sv.base())
    mover = st.mover
    job = next(j for j in sv.jobs()
               if sv.base().arrive(j) == 1 and not sv.prereqs[j - 1])
    contract = {"assign": {str(job): mover},
                "fund": {str(job): sv.cost(mover, job)},
                "pay": [], "expires": st.tick + 2}
    st = _play(st, Action("PROPOSE", {"contract": contract}))
    st = _play(st, Action("ACCEPT", {"offer_id": 1}))
    for _ in range(sv.r + 1):
        st = _play(st, Action("WAIT"))
    while st.mover != mover:
        st = _play(st, Action("WAIT"))
    st = _play(st, Action("RENEGE", {"contract_id": 1}))
    got = score_vector(sv, st)
    assert got["standing"][mover - 1] == -sv.standing_broken
    assert got["materials"] == (0, 0)
    assert got["cash"][mover - 1] == -sv.p


# ---------------------------------------------------------------------------
# the core engine is reused, not forked
# ---------------------------------------------------------------------------

def test_pay_ceiling_is_pay_cap(bank):
    """The payment ceiling is `pay_cap`, not W*, in every bank scenario, so
    the dynamics never read a value column."""
    for s in bank:
        assert 1 <= s.pay_cap <= w_star(s.base())
        for r in RESOURCES:
            assert s.pay_cap <= w_star(ho.shadow(s, r))
    s = bank[0]
    st = fold_mod.initial_state(s.base())
    over = {"assign": {}, "fund": {},
            "pay": [{"from": 1, "to": 2, "amount": s.pay_cap + 1,
                     "turn": s.D - 1}], "expires": st.tick + 2}
    assert actions_mod.validate(st, st.mover,
                                Action("PROPOSE", {"contract": over})) is not None
    ok = dict(over, pay=[{"from": 1, "to": 2, "amount": s.pay_cap,
                          "turn": s.D - 1}])
    assert actions_mod.validate(st, st.mover,
                                Action("PROPOSE", {"contract": ok})) is None


def test_dynamics_do_not_depend_on_the_objective(sv):
    """Replace the reference value column with any single resource column:
    a scripted episode's legal moves and states are unchanged, because the
    engine never reads values except through the (non-binding) W* ceiling."""
    from ledger.game import Game
    base = sv.base(1)
    g = Game(base)
    pol = {1: POLICIES["random-legal"](), 2: POLICIES["always-cooperate"]()}
    while not g.over:
        g.play(pol[g.turn](g, g.turn))
    for r in RESOURCES:
        sh = ho.shadow(sv, r, opening=1)
        st_ref, st_sh = fold_mod.initial_state(base), fold_mod.initial_state(sh)
        for ev in g.events:
            assert (actions_mod.validate(st_ref, ev.seat, ev.action)
                    == actions_mod.validate(st_sh, ev.seat, ev.action))
            st_ref, st_sh = fold_mod.apply(st_ref, ev), fold_mod.apply(st_sh, ev)
            assert st_ref.accounts == st_sh.accounts
            assert st_ref.done == st_sh.done
            assert st_ref.pot_left == st_sh.pot_left


def test_scenario_roundtrip(sv):
    again = ScenarioV2.from_dict(sv.to_dict())
    assert again == sv
    assert again.base().to_dict() == sv.base().to_dict()
    assert sv.with_opening(2).base().opening == 2


def test_generator_is_deterministic():
    assert ho.generate(7).to_dict() == ho.generate(7).to_dict()
    assert ([s.scenario_id for s in ho.build_bank(3)]
            == [s.scenario_id for s in ho.build_bank(3)])


def test_late_arrivals_land_outside_the_window(bank):
    for s in bank:
        assert s.D == 48 and s.scored_turns == 24
        late = [j for j in s.jobs() if s.base().arrive(j) > s.scored_turns]
        assert late, s.scenario_id


# ---------------------------------------------------------------------------
# prompts
# ---------------------------------------------------------------------------

def test_objective_arms_differ_in_exactly_one_line(sv):
    st = fold_mod.initial_state(sv.base())
    audit = ho.arms_differ_in_one_line(sv, st, (), st.mover)
    assert audit["differing_lines"] == {r: ho.objective_line(r)
                                        for r in RESOURCES}
    assert len(set(audit["digests"].values())) == 3


def test_observer_view_hides_private_values_and_objective(bank):
    for s in bank:
        st = fold_mod.initial_state(s.base())
        for seat in (1, 2):
            acting = ho.render_user_v2(s, st, (), seat, "cash")
            view = ho.observer_board(s, st, seat)
            assert "YOUR ASSIGNED OBJECTIVE" in acting
            for marker in ("YOUR ASSIGNED OBJECTIVE", "YOUR-MATERIALS",
                           "YOUR-VALUE", "YOUR-CASH", "## Your ledger"):
                assert marker not in view
            assert "P-target" in view
        system = ho.observer_system(s, 40)
        assert ho.PREDICTION_MANDATE in system
        assert "YOUR ASSIGNED OBJECTIVE" not in system


# ---------------------------------------------------------------------------
# play and replay
# ---------------------------------------------------------------------------

SPEC = ModelSpec(slug="fake/model", label="fake", provider_order=("prov-a",),
                 price_in=1.0, price_out=5.0)


class FakeClient:
    """No network.  Replies with a scripted sequence of tool calls."""

    def __init__(self, calls):
        self.calls = list(calls)
        self.seen = []

    def chat(self, spec, messages, tools=None):
        self.seen.append(messages)
        name, args = self.calls.pop(0) if self.calls else ("end", {})
        raw = {"provider": "prov-a", "model": spec.slug,
               "choices": [{"message": {
                   "role": "assistant", "content": None,
                   "tool_calls": [{"id": "c1", "type": "function",
                                   "function": {"name": name,
                                                "arguments": json.dumps(args)}}]}}],
               "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                         "cost": 0.0}}
        return CallResult(raw=raw, provider="prov-a", model=spec.slug,
                          usage=raw["usage"], cost_usd=0.0, latency_s=0.0,
                          attempts=1)


def test_scripted_episode_logs_variant_meta_and_scores(sv, tmp_path):
    agents = {1: ScriptedAgent("greedy-optimal", POLICIES["greedy-optimal"]()),
              2: ScriptedAgent("tit-for-tat", POLICIES["tit-for-tat"]())}
    out = ho.play_episode(sv, 2, ("materials", "standing"), agents, tmp_path,
                          episode_id="ep")
    recs = read_records(tmp_path / "ep.jsonl")
    meta = recs[0]
    assert meta["variant"] == "hidden_objectives"
    assert meta["objectives"] == {"1": "materials", "2": "standing"}
    assert meta["variant_generator_version"] == ho.GENERATOR_VERSION
    assert meta["opening"] == 2 and meta["message_cap"] == 40
    _, events = ho.load_episode(tmp_path / "ep.jsonl")
    final = fold_mod.fold(sv.base(2), events)
    assert out["scores"] == score_vector(sv, final)
    assert out["assigned_payoff"] == (out["scores"]["materials"][0],
                                      out["scores"]["standing"][1])
    assert out["engine_result"]["pi"] == (final.score(1), final.score(2))


def test_model_agent_sends_the_replayable_prompt(sv, tmp_path):
    """A model seat is shown exactly `acting_prompt` at every tick, and the
    logged digest is that prompt's digest."""
    client = FakeClient([("chat", {"text": "what do you need?"}),
                         ("chat", {"text": "materials, mostly."}),
                         ("wait", {}), ("end", {}), ("end", {})])
    agents = {1: ho.ModelAgentV2(SPEC, client, sv, "cash"),
              2: ho.ModelAgentV2(SPEC, client, sv, "materials")}
    out = ho.play_episode(sv, 1, ("cash", "materials"), agents, tmp_path,
                          episode_id="m")
    assert out is not None
    recs = read_records(tmp_path / "m.jsonl")
    _, events = ho.load_episode(tmp_path / "m.jsonl")
    calls = [r for r in recs if r.get("kind") == "call"]
    assert len(calls) == len(events) == len(client.seen)
    for call, sent in zip(calls, client.seen):
        obj = ("cash", "materials")[call["seat"] - 1]
        data, digest = ho.acting_prompt(sv, 1, events, call["tick"], obj)
        assert call["digest"] == digest
        assert (sent[0]["content"] + "\n" + sent[1]["content"]).encode() == data
        assert call["model"]["assigned_objective"] == obj


def test_agent_objective_must_match_assignment(sv, tmp_path):
    agents = {1: ho.ModelAgentV2(SPEC, FakeClient([]), sv, "cash"),
              2: ScriptedAgent("always-cooperate", POLICIES["always-cooperate"]())}
    with pytest.raises(ValueError):
        ho.play_episode(sv, 1, ("standing", "cash"), agents, tmp_path)
    with pytest.raises(ValueError):
        ho.ModelAgentV2(SPEC, None, sv, "gold")


def test_extra_meta_cannot_overwrite_standard_keys(sv, tmp_path):
    agents = {s: ScriptedAgent("always-cooperate", POLICIES["always-cooperate"]())
              for s in (1, 2)}
    with pytest.raises(ValueError):
        run_episode(sv.base(), agents, tmp_path, extra_meta={"opening": 2})


@pytest.mark.token_bounds
@pytest.mark.skipif(not tok.tokenizer_available(),
                    reason="tiktoken o200k_base not available")
def test_played_events_recover_truncated_messages(sv, tmp_path):
    """The episode log keeps the text the agent returned; the game played
    the truncated text.  `played_events` recovers what was played, and
    `load_events` (raw) does not, for an over-cap message."""
    long = " ".join(["negotiate"] * 120)
    client = FakeClient([("chat", {"text": long}), ("end", {}), ("end", {})])
    agents = {1: ho.ModelAgentV2(SPEC, client, sv, "cash"),
              2: ho.ModelAgentV2(SPEC, client, sv, "standing")}
    ho.play_episode(sv, 1, ("cash", "standing"), agents, tmp_path,
                    episode_id="t")
    recs = read_records(tmp_path / "t.jsonl")
    played = played_events(recs)
    assert played[0].truncated
    assert assert_replays_as_played(sv.base(1), recs)["truncated_messages"] == 1
    raw = load_events(sv.base(1), recs)
    assert raw[0].action.args["text"] == long != played[0].action.args["text"]
    # the second mover's logged prompt is reproduced only from played events
    second = next(r for r in recs if r.get("kind") == "call" and r["tick"] == 2)
    assert ho.acting_prompt(sv, 1, played, 2, "standing")[1] == second["digest"]
    assert ho.acting_prompt(sv, 1, raw, 2, "standing")[1] != second["digest"]
