"""Render report.md into the report body HTML.

The prose lives in markdown so it can be edited without touching HTML.
This renderer is deliberately small and strict: it supports exactly the
constructs the report uses, and it fails loudly on anything it does not
recognise rather than silently emitting broken markup.

SYNTAX
------
  # Section title {#id}     starts a section (h2).  The id is the anchor
                            used by the contents bar and cross-links.
  ## Subheading             h3 inside the current section
  ### hero                  the title block (first section only)

  Plain paragraphs are separated by blank lines.

  !! Head line
     body line(s)           a highlighted finding box: the FIRST line is
                            the bold head, the rest of the block is the
                            body.  Keeping them on separate lines means a
                            head can contain any punctuation.

  ?? Head line              a bordered note box, same two-part rule
     body line(s)

  @figure some-id           an empty div the charts script fills in
  @table some-id            same, for a table built by the script
  @chart some-id            a chart div wrapped in <figure>; any following
    caption text...         lines in the block become its caption
  @html <div ...>...</div>  raw HTML escape hatch, one line

  | a | b |                 a markdown table; the first row is the header
  |---|---|                 (the separator row is optional)
  | 1 | 2 |

INLINE
------
  **bold**  *italic*  `code`  [text](url)
  {{anchor}}                  an injected number: <b id="anchor"></b>
  the charts script writes these, so prose can never hardcode a result
"""
from __future__ import annotations

import html
import re

_INLINE = (
    (re.compile(r"\{\{([a-z0-9-]+)\}\}"), r'<b id="\1"></b>'),
    (re.compile(r"\*\*(.+?)\*\*"), r"<b>\1</b>"),
    (re.compile(r"(?<![\w*])\*([^*\n]+?)\*(?![\w*])"), r"<i>\1</i>"),
    (re.compile(r"`([^`]+?)`"), r"<code>\1</code>"),
    (re.compile(r"\[([^\]]+)\]\(([^)]+)\)"), r'<a href="\2">\1</a>'),
)


class MarkdownError(Exception):
    pass


def inline(text: str) -> str:
    out = html.escape(text.strip(), quote=False)
    for pattern, repl in _INLINE:
        out = pattern.sub(repl, out)
    return out




def _table(rows: list[str]) -> str:
    cells = [[c.strip() for c in r.strip().strip("|").split("|")]
             for r in rows if not re.fullmatch(r"\|[\s:|-]+\|", r.strip())]
    if not cells:
        raise MarkdownError("empty table")
    head, *body = cells
    out = ["<table>", "<tr>" + "".join(f"<th>{inline(c)}</th>"
                                       for c in head) + "</tr>"]
    for row in body:
        out.append("<tr>" + "".join(f"<td>{inline(c)}</td>"
                                    for c in row) + "</tr>")
    out.append("</table>")
    return "\n".join(out)


def render(md: str) -> tuple[str, list[tuple[str, str]]]:
    """(body html, [(section id, title)]) for the contents bar."""
    blocks, current = [], []
    for line in md.split("\n"):
        if line.strip() == "":
            if current:
                blocks.append(current)
                current = []
        else:
            current.append(line)
    if current:
        blocks.append(current)

    out, sections, open_section = [], [], False
    hero: list[str] = []
    for block in blocks:
        first = block[0]
        text = " ".join(b.strip() for b in block)

        if first.startswith("### hero"):
            hero = block[1:]
            continue

        if first.startswith("# "):
            m = re.match(r"#\s+(.+?)\s*\{#([a-z0-9-]+)\}\s*$", first)
            if not m:
                raise MarkdownError(f"section needs a {{#id}}: {first!r}")
            title, sid = m.group(1), m.group(2)
            if open_section:
                out.append("</section>")
            out.append(f'<section id="{sid}">')
            out.append(f"<h2>{inline(title)}</h2>")
            sections.append((sid, title))
            open_section = True
            if len(block) > 1:
                raise MarkdownError(f"put a blank line after: {first!r}")
            continue

        if first.startswith("## "):
            out.append(f"<h3>{inline(first[3:])}</h3>")
            for extra in block[1:]:
                out.append(f"<p>{inline(extra)}</p>")
            continue

        if first.startswith("!!") or first.startswith("??"):
            kind = "finding" if first.startswith("!!") else "note"
            head = first[2:].strip()
            body = " ".join(b.strip() for b in block[1:])
            if not head:
                raise MarkdownError(f"{first[:2]} needs a head line")
            head_html = (f'<b class="head">{inline(head)}</b>'
                         if kind == "finding" else f"<b>{inline(head)}</b>")
            sep = " " if body else ""
            out.append(f'<div class="{kind}">{head_html}{sep}'
                       f"{inline(body)}</div>")
            continue

        if first.startswith("@figure ") or first.startswith("@table "):
            out.append(f'<div id="{first.split(None, 1)[1].strip()}"></div>')
            continue

        if first.startswith("@chart "):
            cid = first.split(None, 1)[1].strip()
            caption = " ".join(b.strip() for b in block[1:])
            out.append(f'<figure>\n  <div class="chart" id="{cid}"></div>\n'
                       f"  <figcaption>{inline(caption)}</figcaption>\n"
                       f"</figure>")
            continue

        if first.startswith("@html "):
            out.append(first[6:].strip())
            continue

        if first.lstrip().startswith("|"):
            out.append(_table(block))
            continue

        out.append(f"<p>{inline(text)}</p>")

    if open_section:
        out.append("</section>")

    toc = "".join(f'<a href="#{sid}">{html.escape(title)}</a>'
                  for sid, title in sections)
    header = ""
    if hero:
        title, subtitle, version = hero[0], hero[1], " ".join(hero[2:])
        header = (f'<header class="hero">\n<h1>{inline(title)}</h1>\n'
                  f'<p class="subtitle">{inline(subtitle)}</p>\n'
                  f'<p class="version">{inline(version)}</p>\n'
                  f'<div class="statstrip" id="statstrip"></div>\n</header>')
    body = ('<nav id="toc">\n  <span class="toc-head">Contents</span>'
            f'{toc}\n</nav>\n<main>\n{header}\n\n'
            + "\n\n".join(out) + "\n\n</main>\n")
    return body, sections


def render_file(path) -> str:
    body, _ = render(open(path, encoding="utf-8").read())
    return body
