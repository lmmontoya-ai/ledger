"""Build a standalone preview of the pilot sections for visual checks."""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
body = (HERE / "report_body.html").read_text(encoding="utf-8")
js = (HERE / "report.js").read_text(encoding="utf-8")
data = json.loads((HERE / "report_data.json").read_text(encoding="utf-8"))

m = re.search(r'<section id="ran">.*?</section>\s*'
              r'<section id="found">.*?</section>', body, re.S)
assert m, "pilot sections not found in body"
css = ("body{font-family:Segoe UI,sans-serif;max-width:900px;margin:20px auto;"
       "padding:0 16px} table{border-collapse:collapse;margin:10px 0} "
       "th,td{border:1px solid #ccc;padding:5px 10px;font-size:14px} "
       ".finding{background:#f6f6f0;padding:10px 14px;margin:12px 0;"
       "border-radius:8px}")
html = (f'<!DOCTYPE html><html><head><meta charset="utf-8">'
        f"<style>{css}</style></head><body>{m.group(0)}"
        f"<script>const D = {json.dumps(data)};</script>"
        f"<script>{js}</script></body></html>")
out = HERE.parent.parent / "docs" / "report" / "_pilot_only.html"
out.write_text(html, encoding="utf-8")
print(f"wrote {out}")
