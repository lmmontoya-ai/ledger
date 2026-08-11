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

  /* ---- the action vocabulary, from the frozen spec ---- */
  (function () {
    const el = document.getElementById("action-table");
    if (!el || !D.actions) return;
    const t = document.createElement("table");
    t.innerHTML = "<tr><th>Action</th><th>Takes</th><th>What it does</th></tr>";
    D.actions.rows.forEach(r => {
      const tr = document.createElement("tr");
      const a = document.createElement("td");
      const code = document.createElement("code"); code.textContent = r.name;
      a.appendChild(code);
      const b = document.createElement("td");
      b.textContent = r.args === "none" ? "\u2014" : r.args;
      b.style.whiteSpace = "nowrap";
      const c = document.createElement("td"); c.textContent = r.what;
      tr.appendChild(a); tr.appendChild(b); tr.appendChild(c);
      t.appendChild(tr);
    });
    el.appendChild(t);
  })();
  /* ---- pilot results, injected from the experiment artifacts ---- */
  (function () {
    const P = D.pilot;
    if (!P) return;
    setText("p-games", P.games);
    setText("p-dec", P.decisions);
    setText("p-spend", P.spend_total);
    setText("p-mandate-pairs", P.axes[0].pairs.split("/")[1]);
    setText("p-ent-neg", P.entropy_negotiation.toFixed(2));
    setText("p-ent-mech", P.entropy_mechanical.toFixed(2));
    setText("p-profitable", P.premiums.n_profitable);
    setText("p-maxprem", "+" + P.premiums.max);
    setText("p-reneges", P.reneges);
    setText("p-c6loss", P.c6_median_loss);
    setText("p-sens-r1", P.sens_r1);
    setText("p-sens-lowt", P.sens_lowt);
    setText("p-c5-real", P.c5_real.toFixed(2));
    setText("p-c5-filler", P.c5_filler.toFixed(2));
    function table(id, header, rows) {
      const el = document.getElementById(id);
      if (!el) return;
      const t = document.createElement("table");
      t.innerHTML = "<tr>" + header.map(h => `<th>${h}</th>`).join("") + "</tr>";
      rows.forEach(r => {
        const tr = document.createElement("tr");
        r.forEach(c => {
          const td = document.createElement("td");
          td.textContent = c;
          tr.appendChild(td);
        });
        t.appendChild(tr);
      });
      el.appendChild(t);
    }
    table("axes-table",
          ["Comparison", "Decisions told apart", "Pairs told apart"],
          P.axes.map(a => [a.name, Math.round(100 * a.rate) + "%", a.pairs]));
    table("mandate-table",
          ["Instruction", "Games", "Mean efficiency", "Agreements",
           "Contracts broken"],
          Object.entries(P.mandates).map(([m, v]) =>
            [m, v.n, v.mean_efficiency.toFixed(2),
             Math.round(100 * v.agreement_rate) + "%", v.reneges]));
    table("views-table",
          ["What the predictor saw", "Prediction error (excess bits)"],
          [["The board alone", P.views["L0"].mean_excess.toFixed(3)],
           ["+ the mover's actions, counted",
            P.views["C-count"].mean_excess.toFixed(3)],
           ["+ the mover's actions, in order",
            P.views["C-target"].mean_excess.toFixed(3)],
           ["+ the mover's actions, shuffled",
            P.views["C-shuf"].mean_excess.toFixed(3)]]);

    /* ---- who predicts whom: matrix, forest, self-vs-other ---- */
    const F = P.forecast;
    if (!F) return;
    const NAME = { luna: "Luna", sonnet: "Sonnet", grok: "Grok" };
    const ORDER = ["luna", "sonnet", "grok"];

    (function () {
      const el = document.getElementById("matrix-table"); if (!el) return;
      const t = document.createElement("table");
      t.innerHTML = "<tr><th>Predictor</th>"
        + ORDER.map(m => `<th>predicting ${NAME[m]}</th>`).join("") + "</tr>";
      const vals = ORDER.flatMap(p => ORDER.map(q => F.matrix[p][q].mean));
      const vmax = Math.max(...vals);
      ORDER.forEach(p => {
        const tr = document.createElement("tr");
        const h = document.createElement("td");
        h.textContent = NAME[p]; h.style.fontWeight = 600;
        tr.appendChild(h);
        ORDER.forEach(q => {
          const c = F.matrix[p][q];
          const td = document.createElement("td");
          td.textContent = c.mean.toFixed(2);
          td.style.textAlign = "center";
          td.style.background =
            `rgba(42,120,214,${(0.45 * c.mean / vmax).toFixed(3)})`;
          if (p === q) { td.style.fontWeight = 700; td.style.outline = `2px solid ${INK}`; td.style.outlineOffset = "-2px"; }
          tr.appendChild(td);
        });
        t.appendChild(tr);
      });
      el.appendChild(t);
      const cap = document.createElement("div"); cap.className = "fcap";
      cap.textContent = "Prediction error in excess bits (0 = as accurate as "
        + "a fresh sample of the target itself; darker = worse). Boxed "
        + "diagonal = a model predicting itself.";
      el.appendChild(cap);
    })();

    /* dot-and-interval rows shared by the two charts */
    function dotChart(elId, rows, caption) {
      const el = document.getElementById(elId); if (!el) return;
      const w = 860, rowH = 36, labW = 250, padR = 30, axisH = 30;
      const h = rows.length * rowH + axisH + 14;
      const hi = Math.max(...rows.flatMap(r => r.pts.map(p => p.hi ?? p.v)));
      const xmax = Math.max(0.1, Math.ceil(hi * 10) / 10);
      const X = v => labW + (w - labW - padR) * v / xmax;
      const svg = svgEl("svg", { viewBox: `0 0 ${w} ${h}`, width: "100%" });
      el.appendChild(svg);
      for (let v = 0; v <= xmax + 1e-9; v += 0.1) {
        svg.appendChild(svgEl("line", { x1: X(v), y1: 2, x2: X(v),
          y2: h - axisH, stroke: v < 0.05 ? INK2 : GRID,
          "stroke-width": v < 0.05 ? 1.5 : 1 }));
        const t = svgEl("text", { x: X(v), y: h - axisH + 16,
          "text-anchor": "middle", "font-size": 12, fill: MUTED });
        t.textContent = v.toFixed(1); svg.appendChild(t);
      }
      rows.forEach((r, i) => {
        const y = i * rowH + rowH / 2;
        const lab = svgEl("text", { x: labW - 12, y: y + 4,
          "text-anchor": "end", "font-size": 13.5,
          fill: r.strong ? INK : INK2, "font-weight": r.strong ? 600 : 400 });
        lab.textContent = r.label; svg.appendChild(lab);
        r.pts.forEach(p => {
          if (p.lo != null) svg.appendChild(svgEl("line", { x1: X(p.lo),
            y1: y + p.dy, x2: X(p.hi), y2: y + p.dy, stroke: p.color,
            "stroke-width": 2 }));
          svg.appendChild(svgEl("circle", { cx: X(p.v), cy: y + p.dy, r: 5,
            fill: p.color }));
        });
      });
      const cap = document.createElement("div"); cap.className = "fcap";
      cap.textContent = caption; el.appendChild(cap);
    }

    (function () {
      const rows = [];
      ORDER.forEach(tgt => {
        const cells = ORDER.map(p => ({ p, c: F.matrix[p][tgt] }))
          .sort((a, b) => a.c.mean - b.c.mean);
        cells.forEach(({ p, c }) => rows.push({
          label: (p === tgt ? `${NAME[p]} about itself`
                            : `${NAME[p]} about ${NAME[tgt]}`),
          strong: p === tgt,
          pts: [{ v: c.mean, lo: c.lo, hi: c.hi, dy: 0,
                  color: p === tgt ? BLUE : GRAY }]
        }));
      });
      dotChart("forest-plot", rows,
        "Mean prediction error per predictor-target pair, 95% interval, "
        + "all 96 frozen decisions. Blue = a model predicting itself. "
        + "0 = indistinguishable from the target's own repeat runs.");
    })();

    (function () {
      const PH = { negotiation: "Negotiation", execution: "Execution",
                   endgame: "Endgame" };
      const rows = [];
      for (const ph of ["negotiation", "execution", "endgame"]) {
        const s = F.self_other.by_phase[ph];
        rows.push({ label: PH[ph],
          strong: ph === "negotiation",
          pts: [{ v: s.self.mean, lo: s.self.lo, hi: s.self.hi, dy: -5,
                  color: BLUE },
                { v: s.other.mean, lo: s.other.lo, hi: s.other.hi, dy: 6,
                  color: GRAY }] });
      }
      dotChart("selfother-plot", rows,
        "Blue = predicting yourself, gray = predicting the other two "
        + "models. 95% intervals; one point per frozen decision, the four "
        + "views averaged first.");
      const n = F.self_other.by_phase.negotiation;
      setText("p-fx-selfneg", n.self.mean.toFixed(2));
      setText("p-fx-otherneg", n.other.mean.toFixed(2));
      setText("p-fx-luna-self", F.matrix.luna.luna.mean.toFixed(2));
      setText("p-fx-sonnet-self", F.matrix.sonnet.sonnet.mean.toFixed(2));
      setText("p-fx-grok-self", F.matrix.grok.grok.mean.toFixed(2));
      setText("p-fx-sonnet-grok", F.matrix.sonnet.grok.mean.toFixed(2));
      setText("p-fx-luna-grok", F.matrix.luna.grok.mean.toFixed(2));
    })();
  })();
  setText("ntests", D.tests || 151);
})();
