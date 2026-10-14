"""LEDGER with hidden objectives: the Contracting environment of the paper.

Each job pays each seat in three private resources (cash, materials,
standing) instead of one value.  Each seat is privately assigned ONE of the
three to maximise; only that resource counts for it, and neither seat is
told the other's assignment.  Episodes run 48 turns and the objective is
scored on the first 24.

This is a variant layer, not a fork.  The core engine (legality, the fold,
the contract lifecycle, settlement, rendering, the runtime, Omega_2) runs
unmodified on `ScenarioV2.base(opening)`, whose value column is the
per-seat sum of the three resources.  What the variant adds:

  scenario   ScenarioV2 (one yield column per resource per seat) and the
             resource scorer
  generate   the seeded generator, the admission rule, the studied bank
             (`paper_bank`, `load_bank`)
  render     the acting prompt: core board + "## Your ledger" + one
             objective line + core history
  observer   what a third party may see: the board with private values and
             the objective removed
  play       ModelAgentV2, `play_episode`, `outcome`, prompt replay
  sham       the sham-objective arm: an opaque label scored as 40 + cash
  reader     the forecaster's view ladder (board, ordered, shuffled, trace,
             tally) and the goal-naming probe
  solver     the exact value calculation: per-objective, per-belief action
             values, goal-revealing and hedge classification
  rollout    deterministic solver-played episodes (the fixed-state gates)

Provenance: ported from self-other-prediction-smoke-tests
`ledger-experiments/engine_v2/`, `ledger-experiments/ledger_v2_bridge.py`,
`ledger-experiments/ledger_v2_sham.py` and the solver helpers named in
`solver.py`, which ran against this repository at commit 008de57.  The
research harness names this variant "LEDGER v2".
`scripts/check_hidden_objectives_equivalence.py` and
`scripts/check_report_equivalence.py` check that this port reproduces the
original byte for byte.

Not ported: forecast collection, the partner-objective disclosure probe,
campaign drivers and all analysis.
"""
from .generate import (GENERATOR_VERSION, PAPER_BANK_ID, PAPER_BANK_SIZE,
                       PAPER_KNOBS, PAPER_PROFILE, AdmissionProfile, Knobs,
                       admit, build_bank, freeze_bank, generate, load_bank,
                       paper_bank)
from .observer import (PREDICTION_MANDATE, observer_board, observer_system,
                       redact_board)
from .play import (ModelAgentV2, acting_prompt, load_episode, outcome,
                   play_episode, state_and_prefix)
from .render import (arms_differ_in_one_line, messages_v2, objective_line,
                     render_prompt_v2, render_user_v2, system_block_v2)
from .scenario import (RESOURCES, ScenarioV2, objective_menu, score_resource,
                       score_vector, shadow)
from . import reader, rollout, sham, solver
from .reader import build_view_v2, objective_probe_messages
from .sham import (SHAM_LABELS, ShamModelAgentV2, play_sham_episode,
                   sham_acting_prompt)

__all__ = [
    "GENERATOR_VERSION", "PAPER_BANK_ID", "PAPER_BANK_SIZE", "PAPER_KNOBS",
    "PAPER_PROFILE", "AdmissionProfile", "Knobs", "admit", "build_bank",
    "freeze_bank", "generate", "load_bank", "paper_bank",
    "PREDICTION_MANDATE", "observer_board", "observer_system", "redact_board",
    "ModelAgentV2", "acting_prompt", "load_episode", "outcome", "play_episode",
    "state_and_prefix",
    "arms_differ_in_one_line", "messages_v2", "objective_line",
    "render_prompt_v2", "render_user_v2", "system_block_v2",
    "RESOURCES", "ScenarioV2", "objective_menu", "score_resource",
    "score_vector", "shadow",
    "reader", "rollout", "sham", "solver",
    "build_view_v2", "objective_probe_messages",
    "SHAM_LABELS", "ShamModelAgentV2", "play_sham_episode",
    "sham_acting_prompt",
]
