"""Check this repository against every Contracting surface of the report.

The report is "When can language models predict each other?" (final report,
version 4, 2026-09-03).  Its Contracting results come from the research
harness self-other-prediction-smoke-tests, which played and replayed LEDGER
from this repository.  This script reads that harness's logs, stores and
manifests read-only and checks that the code here reproduces them:

  bank      banks/v2-d0.json is the harness's bank_v2d0.json, byte for byte,
            and `load_bank("v2-d0")` gives its scenarios in both seat orders.
  default   every logged acting-call digest of the default-game runs on
            v2-d0 (q0_gate, q0_c3val, r1), re-rendered from the logs.
  phase3    every logged acting-call digest of the phase-3 free-play
            episodes, active arm (`acting_prompt`) and sham arm
            (`sham.sham_acting_prompt`), final attempt of each log.
  reader    forecaster prompts: the recorded prompt hashes of the
            ordinary-play panel and perspective manifests, the recorded
            digests of the phase-2 forecast store, the nine-forecaster
            extension store and the successor-bridge stores; recorded
            trace and summary sizes; and byte equality with the harness's own
            view builders where no hash was recorded.
  solver    the free-play goal-revealing census (every state, every field),
            the fixed-state gate rollouts and their belief-sensitivity rows,
            and the fixed-state position bank with its strata.
  fixtures  (only with --write-fixtures) computes, with the ORIGINAL code,
            the digests that tests/test_report_v4.py checks without the
            harness: scripted games on v2-d0 rendered by the engine at commit
            008de57, and the harness's sham, reader and solver code on
            scripted hidden-objectives games.

No model calls and no network.  Nothing is written outside this repository
except a temporary directory (copies of the harness's SQLite indexes, which
are opened read-only, and an extracted copy of the engine at 008de57).
Bytecode writing is disabled so the harness tree is not touched.  The
selection salt and the perspective sentence are read from the harness at run
time and never written anywhere.

    python scripts/check_report_equivalence.py --smoke-tests PATH \\
        [--only bank default phase3 reader solver] [--workers N] \\
        [--write-golden] [--write-fixtures]

--write-golden freezes the counts and per-episode digest-of-digests of the
sections run into tests/golden/report_v4_equivalence.json.  Needs tiktoken
with o200k_base, as live play did.
"""
from __future__ import annotations

import os

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

import argparse  # noqa: E402
import ast  # noqa: E402
import hashlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tarfile  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from concurrent.futures import ProcessPoolExecutor  # noqa: E402
from pathlib import Path  # noqa: E402

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

GOLDEN = ROOT / "tests" / "golden" / "report_v4_equivalence.json"
FIXTURES = ROOT / "tests" / "golden" / "report_v4_fixtures.json"
V2_D0_SHA256 = "a62d64f18755c737100c567e34062961bd980782afe29cec5eb60ddc6eba871f"
REPORT_ENGINE_COMMIT = "008de57"
FIXTURE_SALT = "fixture-salt"


def sha(data) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def sha_lines(items) -> str:
    """sha256 of the items joined by newlines: a digest of a digest list."""
    return sha("\n".join(items))


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def git_head(path: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                              capture_output=True, text=True,
                              timeout=30).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


class Tally:
    """Counts checks by kind; keeps going after a mismatch and reports the
    first few of each kind at the end."""

    def __init__(self):
        self.counts: Counter = Counter()
        self.bad: dict[str, list[str]] = defaultdict(list)

    def ok(self, key: str, cond: bool, detail: str = "") -> bool:
        if cond:
            self.counts[key] += 1
        else:
            self.bad[key].append(detail)
        return bool(cond)

    def report(self) -> int:
        print("checks passed, by kind:")
        for k in sorted(self.counts):
            print(f"  {k:40s} {self.counts[k]}")
        if self.bad:
            print("MISMATCHES:")
            for k, items in sorted(self.bad.items()):
                print(f"  {k}: {len(items)}")
                for d in items[:5]:
                    print(f"    {d}")
            return 1
        print("no mismatches")
        return 0


# ---------------------------------------------------------------------------
# harness data access, read-only
# ---------------------------------------------------------------------------

class Harness:
    """Paths into a self-other-prediction-smoke-tests checkout."""

    def __init__(self, root: Path, tmp: Path):
        self.root = root
        self.lx = root / "ledger-experiments"
        self.runs = self.lx / "runs"
        self.tmp = tmp
        self._salt = None

    def salt(self) -> str:
        if self._salt is None:
            path = self.lx / ".secrets" / "selection_salt.txt"
            self._salt = path.read_text(encoding="utf-8").strip()
        return self._salt

    def store_results(self, rel: str) -> dict[str, dict]:
        """COMMITTED rows of a harness RunStore, read from a copy of its
        index so the original is never opened."""
        src = self.root / rel
        dst = self.tmp / "stores" / rel.replace("/", "_")
        dst.mkdir(parents=True, exist_ok=True)
        for suffix in ("", "-wal", "-shm"):
            p = src / ("index.sqlite" + suffix)
            if p.exists():
                shutil.copy2(p, dst / p.name)
        con = sqlite3.connect(dst / "index.sqlite")
        try:
            rows = con.execute(
                "SELECT cell_id, result_json FROM cells "
                "WHERE status='COMMITTED' AND result_json IS NOT NULL"
            ).fetchall()
        finally:
            con.close()
        return {cid: json.loads(rj) for cid, rj in rows}

    def import_modules(self):
        """The harness's own modules, bound to THIS repository's ledger."""
        os.environ["LEDGER_SRC"] = str(SRC)
        import ledger  # noqa: F401  (bind the name before the harness)
        for p in (self.lx / "harness", self.lx):
            if str(p) not in sys.path:
                sys.path.insert(0, str(p))
        import forecast  # noqa: F401
        import ledger_v2_bridge  # noqa: F401
        import ledger_v2_sham  # noqa: F401
        import reason_view  # noqa: F401
        import views  # noqa: F401
        if Path(ledger.__file__).resolve().parent != (SRC / "ledger").resolve():
            raise SystemExit(f"ledger resolved to {ledger.__file__}, not {SRC}")
        return sys.modules


def final_segment(records: list[dict]) -> list[dict]:
    """The records after the last meta record: the played attempt of a log
    that was restarted.  Checked to be one clean play: ticks 1..n in order,
    closed by a result record."""
    last = max(i for i, r in enumerate(records) if r.get("kind") == "meta")
    seg = records[last:]
    ticks = [r["tick"] for r in seg if r.get("kind") == "event"]
    if ticks != list(range(1, len(ticks) + 1)):
        raise AssertionError("final segment ticks are not 1..n")
    if not any(r.get("kind") == "result" for r in seg):
        raise AssertionError("final segment has no result record")
    return seg


def act_calls(records: list[dict]) -> list[dict]:
    return [r for r in records
            if r.get("kind") == "call" and r.get("purpose") == "act"]


# ---------------------------------------------------------------------------
# bank
# ---------------------------------------------------------------------------

def check_bank(H: Harness, T: Tally) -> dict:
    from ledger.core.scenario import Scenario
    from ledger.scenarios.bank import BANKS_DIR, load_bank
    ours = (BANKS_DIR / "v2-d0.json").read_bytes()
    theirs = (H.runs / "divergence_audit" / "bank_v2d0.json").read_bytes()
    T.ok("bank_bytes", ours == theirs, "banks/v2-d0.json differs")
    T.ok("bank_sha256", sha(ours) == V2_D0_SHA256, sha(ours))
    raw = json.loads(theirs.decode("utf-8"))
    loaded = load_bank("v2-d0")
    T.ok("bank_templates", len(loaded) == 2 * len(raw))
    for i, d in enumerate(raw):
        sc = Scenario.from_dict(d)
        T.ok("bank_scenario", loaded[2 * i].to_dict() == sc.to_dict(), str(i))
        T.ok("bank_scenario_other_opening",
             loaded[2 * i + 1].to_dict() == sc.with_opening(2).to_dict(),
             str(i))
    return {"file": "banks/v2-d0.json", "sha256": sha(ours),
            "scenarios": len(raw), "templates": len(loaded),
            "generator_version": sorted({d["generator_version"] for d in raw})}


# ---------------------------------------------------------------------------
# default-game acting digests on v2-d0
# ---------------------------------------------------------------------------

DEFAULT_RUNS = ("q0_gate", "q0_c3val", "r1")


def default_episodes(H: Harness, run: str):
    """(path, records, meta, scenario, played events) per episode."""
    from ledger.runtime import read_records, played_events
    from ledger.scenarios.bank import load_bank
    by = {(s.scenario_id, s.opening): s for s in load_bank("v2-d0")}
    for p in sorted((H.runs / run / "episodes").glob("*.jsonl")):
        recs = read_records(p)
        meta = recs[0]
        sc = by[(meta["scenario_id"], meta["opening"])]
        yield p, recs, meta, sc, played_events(recs, int(meta["message_cap"]))


def check_default(H: Harness, T: Tally) -> dict:
    from ledger.render.render import render_prompt
    from ledger.runtime import assert_replays_as_played, state_at
    out = {}
    for run in DEFAULT_RUNS:
        per, metas = [], Counter()
        for p, recs, meta, sc, ev in default_episodes(H, run):
            cap = int(meta["message_cap"])
            T.ok("default_single_meta",
                 sum(1 for r in recs if r.get("kind") == "meta") == 1, p.name)
            metas[(meta.get("bank"), cap, meta.get("code_version"),
                   meta.get("mandate"))] += 1
            assert_replays_as_played(sc, recs, cap)
            T.ok("default_replays_as_played", True)
            logged = []
            for r in act_calls(recs):
                st = state_at(sc, ev, r["tick"])
                prefix = tuple(e for e in ev if e.tick < r["tick"])
                _, d = render_prompt(st, prefix, r["seat"],
                                     meta.get("mandate", "principal"), cap)
                T.ok(f"default_digest_{run}", d == r["digest"],
                     f"{p.stem} tick {r['tick']}")
                logged.append(r["digest"])
            per.append({"episode_id": p.stem, "calls": len(logged),
                        "digests_sha256": sha_lines(logged)})
        n = sum(e["calls"] for e in per)
        out[run] = {"episodes": len(per), "logged_digests": n,
                    "matched": T.counts[f"default_digest_{run}"],
                    "bank_cap_commit_mandate": [list(k) + [v] for k, v
                                                in sorted(metas.items())],
                    "per_episode": per}
        print(f"  {run}: {out[run]['matched']}/{n} digests over "
              f"{len(per)} episodes")
    return out


# ---------------------------------------------------------------------------
# phase-3 free play: active and sham arms
# ---------------------------------------------------------------------------

PHASE3_EPISODES = "data/outputs/phase3/ledger/s0/episodes"


def phase3_episodes(H: Harness, arm: str):
    """(eid, final segment records, meta, sv, opening, cap, played events)."""
    from ledger.runtime import read_records, played_events
    from ledger.variants import hidden_objectives as ho
    by = {s.scenario_id: s for s in ho.load_bank()}
    for p in sorted((H.root / PHASE3_EPISODES).glob(f"p3_{arm}_*.jsonl")):
        recs = read_records(p)
        seg = final_segment(recs)
        meta = seg[0]
        cap = int(meta["message_cap"])
        yield (p.stem, seg, meta, by[meta["scenario_id"]], int(meta["opening"]),
               cap, played_events(seg, cap), recs)


def check_phase3(H: Harness, T: Tally) -> dict:
    from ledger.runtime import assert_replays_as_played
    from ledger.variants import hidden_objectives as ho
    from ledger.variants.hidden_objectives import sham
    out = {}
    for arm in ("active", "sham"):
        per, restarted = [], 0
        for eid, seg, meta, sv, opening, cap, ev, recs in phase3_episodes(H, arm):
            restarted += sum(1 for r in recs if r.get("kind") == "meta") > 1
            assert_replays_as_played(sv.base(opening), seg, cap)
            T.ok("phase3_replays_as_played", True)
            seats = meta["seats"]
            logged = []
            for r in act_calls(seg):
                seat = str(r["seat"])
                if arm == "active":
                    obj = seats[seat]["assigned_objective"]
                    _, d = ho.acting_prompt(sv, opening, ev, r["tick"], obj,
                                            mandate=meta["mandate"],
                                            message_cap=cap)
                else:
                    T.ok("sham_meta", seats[seat]["kind"] == "model_v2_sham"
                         and seats[seat]["effective_objective"]
                         == sham.EFFECTIVE_OBJECTIVE
                         and seats[seat]["sham_offset"] == sham.SHAM_OFFSET
                         and seats[seat]["sham_scale"] == sham.SHAM_SCALE, eid)
                    _, d = sham.sham_acting_prompt(
                        sv, opening, ev, r["tick"],
                        seats[seat]["displayed_label"],
                        mandate=meta["mandate"], message_cap=cap)
                T.ok(f"phase3_digest_{arm}", d == r["digest"],
                     f"{eid} tick {r['tick']}")
                logged.append(r["digest"])
            per.append({"episode_id": eid, "calls": len(logged),
                        "digests_sha256": sha_lines(logged)})
        n = sum(e["calls"] for e in per)
        out[arm] = {"episodes": len(per), "restarted_logs": restarted,
                    "logged_digests": n,
                    "matched": T.counts[f"phase3_digest_{arm}"],
                    "per_episode": per}
        print(f"  phase-3 {arm}: {out[arm]['matched']}/{n} digests over "
              f"{len(per)} episodes ({restarted} restarted logs)")
    return out


# ---------------------------------------------------------------------------
# reader views
# ---------------------------------------------------------------------------

PANEL_MANIFEST = "docs/ordinary_prediction_panel/manifests/ledger.json"
SELF_SIM_MANIFEST = "docs/self_simulation_prediction/manifests/{}/manifests/ledger.json"
PHASE2 = "ledger-experiments/runs/ledger_v2_campaign"
EXTENSION_STORE = "data/outputs/predictor_extension/ledger/_store"
BRIDGE_STORES = {
    "successor_bridge_r2":
        "data/outputs/successor_bridge/ledger/_store_r2_reasoning_contract",
    "proj_r_own_policy":
        "data/outputs/successor_bridge/ledger/proj_r_ownpolicy/"
        "_store_proj_r_ownpolicy",
}
PANEL_VIEWS = {"situation": "L0", "full_record": "C-target"}
DEFAULT_GAME_CAP = 200     # the cap the v2-d0 episodes were played under


def _source_constant(path: Path, name: str, func: str | None = None):
    """A string constant from a harness source file, read with `ast`, never
    imported.  With `func`, the first assignment to `name` inside that
    function; for a `"..." + variable` expression, its constant prefix."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    scopes = [tree] if func is None else [
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == func]
    for scope in scopes:
        for node in ast.walk(scope):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == name):
                value = node.value
                if isinstance(value, ast.BinOp):
                    value = value.left
                return ast.literal_eval(value)
    raise KeyError(f"{name} not found in {path}")


def _append_sentence(messages: list[dict], sentence: str) -> list[dict]:
    """The perspective study's construction: one sentence appended to the
    user message.  The sentence itself is read from the harness."""
    out = json.loads(json.dumps(messages))
    out[-1]["content"] = out[-1]["content"].rstrip() + "\n\n" + sentence + "\n"
    return out


def _manifest_ok(T: Tally, man: dict, name: str) -> None:
    body = {k: v for k, v in man.items() if k != "manifest_sha256"}
    T.ok("manifest_sha256", sha(canonical(body)) == man["manifest_sha256"],
         name)


def q0_index(H: Harness) -> dict:
    return {p.stem: (sc, ev, recs, meta)
            for p, recs, meta, sc, ev in default_episodes(H, "q0_gate")}


def phase2_index(H: Harness) -> dict:
    """eid -> (sv, opening, played events, records, cap) for the phase-2 S0
    episodes, one log per episode."""
    from ledger.runtime import read_records, played_events
    from ledger.variants import hidden_objectives as ho
    by = {s.scenario_id: s for s in ho.load_bank()}
    out = {}
    for p in sorted((H.root / PHASE2 / "s0" / "episodes").rglob("*.jsonl")):
        recs = read_records(p)
        meta = recs[0]
        if p.stem in out:
            raise AssertionError(f"two logs for {p.stem}")
        cap = int(meta["message_cap"])
        out[p.stem] = (by[meta["scenario_id"]], int(meta["opening"]),
                       played_events(recs, cap), recs, cap)
    return out


def phase2_positions(s2_rows: dict) -> dict:
    """position_id -> (eid, tick, mover) from the phase-2 forecast store."""
    out = {}
    for r in s2_rows.values():
        key = (r["eid"], int(r["tick"]), int(r["mover"]))
        if out.setdefault(r["position_id"], key) != key:
            raise AssertionError(f"position {r['position_id']} is ambiguous")
    return out


def check_reader(H: Harness, T: Tally) -> dict:
    from ledger.reader import prompt_sha256, view_messages
    from ledger.reader import views as RV
    from ledger.variants import hidden_objectives as ho
    from ledger.variants.hidden_objectives import reader as HR
    out = {}
    salt = H.salt()
    q0 = q0_index(H)

    # -- the ordinary-play panel and the perspective study, ordinary arm ----
    def panel_messages(position_id: str, frozen_view: str):
        eid, t = position_id.split(":t")
        sc, ev, _recs, _meta = q0[eid]
        return view_messages(sc, ev, int(t), frozen_view, salt=salt,
                             episode_id=eid, message_cap=DEFAULT_GAME_CAP)

    man = json.loads((H.root / PANEL_MANIFEST).read_text(encoding="utf-8"))
    _manifest_ok(T, man, "panel")
    T.ok("selection_salt_sha256",
         sha(salt) == man["source"]["salt_sha256"], "salt file differs")
    cache = {}
    for cell in man["cells"]:
        key = (cell["position_id"], cell["view"])
        if key not in cache:
            cache[key] = prompt_sha256(panel_messages(
                cell["position_id"], PANEL_VIEWS[cell["view"]]))
        T.ok("panel_prompt_sha256", cache[key] == cell["prompt_sha256"],
             str(key))
    out["ordinary_panel"] = {
        "manifest": PANEL_MANIFEST, "cells": len(man["cells"]),
        "matched": T.counts["panel_prompt_sha256"],
        "distinct_prompts": len(cache),
        "views": dict(PANEL_VIEWS),
        "prompt_sha256_list_sha256": sha_lines(sorted(set(cache.values())))}
    print(f"  ordinary panel: {out['ordinary_panel']['matched']}/"
          f"{len(man['cells'])} cells")

    sentence = _source_constant(
        H.root / "scripts" / "self_simulation_prediction.py", "IMAGINE")
    man = json.loads((H.root / SELF_SIM_MANIFEST.format("ordinary"))
                     .read_text(encoding="utf-8"))
    _manifest_ok(T, man, "perspective ordinary")
    cache = {}
    for cell in man["cells"]:
        key = (cell["position_id"], cell["view"])
        if key not in cache:
            msgs = panel_messages(cell["position_id"], "C-target")
            if cell["view"] != "standard":
                msgs = _append_sentence(msgs, sentence)
            cache[key] = prompt_sha256(msgs)
        T.ok(f"perspective_ordinary_{cell['view']}",
             cache[key] == cell["prompt_sha256"], str(key))
    out["perspective_ordinary"] = {
        "manifest": SELF_SIM_MANIFEST.format("ordinary"),
        "cells": len(man["cells"]),
        "matched": {v: T.counts[f"perspective_ordinary_{v}"]
                    for v in sorted({c["view"] for c in man["cells"]})},
        "note": "standard = C-target; the other view appends the study's "
                "perspective sentence, read from the harness at check time"}
    print(f"  perspective, ordinary: {out['perspective_ordinary']['matched']}")

    # -- the hidden-objectives variant ---------------------------------------
    p2 = phase2_index(H)
    s2 = H.store_results(f"{PHASE2}/s2/_store")
    pos = phase2_positions(s2)

    def v2_messages(eid: str, tick: int, view: str, trace=None):
        sv, opening, ev, _recs, cap = p2[eid]
        return HR.view_messages_v2(sv, opening, ev, tick, view, salt=salt,
                                   episode_id=eid, message_cap=cap,
                                   trace=trace)

    def v2_trace(eid: str, tick: int, mover: int) -> str:
        sv, _opening, _ev, recs, _cap = p2[eid]
        return HR.trace_text_v2(sv, recs, tick, mover, redacted=True)

    def msg_digest(msgs) -> str:
        return RV.digest(msgs[0]["content"], msgs[1]["content"])

    for r in s2.values():
        trace = None
        if r["view"] == "trace":
            trace = v2_trace(r["eid"], int(r["tick"]), int(r["mover"]))
            T.ok("phase2_trace_chars", len(trace) == r["trace_chars"],
                 f"{r['eid']} t{r['tick']}")
            if not trace:
                continue
        d = msg_digest(v2_messages(r["eid"], int(r["tick"]), r["view"], trace))
        T.ok(f"phase2_forecast_digest_{r['view']}", d == r["digest"],
             f"{r['eid']} t{r['tick']} {r['view']}")
    by_view = Counter(r["view"] for r in s2.values())
    out["phase2_forecast_store"] = {
        "store": f"{PHASE2}/s2/_store", "cells": len(s2),
        "positions": len(pos),
        "matched": {v: T.counts[f"phase2_forecast_digest_{v}"]
                    for v in sorted(by_view)},
        "cells_by_view": dict(sorted(by_view.items())),
        "trace_chars_matched": T.counts["phase2_trace_chars"],
        "digests_sha256": sha_lines(sorted({r["digest"]
                                            for r in s2.values()}))}
    print(f"  phase-2 forecast store: "
          f"{out['phase2_forecast_store']['matched']}")

    man = json.loads((H.root / SELF_SIM_MANIFEST.format("goal"))
                     .read_text(encoding="utf-8"))
    _manifest_ok(T, man, "perspective goal")
    cache = {}
    for cell in man["cells"]:
        key = (cell["position_id"], cell["view"])
        if key not in cache:
            eid, tick, _m = pos[cell["position_id"]]
            T.ok("perspective_goal_episode", eid == cell["episode_id"],
                 cell["position_id"])
            msgs = v2_messages(eid, tick, "ordered")
            if cell["view"] != "standard":
                msgs = _append_sentence(msgs, sentence)
            cache[key] = prompt_sha256(msgs)
        T.ok(f"perspective_goal_{cell['view']}",
             cache[key] == cell["prompt_sha256"], str(key))
    out["perspective_goal"] = {
        "manifest": SELF_SIM_MANIFEST.format("goal"),
        "cells": len(man["cells"]),
        "matched": {v: T.counts[f"perspective_goal_{v}"]
                    for v in sorted({c["view"] for c in man["cells"]})},
        "note": "standard = the variant's ordered view"}
    print(f"  perspective, goal: {out['perspective_goal']['matched']}")

    ext = H.store_results(EXTENSION_STORE)
    ladder = [r for r in ext.values() if r.get("kind") == "ladder"]
    for r in ladder:
        eid, tick, _m = pos[r["position_id"]]
        d = msg_digest(v2_messages(eid, tick, r["arm"]))
        T.ok(f"extension_digest_{r['arm']}", d == r["prompt_digest"],
             f"{r['position_id']} {r['arm']}")
        if r.get("frozen_digest"):
            T.ok("extension_frozen_digest", d == r["frozen_digest"],
                 f"{r['position_id']} {r['arm']}")
    arms = Counter(r["arm"] for r in ladder)
    out["predictor_extension_store"] = {
        "store": EXTENSION_STORE, "ladder_cells": len(ladder),
        "cells_by_arm": dict(sorted(arms.items())),
        "matched": {a: T.counts[f"extension_digest_{a}"] for a in sorted(arms)},
        "frozen_digest_matched": T.counts["extension_frozen_digest"]}
    print(f"  predictor extension: "
          f"{out['predictor_extension_store']['matched']}")

    for name, rel in BRIDGE_STORES.items():
        rows = H.store_results(rel)
        for r in rows.values():
            eid, tick, _mover = pos[r["position_id"]]
            T.ok("bridge_episode", eid == r["cluster"], r["cell_id"])
            sv, opening, ev, _recs, cap = p2[eid]
            _, d = ho.acting_prompt(sv, opening, ev, tick, r["truth"],
                                    message_cap=cap)
            T.ok(f"bridge_digest_{name}", d == r["prompt_digest"], r["cell_id"])
            T.ok("bridge_played_anchor",
                 d == r["frozen_anchors"].get("played"), r["cell_id"])
        out[name] = {"store": rel, "cells": len(rows),
                     "matched": T.counts[f"bridge_digest_{name}"]}
        print(f"  {name}: {out[name]['matched']}/{len(rows)} acting digests")

    out.update(check_reader_against_harness(H, T, q0, p2, salt))
    return out


def _capture_collect(forecast_mod, sc, events, tick, view, salt, eid, extra):
    """The messages the harness's forecast collector would send, captured
    with a client that answers WAIT and never touches a network."""
    from ledger.runtime import CallResult, ModelSpec
    seen = []

    class Capture:
        def chat(self, spec, messages, tools=None):
            seen.append(messages)
            raw = {"choices": [{"finish_reason": "stop", "message": {
                "role": "assistant", "content": None,
                "tool_calls": [{"id": "c1", "type": "function", "function": {
                    "name": "wait", "arguments": "{}"}}]}}]}
            return CallResult(raw=raw, provider="none", model=spec.slug,
                              usage={}, cost_usd=0.0, latency_s=0.0,
                              attempts=1)

    forecast_mod.collect_forecast(
        Capture(), ModelSpec(slug="equivalence/none"), sc, events, tick,
        view=view, m=1, salt=salt, episode_id=eid,
        message_cap=DEFAULT_GAME_CAP, extra_user_block=extra)
    return seen[0]


def check_reader_against_harness(H, T, q0, p2, salt) -> dict:
    """Byte equality with the harness's own builders where the runs recorded
    no prompt hash (E1, the reasoning studies, the summaries, the
    goal-naming probe), plus the trace and summary sizes they did record."""
    mods = H.import_modules()
    hviews, hreason = mods["views"], mods["reason_view"]
    hforecast, BR = mods["forecast"], mods["ledger_v2_bridge"]
    from ledger.reader import (SUMMARY_HEADER, build_view, summary_block,
                               trace_text, view_messages)
    from ledger.runtime import read_records, played_events
    from ledger.scenarios.bank import load_bank
    from ledger.variants.hidden_objectives import reader as HR
    out = {}

    # E1: all four default-game views at the 64 frozen moments
    sel = json.loads((H.runs / "e1" / "selection64.json")
                     .read_text(encoding="utf-8"))["moments"]
    for m in sel:
        sc, ev, _recs, _meta = q0[m["eid"]]
        for view in ("L0", "C-count", "C-target", "C-shuf"):
            ours = build_view(sc, ev, m["tick"], view, salt=salt,
                              episode_id=m["eid"],
                              message_cap=DEFAULT_GAME_CAP)
            theirs = hviews.build_view(sc, ev, m["tick"], view, salt=salt,
                                       episode_id=m["eid"],
                                       message_cap=DEFAULT_GAME_CAP)
            T.ok(f"e1_view_{view}", ours == theirs, f"{m['eid']} {m['tick']}")
    out["e1_views"] = {"moments": len(sel),
                       "matched_harness": {
                           v: T.counts[f"e1_view_{v}"]
                           for v in ("L0", "C-count", "C-target", "C-shuf")}}

    # the reasoning study on the same 64 moments: recorded trace sizes
    for arm in ("redacted", "full"):
        sizes = {}
        for f in sorted((H.runs / "reasoning" / arm).glob("*.json")):
            r = json.loads(f.read_text(encoding="utf-8"))
            sizes.setdefault((r["eid"], int(r["tick"])), set()).add(
                r["trace_chars"])
        for m in sel:
            sc, ev, recs, _meta = q0[m["eid"]]
            seat = next(e.seat for e in ev if e.tick == m["tick"])
            ours = trace_text(sc, recs, m["tick"], seat,
                              redacted=(arm == "redacted"))
            path = H.runs / "q0_gate" / "episodes" / f"{m['eid']}.jsonl"
            theirs = hreason.trace_text(sc, path, m["tick"], seat,
                                        redacted=(arm == "redacted"))
            T.ok(f"reasoning_trace_{arm}", ours == theirs,
                 f"{m['eid']} {m['tick']}")
            if (m["eid"], m["tick"]) in sizes:
                T.ok(f"reasoning_trace_chars_{arm}",
                     sizes[(m["eid"], m["tick"])] == {len(ours)},
                     f"{m['eid']} {m['tick']}")
    out["reasoning_traces"] = {
        "moments": len(sel),
        "matched_harness": {a: T.counts[f"reasoning_trace_{a}"]
                            for a in ("redacted", "full")},
        "recorded_sizes_matched": {a: T.counts[f"reasoning_trace_chars_{a}"]
                                   for a in ("redacted", "full")}}

    # R1: the three views on 12 new episodes, captured from the harness's
    # forecast collector; recorded trace sizes per view file
    by = {(s.scenario_id, s.opening): s for s in load_bank("v2-d0")}
    r1 = {}
    for p in sorted((H.runs / "r1" / "episodes").glob("*.jsonl")):
        recs = read_records(p)
        meta = recs[0]
        r1[p.stem] = (by[(meta["scenario_id"], meta["opening"])],
                      played_events(recs, int(meta["message_cap"])), recs, p)
    recorded = defaultdict(set)
    for f in (H.runs / "r1" / "views").glob("*.json"):
        r = json.loads(f.read_text(encoding="utf-8"))
        recorded[(r["eid"], int(r["tick"]), r["view"])].add(r["trace_chars"])
    moments = json.loads((H.runs / "r1" / "selection.json")
                         .read_text(encoding="utf-8"))["moments"]
    for m in moments:
        sc, ev, recs, path = r1[m["eid"]]
        seat = next(e.seat for e in ev if e.tick == m["tick"])
        for view in ("C-target", "R-redacted", "R-full"):
            extra = None
            if view != "C-target":
                extra = trace_text(sc, recs, m["tick"], seat,
                                   redacted=(view == "R-redacted"))
                T.ok("r1_trace_harness", extra == hreason.trace_text(
                    sc, path, m["tick"], seat,
                    redacted=(view == "R-redacted")), f"{m['eid']} {view}")
                if not extra:
                    T.ok("r1_empty_trace_not_collected",
                         (m["eid"], m["tick"], view) not in recorded)
                    continue
            ours = view_messages(sc, ev, m["tick"], "C-target", salt=salt,
                                 episode_id=m["eid"],
                                 message_cap=DEFAULT_GAME_CAP,
                                 extra_user_block=extra)
            theirs = _capture_collect(hforecast, sc, ev, m["tick"],
                                      "C-target", salt, m["eid"], extra)
            T.ok(f"r1_messages_{view}", ours == theirs, f"{m['eid']} {view}")
            key = (m["eid"], m["tick"], view)
            if key in recorded:
                T.ok(f"r1_trace_chars_{view}",
                     recorded[key] == {len(extra) if extra else 0}, str(key))
    out["r1_views"] = {
        "moments": len(moments),
        "matched_harness": {v: T.counts[f"r1_messages_{v}"]
                            for v in ("C-target", "R-redacted", "R-full")},
        "recorded_sizes_matched": {v: T.counts[f"r1_trace_chars_{v}"]
                                   for v in ("C-target", "R-redacted",
                                             "R-full")},
        "view_files": sum(1 for _ in (H.runs / "r1" / "views").glob("*.json"))}

    # S1: the summary block.  The harness builds it inline, so its header is
    # read from the source; the full message is captured from the harness's
    # collector; the recorded summary sizes are checked.
    header = _source_constant(H.lx / "run_s1.py", "block", "one")
    T.ok("s1_header_from_source", header == SUMMARY_HEADER, repr(header))
    summaries = json.loads((H.runs / "s1" / "summaries.json")
                           .read_text(encoding="utf-8"))
    view_files = {}
    for f in (H.runs / "s1" / "views").glob("*.json"):
        r = json.loads(f.read_text(encoding="utf-8"))
        view_files.setdefault((r["eid"], int(r["tick"])), set()).add(
            r["summary_chars"])
    for key, rec in sorted(summaries.items()):
        if not rec["summary"]:
            continue
        sc, ev, _recs, _p = r1[rec["eid"]]
        block = summary_block(rec["summary"])
        ours = view_messages(sc, ev, rec["tick"], "C-target", salt=salt,
                             episode_id=rec["eid"],
                             message_cap=DEFAULT_GAME_CAP,
                             extra_user_block=block)
        theirs = _capture_collect(hforecast, sc, ev, rec["tick"], "C-target",
                                  salt, rec["eid"], block)
        T.ok("s1_messages", ours == theirs, key)
        if (rec["eid"], rec["tick"]) in view_files:
            T.ok("s1_summary_chars", view_files[(rec["eid"], rec["tick"])]
                 == {len(rec["summary"])}, key)
    out["s1_summaries"] = {"summaries": len(summaries),
                           "matched_harness": T.counts["s1_messages"],
                           "recorded_sizes_matched":
                               T.counts["s1_summary_chars"]}

    # the goal-naming probe at the phase-2 positions
    s3 = H.store_results(f"{PHASE2}/s3/_store")
    done = set()
    for r in s3.values():
        key = (r["eid"], int(r["tick"]), r["view"])
        if key in done:
            continue
        done.add(key)
        sv, opening, ev, _recs, cap = p2[r["eid"]]
        st, prefix = HR.state_and_prefix(sv, opening, ev, int(r["tick"]))
        ours = HR.objective_probe_messages(sv, st, prefix, r["view"],
                                           salt=salt, episode_id=r["eid"],
                                           message_cap=cap)
        theirs = BR.objective_probe_messages(sv, st, prefix, r["view"],
                                             salt=salt, episode_id=r["eid"],
                                             message_cap=cap)
        T.ok("probe_messages", ours == theirs, str(key))
    out["goal_naming_probe"] = {"store_cells": len(s3),
                                "distinct_prompts": len(done),
                                "matched_harness": T.counts["probe_messages"],
                                "note": "the store records no prompt hash"}
    print(f"  harness byte equality: E1 {out['e1_views']['matched_harness']}, "
          f"reasoning {out['reasoning_traces']['matched_harness']}, "
          f"R1 {out['r1_views']['matched_harness']}, "
          f"S1 {out['s1_summaries']['matched_harness']}, "
          f"probe {out['goal_naming_probe']['matched_harness']}")
    return out


# ---------------------------------------------------------------------------
# the exact value calculation
# ---------------------------------------------------------------------------

CENSUS = "data/outputs/phase3/ledger/ledger_freerun_divergence_2026-08-24.json"
G1B_RUN = "ledger-experiments/runs/ledger_v2_iter3"
G1A_POSITIONS = "ledger-experiments/runs/ledger_v2_g1a_iter3/positions.json"
G1_CONFIG = "config/ledger_v2_g1.json"


def _events_json(events) -> list:
    return [[e.tick, e.seat, e.action.name, e.action.args, e.truncated]
            for e in events]


def _events_from_json(rows) -> list:
    from ledger.core.events import Action, Event
    return [Event(t, s, Action(n, a), truncated=tr) for t, s, n, a, tr in rows]


def _census_worker(args) -> list[dict]:
    """Classify every listed state of one episode (runs in a worker)."""
    from ledger.variants.hidden_objectives import ScenarioV2
    from ledger.variants.hidden_objectives import solver as SV
    from ledger.variants.hidden_objectives.play import state_and_prefix
    sv_dict, opening, events, wanted, eps = args
    sv = ScenarioV2.from_dict(sv_dict)
    events = _events_from_json(events)
    out = []
    for pos, tick in wanted:
        row = {"pos": pos}
        st, _prefix = state_and_prefix(sv, opening, events, tick)
        try:
            r = (None if st.over or st.tick != tick
                 else SV.own_objective_tables(sv, st, pruned=True))
        except SV.SpecBudgetExceeded as exc:
            out.append({**row, "kind": "refused_over_derived_bound",
                        "why": str(exc)[:300]})
            continue
        if r is None:
            out.append({**row, "kind": "declined"})
            continue
        out.append({**row, "kind": "classified",
                    **SV.classify_tables(r["tables"], eps)})
    return out


def _rollout_worker(args) -> tuple[dict, list[dict]]:
    """One fixed-state gate episode: its ledger and its scored-window rows,
    in the gate's row format (runs in a worker)."""
    from ledger.variants.hidden_objectives import ScenarioV2
    from ledger.variants.hidden_objectives import rollout as R
    from ledger.variants.hidden_objectives import solver as SV
    sv_dict, opening, objectives, tau, seed = args
    sv = ScenarioV2.from_dict(sv_dict)
    spec = R.EpisodeSpec(scenario=sv, opening=opening,
                         objectives=tuple(objectives), tau=tau, seed=seed)
    res = R.run_episode(sv, spec)
    rows = []
    for p in res.positions:
        if p.tick > sv.scored_turns:
            continue
        cert = SV.certify_row(p.per_belief)
        rows.append({
            "episode_id": p.episode_id, "scenario_id": sv.scenario_id,
            "opening": opening, "tick": p.tick, "mover": p.mover,
            "mover_objective": p.mover_objective,
            "partner_objective_truth": p.partner_objective_truth,
            "n_completions": p.n_completions,
            "exposure_live": p.exposure_live,
            "chosen_class": p.chosen_class,
            "families": cert["families"],
            "action_level": cert["action_level"]})
    return R.episode_ledger(spec, res), rows


def _stratify_worker(args) -> list[dict]:
    """The fixed-state stratifier on every scored turn of one gate ledger,
    unpruned, in the position bank's row format (runs in a worker)."""
    from ledger.analysis.omega2 import legal_omega2_alphabet
    from ledger.variants.hidden_objectives import ScenarioV2
    from ledger.variants.hidden_objectives import solver as SV
    from ledger.variants.hidden_objectives.play import state_and_prefix
    sv_dict, led = args
    sv = ScenarioV2.from_dict(sv_dict)
    events = _events_from_json([[r["tick"], r["seat"], r["action"]["name"],
                                 r["action"]["args"], False]
                                for r in led["events"]])
    out = []
    for tick in range(1, sv.scored_turns + 1):
        st, _prefix = state_and_prefix(sv, led["opening"], events, tick)
        if st.over or st.tick != tick:
            continue
        r = SV.own_objective_tables(sv, st)
        if r is None:
            continue
        out.append({"episode_id": led["episode_id"],
                    "scenario_id": led["scenario_id"],
                    "opening": led["opening"], "tick": tick,
                    "mover": st.mover,
                    "partner_objective_truth":
                        led["objectives"][2 - st.mover],
                    "solver_best_by_arm": r["bests"],
                    "stratum": r["stratum"],
                    "legal_alphabet_size":
                        len(legal_omega2_alphabet(st, st.mover))})
    return out


def _spread(rows: list[dict], n: int) -> list[dict]:
    """The position bank's even, deterministic thinning."""
    if len(rows) <= n:
        return list(rows)
    step = len(rows) / n
    return [rows[int(i * step)] for i in range(n)]


def _share(num: int, den: int):
    return round(num / den, 4) if den else None


def _gate_summary(rows: list[dict], fam: str) -> dict:
    """The fixed-state gate's per-family counts and shares."""
    q = [r for r in rows if r["families"][fam]["qualifies"]]
    diff = [r for r in q if r["families"][fam]["differs"]]
    nocom = [r for r in q if r["families"][fam]["no_common_eps_optimum"]]
    return {
        "positions_total": len(rows),
        "positions_qualifying": len(q),
        "positions_single_class": len(rows) - len(q),
        "positions_where_the_optimum_differs": len(diff),
        "belief_sensitivity_share": _share(len(diff), len(q)),
        "no_common_eps_optimum_share": _share(len(nocom), len(q)),
        "belief_robust_hedge_share": _share(len(q) - len(nocom), len(q)),
        "hedge_share_where_the_optimum_differs": _share(
            len(diff) - len([r for r in diff if r["families"][fam]
                             ["no_common_eps_optimum"]]), len(diff)),
    }


def check_solver(H: Harness, T: Tally, workers: int) -> dict:
    from ledger.variants import hidden_objectives as ho
    from ledger.variants.hidden_objectives import solver as SV
    out = {}
    bank = {s.scenario_id: s for s in ho.load_bank()}

    # -- the free-play census (Figure 12) ------------------------------------
    census = json.loads((H.root / CENSUS).read_text(encoding="utf-8"))
    eps = census["definitions"]["eps_points"]
    T.ok("census_eps", eps == SV.EPS_DEFAULT)
    want = {r["pos"]: r for r in census["per_state"]}
    wanted = defaultdict(list)
    for p in want:
        eid, t = p.rsplit("@", 1)
        wanted[eid].append((p, int(t)))
    tasks = []
    for arm in ("active", "sham"):
        for eid, seg, meta, sv, opening, cap, ev, _r in phase3_episodes(H, arm):
            if eid in wanted:
                sv_dict, events = sv.to_dict(), _events_json(ev)
                for item in sorted(wanted.pop(eid), key=lambda x: x[1]):
                    tasks.append((sv_dict, opening, events, [item], eps))
    T.ok("census_episodes_found", not wanted, str(sorted(wanted)[:3]))
    t = time.time()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        got = [row for rows in ex.map(_census_worker, tasks) for row in rows]
    print(f"  census: {len(got)} states solved in {time.time() - t:.0f} s")
    fields = ("kind", "flip", "stratum", "best_by_arm", "hedge_margin",
              "hedged", "hedge_classes")
    ours = {}
    for row in got:
        w = want[row["pos"]]
        ours[row["pos"]] = {**row, "arm": w["arm"]}
        T.ok("census_state", all(row.get(k) == w.get(k) for k in fields),
             f"{row['pos']}: ours {[row.get(k) for k in fields[:3]]} "
             f"recorded {[w.get(k) for k in fields[:3]]}")
    summaries = {}
    for arm in ("active", "sham"):
        rows = [r for r in ours.values() if r["arm"] == arm]
        cl = [r for r in rows if r["kind"] == "classified"]
        flips = [r for r in cl if r["flip"]]
        hedged = [r for r in flips if r["hedged"]]
        s = {"states": len(rows), "classified": len(cl),
             "declined": sorted(r["pos"] for r in rows
                                if r["kind"] == "declined"),
             "flip": len(flips), "hedged_among_flips": len(hedged),
             "no_hedge_flips": len(flips) - len(hedged),
             "flat": len(cl) - len(flips)}
        rec = census["states"][arm]
        T.ok("census_summary", (s["states"], s["classified"], s["flip"],
                                s["hedged_among_flips"], s["no_hedge_flips"],
                                s["declined"])
             == (rec["states"], rec["classified"], rec["flip"],
                 rec["hedged_among_flips"], rec["no_hedge_flips"],
                 sorted(rec["declined_by_the_stratifiers_own_rule"])), arm)
        summaries[arm] = s
    out["goal_revealing_census"] = {
        "artifact": CENSUS, "eps_points": eps,
        "states_matched": T.counts["census_state"],
        "states": len(want), "by_arm": summaries,
        "per_state_sha256": sha(canonical(sorted(
            ([r["pos"], r["kind"], r.get("flip"), r.get("hedged"),
              r.get("hedge_margin")] for r in ours.values()),
            key=lambda x: x[0])))}
    a = summaries["active"]
    print(f"  census active: {a['classified']} classified = "
          f"{a['no_hedge_flips']} no-hedge flips + {a['hedged_among_flips']} "
          f"hedged flips + {a['flat']} flat; "
          f"{T.counts['census_state']}/{len(want)} states match")

    # -- the fixed-state gate rollouts (G1b, iteration 3) ---------------------
    cfg = json.loads((H.root / G1_CONFIG).read_text(encoding="utf-8"))["g1b"]
    from ledger.variants.hidden_objectives import rollout as R
    grid = R.gate_grid(ho.load_bank(), openings=tuple(cfg["openings"]),
                       tau=cfg["tau"])
    tasks = [(s.scenario.to_dict(), s.opening, list(s.objectives), s.tau,
              s.seed) for s in grid]
    t = time.time()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        got = list(ex.map(_rollout_worker, tasks))
    print(f"  gate rollouts: {len(got)} episodes in {time.time() - t:.0f} s")
    run = H.root / G1B_RUN
    stored_rows = {(r["episode_id"], r["tick"]): r for r in json.loads(
        (run / "g1b_positions.json").read_text(encoding="utf-8"))}
    rows = []
    for led, ep_rows in got:
        stored = json.loads((run / "episodes" / f"{led['episode_id']}.json")
                            .read_text(encoding="utf-8"))
        T.ok("gate_episode_ledger", led == stored, led["episode_id"])
        for r in ep_rows:
            T.ok("gate_position_row",
                 r == stored_rows.get((r["episode_id"], r["tick"])),
                 f"{r['episode_id']} t{r['tick']}")
        rows.extend(ep_rows)
    T.ok("gate_position_count", len(rows) == len(stored_rows))
    report = json.loads((run / "g1b_report.json").read_text(encoding="utf-8"))
    fams = {}
    for fam in SV.FAMILIES:
        s = _gate_summary(rows, fam)
        rec = report["families"][fam]
        T.ok("gate_family_summary", all(rec[k] == v for k, v in s.items()),
             f"{fam}: {s} vs {[rec[k] for k in s]}")
        fams[fam] = s
    head = fams["best_response"]
    out["fixed_state_gate_rollouts"] = {
        "run": G1B_RUN, "episodes": len(got),
        "ledgers_matched": T.counts["gate_episode_ledger"],
        "rows": len(rows), "rows_matched": T.counts["gate_position_row"],
        "families": fams}
    print(f"  gate: {head['positions_where_the_optimum_differs']}/"
          f"{head['positions_qualifying']} qualifying positions differ; "
          f"{T.counts['gate_position_row']}/{len(stored_rows)} rows match")

    # -- the fixed-state position bank (G1a) ----------------------------------
    g1a = json.loads((H.root / "config" / "ledger_v2_g1.json")
                     .read_text(encoding="utf-8"))["g1a"]
    tasks = [(bank[led["scenario_id"]].to_dict(), led) for led, _r in got]
    t = time.time()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        cands = [row for rows in ex.map(_stratify_worker, tasks)
                 for row in rows]
    print(f"  position bank: {len(cands)} candidates stratified in "
          f"{time.time() - t:.0f} s")
    cands.sort(key=lambda r: (r["episode_id"], r["tick"]))
    n = g1a["n_positions"]
    n_div = (n * 2) // 3
    picked = _spread([c for c in cands if c["stratum"] == "divergent"], n_div)
    picked += _spread([c for c in cands if c["stratum"] == "flat"], n - n_div)
    picked.sort(key=lambda r: (r["episode_id"], r["tick"]))
    for i, p in enumerate(picked):
        p["position_id"] = f"p{i:02d}"
        p["short"] = f"{p['episode_id']}_t{p['tick']}"
    stored = json.loads((H.root / G1A_POSITIONS).read_text(encoding="utf-8"))
    T.ok("position_bank", picked == stored,
         f"{len(picked)} rebuilt vs {len(stored)} stored")
    out["fixed_state_position_bank"] = {
        "positions": G1A_POSITIONS, "candidates": len(cands),
        "divergent_candidates": sum(c["stratum"] == "divergent"
                                    for c in cands),
        "picked": len(picked),
        "divergent_picked": sum(p["stratum"] == "divergent" for p in picked),
        "identical_to_stored": picked == stored,
        "note": ("the bank's states and strata; the 0.2445-bit corrected "
                 "divergence is computed from model draws at these states "
                 "and is not recomputed here")}
    print(f"  position bank: {len(picked)} positions, "
          f"{out['fixed_state_position_bank']['divergent_picked']} divergent, "
          f"identical {picked == stored}")
    return out


# ---------------------------------------------------------------------------
# fixtures for tests/test_report_v4.py, computed by the ORIGINAL code
# ---------------------------------------------------------------------------

DEFAULT_PAIRS = [("greedy-optimal", "tit-for-tat"),
                 ("random-legal", "always-cooperate"),
                 ("hold-up", "always-defect"),
                 ("tit-for-tat", "random-legal")]
SHAM_PAIRS = [(a, b) for a in ("INDIGO", "SIENNA", "VIOLET")
              for b in ("INDIGO", "SIENNA", "VIOLET")]
LONG_TEXT = ("I will fund job three if you take job five, and I can pay on "
             "settlement; tell me which jobs matter to you so we can split "
             "the remaining pot fairly between us before the deadline. ")


def synthetic_reasoning(values, costs, seat: int, tick: int) -> dict | None:
    """Reasoning text written for the fixtures, not by a model.  It uses the
    seat's private values so that redaction has work to do: a value-word
    sentence, bare private numbers, a cost, an over-long turn, an empty
    turn and a `reasoning_details` part."""
    if tick % 7 == 0:
        return None
    k = len(values)
    j = tick % k + 1
    j2 = (tick + 1) % k + 1
    text = (f"Turn note {tick}. I value job {j} at {values[j - 1]} and job "
            f"{j2} at {values[j2 - 1]}. Bundle {j}+{j2} totals "
            f"{values[j - 1] + values[j2 - 1]}! The partner offered "
            f"{7 + tick}? Plan: propose jobs {j} and {j2}.\n"
            f"Cost check: {costs[j - 1]} is fine; my payoff improves.")
    if tick % 10 == 5:
        text = text + " " + ("Waiting keeps options open. " * 45)
    details = ([{"type": "reasoning.text",
                 "text": f" Also job {j2} is worth {values[j2 - 1]} to me."}]
               if tick % 3 == 0 else [])
    return {"seat": seat, "tick": tick, "reasoning": text,
            "reasoning_details": details}


def synthetic_records(reasonings: list[dict]) -> list[dict]:
    """Call records carrying the synthetic reasoning, in the log's shape."""
    return [{"kind": "call", "seat": r["seat"], "tick": r["tick"],
             "purpose": "act", "raw": {"choices": [{"message": {
                 "reasoning": r["reasoning"],
                 "reasoning_details": r["reasoning_details"]}}]}}
            for r in reasonings]


def _scripted_default_episodes() -> list[dict]:
    from ledger.core.events import Action
    from ledger.game import Game
    from ledger.policies.scripted import POLICIES
    from ledger.scenarios.bank import load_bank
    bank = load_bank("v2-d0")
    eps = []
    for i, sc in enumerate(bank):
        p1, p2 = DEFAULT_PAIRS[i % len(DEFAULT_PAIRS)]
        g = Game(sc, message_cap=DEFAULT_GAME_CAP)
        pol = {1: POLICIES[p1](), 2: POLICIES[p2]()}
        while not g.over:
            g.play(pol[g.turn](g, g.turn))
        eps.append({"template": i, "policies": [p1, p2], "events": g.events})
    sc = bank[0]
    g = Game(sc, message_cap=DEFAULT_GAME_CAP)
    for a in (Action("CHAT", {"text": LONG_TEXT * 9}),
              Action("REFUSE", {"text": "no. " + LONG_TEXT * 9}),
              Action("WAIT"), Action("END"), Action("END")):
        g.play(a)
    eps.append({"template": 0, "policies": ["hand-written", "hand-written"],
                "events": g.events})
    for n, e in enumerate(eps):
        sc = bank[e["template"]]
        e["episode_id"] = f"fixture-v2d0-{n:02d}"
        e["reasoning"] = [r for ev in e["events"] for r in [
            synthetic_reasoning(sc.v[ev.seat - 1], sc.c[ev.seat - 1],
                                ev.seat, ev.tick)] if r] if n % 4 == 1 else []
    return eps


ENGINE_WORKER = r'''
import hashlib, json, os, sys
sys.dont_write_bytecode = True
engine_src, harness, lx = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, engine_src)
import ledger
if not os.path.realpath(ledger.__file__).startswith(os.path.realpath(engine_src)):
    raise SystemExit("ledger did not resolve to the extracted engine")
for p in (lx, harness):
    sys.path.insert(0, p)
import forecast, reason_view, views
from ledger.core.events import Action, Event
from ledger.core.scenario import Scenario
from ledger.render.render import render_prompt
from ledger.runtime import CallResult, ModelSpec, state_at

def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def psha(msgs):
    return sha(json.dumps(msgs, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":")))

class Capture:
    def __init__(self):
        self.seen = []
    def chat(self, spec, messages, tools=None):
        self.seen.append(messages)
        raw = {"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": None, "tool_calls": [{
                "id": "c1", "type": "function",
                "function": {"name": "wait", "arguments": "{}"}}]}}]}
        return CallResult(raw=raw, provider="none", model=spec.slug,
                          usage={}, cost_usd=0.0, latency_s=0.0, attempts=1)

job = json.load(sys.stdin)
out = []
for ep in job["episodes"]:
    sc = Scenario.from_dict(ep["scenario"])
    events = [Event(t, s, Action(n, a), truncated=tr)
              for t, s, n, a, tr in ep["events"]]
    cap, eid, salt = ep["message_cap"], ep["episode_id"], job["salt"]
    res = {"episode_id": eid, "acting": [], "views": {v: [] for v in views.VIEWS},
           "trace_redacted": [], "trace_full": [], "trace_messages": []}
    for ev in events:
        st = state_at(sc, events, ev.tick)
        prefix = tuple(e for e in events if e.tick < ev.tick)
        res["acting"].append(render_prompt(st, prefix, ev.seat, "principal", cap)[1])
        for v in views.VIEWS:
            system, user, _d = views.build_view(sc, events, ev.tick, v, salt=salt,
                                                episode_id=eid, message_cap=cap)
            res["views"][v].append(psha([{"role": "system", "content": system},
                                         {"role": "user", "content": user}]))
        red = reason_view.trace_text(sc, ep["records_path"], ev.tick, ev.seat, redacted=True)
        full = reason_view.trace_text(sc, ep["records_path"], ev.tick, ev.seat, redacted=False)
        res["trace_redacted"].append(sha(red))
        res["trace_full"].append(sha(full))
        cap_client = Capture()
        forecast.collect_forecast(cap_client, ModelSpec(slug="fixture/none"), sc,
                                  events, ev.tick, view="C-target", m=1, salt=salt,
                                  episode_id=eid, message_cap=cap,
                                  extra_user_block=red or None)
        res["trace_messages"].append(psha(cap_client.seen[0]))
    out.append(res)
json.dump(out, sys.stdout)
'''


def _engine_at(commit: str, dest: Path) -> Path:
    """Extract src/, spec/ and banks/ of `commit` into `dest`."""
    data = subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar",
                           commit, "src", "spec", "banks"],
                          capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        try:
            tar.extractall(dest, filter="data")
        except TypeError:                    # Python without extraction filters
            tar.extractall(dest)
    return dest / "src"


def _default_fixture(H: Harness, tmp: Path) -> dict:
    from ledger.scenarios.bank import load_bank
    bank = load_bank("v2-d0")
    eps = _scripted_default_episodes()
    job = {"salt": FIXTURE_SALT, "episodes": []}
    for e in eps:
        path = tmp / "records" / f"{e['episode_id']}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r) + "\n" for r in
                                synthetic_records(e["reasoning"])),
                        encoding="utf-8")
        job["episodes"].append({
            "scenario": bank[e["template"]].to_dict(),
            "message_cap": DEFAULT_GAME_CAP, "episode_id": e["episode_id"],
            "events": _events_json(e["events"]), "records_path": str(path)})
    engine = _engine_at(REPORT_ENGINE_COMMIT, tmp / "engine")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env.pop("PYTHONPATH", None)
    run = subprocess.run(
        [sys.executable, "-B", "-c", ENGINE_WORKER, str(engine),
         str(H.lx / "harness"), str(H.lx)],
        input=json.dumps(job), capture_output=True, text=True, env=env,
        cwd=str(tmp), check=False)
    if run.returncode:
        raise SystemExit("engine worker failed:\n" + run.stderr[-3000:])
    got = json.loads(run.stdout)
    out = []
    for e, g in zip(eps, got):
        out.append({
            "episode_id": e["episode_id"], "template": e["template"],
            "policies": e["policies"], "message_cap": DEFAULT_GAME_CAP,
            "events": _events_json(e["events"]),
            "reasoning": e["reasoning"],
            "acting_digests_sha256": sha_lines(g["acting"]),
            "views_sha256": {v: sha_lines(x) for v, x in g["views"].items()},
            "trace_redacted_sha256": sha_lines(g["trace_redacted"]),
            "trace_full_sha256": sha_lines(g["trace_full"]),
            "trace_messages_sha256": sha_lines(g["trace_messages"]),
            "n_prompts": len(g["acting"])})
    return {"engine_commit": REPORT_ENGINE_COMMIT, "salt": FIXTURE_SALT,
            "episodes": out}


def _scripted_variant_episodes() -> list[dict]:
    from ledger.core.events import Action
    from ledger.game import Game
    from ledger.policies.scripted import POLICIES
    from ledger.variants import hidden_objectives as ho
    eps = []
    for i, sv in enumerate(ho.load_bank()):
        opening = 1 + i % 2
        p1, p2 = DEFAULT_PAIRS[i % len(DEFAULT_PAIRS)]
        g = Game(sv.base(opening), message_cap=VARIANT_FIXTURE_CAP)
        pol = {1: POLICIES[p1](), 2: POLICIES[p2]()}
        while not g.over:
            g.play(pol[g.turn](g, g.turn))
        eps.append({"index": i, "opening": opening, "policies": [p1, p2],
                    "events": g.events})
    sv = ho.load_bank()[0]
    g = Game(sv.base(1), message_cap=VARIANT_FIXTURE_CAP)
    for a in (Action("CHAT", {"text": LONG_TEXT}),
              Action("REFUSE", {"text": "no. " + LONG_TEXT}),
              Action("WAIT"), Action("END"), Action("END")):
        g.play(a)
    eps.append({"index": 0, "opening": 1,
                "policies": ["hand-written", "hand-written"],
                "events": g.events})
    bank = ho.load_bank()
    for n, e in enumerate(eps):
        e["episode_id"] = f"fixture-hidden-{n:02d}"
        e["labels"] = list(SHAM_PAIRS[n % len(SHAM_PAIRS)])
        sv = bank[e["index"]]
        ref = sv.reference_column()
        e["reasoning"] = [r for ev in e["events"] for r in [
            synthetic_reasoning(ref[ev.seat - 1],
                                sv.base(e["opening"]).c[ev.seat - 1],
                                ev.seat, ev.tick)] if r] if n % 3 == 2 else []
    return eps


VARIANT_FIXTURE_CAP = 40
SOLVER_STATES = [(1, (1, 4)), (2, (2, 7)), (11, (3, 9))]   # (episode, ticks)


def _variant_fixture(H: Harness, tmp: Path) -> dict:
    mods = H.import_modules()
    BR, SH = mods["ledger_v2_bridge"], mods["ledger_v2_sham"]
    import ledger_episode_evidence as EV
    from ledger.reader import prompt_sha256
    from ledger.variants import hidden_objectives as ho
    from ledger.variants.hidden_objectives import reader as HR
    bank = ho.load_bank()
    out = {"salt": FIXTURE_SALT, "message_cap": VARIANT_FIXTURE_CAP,
           "episodes": [], "solver_states": []}
    eps = _scripted_variant_episodes()
    for e in eps:
        sv, opening, events = bank[e["index"]], e["opening"], e["events"]
        path = tmp / "records" / f"{e['episode_id']}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r) + "\n" for r in
                                synthetic_records(e["reasoning"])),
                        encoding="utf-8")
        sham, views, trace_sha, probe, inert = [], defaultdict(list), [], \
            defaultdict(list), None
        tally = []
        for ev in events:
            st, prefix = BR.state_and_prefix(sv, opening, events, ev.tick)
            seat = st.mover
            msgs = BR.acting_messages(sv, st, prefix, seat, SH.EFFECTIVE_OBJECTIVE,
                                      mandate="principal",
                                      message_cap=VARIANT_FIXTURE_CAP)
            user = SH.substitute(msgs[1]["content"], e["labels"][seat - 1])
            sham.append(sha(msgs[0]["content"] + "\n" + user))
            if inert is None and ev.tick >= 3:
                inert = SH.assert_inert(sv, st, prefix, seat)
            for v in ("board", "ordered", "shuffled"):
                views[v].append(BR.build_view_v2(
                    sv, st, prefix, v, salt=FIXTURE_SALT,
                    episode_id=e["episode_id"],
                    message_cap=VARIANT_FIXTURE_CAP)[2])
            trace = BR.trace_text_v2(sv, path, ev.tick, seat, redacted=True)
            trace_sha.append(sha(trace))
            if trace:
                views["trace"].append(BR.build_view_v2(
                    sv, st, prefix, "trace", trace=trace,
                    message_cap=VARIANT_FIXTURE_CAP)[2])
            for v in ("board", "ordered"):
                probe[v].append(prompt_sha256(BR.objective_probe_messages(
                    sv, st, prefix, v, salt=FIXTURE_SALT,
                    episode_id=e["episode_id"],
                    message_cap=VARIANT_FIXTURE_CAP)))
            tally.append(prompt_sha256(HR.tally_view(
                sv, opening, events, ev.tick,
                message_cap=VARIANT_FIXTURE_CAP)))
        out["episodes"].append({
            "episode_id": e["episode_id"], "index": e["index"],
            "opening": opening, "policies": e["policies"],
            "labels": e["labels"], "events": _events_json(events),
            "reasoning": e["reasoning"],
            "sham_digests_sha256": sha_lines(sham),
            "assert_inert": inert,
            "views_sha256": {v: sha_lines(x) for v, x in views.items()},
            "trace_sha256": sha_lines(trace_sha),
            "probe_sha256": {v: sha_lines(x) for v, x in probe.items()},
            "tally_sha256_port_regression": sha_lines(tally),
            "n_prompts": len(sham)})
    for n, ticks in SOLVER_STATES:
        e = eps[n]
        sv, opening = bank[e["index"]], e["opening"]
        ticks = [t for t in ticks if t <= e["events"][-1].tick]
        led = {"episode_id": e["episode_id"], "opening": opening,
               "events": [{"tick": ev.tick, "seat": ev.seat,
                           "action": {"name": ev.action.name,
                                      "args": ev.action.args}}
                          for ev in e["events"]]}
        for tick in ticks:
            st, _prefix = BR.state_and_prefix(sv, opening, e["events"], tick)
            row = {"episode": n, "tick": tick}
            for obj in ("cash", "standing"):
                pb = BR.per_belief_at(sv, st, obj)
                row[f"per_belief_{obj}_sha256"] = sha(canonical(pb))
                row[f"certify_row_{obj}"] = BR.certify_row(pb)
            for pruned in (False, True):
                r = EV._envelope_tables(sv.to_dict(), led, tick, pruned=pruned)
                row["own_objective_" + ("pruned" if pruned else "full")] = (
                    None if r is None else
                    {"stratum": r["stratum"], "bests": r["bests"],
                     "tables_sha256": sha(canonical(r["tables"])),
                     "n_completions": r["n_completions"]})
            rank = SH.rank_equivalence_at(sv, st)
            row["sham_rank_equivalence"] = {
                k: rank[k] for k in ("equivalent", "pairs_checked",
                                     "n_legal_classes",
                                     "certify_row_identical")}
            out["solver_states"].append(row)
    return out


def write_fixtures(H: Harness, tmp: Path) -> None:
    t = time.time()
    payload = {
        "_note": ("Digests computed by the ORIGINAL code on scripted games: "
                  "the default game by the ledger engine at commit "
                  f"{REPORT_ENGINE_COMMIT} with the research harness's view "
                  "and trace builders; the hidden-objectives variant by the "
                  "harness's bridge, sham and solver modules. The reasoning "
                  "text is synthetic, written for these fixtures, not by a "
                  "model. `tally_sha256_port_regression` is computed by "
                  "this port (the harness module that defines the tally rung "
                  "needs packages outside this repository); the rung's "
                  "equivalence rests on the 240 recorded predictor-extension "
                  "digests in report_v4_equivalence.json. Regenerate with "
                  "scripts/check_report_equivalence.py --write-fixtures."),
        "harness_commit": git_head(H.root),
        "ledger_commit_at_generation": git_head(ROOT),
        "default_game_v2_d0": _default_fixture(H, tmp),
        "hidden_objectives": _variant_fixture(H, tmp),
    }
    from ledger.render.tokens import tokenizer_name
    payload["tokenizer"] = tokenizer_name()
    FIXTURES.write_text(json.dumps(payload, indent=1, sort_keys=True,
                                   ensure_ascii=False) + "\n",
                        encoding="utf-8", newline="\n")
    print(f"  wrote {FIXTURES.relative_to(ROOT)} in {time.time() - t:.0f} s")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

SECTIONS = ("bank", "default", "phase3", "reader", "solver")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--smoke-tests", required=True, type=Path,
                    help="path to a self-other-prediction-smoke-tests checkout")
    ap.add_argument("--only", nargs="+", choices=SECTIONS, default=None,
                    help="run only these sections (default: all)")
    ap.add_argument("--workers", type=int,
                    default=max(1, (os.cpu_count() or 2) - 1),
                    help="processes for the solver section")
    ap.add_argument("--write-golden", action="store_true",
                    help=f"freeze the results into {GOLDEN.name}")
    ap.add_argument("--write-fixtures", action="store_true",
                    help=f"compute {FIXTURES.name} with the original code")
    args = ap.parse_args()
    from ledger.render.tokens import tokenizer_name
    if tokenizer_name() != "o200k_base":
        raise SystemExit("tiktoken o200k_base is required: live play "
                         "truncated messages with it")
    smoke = args.smoke_tests.resolve()
    sections = args.only or list(SECTIONS)
    T = Tally()
    results = {}
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="ledger-report-check-") as tmp:
        H = Harness(smoke, Path(tmp))
        for name in sections:
            print(f"[{name}]", flush=True)
            t = time.time()
            fn = {"bank": check_bank, "default": check_default,
                  "phase3": check_phase3, "reader": check_reader,
                  "solver": check_solver}[name]
            results[name] = (fn(H, T, args.workers) if name == "solver"
                             else fn(H, T))
            print(f"  ({time.time() - t:.0f} s)", flush=True)
        if args.write_fixtures:
            print("[fixtures]", flush=True)
            write_fixtures(H, Path(tmp))
    status = T.report()
    print(f"total {time.time() - t0:.0f} s")
    if args.write_golden:
        if status:
            raise SystemExit("not writing the golden file: mismatches above")
        golden = (json.loads(GOLDEN.read_text(encoding="utf-8"))
                  if GOLDEN.exists() else {})
        golden.update({
            "_note": ("Results of scripts/check_report_equivalence.py against "
                      "the research harness's logs, stores and manifests "
                      "(self-other-prediction-smoke-tests). Counts are "
                      "checks that passed; every check passed when this was "
                      "written. Per-episode entries hold the sha256 of the "
                      "logged digests joined by newlines, in log order. No "
                      "prompt text is stored here."),
            "report": "final report v4, 2026-09-03",
            "harness_commit": git_head(smoke),
            "ledger_commit_at_generation": git_head(ROOT),
            "tokenizer": tokenizer_name(),
        })
        golden.setdefault("sections", {}).update(results)
        GOLDEN.write_text(json.dumps(golden, indent=1, sort_keys=True,
                                     ensure_ascii=False) + "\n",
                          encoding="utf-8", newline="\n")
        print(f"wrote {GOLDEN.relative_to(ROOT)}")
    return status


if __name__ == "__main__":
    sys.exit(main())
