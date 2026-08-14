"""One-time migration: current report_body.html -> report.md.

Kept in the repo as the record of how the markdown source was produced,
and as a check: rendering the markdown must reproduce the same anchors,
figure ids and text content as the HTML it came from.
"""
import html
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent


def inline_to_md(s: str) -> str:
    # any anchored <b>, with or without placeholder text: the value is
    # injected at render time, so the placeholder must not survive
    s = re.sub(r'<b id="([a-z0-9-]+)">.*?</b>', r"{{\1}}", s, flags=re.S)
    s = re.sub(r"<b[^>]*>(.*?)</b>", r"**\1**", s, flags=re.S)
    s = re.sub(r"<i>(.*?)</i>", r"*\1*", s, flags=re.S)
    s = re.sub(r"<code>(.*?)</code>", r"`\1`", s, flags=re.S)
    s = re.sub(r'<a href="([^"]+)">(.*?)</a>', r"[\2](\1)", s, flags=re.S)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def main() -> None:
    t = (HERE / "report_body.html").read_text(encoding="utf-8")
    out: list[str] = []

    hero = re.search(r'<h1>(.*?)</h1>.*?class="subtitle">(.*?)</p>'
                     r'.*?class="version">(.*?)</p>', t, re.S)
    out += ["### hero", inline_to_md(hero.group(1)),
            inline_to_md(hero.group(2)), inline_to_md(hero.group(3)), ""]

    body = t[t.index("<section"):]
    for sec in re.finditer(r'<section id="([a-z]+)">(.*?)</section>',
                           body, re.S):
        sid, inner = sec.group(1), sec.group(2)
        h2 = re.search(r"<h2>(.*?)</h2>", inner, re.S)
        out += [f"# {inline_to_md(h2.group(1))} {{#{sid}}}", ""]
        rest = inner[h2.end():]
        for m in re.finditer(
                r"<h3>(.*?)</h3>|<div class=\"finding\">(.*?)</div>"
                r"|<div class=\"note\">(.*?)</div>"
                r"|<figure>(.*?)</figure>"
                r"|<div id=\"([a-z0-9-]+)\"></div>"
                r"|<table>(.*?)</table>|<p>(.*?)</p>", rest, re.S):
            h3, finding, note, chart, figure, table, para = m.groups()
            if chart:
                cid = re.search(r'id="([a-z0-9-]+)"', chart).group(1)
                cap = re.search(r"<figcaption>(.*?)</figcaption>", chart, re.S)
                out += [f"@chart {cid}", inline_to_md(cap.group(1)), ""]
                continue
            if h3:
                out += [f"## {inline_to_md(h3)}", ""]
            elif finding or note:
                raw = finding or note
                marker = "!!" if finding else "??"
                hm = re.match(r"\s*<b[^>]*>(.*?)</b>(.*)", raw, re.S)
                head, body = (hm.group(1), hm.group(2)) if hm else ("", raw)
                out += [f"{marker} {inline_to_md(head)}",
                        inline_to_md(body), ""]
            elif figure:
                out += [f"@figure {figure}", ""]
            elif table:
                rows = re.findall(r"<tr>(.*?)</tr>", table, re.S)
                for i, r in enumerate(rows):
                    cells = [inline_to_md(c) for c in
                             re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", r, re.S)]
                    out.append("| " + " | ".join(cells) + " |")
                    if i == 0:
                        out.append("|" + "---|" * len(cells))
                out.append("")
            elif para:
                out += [inline_to_md(para), ""]

    (HERE / "report.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("wrote report.md")

    # verification: the rendered markdown must carry the same anchors,
    # figure ids and visible words as the HTML it came from
    import md_render
    rendered, _ = md_render.render((HERE / "report.md").read_text(
        encoding="utf-8"))

    def facts(x):
        return (sorted(re.findall(r'<b id="([a-z0-9-]+)"></b>', x)),
                sorted(re.findall(r'<div id="([a-z0-9-]+)"></div>', x)),
                re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", x)).strip())

    a, b = facts(t), facts(rendered)
    print("anchors match:", a[0] == b[0], f"({len(a[0])})")
    print("figures match:", a[1] == b[1], f"({len(a[1])})")
    wa, wb = a[2].split(), b[2].split()
    print(f"words: html {len(wa)}, md {len(wb)}")
    if wa != wb:
        for i, (x, y) in enumerate(zip(wa, wb)):
            if x != y:
                print(f"  first difference at word {i}:\n    html: "
                      f"{' '.join(wa[max(0,i-6):i+8])}\n    md:   "
                      f"{' '.join(wb[max(0,i-6):i+8])}")
                break
        else:
            print("  one is a prefix of the other")


if __name__ == "__main__":
    main()
