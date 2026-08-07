# LEDGER

**A contracting economy for measuring prediction between language-model agents.**

Two agents jointly run a venture with a shared budget, tasks worth different amounts to each of them, limited capacity, and a deadline. They negotiate by exchanging structured contract proposals and short messages. An accepted contract binds instantly, with a brief cooling-off window to cancel cheaply; locked obligations execute or settle as breach at the end. Agents may also spend the shared budget unilaterally, and may break locked commitments at a penalty that is small for the breaker and large for the counterpart.

The whole world is a deterministic state machine over an append-only event log, so any moment of any episode reconstructs byte-for-byte and replays exactly.

## Why it exists

Claims that one AI system can anticipate another — the premise behind monitoring, adjudication, and multi-agent coordination — are usually asserted rather than measured. Measuring them needs four things that no existing environment supplies together:

- **Policy-level ground truth.** Replaying a frozen decision many times gives the agent's *distribution* over next actions, not one sample, plus its own sampling noise.
- **A distinctness gate.** Before asking whether A can recognize B, establish that A and B actually behave differently there, beyond both their noise floors.
- **Stakes without trained refusals.** Consequential harm through broken contracts and drained budgets, not through content that providers filter and models are trained to refuse.
- **A real forecast to inject.** Because replay yields a partner's policy at a probed state, a genuine (one-step-stale) forecast exists — so "does anticipation improve coordination" becomes a causal question with a format-matched decoy control.

## Documents

The environment and the research conducted on it are specified separately, and the environment does not depend on the research.

- [`docs/ENVIRONMENT_DESIGN.md`](docs/ENVIRONMENT_DESIGN.md) — the world, its actions, its economy, what an agent sees, and how to implement it. Self-contained. Read §2 to learn the game in two minutes and §7 to see exactly what a player reads.
- [`docs/EXPERIMENT_PLAN.md`](docs/EXPERIMENT_PLAN.md) — the prediction study: research questions, instrument, the experiment register, sequencing, and what each result would mean.

## Status

Pure core implemented and validated (M0); pre-pilot on any model spend. The engine, spec files, scenario generator, renderer, `Game` API, and scripted policies exist under `src/ledger/` and `spec/`, with **149 tests passing** (every §13 invariant, the §9.4 harm regression to the integer, the 37-outcome Ω₂ instrument, projection-null sizing, golden renders under two encodings, and statistical-estimator validation). See [`docs/M0_VALIDATION.md`](docs/M0_VALIDATION.md). Not yet built: the impure provider runtime and anything requiring an LLM call. No confirmatory spend is authorized.

Run the suite: `python -m pytest tests`. Rebuild the validation numbers: `python scripts/m0_report.py`.

## Token budget

The environment's own text is overhead, so it is budgeted and measured (o200k and cl100k; vendor-private tokenizers approximated with stated headroom). A player reads a fixed system block (~600 tokens, byte-identical in every call and therefore cached) plus a state board (measured 323, bound ≤340, does not grow) and a one-line-per-tick history with per-class bounds (simple ≤8, executive ≤16, lifecycle ≤28, contract 14+8·jobs+10·pays, message ≤48). Typical play runs **~600–800 variable tokens per call**; a full worked-episode prompt at tick 15 measures 1,077. Golden tests enforce every bound under both encodings. The equivalent world rendered as a JSON event log runs 1,500–4,000 tokens per call before any messages, so typical play is 2–5× cheaper.

## Design at a glance

| | |
|---|---|
| Agents | 2, alternating moves, 24 ticks |
| Tasks | 8, with prerequisites, private per-agent values, public per-agent costs |
| Actions | 14 labels with typed arguments |
| Resources | Shared budget 100, capacity 3 each, unilateral draw cap 25 each |
| Harm channel | Reneging, unilateral draws, deadline loss — all legal, all visible |
| Determinism | Pure fold over an append-only log; no floats anywhere |
| External services | None |

## Repository layout

```
spec/            frozen machine-readable action, outcome, and template definitions
src/ledger/core     pure economy: events, fold, contracts, welfare, harm  (no LLM dependency)
src/ledger/render   pure rendering: ledger -> bytes -> digest
src/ledger/runtime  the only code that touches a provider
src/ledger/measure  the research instrument: selection, replay, scoring, gate, projection
banks/           frozen, versioned scenario banks
```

`ledger.core` is a standalone library with no LLM dependency. The economy can be driven by scripted policies, humans, or RL agents; the research instrument is a client of it, not a part of it.
