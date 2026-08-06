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

## Measured token counts (o200k_base) vs §7.6 bounds

| Element | Measured | Bound |
|---|---:|---:|
| System block (invariant, cached) | 596 | — (spec estimate ~800-1200 incl. tool schemas; schemas live in `spec/tools.v1.json` and are counted by the runtime, not the renderer) |
| Board, K=8, 2 live contracts (§7.2 reference position) | **323** | ≤ 340 |
| Simple line (`WAIT`, `END`) | 5-6 | ≤ 8 |
| Executive line (`EXECUTE job3 [done]`, `TRANSFER`) | 10-13 | ≤ 16 |
| Lifecycle line (`ACCEPT` 21, `RENEGE` 26, window-close `WAIT` 11) | 11-26 | ≤ 28 |
| Contract line (2 jobs: 23; 2 jobs + 1 pay: 30) | 23-30 | ≤ 14 + 8·jobs + 10·pays |
| Message line at the 40-token cap | 46-48 | ≤ 48 |
| Full prompt, tick 15 of the worked episode | 1077 | — |

All bounds are asserted as golden tests (`test_render.py`, marker
`token_bounds`, skipped if tiktoken is unavailable).

## Branching under scripted mixed play

All 36 policy pairs on 4 admitted scenarios (1,916 mover ticks): pooled
Omega_1 label entropy **2.98 bits** across 12 of 14 labels in play
(PROPOSE .23, END .20, EXECUTE .14, REJECT .13, DRAW .10, WAIT .09, and
ACCEPT/INFORM/QUERY/TRANSFER/RENEGE/CANCEL the rest).  This is a property of
the scripted mix, not of any model; it demonstrates the environment offers
the branching the E0 criterion will measure on real policies.

## Interpretation choices

Every deliberate interpretation choice is recorded in
[`M0_DECISIONS.md`](M0_DECISIONS.md) (36 entries); the three genuine spec
tensions and their resolutions are in
[`M0_SPEC_FINDINGS.md`](M0_SPEC_FINDINGS.md).

## Not in scope for M0

The impure runtime (providers, retries, abandon-and-quarantine), the message
claim annotator (explicitly analysis tooling per §9.5), the Omega_2
refinement tokens (experiment plan §3.3, an instrument over the engine), and
the human read-through of §13 (requires a human).
