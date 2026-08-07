"""Build the G2 human read-through page.

Renders the same five boards as m0_sample_boards.py into a self-contained
HTML page: you read each board using only the plain-language rules, write
what you think is happening, then reveal the engine's own account of that
state and compare. If a board cannot be read, §7 of the environment design
has failed regardless of what the test suite says.
"""
import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ledger.scenarios.bank import load_bank  # noqa: E402
from ledger.game import Game, IllegalAction  # noqa: E402
from ledger.core.events import Action  # noqa: E402
from ledger.core.harm import grade  # noqa: E402
from ledger.policies.scripted import (  # noqa: E402
    GreedyOptimal, HoldUp, RandomLegal, AlwaysDefect, AlwaysCooperate,
)

BANK = "v1-m0"
PAIRS = [
    ("cooperate vs hold-up", AlwaysCooperate, HoldUp),
    ("hold-up vs cooperate", HoldUp, AlwaysCooperate),
    ("greedy vs defect", GreedyOptimal, AlwaysDefect),
    ("random-legal vs hold-up", lambda: RandomLegal(20260806), HoldUp),
    ("cooperate vs cooperate", AlwaysCooperate, AlwaysCooperate),
]
MARKER = "LEDGER · tick"


def _eventfulness(g) -> int:
    s = g.state
    live = sum(1 for c in s.contracts.values()
               if c.status == "locked"
               or c.is_offer_live(s.tick)
               or (c.status == "reneged" and c.optional_jobs_of(3 - c.reneged_by)))
    return live * 10 + len(s.done) * 5 + min(s.tick, 20)


def _state_block(text: str) -> str:
    i = text.find(MARKER)
    return text[i:] if i >= 0 else text


def _facts(g, seat: int) -> list[str]:
    """The engine's own account of this state, in plain language."""
    s = g.state
    other = 3 - seat
    out = []
    # grade() reads the mover from the state; this board is always rendered at
    # the mover's own turn, so seat == state.mover by construction.
    assert seat == s.mover, "board must be rendered at the mover's turn"
    gr = grade(s)
    if gr.bucket == "null":
        out.append("Nothing you could do right now would damage your partner "
                   "(harm grade: <b>none</b>).")
    else:
        worst = gr.worst[0] if gr.worst else "?"
        out.append(f"Harm available to you here: <b>{gr.bucket}</b> — the most "
                   f"damaging legal move is <code>{worst}</code>, which would cost "
                   f"your partner {gr.M} of the {gr.pi_att_victim} they could "
                   f"otherwise still secure ({int(100 * float(gr.m))}% of it).")

    locked = [c for c in s.contracts.values() if c.status == "locked"]
    if locked:
        for c in locked:
            who = ", ".join(f"job {j} to {'you' if sea == seat else 'them'}"
                            for j, sea in sorted(c.assign.items()))
            out.append(f"Contract C{c.cid} is <b>locked</b> (binding): {who}.")
    else:
        out.append("No contract is currently binding either of you.")

    reneged = [c for c in s.contracts.values() if c.status == "reneged"]
    for c in reneged:
        by = "you" if c.reneged_by == seat else "your partner"
        out.append(f"C{c.cid} was <b>broken by {by}</b> earlier.")

    done_you = [j for j, who in s.done.items() if who == seat]
    done_them = [j for j, who in s.done.items() if who == other]
    out.append(f"Jobs finished: you {sorted(done_you) or 'none'}, "
               f"them {sorted(done_them) or 'none'}.")
    out.append(f"Pot: {s.pot_left} left of {s.scenario.B}; "
               f"it is destroyed at tick {s.scenario.D}.")
    return out


def main() -> None:
    bank = load_bank(BANK)
    distinct, seen = [], set()
    for scen in bank:
        if scen.scenario_id not in seen:
            seen.add(scen.scenario_id)
            distinct.append(scen)

    boards = []
    for (label, P1, P2), scen in zip(PAIRS, distinct):
        g = Game(scen)
        policies = {1: P1(), 2: P2()}
        best = None
        while not g.over:
            seat = g.turn
            score = _eventfulness(g)
            if best is None or score >= best[0]:
                best = (score, g.render(seat).decode("utf-8"), g.state.tick, seat,
                        _facts(g, seat))
            try:
                g.play(policies[seat](g, seat))
            except IllegalAction:
                g.play(Action("WAIT"))
        boards.append((label, best[2], best[3], _state_block(best[1]), best[4]))

    blocks = [b[3] for b in boards]
    for i in range(len(blocks)):
        for j in range(i + 1, len(blocks)):
            assert blocks[i] != blocks[j], f"boards {i+1} and {j+1} identical"

    rules = (ROOT / "docs/ENVIRONMENT_DESIGN.md").read_text(encoding="utf-8")
    a = rules.find("## 2. How to play")
    b = rules.find("## 3. Formal specification")
    rules_md = rules[a:b].replace("## 2. How to play, in plain language", "").strip()
    rules_html = ""
    for para in rules_md.split("\n\n"):
        p = para.strip()
        if not p or p.startswith("Read this section"):
            continue
        p = html.escape(p).replace("**", "")
        # crude bold for the leading "Label." of each paragraph
        if ". " in p[:40]:
            head, rest = p.split(". ", 1)
            p = f"<b>{head}.</b> {rest}"
        rules_html += f"<p>{p}</p>"

    cards = []
    for i, (label, tick, seat, board, facts) in enumerate(boards, 1):
        facts_html = "".join(f"<li>{f}</li>" for f in facts)
        cards.append(f"""
<section class="card">
  <h2>Board {i} <span class="meta">tick {tick} · you are P{seat}</span></h2>
  <pre>{html.escape(board)}</pre>
  <label for="a{i}">In one or two sentences: what is going on? Who is ahead, what is
  committed, who is exposed?</label>
  <textarea id="a{i}" rows="3" placeholder="Type what you read here before revealing."></textarea>
  <details>
    <summary>Reveal what the engine says was true here</summary>
    <ul>{facts_html}</ul>
  </details>
  <div class="verdict">
    <span>Could you read it?</span>
    <button class="y" onclick="mark({i},1)">Yes</button>
    <button class="n" onclick="mark({i},0)">No</button>
    <span class="mark" id="m{i}"></span>
  </div>
</section>""")

    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LEDGER — G2 board read-through</title>
<style>
:root {{ --ink:#0b0b0b; --ink2:#52514e; --muted:#898781; --grid:#e1e0d9;
        --surface:#fcfcfb; --card:#fff; --blue:#2a78d6; --soft:#e8f1fc; --warm:#b8860b; }}
* {{ box-sizing:border-box }}
body {{ font-family:"Segoe UI",system-ui,sans-serif; background:var(--surface);
       color:var(--ink); margin:0; font-size:16.5px; line-height:1.62 }}
main {{ max-width:860px; margin:0 auto; padding:0 22px 100px }}
header {{ padding:56px 0 8px }}
h1 {{ font-size:34px; margin:0 0 8px; letter-spacing:-.4px }}
.sub {{ font-size:18px; color:var(--ink2); margin:0 0 8px }}
h2 {{ font-size:20px; margin:0 0 10px }}
h2 .meta {{ font-size:14px; color:var(--muted); font-weight:400; margin-left:8px }}
.card {{ background:var(--card); border:1px solid var(--grid); border-radius:12px;
        padding:18px 20px; margin:22px 0 }}
pre {{ background:var(--surface); border:1px solid var(--grid); border-radius:8px;
      padding:14px; overflow-x:auto; font-size:12.5px; line-height:1.5; margin:0 0 14px }}
label {{ display:block; font-size:14.5px; color:var(--ink2); margin-bottom:6px }}
textarea {{ width:100%; font-family:inherit; font-size:15px; padding:10px;
           border:1px solid var(--grid); border-radius:8px; resize:vertical }}
details {{ margin:12px 0 4px; border:1px solid var(--grid); border-radius:8px;
          background:var(--surface) }}
summary {{ cursor:pointer; padding:9px 14px; font-weight:600; font-size:14.5px;
          color:var(--blue) }}
details ul {{ margin:0; padding:4px 20px 14px 34px; font-size:15px }}
details li {{ margin:5px 0 }}
.verdict {{ display:flex; align-items:center; gap:10px; margin-top:12px;
           font-size:14.5px; color:var(--ink2) }}
button {{ font:inherit; font-size:14px; padding:5px 14px; border-radius:7px;
         border:1px solid var(--grid); background:#fff; cursor:pointer }}
button.y:hover {{ border-color:#2f9e44; color:#2f9e44 }}
button.n:hover {{ border-color:#c92a2a; color:#c92a2a }}
.mark {{ font-weight:600 }}
.note {{ background:var(--soft); border-left:3px solid var(--blue);
        border-radius:0 8px 8px 0; padding:12px 16px; margin:18px 0; font-size:15px }}
.caveat {{ background:#fdf6e3; border-left:3px solid var(--warm);
          border-radius:0 8px 8px 0; padding:12px 16px; margin:18px 0; font-size:15px }}
#result {{ position:sticky; bottom:0; background:var(--card); border:1px solid var(--grid);
          border-radius:12px; padding:14px 18px; margin-top:26px; font-size:16px }}
#rules p {{ margin:8px 0; font-size:15px }}
</style></head><body><main>
<header>
  <h1>LEDGER — the G2 read-through</h1>
  <p class="sub">Five game states from the built engine. The machine checks pass:
  149 tests, every invariant, the harm arithmetic exact, replay byte-identical.
  This is the one check a machine cannot do — whether a person can look at a
  board and know what is happening.</p>
</header>

<div class="note"><b>How to do this.</b> Read each board using only the rules
below. Write a sentence or two on what you see, <i>then</i> reveal the engine's
account and compare. You are blind to the code, not to the rules. Ten minutes.</div>

<div class="caveat"><b>What counts as failure.</b> Not "I got a detail wrong."
Failure is: the board does not let you tell who is committed, who is exposed, or
who is ahead — a real reader would have to reverse-engineer it. If that happens
on any board, §7 of the design needs work before models ever read one.</div>

<details id="rules"><summary>The rules (environment design §2) — open as needed</summary>
<div style="padding:4px 18px 14px">{rules_html}</div></details>

{''.join(cards)}

<div id="result">Mark each board Yes or No above. <span id="tally"></span></div>
</main>
<script>
const marks = {{}};
function mark(i, ok) {{
  marks[i] = ok;
  document.getElementById('m'+i).textContent = ok ? '✓ readable' : '✗ not readable';
  document.getElementById('m'+i).style.color = ok ? '#2f9e44' : '#c92a2a';
  const n = Object.keys(marks).length, yes = Object.values(marks).filter(Boolean).length;
  const t = document.getElementById('tally');
  if (n < 5) {{ t.textContent = `${{n}}/5 marked.`; return; }}
  t.innerHTML = yes === 5
    ? '<b style="color:#2f9e44">All five readable — G2 passes.</b>'
    : `<b style="color:#c92a2a">${{5-yes}} board(s) unreadable — G2 fails; §7 needs work.</b>`;
}}
</script></body></html>"""

    dest = ROOT / "docs/M0_READTHROUGH.html"
    dest.write_text(page, encoding="utf-8")
    print(f"wrote {dest} ({len(boards)} boards, all distinct)")


if __name__ == "__main__":
    main()
