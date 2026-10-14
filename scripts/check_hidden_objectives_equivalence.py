"""Prove that ledger.variants.hidden_objectives reproduces the research
harness it was ported from, byte for byte.

The original lives in the self-other-prediction-smoke-tests repository
(`ledger-experiments/engine_v2/` and `ledger-experiments/ledger_v2_bridge.py`).
This script imports that code read-only, points it at THIS repository's
`src` (through the harness's own LEDGER_SRC override), and compares:

  1. generator and admission: every seed in a range, under the default and
     the studied admission rule; the studied 12-scenario bank; the frozen
     bank file.
  2. the paper's campaign episode logs (S0, 36 episodes, if present): the
     played-event reader, the replay check against `Game`, the acting
     prompt at every tick under all three objectives, the observer view,
     the model agent payload, the logged call digests, and the final fold.
  3. solver rollouts: the harness's own 48-turn episodes, scored by the port.
  4. scripted episodes on every bank scenario and both seat orders, plus a
     hand-written episode with an over-cap CHAT.  With --write-fixture the
     harness's digests for these are frozen to
     tests/golden/hidden_objectives_equivalence.json, which
     tests/test_hidden_objectives.py checks without the harness present.

No model calls, no network, no writes outside this repository (bytecode
writing is disabled so the harness tree is not touched).

    python scripts/check_hidden_objectives_equivalence.py \
        --smoke-tests ../self-other-prediction-smoke-tests [--write-fixture]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import types
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
FIXTURE = ROOT / "tests" / "golden" / "hidden_objectives_equivalence.json"


def sha(data) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def git_head(path: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                              capture_output=True, text=True,
                              timeout=30).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def load_harness(smoke: Path):
    """Import the harness modules against this repository's ledger core."""
    os.environ["LEDGER_SRC"] = str(SRC)
    sys.path.insert(0, str(SRC))
    import ledger  # noqa: F401  (bind the name to this repo before the harness)
    sys.path.insert(0, str(smoke / "ledger-experiments"))
    import ledger_v2_bridge as bridge
    from engine_v2 import generate_v2res, render_v2, rollout_v2, scenario_v2
    if Path(ledger.__file__).resolve().parent != (SRC / "ledger").resolve():
        raise SystemExit(f"ledger resolved to {ledger.__file__}, not {SRC}")
    return types.SimpleNamespace(bridge=bridge, gen=generate_v2res,
                                 render=render_v2, rollout=rollout_v2,
                                 scenario=scenario_v2)


def harness_bank(H, smoke: Path):
    """The studied bank exactly as the harness's campaign driver builds it."""
    g1 = json.loads((smoke / "config" / "ledger_v2_g1.json")
                    .read_text(encoding="utf-8"))
    it = g1["g1b"]["iterations"][str(g1["g1b"]["current_iteration"])]
    k = dict(g1["knobs"])
    k.update(it.get("knobs_override") or {})
    for key in ("kappa", "u", "dom_hi", "dom_mid", "n_chains", "chain_len"):
        k[key] = tuple(k[key])
    prof = H.gen.AdmissionProfile.from_dict(it["admission"])
    return (H.gen.build_bank(g1["g1b"]["n_scenarios"], H.gen.Knobs(**k),
                             profile=prof),
            H.gen.Knobs(**k), prof)


class Tally:
    def __init__(self):
        self.counts: dict[str, int] = {}

    def ok(self, key: str, cond: bool, detail: str = "") -> None:
        if not cond:
            raise AssertionError(f"MISMATCH [{key}] {detail}")
        self.counts[key] = self.counts.get(key, 0) + 1


def ev_tuple(e):
    return (e.tick, e.seat, e.action.name, e.action.args, e.truncated)


def harness_outcome(H, sv, opening, events, objectives):
    """The scoring in rollout_v2.run_episode, applied to a given event list
    with the harness's own scorer."""
    from ledger.core import fold as fold_mod
    st = fold_mod.initial_state(sv.base(opening))
    scored_state = None
    for ev in events:
        st = fold_mod.apply(st, ev)
        if ev.tick == sv.scored_turns:
            scored_state = st
    if scored_state is None:
        scored_state = st
    final = H.scenario.score_vector(sv, st)
    win = H.scenario.score_vector(sv, scored_state)
    return {"scores": final,
            "assigned_payoff": (final[objectives[0]][0],
                                final[objectives[1]][1]),
            "scored_window_scores": win,
            "scored_window_payoff": (win[objectives[0]][0],
                                     win[objectives[1]][1])}


def jsonable_outcome(o: dict) -> dict:
    return {"scores": {r: list(v) for r, v in o["scores"].items()},
            "assigned_payoff": list(o["assigned_payoff"]),
            "scored_window_scores": {r: list(v) for r, v in
                                     o["scored_window_scores"].items()},
            "scored_window_payoff": list(o["scored_window_payoff"])}


def compare_positions(H, P, T, sv_h, sv_p, opening, events, cap,
                      logged: dict | None = None):
    """Every tick of one episode, both implementations.  Returns the
    harness's acting and observer digests (for the fixture)."""
    from ledger.runtime.config import ModelSpec
    acting, observer = [], []
    spec = ModelSpec(slug="equivalence/none")
    for ev in events:
        tick = ev.tick
        st_h, pre_h = H.bridge.state_and_prefix(sv_h, opening, events, tick)
        st_p, pre_p = P.state_and_prefix(sv_p, opening, events, tick)
        T.ok("state", st_h == st_p, f"tick {tick}")
        T.ok("prefix", [ev_tuple(e) for e in pre_h]
             == [ev_tuple(e) for e in pre_p], f"tick {tick}")
        seat = st_h.mover
        for r in P.RESOURCES:
            bh, dh = H.render.render_prompt_v2(sv_h, st_h, pre_h, seat, r,
                                               message_cap=cap)
            bp, dp = P.render_prompt_v2(sv_p, st_p, pre_p, seat, r,
                                        message_cap=cap)
            T.ok("acting_prompt_bytes", bh == bp, f"tick {tick} {r}")
            _, dr = P.acting_prompt(sv_p, opening, events, tick, r,
                                    message_cap=cap)
            T.ok("acting_prompt_replay", dr == dh, f"tick {tick} {r}")
            acting.append(dh)
        T.ok("one_line_arms",
             H.render.arms_differ_in_one_line(sv_h, st_h, pre_h, seat)
             == P.arms_differ_in_one_line(sv_p, st_p, pre_p, seat))
        ob_h = H.bridge.redact_user_v2(sv_h, st_h, pre_h, seat)
        ob_p = P.observer_board(sv_p, st_p, seat)
        T.ok("observer_board", ob_h == ob_p, f"tick {tick}")
        observer.append(sha(ob_h))
        if logged is not None:
            obj = logged["objectives"][seat - 1]
            game = types.SimpleNamespace(state=st_h, events=list(pre_h),
                                         message_cap=cap)
            ah = H.bridge.ModelAgentV2(spec, None, sv_h, obj, message_cap=cap)
            ap = P.ModelAgentV2(spec, None, sv_p, obj)
            T.ok("agent_payload", ah._payload(game, seat)
                 == ap._payload(game, seat), f"tick {tick}")
            want = logged["digests"].get((tick, seat))
            if want:
                _, dp = P.render_prompt_v2(sv_p, st_p, pre_p, seat, obj,
                                           message_cap=cap)
                T.ok("logged_call_digest", want == {dp},
                     f"tick {tick}: logged {want} vs port {dp}")
    return acting, observer


def check_generator(H, P, T, smoke: Path):
    for seed in range(1, 301):
        for knobs_h, knobs_p in ((H.gen.Knobs(), P.Knobs()),):
            a, b = H.gen.generate(seed, knobs_h), P.generate(seed, knobs_p)
            T.ok("generate_default", (a is None and b is None)
                 or a.to_dict() == b.to_dict(), f"seed {seed}")
            if a is None:
                continue
            T.ok("admit_default", H.gen.admit(a) == P.admit(b), f"seed {seed}")
    bank_h, knobs_h, prof_h = harness_bank(H, smoke)
    T.ok("paper_knobs", knobs_h.digest() == P.PAPER_KNOBS.digest())
    T.ok("paper_profile", vars(prof_h) == vars(P.PAPER_PROFILE))
    bank_p = P.paper_bank()
    T.ok("paper_bank", [s.to_dict() for s in bank_h]
         == [s.to_dict() for s in bank_p])
    T.ok("paper_bank_file", [s.to_dict() for s in P.load_bank()]
         == [s.to_dict() for s in bank_h])
    for seed in range(1, 201):
        a = H.gen.generate(seed, knobs_h)
        b = P.generate(seed, P.PAPER_KNOBS)
        T.ok("generate_paper", (a is None and b is None)
             or a.to_dict() == b.to_dict(), f"seed {seed}")
        if a is not None:
            T.ok("admit_paper", H.gen.admit(a, profile=prof_h)
                 == P.admit(b, profile=P.PAPER_PROFILE), f"seed {seed}")
    for sv in bank_h:
        svp = P.ScenarioV2.from_dict(sv.to_dict())
        for cap in (40, 200):
            T.ok("system_block", H.render.system_block_v2(sv, message_cap=cap)
                 == P.system_block_v2(svp, message_cap=cap))
            T.ok("observer_system", H.bridge.predictor_system_v2(sv, cap)
                 == P.observer_system(svp, cap))
    return bank_h


def check_campaign(H, P, T, bank_h, episodes_dir: Path) -> dict:
    from ledger.runtime import assert_replays_as_played, played_events
    from ledger.runtime.log import read_records
    by_id = {s.scenario_id: s for s in bank_h}
    paths = sorted(episodes_dir.rglob("*.jsonl"))
    summary = {"episodes": 0, "ticks": 0, "truncated_messages": 0,
               "logged_digests_matched": 0}
    for path in paths:
        recs = read_records(path)
        meta = recs[0]
        sv_h = by_id[meta["scenario_id"]]
        sv_p = P.ScenarioV2.from_dict(sv_h.to_dict())
        opening, cap = meta["opening"], int(meta["message_cap"])
        ev_h = H.bridge.events_from_records(recs, cap)
        ev_p = played_events(recs, cap)
        T.ok("played_events", [ev_tuple(e) for e in ev_h]
             == [ev_tuple(e) for e in ev_p], path.name)
        rh = H.bridge.assert_replays_as_played(sv_h, opening, recs, cap)
        rp = assert_replays_as_played(sv_p.base(opening), recs, cap)
        T.ok("replays_as_played", rh == rp, path.name)
        objectives = (meta["seats"]["1"]["assigned_objective"],
                      meta["seats"]["2"]["assigned_objective"])
        digests: dict = {}
        for r in recs:
            if r.get("kind") == "call" and r.get("purpose") == "act":
                digests.setdefault((r["tick"], r["seat"]), set()).add(
                    r["digest"])
        before = T.counts.get("logged_call_digest", 0)
        compare_positions(H, P, T, sv_h, sv_p, opening, ev_p, cap,
                          logged={"objectives": objectives,
                                  "digests": digests})
        summary["logged_digests_matched"] += (
            T.counts.get("logged_call_digest", 0) - before)
        res = next((r for r in recs if r.get("kind") == "result"), None)
        if res is not None:
            from ledger.core import fold as fold_mod
            fin = fold_mod.fold(sv_p.base(opening), ev_p)
            T.ok("logged_result_pi", [fin.score(1), fin.score(2)]
                 == list(res["pi"]), path.name)
        T.ok("outcome", harness_outcome(H, sv_h, opening, ev_h, objectives)
             == {k: v for k, v in P.outcome(sv_p, opening, ev_p, objectives)
                 .items() if k != "objectives"}, path.name)
        summary["episodes"] += 1
        summary["ticks"] += len(ev_p)
        summary["truncated_messages"] += rp["truncated_messages"]
    return summary


def check_rollouts(H, P, T, bank_h) -> int:
    n = 0
    assignments = [(a, b) for a in P.RESOURCES for b in P.RESOURCES]
    for i, sv in enumerate(bank_h[:6]):
        for opening in (1, 2):
            objectives = assignments[(2 * i + opening) % len(assignments)]
            spec = H.rollout.EpisodeSpec(scenario=sv, opening=opening,
                                         objectives=objectives, tau=1.5,
                                         seed=i)
            res = H.rollout.run_episode(sv, spec)
            svp = P.ScenarioV2.from_dict(sv.to_dict())
            got = P.outcome(svp, opening, res.events, objectives)
            T.ok("rollout_outcome",
                 (got["scores"], got["assigned_payoff"],
                  got["scored_window_scores"], got["scored_window_payoff"])
                 == (res.final_scores, res.assigned_payoff,
                     res.scored_window_scores, res.scored_window_payoff),
                 spec.episode_id)
            compare_positions(H, P, T, sv, svp, opening, res.events, 40)
            n += 1
    return n


def scripted_episodes(P):
    """Deterministic scripted play on every bank scenario and seat order,
    plus one hand-written episode that exercises CHAT truncation."""
    from ledger.core.events import Action
    from ledger.game import Game
    from ledger.policies.scripted import POLICIES
    pairs = [("greedy-optimal", "tit-for-tat"),
             ("random-legal", "always-cooperate"),
             ("hold-up", "always-defect")]
    assignments = [(a, b) for a in P.RESOURCES for b in P.RESOURCES]
    out = []
    for i, sv in enumerate(P.load_bank()):
        for opening in (1, 2):
            p1, p2 = pairs[(2 * i + opening) % len(pairs)]
            g = Game(sv.base(opening), message_cap=40)
            pol = {1: POLICIES[p1](), 2: POLICIES[p2]()}
            while not g.over:
                g.play(pol[g.turn](g, g.turn))
            out.append({"scenario_id": sv.scenario_id, "opening": opening,
                        "policies": [p1, p2],
                        "objectives": list(assignments[(i + opening) % 9]),
                        "message_cap": 40, "events": g.events})
    sv = P.load_bank()[0]
    g = Game(sv.base(1), message_cap=40)
    long_text = ("I will fund job three if you take job five, and I can pay "
                 "on settlement; tell me which resource matters to you so we "
                 "can split the remaining pot fairly between us before the "
                 "late jobs open at turn twenty eight.")
    for a in (Action("CHAT", {"text": long_text}),
              Action("REFUSE", {"text": "no. " + long_text}),
              Action("WAIT"), Action("END"), Action("END")):
        g.play(a)
    out.append({"scenario_id": sv.scenario_id, "opening": 1,
                "policies": ["hand-written", "hand-written"],
                "objectives": ["standing", "cash"], "message_cap": 40,
                "events": g.events})
    return out


def check_scripted(H, P, T, bank_h) -> dict:
    by_id = {s.scenario_id: s for s in bank_h}
    fixture = []
    for ep in scripted_episodes(P):
        sv_h = by_id[ep["scenario_id"]]
        sv_p = P.ScenarioV2.from_dict(sv_h.to_dict())
        events = ep["events"]
        acting, observer = compare_positions(H, P, T, sv_h, sv_p,
                                             ep["opening"], events,
                                             ep["message_cap"])
        objectives = tuple(ep["objectives"])
        ho = harness_outcome(H, sv_h, ep["opening"], events, objectives)
        T.ok("scripted_outcome", ho == {
            k: v for k, v in P.outcome(sv_p, ep["opening"], events,
                                       objectives).items()
            if k != "objectives"})
        fixture.append({
            "scenario_id": ep["scenario_id"], "opening": ep["opening"],
            "policies": ep["policies"], "objectives": ep["objectives"],
            "message_cap": ep["message_cap"],
            "events": [[e.tick, e.seat, e.action.name, e.action.args,
                        e.truncated] for e in events],
            "acting_digests_sha256": sha("\n".join(acting)),
            "observer_board_digests_sha256": sha("\n".join(observer)),
            "n_prompts": len(acting),
            "outcome": jsonable_outcome(ho),
        })
    systems = {s.scenario_id: {
        "system_block_sha256": sha(H.render.system_block_v2(s, message_cap=40)),
        "observer_system_sha256": sha(H.bridge.predictor_system_v2(s, 40))}
        for s in bank_h}
    return {"episodes": fixture, "system_blocks": systems}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--smoke-tests", required=True, type=Path,
                    help="path to a self-other-prediction-smoke-tests checkout")
    ap.add_argument("--episodes", type=Path, default=None,
                    help="campaign episode logs (default: the S0 directory "
                         "inside the harness checkout, if present)")
    ap.add_argument("--write-fixture", action="store_true",
                    help=f"freeze the harness's digests to {FIXTURE.name}")
    args = ap.parse_args()
    smoke = args.smoke_tests.resolve()

    H = load_harness(smoke)
    import ledger.variants.hidden_objectives as P
    from ledger.render.tokens import tokenizer_name
    if tokenizer_name() != "o200k_base":
        raise SystemExit("tiktoken o200k_base is required: live play "
                         "truncated messages with it")
    T = Tally()

    bank_h = check_generator(H, P, T, smoke)
    print("generator, admission, bank, system blocks: OK")

    episodes_dir = args.episodes or (smoke / "ledger-experiments" / "runs"
                                     / "ledger_v2_campaign" / "s0"
                                     / "episodes")
    if episodes_dir.is_dir():
        summary = check_campaign(H, P, T, bank_h, episodes_dir)
        print(f"campaign logs: OK {summary}")
    else:
        print(f"campaign logs: SKIPPED ({episodes_dir} not found)")

    n = check_rollouts(H, P, T, bank_h)
    print(f"solver rollouts: OK ({n} episodes)")

    fx = check_scripted(H, P, T, bank_h)
    print(f"scripted episodes: OK ({len(fx['episodes'])} episodes)")

    print("checks passed, by kind:")
    for k in sorted(T.counts):
        print(f"  {k:24s} {T.counts[k]}")

    if args.write_fixture:
        payload = {
            "_note": ("Digests computed by the ORIGINAL research-harness "
                      "implementation (self-other-prediction-smoke-tests "
                      "ledger-experiments/engine_v2 and ledger_v2_bridge.py) "
                      "on these event lists. tests/test_hidden_objectives.py "
                      "recomputes them with ledger.variants.hidden_objectives. "
                      "Regenerate with "
                      "scripts/check_hidden_objectives_equivalence.py "
                      "--write-fixture."),
            "harness_commit": git_head(smoke),
            "ledger_commit_at_generation": git_head(ROOT),
            "tokenizer": tokenizer_name(),
            **fx,
        }
        FIXTURE.write_text(json.dumps(payload, indent=1, sort_keys=True,
                                      ensure_ascii=False) + "\n",
                           encoding="utf-8", newline="\n")
        print(f"wrote {FIXTURE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
