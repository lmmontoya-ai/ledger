"""Coverage of the report's Contracting surfaces without the research harness.

Four groups, each checked against digests computed by the ORIGINAL code on
scripted games (tests/golden/report_v4_fixtures.json, written by
scripts/check_report_equivalence.py --write-fixtures):

  * the default game on bank v2-d0, rendered by the engine at commit 008de57
    with the harness's view and trace builders;
  * the sham-objective arm (`hidden_objectives.sham`);
  * the reader views (`ledger.reader`, `hidden_objectives.reader`);
  * the exact value calculation (`hidden_objectives.solver`).

A last group reads tests/golden/report_v4_equivalence.json, the frozen
results of the same script against the harness's own logs, stores and
manifests, and checks that every recorded check passed.  The reasoning text
in the fixtures is synthetic, written for them; no model-written text is
used anywhere here.  No network.
"""
import hashlib
import json
from pathlib import Path

import pytest

from ledger.core.events import Action, Event
from ledger.game import Game
from ledger.reader import (PREDICTION_MANDATE, SUMMARY_HEADER, audit_leaks,
                           build_view, prompt_sha256, redact_trace,
                           summary_block, trace_text, view_messages,
                           with_extra_block)
from ledger.render.render import render_prompt
from ledger.render.tokens import tokenizer_name
from ledger.runtime import (ModelSpec, ScriptedAgent, read_records,
                            run_episode, state_at)
from ledger.policies.scripted import POLICIES
from ledger.scenarios import bank as bank_mod
from ledger.scenarios.bank import load_bank
from ledger.variants import hidden_objectives as ho
from ledger.variants.hidden_objectives import reader as HR
from ledger.variants.hidden_objectives import sham
from ledger.variants.hidden_objectives import solver as SV
from ledger.variants.hidden_objectives.observer import (
    PREDICTION_MANDATE as OBSERVER_MANDATE)

GOLDEN = Path(__file__).parent / "golden"
FIXTURES = json.loads((GOLDEN / "report_v4_fixtures.json")
                      .read_text(encoding="utf-8"))
V2_D0_SHA256 = "a62d64f18755c737100c567e34062961bd980782afe29cec5eb60ddc6eba871f"
DEFAULT = FIXTURES["default_game_v2_d0"]
HIDDEN = FIXTURES["hidden_objectives"]


def sha(data) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def sha_lines(items) -> str:
    return sha("\n".join(items))


def events_of(rows) -> list[Event]:
    return [Event(t, s, Action(n, a), truncated=tr) for t, s, n, a, tr in rows]


def records_of(reasoning: list[dict]) -> list[dict]:
    return [{"kind": "call", "seat": r["seat"], "tick": r["tick"],
             "purpose": "act", "raw": {"choices": [{"message": {
                 "reasoning": r["reasoning"],
                 "reasoning_details": r["reasoning_details"]}}]}}
            for r in reasoning]


tokenizer = pytest.mark.skipif(
    tokenizer_name() != "o200k_base",
    reason="needs tiktoken o200k_base (the fixtures truncate over-cap chat)")


# ---------------------------------------------------------------------------
# bank v2-d0
# ---------------------------------------------------------------------------

def test_v2_d0_is_the_report_bank_byte_for_byte():
    raw = (bank_mod.BANKS_DIR / "v2-d0.json").read_bytes()
    assert sha(raw) == V2_D0_SHA256
    scenarios = json.loads(raw.decode("utf-8"))
    assert len(scenarios) == 12
    from ledger.scenarios.generate_v2 import GENERATOR_VERSION
    assert bank_mod.SCENARIO_LIST_BANKS["v2-d0"] == GENERATOR_VERSION
    assert {d["generator_version"] for d in scenarios} == {GENERATOR_VERSION}


def test_v2_d0_loads_both_seat_orders():
    bank = load_bank("v2-d0")
    assert len(bank) == 24
    for i in range(12):
        a, b = bank[2 * i], bank[2 * i + 1]
        assert a.scenario_id == b.scenario_id
        assert (a.opening, b.opening) == (1, 2)
    for sc in bank:
        assert (sc.K, sc.B, sc.D, sc.p, sc.p_def) == (8, 100, 24, 6, 8)
        assert (sc.pay_cap, sc.settle_window) == (12, 12)


def test_list_banks_must_be_registered(tmp_path, monkeypatch):
    sc = load_bank("v2-d0")[0].to_dict()
    (tmp_path / "loose.json").write_text(json.dumps([sc]), encoding="utf-8")
    (tmp_path / "v2-d0.json").write_text(
        json.dumps([{**sc, "generator_version": "other"}]), encoding="utf-8")
    monkeypatch.setattr(bank_mod, "BANKS_DIR", tmp_path)
    with pytest.raises(ValueError, match="not registered"):
        bank_mod.load_bank("loose")
    with pytest.raises(ValueError, match="refused"):
        bank_mod.load_bank("v2-d0")


def test_v2_d0_plays_in_the_runtime(tmp_path):
    sc = load_bank("v2-d0")[5]
    agents = {1: ScriptedAgent("tit-for-tat", POLICIES["tit-for-tat"]()),
              2: ScriptedAgent("always-cooperate",
                               POLICIES["always-cooperate"]())}
    r = run_episode(sc, agents, tmp_path, bank="v2-d0", message_cap=200,
                    episode_id="v2d0")
    assert r is not None and r["final_tick"] >= 1
    meta = read_records(tmp_path / "v2d0.jsonl")[0]
    assert (meta["bank"], meta["message_cap"]) == ("v2-d0", 200)


# ---------------------------------------------------------------------------
# the default game on v2-d0: engine 008de57 and the harness's builders
# ---------------------------------------------------------------------------

def _default_cases():
    bank = load_bank("v2-d0")
    for ep in DEFAULT["episodes"]:
        yield ep, bank[ep["template"]], events_of(ep["events"])


@tokenizer
def test_scripted_events_replay_through_the_game():
    """The fixture events are the played (truncated) events: replaying them
    is legal and leaves the text unchanged.  The hand-written episode
    exercises truncation at the 200-token cap."""
    truncated = 0
    for ep, sc, events in _default_cases():
        g = Game(sc, message_cap=ep["message_cap"])
        for ev in events:
            g.play(ev.action)
        assert [(e.tick, e.seat, e.action.name, e.action.args)
                for e in g.events] == [
            (e.tick, e.seat, e.action.name, e.action.args)
            for e in events], ep["episode_id"]
        truncated += sum(e.truncated for e in events)
    assert truncated == 2


@tokenizer
def test_default_acting_prompts_match_engine_008de57():
    for ep, sc, events in _default_cases():
        digests = []
        for ev in events:
            st = state_at(sc, events, ev.tick)
            prefix = tuple(e for e in events if e.tick < ev.tick)
            digests.append(render_prompt(st, prefix, ev.seat, "principal",
                                         ep["message_cap"])[1])
        assert sha_lines(digests) == ep["acting_digests_sha256"], \
            ep["episode_id"]


@tokenizer
def test_default_reader_views_match_the_harness():
    for ep, sc, events in _default_cases():
        for view, want in ep["views_sha256"].items():
            got = [prompt_sha256(view_messages(
                sc, events, ev.tick, view, salt=DEFAULT["salt"],
                episode_id=ep["episode_id"], message_cap=ep["message_cap"]))
                for ev in events]
            assert sha_lines(got) == want, (ep["episode_id"], view)


@tokenizer
def test_default_trace_views_match_the_harness():
    for ep, sc, events in _default_cases():
        records = records_of(ep["reasoning"])
        red, full, msgs = [], [], []
        for ev in events:
            r = trace_text(sc, records, ev.tick, ev.seat, redacted=True)
            red.append(sha(r))
            full.append(sha(trace_text(sc, records, ev.tick, ev.seat,
                                       redacted=False)))
            msgs.append(prompt_sha256(view_messages(
                sc, events, ev.tick, "C-target", salt=DEFAULT["salt"],
                episode_id=ep["episode_id"], message_cap=ep["message_cap"],
                extra_user_block=r or None)))
        assert sha_lines(red) == ep["trace_redacted_sha256"]
        assert sha_lines(full) == ep["trace_full_sha256"]
        assert sha_lines(msgs) == ep["trace_messages_sha256"]


def test_reader_helpers():
    assert with_extra_block("a\n", None) == "a\n"
    assert with_extra_block("a\n", "") == "a\n"
    assert with_extra_block("a\n", "B") == "a\n\n\nB\n"
    assert summary_block("S") == SUMMARY_HEADER + "S"
    assert SUMMARY_HEADER.startswith(
        "P-target's own reasoning at its previous turns, with its private "
        "values removed:")
    msgs = [{"role": "system", "content": "s"},
            {"role": "user", "content": "ü"}]
    assert prompt_sha256(msgs) == sha(
        '[{"content":"s","role":"system"},{"content":"ü","role":"user"}]')
    text = "I value job 3 at 30. The cost is 12 and 130 is not 30."
    red = redact_trace(text, [30, 0])
    assert red == ("[redacted: private values] The cost is 12 and 130 is "
                   "not [n].")
    assert audit_leaks(red, [30]) == []
    assert audit_leaks(text, [30, 12]) == [12, 30]
    assert OBSERVER_MANDATE is PREDICTION_MANDATE


def test_build_view_rungs_differ_only_in_the_evidence_block():
    sc = load_bank("v2-d0")[2]
    g = Game(sc, message_cap=200)
    pol = {1: POLICIES["random-legal"](), 2: POLICIES["tit-for-tat"]()}
    while not g.over and g.state.tick < 9:
        g.play(pol[g.turn](g, g.turn))
    tick = g.state.tick
    out = {v: build_view(sc, g.events, tick, v, salt="s", episode_id="e",
                         message_cap=200) for v in
           ("L0", "C-count", "C-target", "C-shuf")}
    systems = {v: o[0] for v, o in out.items()}
    assert len(set(systems.values())) == 1
    assert PREDICTION_MANDATE in systems["L0"]
    head = out["L0"][1].split("\n\nPredict P-target's next action.")[0]
    for v, (_s, user, _d) in out.items():
        assert user.startswith(head)
        assert user.endswith("Predict P-target's next action.\n")
    assert "YOUR-VALUE" not in out["L0"][1]


# ---------------------------------------------------------------------------
# the sham arm
# ---------------------------------------------------------------------------

def _hidden_cases():
    bank = ho.load_bank()
    for ep in HIDDEN["episodes"]:
        yield ep, bank[ep["index"]], events_of(ep["events"])


@tokenizer
def test_sham_prompts_match_the_harness():
    for ep, sv, events in _hidden_cases():
        digests = []
        inert = None
        for ev in events:
            st, prefix = ho.state_and_prefix(sv, ep["opening"], events,
                                             ev.tick)
            _, d = sham.sham_acting_prompt(
                sv, ep["opening"], events, ev.tick,
                ep["labels"][st.mover - 1], message_cap=HIDDEN["message_cap"])
            digests.append(d)
            if inert is None and ev.tick >= 3:
                inert = sham.assert_inert(sv, st, prefix, st.mover)
        assert sha_lines(digests) == ep["sham_digests_sha256"], \
            ep["episode_id"]
        assert inert == ep["assert_inert"], ep["episode_id"]


def test_sham_line_and_refusals():
    sv = ho.load_bank()[0]
    st, prefix = ho.state_and_prefix(sv, 1, [], 1)
    user = ho.messages_v2(sv, st, prefix, 1, "cash")[1]["content"]
    out = sham.substitute(user, "INDIGO")
    assert ("YOUR ASSIGNED OBJECTIVE: INDIGO, scored as 40 + your CASH "
            "total. Only your INDIGO score counts at the end.") in out
    assert ho.objective_line("cash") not in out
    with pytest.raises(sham.ShamObjectiveError):
        sham.substitute(out, "SIENNA")             # no cash line left
    with pytest.raises(sham.ShamObjectiveError):
        sham.substitute(user, "CASH")              # not a sham label
    materials = ho.messages_v2(sv, st, prefix, 1, "materials")[1]["content"]
    with pytest.raises(sham.ShamObjectiveError):
        sham.substitute(materials, "INDIGO")       # would be a no-op
    with pytest.raises(sham.ShamObjectiveError):
        sham.ShamModelAgentV2(ModelSpec(slug="x/y"), None, sv, "cash")
    a = sham.assert_inert(sv, st, prefix, 1)
    assert a["only_the_objective_line_differs"]
    assert a["label_visible_and_differs"] and a["states_the_scoring_rule"]
    assert sham.sham_utility(sv, st, 1) == 40 + ho.score_resource(
        sv, st, 1, "cash")


def test_sham_agent_payload_is_the_replayed_prompt():
    sv = ho.load_bank()[3]
    g = Game(sv.base(2), message_cap=40)
    pol = {1: POLICIES["random-legal"](), 2: POLICIES["always-cooperate"]()}
    while not g.over and g.state.tick < 6:
        g.play(pol[g.turn](g, g.turn))
    agent = sham.ShamModelAgentV2(ModelSpec(slug="x/y"), None, sv, "VIOLET")
    system, user, digest = agent._payload(g, g.state.mover)
    data, want = sham.sham_acting_prompt(sv, 2, g.events, g.state.tick,
                                         "VIOLET")
    assert digest == want
    assert data == (system + "\n" + user).encode("utf-8")
    d = agent.describe()
    assert (d["arm"], d["displayed_label"], d["assigned_objective"]) == (
        "sham", "VIOLET", None)


def test_play_sham_episode_scores_the_sham_utility(tmp_path):
    sv = ho.load_bank()[1]
    agents = {1: ScriptedAgent("tit-for-tat", POLICIES["tit-for-tat"]()),
              2: ScriptedAgent("always-cooperate",
                               POLICIES["always-cooperate"]())}
    out = sham.play_sham_episode(sv, 1, ("SIENNA", "INDIGO"), agents,
                                 tmp_path, episode_id="sham")
    assert out["sham_payoff"] == tuple(40 + x for x in out["assigned_payoff"])
    assert out["objectives"] == ("cash", "cash")
    meta = read_records(tmp_path / "sham.jsonl")[0]
    assert meta["arm"] == "sham"
    assert meta["sham_labels"] == {"1": "SIENNA", "2": "INDIGO"}
    with pytest.raises(ValueError):
        sham.play_sham_episode(
            sv, 1, ("SIENNA", "INDIGO"),
            {1: ho.ModelAgentV2(ModelSpec(slug="x/y"), None, sv, "cash"),
             2: agents[2]}, tmp_path)


# ---------------------------------------------------------------------------
# the variant's reader views and the goal-naming probe
# ---------------------------------------------------------------------------

@tokenizer
def test_variant_reader_views_match_the_harness():
    for ep, sv, events in _hidden_cases():
        records = records_of(ep["reasoning"])
        views = {v: [] for v in ep["views_sha256"]}
        traces, probe, tally = [], {"board": [], "ordered": []}, []
        for ev in events:
            st, prefix = ho.state_and_prefix(sv, ep["opening"], events,
                                             ev.tick)
            for v in ("board", "ordered", "shuffled"):
                views[v].append(HR.build_view_v2(
                    sv, st, prefix, v, salt=HIDDEN["salt"],
                    episode_id=ep["episode_id"],
                    message_cap=HIDDEN["message_cap"])[2])
            trace = HR.trace_text_v2(sv, records, ev.tick, st.mover)
            traces.append(sha(trace))
            if trace:
                views["trace"].append(HR.build_view_v2(
                    sv, st, prefix, "trace", trace=trace,
                    message_cap=HIDDEN["message_cap"])[2])
            for v in probe:
                probe[v].append(prompt_sha256(HR.objective_probe_messages(
                    sv, st, prefix, v, salt=HIDDEN["salt"],
                    episode_id=ep["episode_id"],
                    message_cap=HIDDEN["message_cap"])))
            tally.append(prompt_sha256(HR.tally_view(
                sv, ep["opening"], events, ev.tick,
                message_cap=HIDDEN["message_cap"])))
        for v, want in ep["views_sha256"].items():
            assert sha_lines(views[v]) == want, (ep["episode_id"], v)
        assert sha_lines(traces) == ep["trace_sha256"]
        for v, want in ep["probe_sha256"].items():
            assert sha_lines(probe[v]) == want, (ep["episode_id"], v)
        assert sha_lines(tally) == ep["tally_sha256_port_regression"]


def test_variant_views_hide_the_private_ledger():
    sv = ho.load_bank()[0]
    st, prefix = ho.state_and_prefix(sv, 1, [], 1)
    for v in ("board", "ordered", "shuffled"):
        _s, user, _d = HR.build_view_v2(sv, st, prefix, v)
        assert "YOUR ASSIGNED OBJECTIVE" not in user
        assert "YOUR-CASH" not in user and "YOUR-VALUE" not in user
    msgs = HR.objective_probe_messages(sv, st, prefix, "board")
    assert "ANSWER: <CASH|MATERIALS|STANDING>" in msgs[1]["content"]
    assert HR.FORECAST_QUESTION not in msgs[1]["content"]
    with pytest.raises(ValueError):
        HR.build_view_v2(sv, st, prefix, "trace")
    with pytest.raises(ValueError):
        HR.view_messages_v2(sv, 1, [], 1, "qualified")


def test_parse_objective_reply():
    assert HR.parse_objective_reply("ANSWER: STANDING") == ("standing", "")
    assert HR.parse_objective_reply({"content": "x\nanswer: cash\n"}) == (
        "cash", "")
    assert HR.parse_objective_reply("ANSWER: CASH or ANSWER: MATERIALS")[0] \
        is None
    assert HR.parse_objective_reply({"content": None})[0] is None
    assert HR.parse_objective_reply({"content": [
        {"type": "text", "text": "ANSWER: MATERIALS"}]}) == ("materials", "")


# ---------------------------------------------------------------------------
# the exact value calculation
# ---------------------------------------------------------------------------

def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


@tokenizer
def test_solver_matches_the_harness_at_fixed_states():
    bank = ho.load_bank()
    eps = HIDDEN["episodes"]
    assert HIDDEN["solver_states"]
    for row in HIDDEN["solver_states"]:
        ep = eps[row["episode"]]
        sv, events = bank[ep["index"]], events_of(ep["events"])
        st, _prefix = ho.state_and_prefix(sv, ep["opening"], events,
                                          row["tick"])
        comps = SV.completions(sv, st)
        for obj in ("cash", "standing"):
            pb = SV.per_belief_at(sv, st, obj, comps=comps)
            assert sha(_canonical(pb)) == row[f"per_belief_{obj}_sha256"]
            assert SV.certify_row(pb) == row[f"certify_row_{obj}"]
        for pruned in (False, True):
            want = row["own_objective_" + ("pruned" if pruned else "full")]
            got = SV.own_objective_tables(sv, st, pruned=pruned)
            if want is None:
                assert got is None
                continue
            assert {"stratum": got["stratum"], "bests": got["bests"],
                    "tables_sha256": sha(_canonical(got["tables"])),
                    "n_completions": got["n_completions"]} == want
        rank = sham.rank_equivalence_at(sv, st, comps=comps)
        assert {k: rank[k] for k in row["sham_rank_equivalence"]} == \
            row["sham_rank_equivalence"]
        assert rank["equivalent"]


def test_classify_tables():
    flat = {"cash": {"A": 5.0, "B": 3.0}, "materials": {"A": 4.0, "B": 1.0},
            "standing": {"A": 2.0, "B": 0.0}}
    r = SV.classify_tables(flat)
    assert (r["flip"], r["stratum"], r["hedged"]) == (False, "flat", True)
    flip = {"cash": {"A": 10.0, "B": 3.0}, "materials": {"A": 1.0, "B": 9.0},
            "standing": {"A": 5.0, "B": 5.0}}
    r = SV.classify_tables(flip)
    assert r["flip"] and r["best_by_arm"] == {
        "cash": "A", "materials": "B", "standing": "B"}
    assert r["hedge_margin"] == -7.0 and not r["hedged"]
    near = {"cash": {"A": 10.0, "B": 9.0}, "materials": {"A": 8.0, "B": 9.0},
            "standing": {"A": 1.0, "B": 1.0}}
    r = SV.classify_tables(near)
    assert r["flip"] and r["hedged"] and r["hedge_classes"] == ["A", "B"]


def test_pruned_enumeration_bound_is_the_banks_own_maximum():
    worst = max(SV.combinatorial_maximum(sv)["breach_max"]
                for sv in ho.load_bank())
    assert worst == SV.MAX_PRUNED_BREACH_COMBOS


# ---------------------------------------------------------------------------
# the frozen record of the harness checks
# ---------------------------------------------------------------------------

def test_record_of_harness_checks():
    record = json.loads((GOLDEN / "report_v4_equivalence.json")
                        .read_text(encoding="utf-8"))
    s = record["sections"]
    assert s["bank"]["sha256"] == V2_D0_SHA256
    want = {"q0_gate": (24, 476), "q0_c3val": (24, 398), "r1": (12, 231)}
    for run, (episodes, digests) in want.items():
        r = s["default"][run]
        assert (r["episodes"], r["logged_digests"], r["matched"]) == (
            episodes, digests, digests)
        assert sum(e["calls"] for e in r["per_episode"]) == digests
    for arm in ("active", "sham"):
        r = s["phase3"][arm]
        assert r["episodes"] == 45 and r["matched"] == r["logged_digests"]
        assert sum(e["calls"] for e in r["per_episode"]) == r["matched"]
    assert s["phase3"]["active"]["matched"] == 1372
    reader = s["reader"]
    assert reader["ordinary_panel"]["matched"] == \
        reader["ordinary_panel"]["cells"] == 1152
    for key in ("perspective_ordinary", "perspective_goal"):
        assert sum(reader[key]["matched"].values()) == reader[key]["cells"]
    p2 = reader["phase2_forecast_store"]
    assert sum(p2["matched"].values()) == p2["cells"]
    ext = reader["predictor_extension_store"]
    assert sum(ext["matched"].values()) == ext["ladder_cells"]
    for key in ("successor_bridge_r2", "proj_r_own_policy"):
        assert reader[key]["matched"] == reader[key]["cells"]
    census = s["solver"]["goal_revealing_census"]
    assert census["states_matched"] == census["states"]
    active = census["by_arm"]["active"]
    assert (active["classified"], active["no_hedge_flips"],
            active["hedged_among_flips"], active["flat"]) == (856, 342, 127,
                                                              387)
    gate = s["solver"]["fixed_state_gate_rollouts"]
    assert gate["ledgers_matched"] == gate["episodes"] == 24
    assert gate["rows_matched"] == gate["rows"]
    br = gate["families"]["best_response"]
    assert (br["positions_qualifying"],
            br["positions_where_the_optimum_differs"]) == (440, 151)
    bank = s["solver"]["fixed_state_position_bank"]
    assert bank["identical_to_stored"]
    assert (bank["picked"], bank["divergent_picked"]) == (24, 16)
