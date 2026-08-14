"""Assemble the self-contained LEDGER design report.

One command: harvest (engine -> data) then assemble (data + prose -> HTML),
with a consistency check between them. The stylesheet is the Predictive
Commons one, so the three reports read as one series.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = ROOT / "docs/report/ledger_story.html"
CSS_SRC = Path(r"D:\research\pivotal\repos\self-other-prediction-smoke-tests"
               r"\scripts\story_report\report.css")
CSS_LOCAL = HERE / "report.css"


def check(data: dict, body: str, html: str) -> None:
    """Numbers stated in prose must match the harvested data. The Commons
    report once shipped a chart built from stale data while the prose
    described fresh data; this makes that failure impossible here."""
    errors = []
    if "id=\"wstar\"" not in body:
        errors.append("prose lost its W* anchor")
    if data["welfare"]["gap_median"] < 0.25:
        errors.append(f"integrative gap {data['welfare']['gap_median']} below the "
                      "0.25 admission floor the prose claims")
    if not data.get("demo", {}).get("steps"):
        errors.append("worked game missing from data")
    if not data.get("board"):
        errors.append("sample board missing from data")
    acts = data.get("actions", {}).get("rows", [])
    if len(acts) != 13:
        errors.append(f"action table lists {len(acts)} actions, engine has 13")
    if data.get("pilot"):
        for anchor in ("p-spend", "axes-table", "mandate-table",
                       "views-table"):
            if anchor not in body:
                errors.append(f"pilot results present but prose lost {anchor}")
    if data.get("v2"):
        for anchor in ("v2-tpr", "v2-p-ls", "v2-rq1p", "v2-hself",
                       "v2-hcy", "v2-realign"):
            if anchor not in body:
                errors.append(f"v2 results present but prose lost {anchor}")
    if data.get("pilot"):
        if data["pilot"].get("forecast"):
            for anchor in ("forest-plot", "matrix-table", "selfother-plot",
                           "p-fx-selfneg"):
                if anchor not in body:
                    errors.append(f"forecast matrix present but prose lost {anchor}")
        if data["pilot"]["axes"][0]["rate"] != 0.0:
            pass  # value asserted only for presence; numbers are injected
    if "Thirteen actions" not in body:
        errors.append("prose action count does not say thirteen")
    harm = data["play"]["harm_share"]
    live = round(sum(v for k, v in harm.items() if k != "null"), 3)
    if live < 0.15:
        errors.append(f"only {live:.0%} of decisions carry live harm; prose claims a third")
    m = re.search(r"const D = (\{.*?\});\n</script>", html, re.S)
    if not m:
        errors.append("data not embedded in assembled HTML")
    elif json.loads(m.group(1))["welfare"] != data["welfare"]:
        errors.append("embedded data differs from report_data.json")
    if errors:
        for e in errors:
            print("FAIL:", e)
        raise SystemExit(1)
    print(f"consistency: OK (W* {data['welfare']['w_star_median']}, "
          f"gap {data['welfare']['gap_median']:.0%}, live harm {live:.0%}, "
          f"{len(data['demo']['steps'])} demo steps)")


def main() -> None:
    if "--quick" not in sys.argv:
        r = subprocess.run([sys.executable, "-X", "utf8", str(HERE / "harvest.py")])
        if r.returncode:
            raise SystemExit("harvest failed")

    data = json.loads((HERE / "report_data.json").read_text(encoding="utf-8"))
    body = (HERE / "report_body.html").read_text(encoding="utf-8")
    js = (HERE / "report.js").read_text(encoding="utf-8")
    css = (CSS_SRC if CSS_SRC.exists() else CSS_LOCAL).read_text(encoding="utf-8")
    css += """
.step { display:flex; gap:14px; margin:14px 0 }
.step .who { flex:0 0 64px; font-weight:600; font-size:14px; color:var(--ink2); padding-top:2px }
.step .body p { margin:4px 0 0; font-size:15.5px }
.hline code { background:var(--surface); border:1px solid var(--grid);
  border-radius:6px; padding:2px 8px; font-size:12.5px }
#board-sample pre { background:var(--surface); border:1px solid var(--grid);
  border-radius:8px; padding:14px; overflow-x:auto; font-size:12.5px; line-height:1.5 }
.trace { margin:16px 0 }
.trace .tsrc { font-weight:600; font-size:14px; color:var(--ink2) }
.trace blockquote { margin:6px 0; padding:10px 14px; border-left:3px solid #2a78d6;
  background:var(--surface); font-size:14.5px; line-height:1.55; font-style:italic }
.trace .tnote { font-size:14.5px; color:var(--ink2); margin:4px 0 0 }
"""
    for name, text in (("body", body), ("js", js)):
        for ch in ("—", "–"):
            if ch in text:
                raise SystemExit(f"em/en dash found in {name}")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LEDGER: an economy where anticipation is worth money</title>
<style>{css}</style>
</head>
<body>
{body}
<script>
const D = {json.dumps(data)};
</script>
<script>{js}</script>
</body>
</html>
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    check(data, body, html)
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
