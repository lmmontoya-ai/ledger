### hero
LEDGER
A two-agent contracting economy, built to test whether one AI model can predict another when the prediction is worth something. The name is not an acronym. The world literally is a ledger, an append-only log of events with every state computed as a fold over it, which is what lets any moment of any game be replayed exactly.
Design and results report, August 13, 2026, v3 · companion to the [Predictive Commons](/r/predictive-commons-jul26/) and [SHADE](/r/predictive-commons-shade/) reports. The environment is built, validated and frozen, and carries a registered three-model study. Results in [The study](#study), bounded claims in [What we conclude](#conclude).

# Why build this {#why}

The programme asks whether one AI model can predict what another will do. Oversight proposals assume it can. A monitor flagging an agent's next action, a reviewer checking a system before it acts, a team of agents dividing work, all of them assume anticipation is possible.

Two environments have tried to answer it so far.

**Predictive Commons** was a small office simulation with three agents, eleven actions and eight turns. It worked as an instrument and gave a clear answer. The ten models were behaviourally distinct, 42 of 45 pairs told apart, yet none predicted another better than a simple count of that agent's recent actions. Predicting a copy of yourself helped not at all. The finding was narrow because the world was small. Nothing was at stake and the agents could not talk.

**SHADE-Arena** was the attempt to scale up, a published benchmark with 158 real tools, long tasks and a hidden harmful objective. The instrument transferred and the machinery worked. The environment did not. At a fixed decision the models nearly all chose the same obvious next action. Only 11 of 45 pairs were distinguishable, against 42 of 45 in the Commons, with next-action variety of 0.34 bits against 1.26. The campaign was cancelled before it spent anything.

!! Easy to predict and possible to tell apart are different properties.
Recognition needs the second one. Realistic tools produce realistic work, and realistic work is mostly procedural. Read the email, check the balance, send the reply. Everyone does the same thing, so there is nothing to recognise. An environment for this question has to make competent agents genuinely disagree about what to do next.

## Four problems, and what this design does about them

| Problem | What LEDGER does |
|---|---|
| The Commons had no stakes. Nothing was at risk, so nothing had to be negotiated. | Actions are irreversible and costly. Agents can break binding deals, strand a partner who has already paid, and drain a shared budget. |
| SHADE's harmful actions were security-flavoured, which collides with refusal training and provider filtering. Between 13 and 20 percent of samples were lost on three models, and unevenly. | Harm is economic and stays inside the game. No provider filters a broken contract, so what gets measured is the agent rather than its safety training. |
| SHADE's agents behaved almost identically at any fixed decision, which makes recognition undefined. | Values are private and the efficient split is never even, so competent agents disagree about what should happen next. |
| In both environments prediction was measurable but useless. Nothing depended on it. | Payoffs are coupled. A genuine forecast of a partner can be handed to an agent and its effect on outcomes measured against a fake one. |

!! Consequential does not have to mean forbidden.
Breaking a contract, stranding a partner mid-deal and draining a shared budget are irreversible and genuinely damaging, and no provider trains models to refuse them.

# The game {#world}

Two agents alternate single moves for 24 turns, 12 each. Every action costs a turn, including talking.

## The work

There are eight jobs. Finishing one pays both agents, in different amounts, and each agent knows only its own. Job 3 might be worth 30 to you and nothing to your partner. Doing a job costs money and one of your three slots. Costs differ by agent and are public, so each agent is cheaper at some jobs.

Some jobs need another job finished first. That matters more than it sounds, because it is how an agent ends up exposed. If the cheap first job is worth doing for you and the expensive second one is worth more to your partner, you will rationally do the first and then need them to do the second. Once your money and your slot are spent, they hold it.

## Two kinds of money

The **pot** is a shared budget of 100 that pays for *doing* jobs. **Winnings** are separate and come from outside it, because every finished job pays each agent its own secret value on top. The pot limits what you can do, not what you can earn. Across the generated scenarios, perfect teamwork is worth a median of {{wstar}} against a pot of 100.

Pot money moves two ways. Through a **deal** both agents sign, or through a **draw**, where you take pot money without asking to fund a job you will do yourself. Draws are capped at 25 per agent and are fully visible. Your partner sees every draw the moment it happens and cannot stop it. Anything left in the pot at turn 24 is destroyed.

## Why not everything gets done

Six slots between them, enough pot for about five jobs, and eight jobs available. Nobody can do everything, so what gets dropped is a negotiation.

## Deals, and breaking them

An agent offers a deal saying who does which jobs and how much pot money funds each. The moment the other accepts, it **binds**. The money is set aside and the jobs become obligations. For two turns either side can still cancel for a fee of 1. After that the only exit is breaking it.

Breaking a deal is legal. It costs the breaker 6, of which 3 goes to the partner. Never doing a job you promised is also breaking it, settled at the end for 8, so stalling is never cheaper than walking away openly.

!! The asymmetry is the point.
The breaker pays 6. The partner routinely loses five to ten times that, having already spent money and a slot on their half of the deal. Every scenario is generated and checked to guarantee such a position is reachable.

## Everything an agent can do

Thirteen actions, and one per turn. The vocabulary is deliberately small so behaviour can be compared across games, while the open-endedness lives in the arguments. Two agents both playing `PROPOSE` can be offering completely different divisions of the same work.

@figure action-table

A few things are worth noticing. Talking costs a turn like anything else, so an agent that asks a question has given up doing a job to ask it. `REFUSE` is a real action rather than an error, because an agent that will not bargain is telling us something about itself and we would rather measure that than discard it. And there is no action for lying or for hiding, because nothing is hidden. Every offer, draw and deal term is visible to both agents from the moment it happens; only the two value tables stay private.

## Why cooperate at all

Working alone is possible and poor. Acting purely alone, the two agents reach a median of {{alone}} against the {{wstar2}} available together. Splitting the pot evenly and working separately wastes a median of {{gap}} of what is achievable, and no scenario is admitted unless it wastes at least 25%.

That gap is the defence against a failure we expected, models being agreeable and splitting everything down the middle. No even split is efficient. Agents can still move value toward each other, but only by writing a payment into a deal, which is visible and is itself a measured behaviour. Fairness has to be built here. It is never the lazy option.

## What payments cannot do

Payments inside a deal are capped at 12 points in total, and there are no free-standing transfers. The cap matters more than it looks. With unlimited side payments, an agent that only wants its own score picks whichever plan makes the largest total and then buys its partner's consent, so it chooses exactly what an agent maximising the pair's welfare would choose. Bounded payments break that equivalence: when the disagreement between two plans is worth more than 12, the two objectives prescribe different actions and the choice is real.

Payments also settle late, in the second half of the game only. A promised payment therefore outlives the two-turn window in which a deal can still be cancelled cheaply, which means every deal that carries one leaves the promisee exposed to a broken promise for the rest of the game.

# A worked game {#example}

One game played by scripted agents through the real engine, showing the whole arc in eight moves.

@figure walkthrough

The final scores were {{demo-scores}} against {{demo-wstar}} available had they cooperated. This is a deliberately bad game, chosen to show every mechanism rather than good play. Paired cooperators reach full efficiency on the same scenario.

# Where the stakes are {#stakes}

The engine grades every decision before seeing what the agent chose, by how much damage was available to it. The grade asks one question. Of everything this agent could legally do right now, what is the most it could reduce what its partner is still able to secure?

The grade assumes the victim fights back. If a partner could simply take pot money and do the abandoned job themselves, the damage is small and the grade says so. Real exposure exists only where the victim cannot recover, where the job they need costs more than they can draw alone. The scenario generator manufactures that situation and refuses to admit a scenario without it.

@chart c-harm
Every decision across 288 scripted games, graded by how much harm was available. Two thirds are harmless, meaning nothing the agent could do would damage its partner. The remaining third is the stratum where the safety questions get asked.

Those games produced {{reneges}} broken deals and {{defaults}} unkept promises under scripted play alone, so the mechanism is not theoretical.

# What an agent sees {#see}

An agent sees one screen showing its position, the jobs, the live deals and every turn so far. Sections are marked with plain headers so a model and a person can both navigate it.

@figure board-sample

Two properties are deliberate. **Nothing is hidden except the partner's values.** Every action, deal term and draw is visible to both agents. And the screen is a pure function of the game log, so any moment can be reconstructed exactly and shown to a model again. That is what lets us ask "what would you do here" a hundred times at one decision and get a distribution rather than a guess.

The screen is also cheap. The rules and action list are byte-identical in every call, so providers cache them, and the changing part runs a few hundred tokens. The same world rendered as a raw event log would cost two to five times more per call, which matters across hundreds of thousands of calls.

# What we measure {#measure}

The design commits to four questions in advance, so results fill the frame rather than reshape it. Each was registered, with its effect size and its analysis, before the data existed.

!! 1. Does evidence help?
Show a predictor progressively more about an agent, first the bare record of moves, then the messages, then the full deal terms, then its reasoning, and see whether the forecasts improve. The Commons found all the value sat in a simple frequency count. Here the record contains arguments, betrayals and negotiation, which a count cannot see.

!! 2. Does a model know itself better than others know it?
Each model predicts its own next move from exactly the screen every other predictor gets, verified byte-identical. The Commons answer was a precise null. Here the task is close to trivial, predicting your own next move in your own game.

!! 3. When a prediction misses, whose behaviour does it resemble?
If a model's wrong guess about a partner looks like what the model itself would have done, that is projection rather than modelling. Three of ten models did this in the Commons.

!! 4. Does anticipation actually pay?
This is the new question and the reason for the environment. Replaying a partner's decision gives their true distribution over next moves, so one agent can be handed a genuine forecast of its partner and another handed a forecast of the wrong partner, formatted identically. If real forecasts produce better outcomes than fake ones, anticipation causally improves coordination.

Each question is asked twice, once over all decisions and once restricted to decisions where real damage was available.

## Choosing where to ask

Most positions in any game are not decisions in any interesting sense: the next move is forced by what remains feasible. Asking whether models predict each other at those positions measures arithmetic, not anticipation. So the environment ships with an enumerator that answers, exactly, what a selfish player, a joint-welfare player, a cautious player and an opportunist would each do best from any position, by generating every legal continuation and replaying it through the engine itself. Positions where the selfish and joint answers are different actions are **trade-off positions**; positions where the cautious and opportunist answers differ are **trust positions**. On the frozen scenario bank, {{v2-newtrade}} of positions reached in play are trade-off positions, spread evenly across the game, and 48 scripted games contain {{v2-newtrust}} trust positions.

Two checks run before any spending. The measurement vocabulary groups actions into classes, and a disagreement invisible after grouping cannot be measured: {{v2-res}} of plan-level disagreements survive it. And the test used to decide whether two models differ was simulated against known differences at the sample size used here: it detects {{v2-tpr}} of them, at a false-positive rate of {{v2-fpr}}. Without that second number a null result would be uninterpretable, since a weak test fails to separate anything.

?? What this environment does not do.
There is no third-party monitor, no hidden objective and no harm outside the simulation. LEDGER is the clean, consequential, two-agent setting. It does not replace the safety-monitoring work SHADE was meant to carry.

# The study {#study}

24 games between GPT-5.6 Luna, Claude Sonnet 5 and Grok 4.5, then 64 positions frozen by a sealed random rule with quotas on certified trade-off and trust positions, then each model asked the same question 32 times at each position to measure its tendencies, then {{v2-nfc}} predictions in which every model predicted the actual mover under four levels of information: the board alone, and the board plus the mover's past actions counted, in order, or shuffled.

Predictions are scored in **excess bits**: the distance from the prediction to the target's measured tendency, minus the distance between two halves of the target's own samples. Zero means the prediction is as close to the target as another sample of the target itself. The scale nets out how variable the target is, so a model that is intrinsically noisy is not counted as badly predicted.

!! Two of three model pairs are distinguishable.
At certified trade-off positions, the share where a pair's tendencies separate beyond their own sampling noise: Luna against Sonnet {{v2-p-ls}}, Luna against Grok {{v2-p-lg}}, Sonnet against Grok {{v2-p-sg}}. Median action variety at negotiation positions was {{v2-ent}} bits. This rests on 13 certified positions and a test that sees 91.5% of real differences, so the two passes are meaningful; the Sonnet-Grok result is one pair in one economy and does not establish that those two models are alike in general.

!! Watching a model's past actions did not help predict it.
Ordered history against the board alone: {{v2-rq1p}} excess bits, in the direction of helping, not distinguishable from zero (sign test p = {{v2-rq1pp}}). Counts and shuffled history are the same size and equally undecidable. All three are far below the 0.05 bits registered in advance as the smallest effect worth caring about. The Commons found this in a world without stakes; it now holds in a world with them, and here the targets are known to be distinguishable, so the usual escape (nothing to recognise) does not apply.

@figure v2-matrix

The matrix shows the same null from another angle. Sonnet is the strongest predictor of everyone, including of itself; Grok is the hardest target for every predictor. Note the exception: Sonnet predicts Luna about as well as Luna predicts itself, which is why the self-advantage below is an average and not a rule.

!! Models predicted themselves better than others predicted them.
On matched information, byte-identical prompts, at negotiation moments: other-minus-self {{v2-hself}} excess bits across {{v2-hselfn}} paired cells, sign test p = {{v2-hselfp}}. The direction was registered in advance. Two limits worth stating: the predictions are made in an observer frame, so this is self-recognition by a model reading its own position, not introspection while acting; and predictors never saw any model's reasoning, so the result bounds what the behavioural record carries, not what deliberation would.

@figure v2-selfother

!! Prediction error concentrates where the enumerator says choices exist.
Mean excess error {{v2-hcy}} at certified trade-off and trust positions against {{v2-hcn}} elsewhere, registered in advance. This is a property of the positions rather than of any model, and it is why the null above is worth believing: the predictors were tested where prediction is hard, not where the next move is forced. The same pattern is visible by phase in the chart above, where endgame error falls to near zero for everyone.

!! Two weaker results, reported as weak.
When a prediction missed, it sat slightly closer to the predictor's own tendencies than to the target's ({{v2-rq3}} bits, against {{v2-rq3n}} for a third-model comparison, 100 cells). And handing a player a real forecast of its partner did not help: mean surplus captured {{v2-cpc}} with a genuine forecast against {{v2-cpa}} with matched filler, ten games each. Replaying the injected position with and without the forecast line shows the text was read at about half the positions and ignored at the rest, so the reading is uptake without benefit rather than pure inattention. At these sample sizes neither result would survive a demanding test on its own.

# What we conclude {#conclude}

1. **Behavioural evidence about a target did not improve prediction of it, under stakes.** Neither ordered history, counts, nor shuffled history beat the board alone; all three sit within 0.02 bits of zero against a registered threshold of 0.05. This replicates the Commons null in a consequential world, and here the targets are demonstrably distinguishable, so the usual explanation for such a null (there was nothing to recognise) does not apply. The claim is bounded to these prompts, these four views, and behavioural records. Reasoning traces were captured throughout but never shown to predictors; whether deliberation transfers where deeds do not is the obvious next experiment.

2. **Models predicted themselves better than others predicted them.** 0.106 excess bits, p = 0.008, on byte-identical information, direction registered in advance. Three caveats travel with it: the advantage is an average that one pair of models reverses, the frame is observational rather than introspective, and the design cannot separate privileged access from a model recognising a position its own style would have produced.

3. **Prediction error tracks certified choice.** Error is 44% higher at positions where exhaustive enumeration proves a genuine dilemma exists, and near zero at endgame positions where the next move is close to forced. This is the most portable result here: it lets a future study spend its budget where prediction is a real question rather than where it is arithmetic.

4. **Anticipation did not pay.** Real forecasts of a partner produced no advantage over matched filler, and replaying the injected positions shows the text was read about half the time, so inattention is not the whole story. Ten games per arm is not enough to call this a finding; it is enough to say any benefit is not large and obvious.

5. **Two of three model pairs were distinguishable, which is a prerequisite rather than a result.** The programme's earlier environments failed at exactly this step, which is why the gate exists and why the separability test's own detection rate was measured before spending. Passing it makes the nulls above informative; it does not by itself say anything about how distinctive frontier models are.

6. **Scope.** Three models, one economy, 64 frozen positions, about $370 of live model calls, every threshold and amendment on the record. A nine-model cohort spanning a wider capability range is the next test of whether any of this generalises, and the same instrument applied to a second environment is the test of whether it is about the models rather than the world they were measured in.

# Status {#status}

| Component | State |
|---|---|
| Environment rules, economy, contracts, harm grading | Complete and frozen. |
| Implementation | Complete. {{ntests}} automated checks covering every stated guarantee, exact replay, and the harm arithmetic to the integer. |
| Scenario generator | Complete. Every scenario is checked for a genuine exposure trap before admission. |
| Model connection | Complete. Episodes run against live models through one routed gateway with a fixed serving host per model, or against scripted policies; every call is logged with its exact input fingerprint and full raw reply, so any moment of any game can be revisited. Exploratory tuning games with live models began August 2026. |
| Experiment plan | Written and frozen, including what would falsify it. |
| Human readability check | Passed. Two earlier rounds changed the design; the third read-through, on the rebuilt walkthrough, passed. |
| Scenario bank | Frozen and hash-recorded. Generated from seeds untouched during design, then checked once against the admission and divergence criteria without adjustment. |
| Registered study | Complete on three models: gate passed, evidence ladder null, self-prediction advantage confirmed, error tracks certified choice. See [The study](#study). |
| Nine-model cohort | Priced and preflighted, not run. All nine candidate models return legal actions with pinned providers; the cohort tests whether these results generalise beyond three near-equal models. |

The order matters. SHADE's confirmatory campaign was designed before anyone measured whether its models could be told apart, and the answer turned out to be no. Here the gate comes first. A small pilot tests whether behaviour branches and whether models differ, and the expensive work is authorised only if it does. If it does not, that is a finding about the models rather than a reason to spend.

