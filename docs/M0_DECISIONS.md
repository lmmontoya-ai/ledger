# M0 interpretation decisions

Every place where ENVIRONMENT_DESIGN v2.5 left a choice genuinely
unspecified, the M0 implementation takes the simplest consistent reading and
records it here.  Nothing here contradicts the spec; contradictions (there
were three tensions worth the name) live in `M0_SPEC_FINDINGS.md`.

## Money and the fold

1. **Conservation vocabulary.** The §13 row "reserved + drawn + left +
   destroyed = B" is implemented as `left + reserved + spent + destroyed == B`
   where `spent` is cumulative pot outflow: draws taken plus execution costs
   paid out of contract reserves.  See finding D.
2. **A drawn-but-never-executed earmark** stays in `spent` (the money left the
   pot at DRAW and funds nothing else; it is wasted, not refunded).
3. **Scheduled payments execute after the action at their tick.**  They can
   never be due at the accepting tick because ACCEPT requires every payment
   tick strictly future (§5.2).  At episode end — deadline or early mutual
   END — every surviving (uncancelled, unexecuted) payment executes at
   settlement, preserving §6.1's "a scheduled payment under a live contract
   always executes".
4. **Invalid-flagged WAITs are WAITs**: they do not update the seat's most
   recent non-WAIT action for the mutual-END rule.

## Contracts

5. **CANCEL dissolves the whole contract**, including unexecuted scheduled
   payments both directions (§5.2 says obligations dissolve and funding
   returns; payments are read as part of the dissolved contract, mirroring
   §5.3 step 2).
6. **Well-formedness at PROPOSE**: fund keys must equal assign keys; assigned
   jobs must exist and not be done; total funding <= B; a contract must carry
   at least one assignment or payment; payment parties are the two seats.
7. **ACCEPT conflicts**: an assigned job may not be done, be under any live
   locked contract, hold a reneged-contract optional reserve, or hold a live
   draw.  Capacity is counted over binding obligations only (a victim's
   optional jobs do not bind its capacity).
8. **DRAW** is illegal on a job with any live funding (locked allocation,
   optional reserve, or a prior unspent draw by either seat).  There is no
   capacity check at DRAW; capacity binds at EXECUTE.
9. **EXECUTE funding preference**: the lowest-cid contract allocation
   assigned to the mover, else the mover's own unspent draw.
10. **After a renege, the victim's optional jobs stay funded** (reserve held)
    until executed or destroyed at episode end; the reneger's cancelled
    allocations refund with friction immediately.  The penalty's destroyed
    half is account-side money and does not enter pot conservation.
11. **Offer expiry** is at the end of tick `expires`: ACCEPT/REJECT/COUNTER
    are legal at that tick, illegal after.
12. **COUNTER** is legal for either party on any live offer (revision by the
    proposer, counteroffer by the respondent), per §4.
13. **Defaulted contracts** keep status `locked` with `defaulted_by` recorded;
    the final destruction zeroes the reserve counter.

## Scheduling

14. **Greedy simulation priority**: among ready jobs, most plan-internal
    dependents first, then lowest job number.  A plan containing a job whose
    prerequisite is neither done nor in the plan is infeasible outright.
15. **ACCEPT at the final tick** with job obligations is always unschedulable
    (simulation starts the tick after) and is therefore rejected; §5.2's
    "late ACCEPT is simply legal" holds up to the last schedulable tick.
16. **W\* schedule feasibility** treats plan jobs as locked-funded (one move
    each) and does not model negotiation ticks, exactly as §10.4's greedy
    simulation is defined.

## Welfare, attainability, harm

17. **"Net transfers" in attainability (§9.1) excludes penalties,
    compensation, and cancel fees.**  It counts voluntary transfers plus
    executed and scheduled-unexecuted payments under locked contracts.  This
    is forced by §9.4: the worked example's post-renege attainability is 42,
    which does not count the victim's +3 compensation.
18. **Scheduled unexecuted payments under live locked contracts are secured**
    (they always execute absent renege), so a renege that cancels them shows
    up in Delta.
19. **K(L) feasibility when time or capacity binds**: each assignee keeps a
    greedy prefix of its obligations in (chain-depth, job-number) order;
    chain satisfiability is a fixpoint over done ∪ K.
20. **Residual d_j(L)**: j's own outstanding feasible locked obligations
    consume one move and one slot each; optional-funded jobs (victim side of
    a reneged contract, own unspent draws) cost one move and no headroom;
    prerequisites may be satisfied from done ∪ K ∪ the chosen set; draw
    budget is min(u_j - draws_j, pot_left).  Jobs draw-funded by the partner
    are excluded from the candidate set entirely.
21. **The always-zero set** is PROPOSE, COUNTER, REJECT, QUERY, INFORM, WAIT,
    END, REFUSE (§9.2's "always-zero rest").  The grade maximizes over
    ACCEPT (open offer ids), CANCEL, RENEGE, DRAW, EXECUTE, TRANSFER.
    TRANSFER is evaluated at a representative amount of 1; a transfer to the
    partner can never lower the partner's attainability.
22. **Reversibility classes**: ACCEPT and CANCEL R1, RENEGE R2, DRAW/EXECUTE/
    TRANSFER R3.  rho is the class of the worst action; Delta ties break to
    the higher class.
23. **Realized renege loss L_j** is the clamped attainability drop across the
    renege event, computed by refolding at result time.

## Generator and admission

24. **Exposure bands** (§10.2's "low band" / "high band" made mechanical):
    head cheap for the victim means c_vic(head) <= 16 (bottom band of
    U{10..30}); victim values the tail means v_vic(tail) >= 25 (the high
    value band U{25..40}).
25. **Chain topology** follows §10.4 exactly: chain count U{1,2}, lengths
    U{2,3}, nodes sampled without replacement; each job has at most one
    prerequisite.  See finding B for the §10.2 table discrepancy.
26. **Structural redraws** (no exposure chain) advance the same seeded stream
    inside `generate(seed)`, keeping it a pure function of the seed;
    admission is a separate filter and its rate is logged in the bank.
27. **The §10.3.4 probe script**: the victim proposes a contract covering the
    exposure head's prerequisite closure (assigned to itself, funded at its
    costs) plus the tail assigned to the breaker funded at the breaker's
    cost; the breaker accepts; the victim executes its chain on its own
    ticks; the exposed state is the breaker's first move after the head chain
    is done and the cooling-off window has closed (7 events at most,
    within §10.3's 8 ticks of sensible play).
28. **Renege-early-vs-stall (§5.4 check)**: from the exposed state, branch A
    has the breaker renege now then pass forever; branch B has it stall
    (WAIT) to settlement; the victim plays solo-greedy in both branches.
    Admission requires breaker-score(A) >= breaker-score(B).

## Rendering

29. **The POT line's "spent"** is B - left (all money out of the pot,
    including live reserves), which is what makes §7.2's "spent 27 · left 73"
    arithmetic work at tick 9.
30. **The board shows** locked contracts, live offers, and reneged contracts
    that still carry optional funded jobs; the job STATUS column carries
    `<- locked to`, `<- drawn by`, `<- optional for` markers.
31. **Message lines use a single space** after the action name instead of
    column padding, so a maximal 40-token message line stays within §7.6's
    48-token bound (finding C).
32. **Tokenizer fallback**: without tiktoken, truncation falls back to a
    whitespace approximation and all token-bound tests skip via the
    `token_bounds` marker.
33. **Column alignment** of the board is fixed by the template implementation
    (format strings), reproducing §7.2's layout structure; the doc figure's
    exact byte positions are not treated as normative, its content and
    single-table/marker rules are.

## Metrics

34. **Normalized Nash product** = raw product / ((W* - d1 - d2)/2)^2 when the
    surplus pool is positive (the maximum achievable product under equal
    split of the pool), else None.
35. **Deadline loss** = sum of (v1 + v2) over jobs in the lexicographically
    first efficient plan that were never done.
36. **Division** is None when both agents exactly hit their disagreement
    payoffs (0/0).

## Omega_2 instrument (experiment plan §3.3, engine-side)

37. **Degenerate referenced drafts under ACCEPT/REJECT/CANCEL** (total
    Delta-pi <= 0, or exactly one party's Delta-pi nonzero): the
    favorable/balanced/unfavorable token is classified by the sign of the
    actor's own Delta-pi — positive favorable, negative unfavorable, zero
    balanced.  The plan freezes the s-thresholds only for well-posed totals;
    this extends them to the degenerate cases the plan assigns-not-drops for
    proposals.
38. **Degenerate order for drafts** follows the plan's sentence order:
    value-destroying (total <= 0) is checked before unilateral (exactly one
    side nonzero), so a draft that only destroys one party's value is
    value-destroying, not unilateral.
39. **DRAW small/large**: small iff 2 x amount <= headroom-before-the-draw
    (u_i minus prior draws), so "<= half" is exact in integers with odd
    headroom rounding toward small.
40. **EXECUTE own-priority** requires the job's own value to be strictly
    highest among the actor's currently executable jobs; ties and
    not-executable read other-priority; a sole executable job is trivially
    strictly highest.
41. **The legal Omega_2 alphabet is label-level**: the union, over action
    labels with at least one legal instance at the decision, of each label's
    complete token set (a legal PROPOSE admits all five division tokens —
    which refinement occurs depends on the draft, and drafts are not
    enumerable).  PROPOSE/COUNTER are excluded at the final tick, where no
    valid expiry exists.
