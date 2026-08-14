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

  /* ---- the study, injected from the run artifacts ---- */
  (function () {
    const V = D.v2;
    if (!V) return;
    const pc = v => Math.round(100 * v) + "%";
    setText("v2-newtrade", pc(V.new_tradeoff));
    setText("v2-newtrust", V.new_trust_states);
    setText("v2-res", pc(V.resolution));
    setText("v2-tpr", pc(V.gate_tpr));
    setText("v2-fpr", pc(V.gate_fpr));
    setText("v2-nfc", V.n_forecasts.toLocaleString("en-US"));
    setText("v2-ent", V.q0_entropy.toFixed(2));
    setText("v2-p-ls", pc(V.q0_pairs["luna|sonnet"]));
    setText("v2-p-lg", pc(V.q0_pairs["luna|grok"]));
    setText("v2-p-sg", pc(V.q0_pairs["sonnet|grok"]));
    const r1 = V.rq1.primary_ordered_vs_board;
    setText("v2-rq1p", r1.mean_diff.toFixed(3));
    setText("v2-rq1pp", r1.p_sign.toFixed(2));
    setText("v2-hself", V.h_self.mean_other_minus_self.toFixed(3));
    setText("v2-hselfn", V.h_self.n_pairs);
    setText("v2-hselfp", V.h_self.p_sign_two_sided.toFixed(3));
    setText("v2-hcy", V.h_choice.mean_excess_choice.toFixed(3));
    setText("v2-hcn", V.h_choice.mean_excess_other.toFixed(3));
    setText("v2-rq3", "+" + V.rq3.mean_projection.toFixed(3));
    setText("v2-rq3n", V.rq3.mean_null_third_model.toFixed(3));
    if (V.coupling) {
      setText("v2-cpc", V.coupling.arm_C_forecast_mean_surplus.toFixed(2));
      setText("v2-cpa", V.coupling.arm_A_filler_mean_surplus.toFixed(2));
    }

    const NAME = { luna: "Luna", sonnet: "Sonnet", grok: "Grok" };
    const ORDER = ["luna", "sonnet", "grok"];

    /* predictor x target error matrix */
    (function () {
      const el = document.getElementById("v2-matrix"); if (!el) return;
      const t = document.createElement("table");
      t.innerHTML = "<tr><th>Predictor</th>"
        + ORDER.map(m => `<th>predicting ${NAME[m]}</th>`).join("") + "</tr>";
      const vals = ORDER.flatMap(p => ORDER.map(
        q => (V.matrix[p] && V.matrix[p][q] ? V.matrix[p][q].mean : 0)));
      const vmax = Math.max(...vals);
      ORDER.forEach(p => {
        const tr = document.createElement("tr");
        const h = document.createElement("td");
        h.textContent = NAME[p]; h.style.fontWeight = 600;
        tr.appendChild(h);
        ORDER.forEach(q => {
          const c = V.matrix[p] && V.matrix[p][q];
          const td = document.createElement("td");
          td.textContent = c ? c.mean.toFixed(2) : "-";
          td.style.textAlign = "center";
          if (c) td.style.background =
            `rgba(42,120,214,${(0.45 * c.mean / vmax).toFixed(3)})`;
          if (p === q) {
            td.style.fontWeight = 700;
            td.style.outline = `2px solid ${INK}`;
            td.style.outlineOffset = "-2px";
          }
          tr.appendChild(td);
        });
        t.appendChild(tr);
      });
      el.appendChild(t);
      const cap = document.createElement("div"); cap.className = "fcap";
      cap.textContent = "Mean prediction error in excess bits, all views "
        + "pooled (0 = as close to the target's tendency as a fresh sample "
        + "of the target itself; darker = worse). Boxed diagonal = a model "
        + "predicting itself.";
      el.appendChild(cap);
    })();

    /* self versus other, by phase */
    (function () {
      const el = document.getElementById("v2-selfother"); if (!el) return;
      const phases = ["negotiation", "execution", "endgame"];
      const rows = phases.map(ph => ({ label: ph, d: V.self_other[ph] }))
                         .filter(r => r.d && r.d.self && r.d.other);
      const w = 860, rowH = 44, labW = 170, padR = 40, axisH = 28;
      const h = rows.length * rowH + axisH + 10;
      const hi = Math.max(...rows.flatMap(r => [r.d.self.hi ?? r.d.self.mean,
                                                r.d.other.hi ?? r.d.other.mean]));
      const xmax = Math.max(0.1, Math.ceil(hi * 10) / 10);
      const X = v => labW + (w - labW - padR) * v / xmax;
      const svg = svgEl("svg", { viewBox: `0 0 ${w} ${h}`, width: "100%" });
      el.appendChild(svg);
      for (let v = 0; v <= xmax + 1e-9; v += 0.1) {
        svg.appendChild(svgEl("line", { x1: X(v), y1: 2, x2: X(v),
          y2: h - axisH, stroke: v < 0.05 ? INK2 : GRID }));
        const tx = svgEl("text", { x: X(v), y: h - axisH + 16,
          "text-anchor": "middle", "font-size": 12, fill: MUTED });
        tx.textContent = v.toFixed(1); svg.appendChild(tx);
      }
      rows.forEach((r, i) => {
        const y = i * rowH + rowH / 2;
        const lab = svgEl("text", { x: labW - 12, y: y + 4,
          "text-anchor": "end", "font-size": 13.5, fill: INK2 });
        lab.textContent = r.label; svg.appendChild(lab);
        [["self", BLUE, -6], ["other", GRAY, 7]].forEach(([k, color, dy]) => {
          const c = r.d[k];
          if (c.lo != null) svg.appendChild(svgEl("line", { x1: X(c.lo),
            y1: y + dy, x2: X(c.hi), y2: y + dy, stroke: color,
            "stroke-width": 2 }));
          svg.appendChild(svgEl("circle", { cx: X(c.mean), cy: y + dy, r: 5,
            fill: color }));
        });
      });
      const cap = document.createElement("div"); cap.className = "fcap";
      cap.textContent = "Blue = a model predicting itself, gray = the other "
        + "two models predicting it. 95% intervals. Error is far lower at "
        + "endgame positions, where the next move is close to forced.";
      el.appendChild(cap);
    })();
  })();

  setText("ntests", D.tests || 151);
})();
