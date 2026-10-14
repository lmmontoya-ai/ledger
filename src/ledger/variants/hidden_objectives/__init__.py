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

Provenance: ported from self-other-prediction-smoke-tests
`ledger-experiments/engine_v2/` and `ledger-experiments/ledger_v2_bridge.py`,
which ran against this repository at commit 008de57.  The research harness
names this variant "LEDGER v2".  `scripts/check_hidden_objectives_equivalence.py`
checks that this port reproduces the original byte for byte.

Not ported: the solver and solver rollouts used for the harness's
pre-registration gates, forecast collection, view ladders, probes, and all
analysis.
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
]
