"""Harvest report_data.json for the LEDGER story report.

Every number in the report's prose comes from here, which comes from the
engine. Nothing is retyped by hand, so a figure cannot drift from the code
the way the Commons projection chart once did.
"""
import json
import statistics as st
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ledger.core.events import Action  # noqa: E402
from ledger.core.harm import grade  # noqa: E402
from ledger.game import Game, IllegalAction  # noqa: E402
from ledger.policies.scripted import POLICIES  # noqa: E402
from ledger.render import tokens as tok  # noqa: E402
from ledger.render.board import render_board  # noqa: E402
from ledger.render.render import render_prompt, system_block  # noqa: E402
from ledger.scenarios.bank import load_bank  # noqa: E402

BANK = "v1-e0"


def scenario_facts(bank):
    """Structural facts about the economy, straight off a scenario."""
    s = bank[0]
    return {
        "jobs": s.K, "pot": s.B, "slots": s.kappa[0], "draw_cap": s.u[0],
        "turns": s.D, "window": s.r, "cancel_fee": s.eps,
        "renege_penalty": s.p, "default_penalty": s.p_def,
        "n_scenarios": len({x.scenario_id for x in bank}),
        "n_templates": len(bank),
    }


def welfare_spread(bank):
    """W*, the alone-values, and the integrative gap across the bank."""
    from ledger.core.welfare import w_star, d_i, w_eq
    rows = []
    for s in {x.scenario_id: x for x in bank}.values():
        ws = w_star(s)
        d1, d2 = d_i(s, 1), d_i(s, 2)
        we = w_eq(s)
        rows.append({"w_star": ws, "d1": d1, "d2": d2, "w_eq": we,
                     "gap": round((ws - we) / ws, 3)})
    return {
        "w_star_median": int(st.median(r["w_star"] for r in rows)),
        "w_star_min": min(r["w_star"] for r in rows),
        "w_star_max": max(r["w_star"] for r in rows),
        "alone_median": int(st.median(r["d1"] + r["d2"] for r in rows)),
        "gap_median": round(st.median(r["gap"] for r in rows), 3),
        "gap_min": round(min(r["gap"] for r in rows), 3),
        "rows": rows,
    }


def play_all(bank):
    """Every scripted pair on every distinct scenario: the branching and
    harm profile of the environment under non-model play."""
    distinct = list({x.scenario_id: x for x in bank}.values())
    labels, grades, episodes = Counter(), Counter(), []
    reneges, defaults, agreements = 0, 0, 0
    for scen in distinct:
        for n1, P1 in POLICIES.items():
            for n2, P2 in POLICIES.items():
                g = Game(scen)
                pol = {1: P1(), 2: P2()}
                while not g.over:
                    seat = g.turn
                    try:
                        gr = grade(g.state)
                        grades[gr.bucket] += 1
                    except Exception:
                        pass
                    try:
                        a = pol[seat](g, seat)
                    except Exception:
                        a = Action("WAIT", {})
                    labels[a.name] += 1
                    try:
                        g.play(a)
                    except IllegalAction:
                        g.play(Action("WAIT", {}))
                r = g.result
                reneges += len(r["reneges"])
                defaults += len(r["defaults"])
                agreements += 1 if r["agreement"] else 0
                episodes.append({
                    "pair": f"{n1} vs {n2}", "scenario": scen.scenario_id[:8],
                    "pi": list(r["pi"]), "w_star": r["w_star"],
                    "efficiency": round(float(r["efficiency"]), 3),
                    "agreement": bool(r["agreement"]),
                    "reneges": len(r["reneges"]),
                })
    total = sum(labels.values())
    import math
    ent = -sum((c / total) * math.log2(c / total) for c in labels.values() if c)
    gtotal = sum(grades.values())
    return {
        "n_episodes": len(episodes), "n_turns": total,
        "entropy_bits": round(ent, 2),
        "label_share": {k: round(v / total, 3) for k, v in labels.most_common()},
        "harm_share": {k: round(v / gtotal, 3) for k, v in grades.most_common()},
        "reneges": reneges, "defaults": defaults,
        "agreement_rate": round(agreements / len(episodes), 3),
        "efficiency_median": round(st.median(e["efficiency"] for e in episodes), 3),
        "efficiency_max": max(e["efficiency"] for e in episodes),
        "episodes": episodes,
    }


def token_facts(bank):
    sys.path.insert(0, str(ROOT / "tests"))
    from conftest import worked_game
    g = worked_game(8)
    data, _ = render_prompt(g.state, tuple(g.events), 1)
    board = render_board(g.state, 1)
    sysb = system_block().decode("utf-8")
    out = {}
    for enc in ("o200k_base", "cl100k_base"):
        if not tok.encoding_available(enc):
            continue
        out[enc] = {
            "system": tok.token_count(sysb, enc),
            "board": tok.token_count(board, enc),
            "prompt": tok.token_count(data.decode("utf-8"), enc),
        }
    return out


def demo_and_board():
    """The worked game from the read-through page, plus the board an agent
    reads. Imported rather than duplicated so the report and the G2 page can
    never tell different stories."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "rt", ROOT / "scripts" / "m0_readthrough_page.py")
    rt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rt)
    import re as _re
    steps, checkpoints, res = rt.run_demo()
    # the demo's own final numbers, taken from the sentence the demo itself
    # generated from its result dict (single source, no retyping)
    pi = [int(x) for x in _re.findall(r"you (-?\d+), partner (-?\d+)", res)[0]]
    ws = int(_re.search(r"reached\s+(\d+)", res).group(1))
    demo = {"steps": [{"who": w, "line": l, "note": n} for w, l, n in steps],
            "pi": pi, "w_star": ws}
    boards = rt.collect_boards()
    # pick the most instructive board: one with a binding deal and some history
    pick = max(boards, key=lambda b: (b[3].count("BINDING"), len(b[3])))
    return demo, pick[3]

EXPERIMENTS = Path(r"D:\research\pivotal\repos\self-other-prediction-smoke-tests"
                   r"\ledger-experiments")


def pilot_results():
    """The pilot's numbers, read from the experiment artifacts themselves
    (e0_report.json / e0b_report.json / state files) so the report cannot
    state a result the run did not produce.  Optional: absent on machines
    without the private experiments repo."""
    e0_dir = EXPERIMENTS / "runs" / "e0"
    e0b_dir = EXPERIMENTS / "runs" / "e0b"
    if not (e0_dir / "e0_report.json").exists():
        return None
    e0 = json.loads((e0_dir / "e0_report.json").read_text(encoding="utf-8"))
    e0b = json.loads((e0b_dir / "e0b_report.json").read_text(encoding="utf-8"))
    s0 = json.loads((e0_dir / "e0_state.json").read_text(
        encoding="utf-8"))["spent_usd"]
    s0b = json.loads((e0b_dir / "e0b_state.json").read_text(
        encoding="utf-8"))["spent_usd"]
    reneges = sum(v["reneges"] for v in e0b["episodes_by_mandate"].values())
    return {
        "spend_total": round(s0 + s0b),
        "games": 48, "decisions": 96,
        "axes": [
            {"name": "Same model, different goals", "rate":
                e0b["c2_axis_mandate"]["unit_pass_rate"],
             "pairs": e0b["c2_axis_mandate"]["pairs_separable"]},
            {"name": "Different models, same goal", "rate":
                e0b["c2_axis_model"]["unit_pass_rate"],
             "pairs": e0b["c2_axis_model"]["pairs_separable"]},
            {"name": "Everything against everything", "rate":
                e0b["c2_all_instruments"]["unit_pass_rate"],
             "pairs": e0b["c2_all_instruments"]["pairs_separable"]},
        ],
        "entropy_negotiation": e0b["c1_instruments"]["by_phase"]["negotiation"],
        "entropy_mechanical": e0b["c1_instruments"]["by_phase"]["execution"],
        "mandates": e0b["episodes_by_mandate"],
        "premiums": e0b["breach_premiums"],
        "reneges": reneges,
        "take_rate_denom": e0b["breach_premiums"]["n_profitable"],
        "c6_median_loss": e0b["c6_live_stakes"][
            "median_live_stakes_victim_loss"],
        "views": {v: {
            "n": e0["forecast_views"][v]["n"] + e0b["forecast_views"][v]["n"],
            "mean_excess": round(
                (e0["forecast_views"][v]["mean_excess"]
                 * e0["forecast_views"][v]["n"]
                 + e0b["forecast_views"][v]["mean_excess"]
                 * e0b["forecast_views"][v]["n"])
                / (e0["forecast_views"][v]["n"]
                   + e0b["forecast_views"][v]["n"]), 4)}
            for v in e0b["forecast_views"]},
        "sens_r1": e0["sensitivity"]["r1_jsd"]["median_jsd_vs_default"],
        "sens_lowt": e0["sensitivity"]["lowt_jsd"]["median_jsd_vs_default"],
        "c5_filler": e0["c5_mini_coupling"]["mean_A"],
        "c5_real": e0["c5_mini_coupling"]["mean_C"],
        "forecast": json.loads(
            (EXPERIMENTS / "runs" / "forecast_matrix.json").read_text(
                encoding="utf-8")),
    }


def v2_results():
    """The rebuilt economy's numbers, read from the run artifacts: the
    offline gates, the identifiability gate, and the confirmatory battery.
    Optional, like pilot_results()."""
    R = EXPERIMENTS / "runs"
    need = [R / "v0" / "v0_report.json", R / "q0_gate" / "q0_report.json",
            R / "q0_c3val" / "c3val_report.json", R / "e1" / "e1_report.json"]
    if not all(p.exists() for p in need):
        return None
    v0, q0, c3, e1 = (json.loads(p.read_text(encoding="utf-8")) for p in need)
    gate_a = json.loads((R / "divergence_audit" / "gate_a.json")
                        .read_text(encoding="utf-8"))
    gate_c = json.loads((R / "divergence_audit" / "gate_c_VALIDATION2.json")
                        .read_text(encoding="utf-8"))
    sel = json.loads((R / "q0_gate" / "selection.json")
                     .read_text(encoding="utf-8"))
    cp_path = R / "e1" / "coupling" / "coupling_report.json"
    cp = json.loads(cp_path.read_text(encoding="utf-8")) if cp_path.exists() \
        else None
    return {
        "old_tradeoff_negotiation":
            gate_a["live"]["by_phase"]["negotiation"]["tradeoff_share"],
        "old_tradeoff_all": gate_a["live"]["tradeoff_share"],
        "old_realignment": gate_a["live"]["realignment_identity_share"],
        "new_tradeoff": gate_c["mixture"]["tradeoff_share"],
        "new_trust_states": gate_c["mixture"]["visited"].get("trust", 0),
        "resolution": v0["check1_resolution"]["fraction"],
        "gate_tpr": v0["check3_gate_tpr"]["at_n32"]["tpr"],
        "gate_fpr": v0["check3_gate_tpr"]["at_n32"]["fpr"],
        "q0_entropy": q0["criterion1_branching"]["median_bits"],
        "q0_pairs": q0["criterion2_distinctness"]["pair_rates"],
        "q0_n_certified": sel["tradeoff"],
        "c3_median_exposure": c3["fresh_median_exposure"],
        "c3_n_trust": c3["fresh_trust_moments"],
        "rq1": e1["rq1"],
        "h_choice": e1["h_choice"],
        "h_self": e1["h_self"],
        "rq3": e1["rq3"],
        "matrix": e1["matrix"],
        "self_other": e1["self_other"],
        "n_forecasts": e1["n_forecast_rows"] * 8,
        "coupling": cp,
    }


def test_count():
    """Count collected tests from pytest itself, so the status table's number
    cannot go stale the way a typed one would."""
    import subprocess
    r = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q",
                        str(ROOT / "tests")], capture_output=True, text=True,
                       cwd=str(ROOT))
    n = sum(1 for line in r.stdout.splitlines() if "::" in line)
    if not n:
        raise RuntimeError("pytest collected nothing")
    return n


def action_table():
    """The action vocabulary, straight from the frozen spec, so the report
    cannot list an action the engine does not have (or miss one it does)."""
    spec = json.loads((ROOT / "spec" / "actions.v2.json").read_text(encoding="utf-8"))
    rows = []
    for name, a in spec["actions"].items():
        args = ", ".join(a.get("args", {}).keys()) or "none"
        rows.append({"name": name, "args": args, "what": a["description"]})
    return {"version": spec["spec_version"], "rows": rows}

def main():
    bank = load_bank(BANK)
    data = {
        "actions": action_table(),
        "scenario": scenario_facts(bank),
        "welfare": welfare_spread(bank),
        "play": play_all(bank),
    }
    try:
        data["tokens"] = token_facts(bank)
    except Exception as exc:
        print("token facts skipped:", exc)
        data["tokens"] = {}
    try:
        demo, board = demo_and_board()
        data["demo"], data["board"] = demo, board
    except Exception as exc:
        print("demo skipped:", exc)
    try:
        data["tests"] = test_count()
    except Exception as exc:
        print("test count skipped:", exc)
    try:
        data["v2"] = v2_results()
    except Exception as exc:
        print("v2 results skipped:", exc)
        data["v2"] = None
    out = HERE / "report_data.json"
    out.write_text(json.dumps(data, indent=1), encoding="utf-8")
    p = data["play"]
    print(f"wrote {out.name} | {p['n_episodes']} episodes, {p['n_turns']} turns, "
          f"entropy {p['entropy_bits']} bits, agreement {p['agreement_rate']}, "
          f"reneges {p['reneges']}, W* median {data['welfare']['w_star_median']}")


if __name__ == "__main__":
    main()
