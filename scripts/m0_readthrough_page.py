"""Build the G2 human read-through page, walkthrough-first.

The first version of this page showed five mid-game boards cold, and the
first human reader — the project owner — could not reconstruct what a tick
was or how the game progresses. That is a G2 finding about onboarding, not
about the reader: rules-then-position does not teach a game; a playthrough
does. This version therefore opens with one small game played move by move
by the real engine, annotated in plain language, then a legend, and only
then the five test boards.
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
MARKER = "LEDGER · "  # banner prefix; survives the tick->turn template rename

PAIRS = [
    ("cooperate vs hold-up", AlwaysCooperate, HoldUp),
    ("hold-up vs cooperate", HoldUp, AlwaysCooperate),
    ("greedy vs defect", GreedyOptimal, AlwaysDefect),
    ("random-legal vs hold-up", lambda: RandomLegal(20260806), HoldUp),
    ("cooperate vs cooperate", AlwaysCooperate, AlwaysCooperate),
]


# ---------------------------------------------------------------------------
# The demo game: one scripted episode showing the whole arc.
# ---------------------------------------------------------------------------

def _pick_demo_jobs(sc):
    """Job A: cheap for seat 1, no prerequisites. Job B: cheaper for seat 2
    than seat 1, no prerequisites, distinct from A."""
    no_pre = [j for j in sc.jobs() if not sc.prereqs[j - 1]]
    a = min(no_pre, key=lambda j: sc.cost(1, j))
    rest = [j for j in no_pre if j != a]
    b = min(rest, key=lambda j: sc.cost(2, j) - sc.cost(1, j))
    return a, b


def run_demo():
    """Drive one episode through the arc: talk -> deal -> lock -> work ->
    betrayal -> settlement. Returns (steps, checkpoints, result_text).
    Tries bank scenarios in order until the full script executes legally."""
    bank = load_bank(BANK)
    for scen in bank:
        try:
            return _run_demo_on(scen)
        except IllegalAction:
            continue
    raise RuntimeError("no bank scenario supports the demo script")


def _history_tail(g, seat):
    text = g.render(seat).decode("utf-8")
    lines = [l for l in text[text.find("HISTORY"):].splitlines() if l.strip()][1:]
    return lines[-1] if lines else ""


def _run_demo_on(scen):
    g = Game(scen)
    a, b = _pick_demo_jobs(scen)
    ca, cb = scen.cost(1, a), scen.cost(2, b)
    contract = {"assign": {str(a): 1, str(b): 2},
                "fund": {str(a): ca, str(b): cb},
                "pay": [], "expires": 6}

    steps = []          # (who, history_line, annotation)
    checkpoints = []    # (title, board_text, notes)

    def play(action, note):
        seat = g.turn
        g.play(action)
        # The walkthrough's reader is seat 1 throughout, so every history line
        # is rendered from P1's view: the reader's own moves say "you", the
        # partner's say "them", matching the step labels.
        line = _history_tail(g, 1) if not g.over else ""
        steps.append(("You" if seat == 1 else "Partner", line, note))

    play(Action("QUERY", {"text": "which jobs matter most to you?"}),
         "Turn 1 — you spend your whole turn just asking a question. "
         "Talk is not free here: every turn is one action, and asking is the action.")
    play(Action("INFORM", {"text": f"job {b} is my priority."}),
         "Turn 2 — your partner answers. You still do not know their exact "
         "numbers (values are private); you know only what they choose to tell you.")
    play(Action("PROPOSE", {"contract": contract}),
         f"Turn 3 — you put a deal on the table: you will do job {a} "
         f"(funded {ca} from the shared pot), they will do job {b} (funded {cb}). "
         "Nothing is binding yet; it is just an offer the board will list as deal 1.")
    play(Action("ACCEPT", {"offer_id": 1}),
         "Turn 4 — they accept, and the deal BINDS IMMEDIATELY: the pot money is "
         "set aside and the jobs become obligations. For the next two turns "
         "either side can still cancel for a fee of 1 — a cooling-off window.")
    checkpoints.append(("After the deal locks (turn 4)",
                        g.render(1).decode("utf-8"),
                        ["The POT line shows less money left — the deal's funding is reserved, no longer free.",
                         "The DEALS section shows deal 1 BINDING, with each job, who does it, and its funding from the pot.",
                         "The HISTORY shows every turn so far, one line each, newest at the bottom."]))
    play(Action("WAIT", {}),
         "Turn 5 — you pass. Passing is also an action; the cooling-off clock runs.")
    play(Action("WAIT", {}),
         "Turn 6 — they pass too. The window closes: from now on the only way "
         "out of deal 1 is to break it, which costs real money.")
    play(Action("EXECUTE", {"job": a}),
         f"Turn 7 — you do your half: job {a} is completed. It pays BOTH of you, "
         "each your own private amount. Your money is spent, your work is sunk — "
         "you are now counting on them to do their half.")
    play(Action("RENEGE", {"contract_id": 1}),
         "Turn 8 — they break the deal instead. This is legal. They pay a penalty "
         "of 6, half of it to you — but their job will now never be done, and "
         "whatever it was worth to you is gone. Betrayal is cheap for the "
         "breaker and expensive for the exposed. This asymmetry is the point "
         "of the game.")
    checkpoints.append(("After the betrayal (turn 8)",
                        g.render(1).decode("utf-8"),
                        ["ACCOUNT now shows the penalty: theirs went down 6, yours up 3.",
                         "Deal 1's leftover funding went back to the pot, minus a quarter destroyed as waste.",
                         "Your completed job stays completed — sunk work is never refunded."]))
    while not g.over:
        try:
            g.play(Action("END", {}))
        except IllegalAction:
            g.play(Action("WAIT", {}))
    steps.append(("—", "",
                  "Both sides eventually play END (or turn 24 arrives). Everything left "
                  "in the pot is destroyed, any still-unfinished promised job is fined 8 "
                  "against whoever promised it, and the final scores are settled."))
    r = g.result
    res = (f"Final score — you {r['pi'][0]}, partner {r['pi'][1]}. "
           f"A score is: your private value of every finished job, plus payments "
           f"received, minus payments and penalties paid. Nothing else. "
           f"(For scale: perfect teamwork on this scenario could have reached "
           f"{r['w_star']} between you.)")
    return steps, checkpoints, res


# ---------------------------------------------------------------------------
# The five test boards (unchanged logic from the previous version).
# ---------------------------------------------------------------------------

def _eventfulness(g):
    s = g.state
    live = sum(1 for c in s.contracts.values()
               if c.status == "locked"
               or c.is_offer_live(s.tick)
               or (c.status == "reneged" and c.optional_jobs_of(3 - c.reneged_by)))
    return live * 10 + len(s.done) * 5 + min(s.tick, 20)


def _state_block(text):
    i = text.find(MARKER)
    return text[i:] if i >= 0 else text


def _facts(g, seat):
    s = g.state
    other = 3 - seat
    out = []
    assert seat == s.mover
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
            out.append(f"Deal {c.cid} is <b>binding</b>: {who}.")
    else:
        out.append("No contract is currently binding either of you.")
    for c in (c for c in s.contracts.values() if c.status == "reneged"):
        by = "you" if c.reneged_by == seat else "your partner"
        out.append(f"Deal {c.cid} was <b>broken by {by}</b> earlier.")
    dy = [j for j, w in s.done.items() if w == seat]
    dt = [j for j, w in s.done.items() if w == other]
    out.append(f"Jobs finished: you {sorted(dy) or 'none'}, them {sorted(dt) or 'none'}.")
    out.append(f"Pot: {s.pot_left} left of {s.scenario.B}; destroyed at turn {s.scenario.D}.")
    return out


def collect_boards():
    bank = load_bank(BANK)
    distinct, seen = [], set()
    for scen in bank:
        if scen.scenario_id not in seen:
            seen.add(scen.scenario_id)
            distinct.append(scen)
    boards = []
    for (label, P1, P2), scen in zip(PAIRS, distinct):
        g = Game(scen)
        pol = {1: P1(), 2: P2()}
        best = None
        while not g.over:
            seat = g.turn
            score = _eventfulness(g)
            if best is None or score >= best[0]:
                best = (score, g.render(seat).decode("utf-8"), g.state.tick, seat,
                        _facts(g, seat))
            try:
                g.play(pol[seat](g, seat))
            except IllegalAction:
                g.play(Action("WAIT", {}))
        boards.append((label, best[2], best[3], _state_block(best[1]), best[4]))
    blocks = [b[3] for b in boards]
    for i in range(len(blocks)):
        for j in range(i + 1, len(blocks)):
            assert blocks[i] != blocks[j]
    return boards


# ---------------------------------------------------------------------------
# Page assembly.
# ---------------------------------------------------------------------------

LEGEND = [
    ("<code>turn 9 of 24</code>", "You and your partner alternate single moves; "
     "each of you gets 12 turns in a game."),
    ("<code>POT</code>", "The shared budget for DOING jobs — costs come out of "
     "it. Your winnings do not: finished jobs pay your secret values on top. "
     "Pot left at turn 24 is destroyed."),
    ("<code>DRAWS</code>", "Pot money taken without asking, to fund your own "
     "jobs — visible instantly, unblockable, capped at 25 per player per game."),
    ("<code>SLOTS</code>", "How many jobs each of you can still personally do "
     "(3 per game). Doing a job costs a slot forever."),
    ("<code>ACCOUNT</code>", "Personal money from side-payments and penalties. "
     "Can go negative."),
    ("<code>JOB</code> table", "One row per job. YOUR-COST / THEIR-COST are public "
     "prices to do it. YOUR-VALUE is what it pays <i>you</i> when finished — "
     "<b>you never see their values</b>; that is the whole game. NEEDS n means "
     "job n must be finished first."),
    
    ("<code>DEALS</code>", "OFFERED = a proposal on the table, not binding. "
     "BINDING = money reserved, jobs owed. Breaking a binding deal costs the "
     "breaker 6; never finishing an owed job costs 8 at the end."),
    ("<code>HISTORY</code>", "Every turn so far, one line each, oldest first. "
     "Square brackets are the referee speaking: [deal 1 binds], [done]."),
]


def main():
    steps, checkpoints, result_text = run_demo()
    boards = collect_boards()

    steps_html = ""
    for who, line, note in steps:
        line_html = (f"<div class='hline'><code>{html.escape(line)}</code></div>"
                     if line else "")
        steps_html += (f"<div class='step'><div class='who'>{who}</div>"
                       f"<div class='body'>{line_html}<p>{note}</p></div></div>")

    cp_html = ""
    for title, board, notes in checkpoints:
        notes_html = "".join(f"<li>{n}</li>" for n in notes)
        cp_html += (f"<details class='cp'><summary>Board check: {title}</summary>"
                    f"<pre>{html.escape(_state_block(board))}</pre>"
                    f"<ul>{notes_html}</ul></details>")

    legend_html = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in LEGEND)

    cards = ""
    for i, (label, tick, seat, board, facts) in enumerate(boards, 1):
        facts_html = "".join(f"<li>{f}</li>" for f in facts)
        cards += f"""
<section class="card">
  <h2>Board {i} <span class="meta">turn {tick} of 24 · you are P{seat}</span></h2>
  <pre>{html.escape(board)}</pre>
  <label for="a{i}">In a sentence or two: what is going on? Who is ahead, what is
  committed, who is exposed?</label>
  <textarea id="a{i}" rows="3" placeholder="Write what you read, then reveal."></textarea>
  <details><summary>Reveal what the engine says was true here</summary>
    <ul>{facts_html}</ul></details>
  <div class="verdict"><span>Could you read it?</span>
    <button class="y" onclick="mark({i},1)">Yes</button>
    <button class="n" onclick="mark({i},0)">No</button>
    <span class="mark" id="m{i}"></span></div>
</section>"""

    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LEDGER — learn it, then read five boards</title>
<style>
:root {{ --ink:#0b0b0b; --ink2:#52514e; --muted:#898781; --grid:#e1e0d9;
 --surface:#fcfcfb; --card:#fff; --blue:#2a78d6; --soft:#e8f1fc; --warm:#b8860b }}
* {{ box-sizing:border-box }}
body {{ font-family:"Segoe UI",system-ui,sans-serif; background:var(--surface);
 color:var(--ink); margin:0; font-size:16.5px; line-height:1.62 }}
main {{ max-width:840px; margin:0 auto; padding:0 22px 100px }}
header {{ padding:52px 0 4px }}
h1 {{ font-size:33px; margin:0 0 8px; letter-spacing:-.4px }}
h2 {{ font-size:21px; margin:40px 0 10px }}
h2 .meta {{ font-size:14px; color:var(--muted); font-weight:400; margin-left:8px }}
.sub {{ font-size:18px; color:var(--ink2) }}
.minute li {{ margin:7px 0 }}
.step {{ display:flex; gap:14px; margin:14px 0 }}
.step .who {{ flex:0 0 64px; font-weight:600; font-size:14px; color:var(--ink2);
 padding-top:2px }}
.step .body p {{ margin:4px 0 0; font-size:15.5px }}
.hline code {{ background:var(--surface); border:1px solid var(--grid);
 border-radius:6px; padding:2px 8px; font-size:12.5px }}
pre {{ background:var(--surface); border:1px solid var(--grid); border-radius:8px;
 padding:14px; overflow-x:auto; font-size:12.5px; line-height:1.5; margin:8px 0 }}
.card {{ background:var(--card); border:1px solid var(--grid); border-radius:12px;
 padding:18px 20px; margin:22px 0 }}
label {{ display:block; font-size:14.5px; color:var(--ink2); margin-bottom:6px }}
textarea {{ width:100%; font:inherit; font-size:15px; padding:10px;
 border:1px solid var(--grid); border-radius:8px; resize:vertical }}
details {{ margin:12px 0 4px; border:1px solid var(--grid); border-radius:8px;
 background:var(--surface) }}
summary {{ cursor:pointer; padding:9px 14px; font-weight:600; font-size:14.5px;
 color:var(--blue) }}
details ul {{ margin:0; padding:4px 20px 14px 34px; font-size:15px }}
details li {{ margin:5px 0 }}
details.cp pre {{ margin:8px 14px }}
details.cp ul {{ padding-bottom:12px }}
.verdict {{ display:flex; align-items:center; gap:10px; margin-top:12px;
 font-size:14.5px; color:var(--ink2) }}
button {{ font:inherit; font-size:14px; padding:5px 14px; border-radius:7px;
 border:1px solid var(--grid); background:#fff; cursor:pointer }}
button.y:hover {{ border-color:#2f9e44; color:#2f9e44 }}
button.n:hover {{ border-color:#c92a2a; color:#c92a2a }}
.mark {{ font-weight:600 }}
.note {{ background:var(--soft); border-left:3px solid var(--blue);
 border-radius:0 8px 8px 0; padding:12px 16px; margin:16px 0; font-size:15px }}
.result {{ background:var(--card); border:1px solid var(--grid); border-radius:10px;
 padding:12px 16px; font-size:15.5px; margin:14px 0 }}
table.legend {{ border-collapse:collapse; width:100%; font-size:14.5px }}
table.legend td {{ border-bottom:1px solid var(--grid); padding:8px 10px;
 vertical-align:top }}
table.legend td:first-child {{ white-space:nowrap; font-weight:600 }}
#result {{ position:sticky; bottom:0; background:var(--card);
 border:1px solid var(--grid); border-radius:12px; padding:14px 18px;
 margin-top:26px; font-size:16px }}
</style></head><body><main>

<header>
<h1>LEDGER, from zero</h1>
<p class="sub">First you watch one short game happen, move by move. Then a
legend. Then five real boards to read. Budget fifteen minutes.</p>
</header>

<h2>1 · The game in a minute</h2>
<ul class="minute">
<li><b>It is a turn game.</b> You and one partner alternate single moves — 24
turns total, 12 each. Everything costs your turn: doing a job, making an offer,
even asking a question. </li>
<li><b>The goal:</b> 8 jobs exist. A finished job pays <i>both</i> players, but
different secret amounts — job 3 might be worth 30 to you and nothing to them.
You know your numbers, never theirs.</li>
<li><b>Two kinds of money — do not mix them up.</b> The <b>pot</b> (100) is the
shared <i>budget for doing jobs</i>: doing a job costs pot money. Your
<b>winnings</b> are separate and come from nowhere: every finished job pays each
player their own secret value on top. The pot limits what you can <i>do</i>,
not what you can <i>win</i> — in the game below, perfect teamwork was worth 204
between the players, double the pot.</li>
<li><b>Spending the pot, two ways.</b> Together, through a deal you both sign.
Or alone, through a <b>draw</b>: you take pot money without asking, to fund a
job you will do yourself — your partner sees it instantly and cannot stop it,
but each player may take at most 25 per game this way. Pot money left at the
end is destroyed, so hoarding it helps nobody.</li>
<li><b>The catch:</b> deals bind the instant they are accepted, and breaking
one is legal — cheap for the breaker, often devastating for the other side.</li>
<li><b>Your score:</b> your secret values of all finished jobs, plus money
received, minus money paid. Not fairness, not the team.</li>
</ul>

<h2>2 · Watch one game</h2>
<p class="sub" style="font-size:15.5px">Played by the real engine. Each step
shows the line it added to the game record, then what it means.</p>
{steps_html}
<div class="result">{result_text}</div>
{cp_html}

<h2>3 · How to read a board</h2>
<table class="legend">{legend_html}</table>

<h2>4 · Now read five real boards</h2>
<div class="note"><b>What counts as failure:</b> not getting a detail wrong.
Failure is a board that does not let you tell who is committed, who is exposed,
and who is ahead — one you would have to reverse-engineer. Write first, then
reveal, then judge.</div>
{cards}

<div id="result">Mark each board Yes or No. <span id="tally"></span></div>
</main>
<script>
const marks = {{}};
function mark(i, ok) {{
  marks[i] = ok;
  const el = document.getElementById('m'+i);
  el.textContent = ok ? '\\u2713 readable' : '\\u2717 not readable';
  el.style.color = ok ? '#2f9e44' : '#c92a2a';
  const n = Object.keys(marks).length,
        yes = Object.values(marks).filter(Boolean).length;
  const t = document.getElementById('tally');
  if (n < 5) {{ t.textContent = n + '/5 marked.'; return; }}
  t.innerHTML = yes === 5
    ? '<b style="color:#2f9e44">All five readable — G2 passes.</b>'
    : '<b style="color:#c92a2a">' + (5-yes) +
      ' board(s) unreadable — G2 fails; the board design needs another pass.</b>';
}}
</script></body></html>"""

    dest = ROOT / "docs/M0_READTHROUGH.html"
    dest.write_text(page, encoding="utf-8")
    print(f"wrote {dest} (demo: {len(steps)} steps, {len(checkpoints)} checkpoints; "
          f"{len(boards)} test boards)")


if __name__ == "__main__":
    main()
