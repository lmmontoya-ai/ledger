/* Charts and injected figures for the LEDGER design report.
   D (harvested from the engine) is injected before this script. Every number
   the prose states is also written here from D, so prose and data cannot
   disagree -- the failure mode that once shipped a stale chart in the
   Predictive Commons report. */
(function () {
  const BLUE = "#2a78d6", GRAY = "#c3c2b7", INK = "#0b0b0b", INK2 = "#52514e",
        MUTED = "#898781", GRID = "#e1e0d9";
  const fmt = (v, d = 0) => (+v).toFixed(d);
  const pct = v => Math.round(100 * v) + "%";
  function svgEl(tag, attrs) {
    const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const k in attrs) el.setAttribute(k, attrs[k]);
    return el;
  }
  function setText(id, v) { const e = document.getElementById(id); if (e) e.textContent = v; }

  /* ---- hero stat strip ---- */
  (function () {
    const el = document.getElementById("statstrip"); if (!el) return;
    const s = D.scenario, w = D.welfare;
    [[2, "agents"], [s.turns, "turns"], [s.jobs, "jobs"],
     [s.pot, "shared pot"], [w.w_star_median, "worth cooperating"],
     [w.alone_median, "worth alone"]].forEach(([v, label]) => {
      const d = document.createElement("div"); d.className = "stat";
      const b = document.createElement("b"); b.textContent = v;
      const sp = document.createElement("span"); sp.textContent = label;
      d.appendChild(b); d.appendChild(sp); el.appendChild(d);
    });
  })();

  /* ---- numbers quoted in the prose, written from the data ---- */
  setText("wstar", D.welfare.w_star_median);
  setText("wstar2", D.welfare.w_star_median);
  setText("alone", D.welfare.alone_median);
  setText("gap", pct(D.welfare.gap_median));
  setText("reneges", D.play.reneges);
  setText("defaults", D.play.defaults);
  if (D.demo) {
    setText("demo-scores", `${D.demo.pi[0]} and ${D.demo.pi[1]}`);
    setText("demo-wstar", D.demo.w_star);
  }

  /* ---- harm-availability chart ---- */
  (function () {
    const el = document.getElementById("c-harm"); if (!el) return;
    const order = ["null", "minor", "moderate", "major"];
    const names = { null: "none available", minor: "minor", moderate: "moderate", major: "major" };
    const rows = order.filter(k => D.play.harm_share[k] != null)
                      .map(k => ({ label: names[k], v: D.play.harm_share[k] }));
    const w = 860, rowH = 44, labW = 190, h = rows.length * rowH + 46;
    const svg = svgEl("svg", { viewBox: `0 0 ${w} ${h}`, width: "100%" });
    el.appendChild(svg);
    const max = Math.max(...rows.map(r => r.v)) * 1.15;
    const X = v => labW + (w - labW - 90) * v / max;
    rows.forEach((r, i) => {
      const y = i * rowH + 6;
      const t = svgEl("text", { x: labW - 12, y: y + 20, "text-anchor": "end",
        "font-size": 14, fill: INK2 });
      t.textContent = r.label; svg.appendChild(t);
      const bar = svgEl("rect", { x: X(0), y: y + 4, width: Math.max(2, X(r.v) - X(0)),
        height: 22, rx: 5, fill: r.label === "none available" ? GRAY : BLUE });
      svg.appendChild(bar);
      const v = svgEl("text", { x: X(r.v) + 9, y: y + 21, "font-size": 13.5,
        fill: INK, "font-weight": 600 });
      v.textContent = pct(r.v); svg.appendChild(v);
    });
    const cap = svgEl("text", { x: labW, y: h - 12, "font-size": 12.5, fill: MUTED });
    cap.textContent = `${D.play.n_turns.toLocaleString("en-US")} decisions across `
      + `${D.play.n_episodes} scripted games`;
    svg.appendChild(cap);
  })();

  /* ---- the worked game, step by step ---- */
  (function () {
    const el = document.getElementById("walkthrough");
    if (!el || !D.demo) return;
    D.demo.steps.forEach(s => {
      const row = document.createElement("div"); row.className = "step";
      const who = document.createElement("div"); who.className = "who";
      who.textContent = s.who;
      const body = document.createElement("div"); body.className = "body";
      if (s.line) {
        const c = document.createElement("div"); c.className = "hline";
        const code = document.createElement("code"); code.textContent = s.line;
        c.appendChild(code); body.appendChild(c);
      }
      const p = document.createElement("p"); p.textContent = s.note;
      body.appendChild(p);
      row.appendChild(who); row.appendChild(body); el.appendChild(row);
    });
  })();

  /* ---- the board an agent reads ---- */
  (function () {
    const el = document.getElementById("board-sample");
    if (!el || !D.board) return;
    const pre = document.createElement("pre");
    pre.textContent = D.board;
    el.appendChild(pre);
    const cap = document.createElement("div");
    cap.className = "fcap";
    const t = D.tokens && D.tokens.o200k_base;
    cap.textContent = t
      ? `The changing part of one prompt: ${t.board} tokens for this screen, on top of `
        + `a ${t.system}-token rule block that is identical in every call and therefore cached.`
      : "The changing part of one prompt.";
    el.appendChild(cap);
  })();

  setText("ntests", D.tests || 151);
})();
