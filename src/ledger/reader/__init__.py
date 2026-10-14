"""Reader (observer) views of the default game: what a forecaster that is
not the acting seat sees at one frozen decision.

- `ledger.reader.views`: the evidence ladder `L0` (situation only),
  `C-count` (the target's past action labels, counted), `C-target` (the
  same labels, oldest first) and `C-shuf` (the same labels in a salted
  random order), the forecaster's system block, and the prompt hash the
  report's manifests record.
- `ledger.reader.traces`: the reasoning views appended to `C-target`:
  the target's own reasoning from earlier turns (redacted or not) and a
  summary of it.  Both take the text as input; nothing here produces it.

The hidden-objectives variant has its own ladder in
`ledger.variants.hidden_objectives.reader`.

Pure: nothing here calls a provider or changes the game state.  Ported from
`ledger-experiments/harness/views.py`, `harness/reason_view.py`,
`harness/forecast.py` (the extra-block append) and `run_s1.py` (the summary
block) in self-other-prediction-smoke-tests; the bytes are identical.
"""
from .traces import (MAX_CHARS_PER_TURN, MAX_TURNS, SUMMARY_HEADER,
                     audit_leaks, reasoning_chunks, redact_trace,
                     summary_block, trace_block, trace_text)
from .views import (PREDICTION_MANDATE, VIEWS, build_view, digest,
                    predictor_system, prompt_sha256, redact_board,
                    target_labels, view_messages, with_extra_block)

__all__ = [
    "MAX_CHARS_PER_TURN", "MAX_TURNS", "SUMMARY_HEADER", "audit_leaks",
    "reasoning_chunks", "redact_trace", "summary_block", "trace_block",
    "trace_text",
    "PREDICTION_MANDATE", "VIEWS", "build_view", "digest",
    "predictor_system", "prompt_sha256", "redact_board", "target_labels",
    "view_messages", "with_extra_block",
]
