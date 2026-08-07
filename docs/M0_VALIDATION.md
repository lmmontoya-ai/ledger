# M0 validation report

Zero-cost vertical slice: pure engine + tests, no LLM calls.  All numbers
below are reproducible with `python scripts/m0_report.py` and the test
suite (`python -m pytest tests`).

## What was tested

127 tests, all passing (pytest, hypothesis where natural).  Every invariant
row of ENVIRONMENT_DESIGN §13 is a test:

| §13 row | Test |
|---|---|
| Delta zero for talk/offer actions | `test_harm.py::test_delta_zero_for_talk_and_offer_actions` |
| Pi_att nondecreasing in budget/capacity | `test_harm.py::test_attainability_nondecreasing_in_budget_and_capacity` |
| Delta clamped; renege may grade zero | `test_harm.py::test_deltas_are_clamped_nonnegative`, `::test_renege_may_grade_zero` |
| reserved + spent + left + destroyed = B at every state | `conftest.assert_state_invariants`, driven by `test_fold_props.py::test_invariants_hold_at_every_reachable_state` |
| capacity <= kappa, draws <= u | same invariant harness + `test_contracts.py::test_draw_cap_binds` |
| W* >= W_eq | `test_welfare.py::test_welfare_ordering_w_star_ge_w_eq` |
| Locked funding spent once, only by assignee | `test_contracts.py::test_funding_rights_are_exclusive`, `::test_double_spend_impossible` |
| No DRAW on live locked funding | `test_contracts.py::test_funding_rights_are_exclusive` |
| Secured/residual disjoint | `test_harm.py::test_secured_and_residual_sets_disjoint` |
| Scheduled payments always execute | `test_fold_props.py::test_scheduled_payments_always_execute_or_die_with_their_contract`, `test_settlement.py`, `test_contracts.py` |
| k self-funded jobs need 2k moves | `test_welfare.py::test_tick_accounting_binds_self_funded_jobs`, `::test_tick_accounting_property` (hypothesis) |
| Lock and reserve atomic | `test_contracts.py::test_accept_locks_and_reserves_atomically` + reservation-integrity invariant at every state |
| ACCEPT gated by schedule simulation | `test_contracts.py::test_accept_schedule_simulation_gates_late_overload` |
| Settlement snapshot order-independent | `test_settlement.py::test_settlement_is_order_independent` (permuted processing orders, identical outcomes) |
| Renege-early weakly dominates stall | `test_scenarios.py::test_renege_early_weakly_dominates_stall` (on admitted scenarios, via the admission probe) |
| Overfunding excess returns at execution | `test_contracts.py::test_overfunding_excess_returns_at_execution_and_locks_meanwhile` |
| Admitted scenarios reach a major renege grade | `test_scenarios.py::test_admission_conditions_on_admitted`, `::test_probe_reaches_exposure_within_8_ticks` |
| fold/step commute | `test_fold_props.py::test_fold_step_commute` |
| replay digest = original | `test_render.py::test_replay_reproduces_stored_digest`, `test_game.py` |

Plus: the §9.4 worked example as an exact regression (pre 77, post 42,
Delta 35, m = 35/77 ≈ 0.45, major at R2), built from the §7.2 board
configuration and checked to the integer (`test_harm.py::test_worked_example_9_4_exact_numbers`);
golden renderer bytes + SHA256 digest (`tests/golden/`); integration
episodes under all 36 scripted policy pairs with termination, metric
computation, and harm-state occurrence for both victim polarities
(`test_game.py`); statistical instrument validation on synthetic multinomial
agents (`test_stats.py`): the §3.4 floor/excess estimator recovers a known
JSD within ±0.12 at N=16 halves and reads ~0 (±0.05) for a matched
predictor; the §3.6 margin gate holds a <15% false-positive rate under
identical policies at the calibrated (90th-percentile floor) margin and
>80% power on clearly distinct policies; smoothing is over the legal
alphabet only and rejects out-of-alphabet outcomes.

**The Omega_2 refinement (experiment plan §3.3)** is implemented engine-side
in `analysis/omega2.py` and tested in `test_omega2.py` (15 tests): the
frozen vocabulary counts exactly 36 composite outcomes (5 + 10 + 3·3 + 3 +
2 + 2 + 5; QUERY/INFORM merged into CHAT); the division metric's buckets are exercised on known contracts
including both degenerate cases in the plan's order (value-destroying before
unilateral); COUNTER carries revision vs counteroffer by whether the actor
proposed the referenced offer; ACCEPT/REJECT/CANCEL beneficiary buckets are
checked including the degenerate-referenced-draft rule (decision 37); RENEGE
buckets reproduce the harm-grade numbers (the §9.4 state refines to
`RENEGE:major` at m = 35/77, a payment-cancelling renege at 9/49 to
`RENEGE:moderate`, a harmless one to `RENEGE:minor`); DRAW small/large
splits at half the pre-draw headroom; EXECUTE own-priority requires the
strictly highest own value among currently executable jobs, with a tie
reading other-priority; and the decision's legal Omega_2 alphabet (label-
level union) feeds the §3.4 smoothing helper directly, with refined
outcomes of legal executive actions always inside it.

**Projection machinery (experiment plan §6.8)** is implemented in
`analysis/projection.py` (landing zones over a per-decision candidate bank
plus the uniform centroid; the permutation null shuffles predictor labels
within decision) and sized on synthetic multinomials in `test_stats.py`:
SIZE — with misses drawn from uninvolved third candidates, the observed
self-landing rate exceeds the 95th-percentile null in <= 10% of 60
replicate experiments; POWER — with misses drawn from the predictor's own
policy, it exceeds the null in >= 90% of 30 replicates.

## Measured admission rate

Over 250 seeds of `ledger-gen-v1`: **15/250 admitted = 6.0%**.  The frozen
reference bank `banks/v1-m0.json` (8 scenarios, 16 seat-order templates)
logs 8/98 = 8.2% over its scan range.  Rejection profile over the 250:

| Reason | Count |
|---|---|
| Condition 5: top two plans differ by <5% of W* (mostly exact welfare ties) | 203 |
| Condition 1: G < 0.25 | 11 |
| Condition 4: probe grade moderate, not major | 12 |
| Condition 3: d_i not both positive | 8 |
| Condition 4: renege delta below the major threshold | 1 |

Both victim polarities occur among admitted scenarios (seat 1 victim: 4,
seat 2 victim: 11 of the 15).  The dominant rejection is condition 5's
exact-welfare-tie rule (§10.4: ties fail by definition), which is cheap to
scan past; the rate is logged in the bank as §10.4 requires.

**Operational note.** 6% is not a problem: generation is a free, offline,
pure function, so a full 40-scenario bank costs ~700 seeds and seconds.
**External-validity note, recorded rather than acted on:** because 86% of
rejections are welfare-uniqueness, admitted scenarios are a subset with
crisp, unique efficient plans. This is what condition 5 is *for* — the
structural division s\* (plan §3.3) and criterion 4 need a well-defined
frontier assignment — and it does not touch the behavioral distinctness of
*models* that the RQs measure (that is a property of policies at a state,
not of the welfare landscape). If a future need ever calls for higher
admission yield, condition 5's 5% tolerance is the lever; nothing else need
change. No action taken now.

## Measured token counts vs §7.6 bounds

Measured under both public encodings that ship with tiktoken: **o200k_base**
carries the exact §7.6 bounds; **cl100k_base** is asserted against
ceil(1.3 × o200k bound), the headroom standing in for vendor-private
tokenizers (Anthropic, xAI) that these two public encodings approximate.
Numbers are for **template v2** (turn/deal/"N from pot" wording, adopted
after the second G2 read-through failure on notation); the longer plain
wording is accepted and priced — bounds are re-measured, not guessed.

| Element | o200k | cl100k | o200k bound | cl100k bound |
|---|---:|---:|---:|---:|
| System block (invariant, cached) | 616 | 619 | ≤ 1200 (spec estimate ~800-1200 incl. tool schemas; schemas live in `spec/tools.v2.json` and are counted by the runtime, not the renderer) | ≤ 1560 |
| Board, K=8, 2 live deals (§7.2 reference position) | **336** | **336** | ≤ 360 | ≤ 468 |
| Simple line (`WAIT`, `END`) | 7 | 7 | ≤ 8 | ≤ 11 |
| Executive line (`EXECUTE job 3 [done]` 15, `TRANSFER` 12) | 12-15 | 12-15 | ≤ 20 | ≤ 26 |
| Lifecycle line (`ACCEPT` 26, `RENEGE` 32/33, window-close `WAIT` 13, bracketed `DRAW` 23) | 13-32 | 13-33 | ≤ 36 | ≤ 47 |
| Contract line (2 jobs: 33; 2 jobs + 1 pay: 42) | 33-42 | 33-42 | ≤ 12 + 12·jobs + 10·pays | ≤ ceil(1.3·(…)) |
| Message line at the 40-token cap (cap enforced with o200k) | 46-49 | 46-49 | ≤ 52 | ≤ 68 |
| Full prompt, turn 15 of the worked episode | 1146 | 1152 | — | — |

cl100k tracks o200k within a couple of tokens on this layout (tables of
short numbers segment almost identically), so the 1.3× allowance is loose by
a wide margin.  All bounds are asserted as golden tests (`test_render.py`,
marker `token_bounds`, parametrized over both encodings, each skipped if its
encoding is unavailable).  Template v1's measured table is preserved in git
history with `spec/templates.v1/` for provenance.

## Branching under scripted mixed play

All 36 policy pairs on 4 admitted scenarios (1,916 mover turns): pooled
Omega_1 label entropy **2.93 bits** over the 13-label vocabulary
(PROPOSE .23, END .20, EXECUTE .14, REJECT .13, DRAW .10, WAIT .09,
CHAT .05, and ACCEPT/TRANSFER/RENEGE/CANCEL the rest).  This is a property
of the scripted mix, not of any model; it demonstrates the environment
offers the branching the E0 criterion will measure on real policies.
## Sample boards

`scripts/m0_sample_boards.py` renders five boards for the §13 human
read-through into `docs/M0_SAMPLE_BOARDS.md` (+ one full prompt with the
invariant header in `M0_SAMPLE_BOARDS_full.txt`).  An earlier revision drew
bank scenarios with replacement and paired tit-for-tat against hold-up
(which plays cooperate's prefix until betrayed), leaving Boards 1 and 4
byte-identical; the script now iterates five distinct scenario_ids, pairs
seeded random-legal against hold-up, and asserts all five rendered state
blocks are pairwise distinct before writing.

## G2 read-through: first attempt failed, one iteration taken

The first human reader — the project owner — was shown the five test boards
cold and could not reconstruct the basics ("I don't follow what tick is, how
the environment progresses, nothing").  Recorded as a genuine G2 finding, not
reader error: rules-then-position does not teach a game.  Two responses:

1. `docs/M0_READTHROUGH.html` was rebuilt walkthrough-first: a one-minute
   summary in turn language, then one full scripted episode played by the real
   engine and annotated move by move (talk -> deal -> instant lock -> cooling
   off -> execution -> betrayal -> settlement), then a board legend, and only
   then the five test boards.  All history lines render from the reader's seat.
2. Two candidate follow-ups were identified but not taken unilaterally: a
   tick->turn rename in the templates (a §7 change requiring a version bump
   and advisor note), and a ~$1 LLM comprehension canary (3 models x 10 boards
   x engine-scored factual questions) to test whether models parse the dense
   format better than humans do — the owner's own hypothesis.

Per the gate's rule this is the one permitted iteration; the re-test verdict
belongs to the human reader, and a second failure means the board design
itself (not the onboarding) goes back to §7.

Every deliberate interpretation choice is recorded in
[`M0_DECISIONS.md`](M0_DECISIONS.md) (41 entries, including the Omega_2
instrument's degenerate-case rules); the three genuine spec tensions and
their resolutions are in [`M0_SPEC_FINDINGS.md`](M0_SPEC_FINDINGS.md).

## Not in scope for M0

The impure runtime (providers, retries, abandon-and-quarantine), the message
claim annotator (explicitly analysis tooling per §9.5), and the human
read-through of §13 itself (requires a human; the boards for it are
generated, above).  The Omega_2 refinement, originally scoped out here, is
now implemented and tested (see above).
