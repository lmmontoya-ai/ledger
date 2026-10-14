# LEDGER hidden-objectives variant and observer view

This page gives exact usage for the hidden-objectives variant used in the accompanying paper, where LEDGER is called Contracting. Code lives in `src/ledger/variants/hidden_objectives/`. The core engine runs unmodified: legality, the fold, contracts, settlement and rendering all operate on the variant's base scenario. The default game renders byte-identically with or without the variant code present.

## The variant in one paragraph

Each job pays each seat in three private resources: cash, materials and standing. Each seat is privately assigned one of the three to maximise. Only that resource counts for that seat at the end. Neither seat is told the other's assignment. Episodes run 48 turns, and the objective is scored on turns 1 to 24. The game dynamics do not depend on the assignments. The engine's single value column is the per-seat sum of the three yields. That sum is what the board's YOUR-VALUE column shows, and what the conduct labels and `Game.result` use.

## Parameters: default game and studied variant

| Setting | Default game | Studied variant |
|---|---|---|
| Banks | `v1-m0`, `v1-e0` | `hidden-objectives-iter3` |
| Jobs | 8 | 6 (2 open at turn 28) |
| Shared pot | 100 | 45 |
| Turns | 24 | 48 (turns 1 to 24 scored) |
| Slots per seat | 3 | 3 |
| Draw cap per seat | 25 | 25 |
| Cooling-off window | 2 turns | 2 turns |
| Cancel fee | 1 | 1 |
| Renege penalty | 6 | 2 |
| Default penalty | 8 | 3 |
| Payment cap per deal | none | 6 |
| Payment turns | any turn | turns 33 to 48 only |
| Private values | one column per seat | cash, materials, standing per seat |
| TRANSFER | legal (13 tools) | illegal, absent (12 tools) |
| Bank size | 8 and 12 scenarios | 12 scenarios |

## Resources and scoring

| Resource | Score rule |
|---|---|
| cash | Yields from finished jobs, plus the seat's account. The account holds all deal payments, compensation, penalties and fees. Cash is the only resource that moves between seats. |
| materials | Yields from finished jobs only. Money cannot buy materials. |
| standing | Yields from finished jobs, plus 6 per locked contract the seat fully performed, minus 14 per renege or default by that seat. |

A finished job pays each seat its own yield in each resource, whoever executed it. Scores are computed at the end of play and at the end of the scored window. The scored window ends after turn 24, or at the final state if play ended earlier. Each seat's payoff is its score in its assigned resource. Scheduled payments land in turns 33 to 48 and the late jobs open at turn 28, so neither can change the scored-window payoff. Function `outcome` returns both sets of scores.

The payment cap needs one extra fact. Two engine rules read the value column to set a payment ceiling. In every studied scenario the cap of 6 sits below the best joint score of every single resource, so the ceiling is always the cap itself. Legal play therefore cannot depend on which resource a seat was assigned. Tests in `tests/test_hidden_objectives.py` check both facts.

## TRANSFER in this variant

TRANSFER is illegal in the studied variant and absent from the tool list. The engine rejects it with the reason "transfers are disabled in this scenario". The runner serves 12 tools: propose, counter, accept, reject, cancel, renege, draw, execute, chat, wait, end and refuse. Cash still moves, through scheduled deal payments (at most 6 per deal, payment turns 33 to 48), renege and default penalties, compensation and cancel fees.

## Run the variant

Zero-cost scripted run. It needs no key and no network:

```powershell
.venv\Scripts\python scripts\run_episode.py --variant hidden-objectives --index 0 --opening 1 --objectives cash,standing --p1 scripted:greedy-optimal --p2 scripted:tit-for-tat --out data\runs\smoke
```

Expected result: objectives ('cash', 'standing'), assigned payoff (2, 0), scored window (turns 1 to 24) (2, 0), final tick 5, agreement False, reneges 0, $0.0000 over 0 calls. A second line reports resource scores by seat: cash (2, 2), materials (24, 31), standing (0, 0). Scripted seats do not read their assigned objective. The scores are still computed and reported.

Run with language models through OpenRouter. Install the runtime extras, copy `models.example.json` to `models.json`, and edit the model slugs, providers and prices first. Set the key in your shell. Do not put a key in a file.

```powershell
.venv\Scripts\python -m pip install -e ".[runtime]"
$env:OPENROUTER_API_KEY = "your key here"
.venv\Scripts\python scripts\run_episode.py --variant hidden-objectives --index 0 --opening 1 --objectives cash,materials --models models.json --p1 model:sonnet --p2 model:gpt --cap-usd 2 --out data\runs\pilot
```

Without a key, the command stops before any call with `no API key: pass api_key or set OPENROUTER_API_KEY`. Flags: `--index` selects the scenario in the bank, `--opening` selects the seat that moves first (1 or 2), `--objectives` gives the assigned resource for seat 1 and seat 2, `--mandate` defaults to `principal`, `--message-cap` defaults to 40 for this variant, and `--cap-usd` bounds total spend.

### Settings as studied

The campaign behind the accompanying paper used bank `hidden-objectives-iter3`, openings 1 and 2, all 9 ordered objective assignments (each seat cash, materials or standing), mandate `principal`, message cap 40, 48 turns with scoring on turns 1 to 24, and temperature 1.0 for every model. Model settings, for building your own `models.json`:

| Name | Slug | Provider | Max tokens | Tool choice |
|---|---|---|---|---|
| GPT-5.6 | `openai/gpt-5.6-luna` | OpenAI | 24576 | required |
| Claude Sonnet 5 | `anthropic/claude-sonnet-5` | Anthropic | 40960 | auto |
| Grok 4.5 | `x-ai/grok-4.5` | xAI | 16384 | default |

Reasoning settings: GPT-5.6 used effort high, Claude Sonnet 5 recorded a reasoning `max_tokens` of 8000, Grok 4.5 used none. Prices are not part of this record. The runner refuses a model with no `price_in` and `price_out` in `models.json` before any call, so add current OpenRouter prices yourself. Check that the slugs still exist before a run. The shipped `models.example.json` is a generic example with different models.

## What the seat sees

The system block is the core system block (with the payment cap, payment window and job openings stated) plus a fixed addendum. The addendum describes the three resources and states that each seat holds a private assigned objective. It names the menu only, never an assignment, and it is identical for all assignments.

The user block is the core board, then a `## Your ledger` section, then one objective line, then the core history. The ledger section lists the seat's yields per job per resource, its running totals, and the standing rule. The objective line is the only text that differs between assignments. Function `arms_differ_in_one_line` checks this, and the test suite runs it.

The excerpt below is real output: the ledger section for seat 1 at turn 1 of scenario index 0, with objective cash, generated by `acting_prompt`.

```text
## Your ledger

JOB  YOUR-CASH  YOUR-MATERIALS  YOUR-STANDING
 1          0              33              3
 2          0               1              0
 3          0               1              1
 4          2               1             33
 5         24               1              2
 6          2              24              0

YOUR TOTALS SO FAR  cash 0  ·  materials 0  ·  standing 0
Deals kept add 6 standing; a deal you break costs 14.

YOUR ASSIGNED OBJECTIVE: CASH. Only your CASH total counts at the end.
```

Measured sizes at the same position (tiktoken `o200k_base`): variant system block 896 tokens, user block 365 tokens, board alone 216 tokens. The board header at this position reads "turn 1 of 48".

### The rules text and the enforced parameters

The system text served with this variant comes from `spec/templates.v2/system.txt`. It states "24 turns total", a renege "penalty of 6" and a default "penalty of 8". The renderer does not substitute scenario numbers into those three sentences. The studied bank enforces different numbers: 48 turns, renege penalty 2, default penalty 3. Two other served texts state the enforced horizon correctly: the board header ("turn 1 of 48") and the variant addendum, which says the bonus is scored on the first 24 turns of the 48-turn game.

These exact bytes are what the models in the accompanying paper received. All 690 logged acting-call digests from the paper's episode logs match renders that include the three sentences above. The bytes are kept unchanged in this release so that replay of the original runs stays equivalent byte for byte. New runs through this variant receive the same text. The default-game banks have no such mismatch: text and engine both use 24 turns and penalties of 6 and 8.

## Observer view

Code lives in `src/ledger/variants/hidden_objectives/observer.py`. Entry points: `observer_board` and `observer_system`.

The observer board is the acting seat's board with every private number removed. The whole `## Your ledger` section is dropped, including the objective line. The jobs table loses its value column. Seat words are relabelled: the acting seat becomes P-target and the other seat becomes the partner. The board carries no history. Callers that want to show past play add it as their own block.

The observer system block keeps the acting rules bytes, replaces the Mandate paragraph with an observer mandate ("You are an observer, not a player..."), and rewrites the resource addendum in the third person. It names the three resources and states that assignments are private. It never names an assignment.

Measured sizes at scenario index 0, seat 1, turn 1: observer system block 874 tokens, observer board 194 tokens.

This module builds the view only. It does not call models, collect forecasts or score them.

## Library use

All names below are exported from `ledger.variants.hidden_objectives`.

| Function | Purpose |
|---|---|
| `load_bank()` | The studied bank, 12 scenarios. |
| `paper_bank()` | Rebuild the studied bank from its generator settings. |
| `play_episode(sv, opening, objectives, agents, out_dir)` | Play one episode and score it. |
| `outcome(sv, opening, events, objectives)` | Resource scores at end of play and at end of turn 24. |
| `acting_prompt(sv, opening, events, tick, objective)` | Exact prompt bytes and digest the mover saw at a turn. |
| `load_episode(path)` | Meta record and played events from an episode log. Played events have message truncation re-applied. |
| `observer_board`, `observer_system` | The observer view described above. |
| `ModelAgentV2(spec, client, sv, objective)` | The model seat used by the runner. |

Minimal example, run from the repository root. It prints the digest of the turn 1 prompt for the excerpt above:

```python
import sys
sys.path.insert(0, "src")
from ledger.variants import hidden_objectives as ho

sv = ho.load_bank()[0]
data, digest = ho.acting_prompt(sv, 1, [], 1, "cash")
print(digest)
```

Episode logs from `play_episode` add four fields to the meta record: `variant`, `variant_generator_version`, `objectives` and `scored_turns`. The older `generator_version` field still reads `ledger-gen-v1`, as it did in the paper's logs.

## The studied bank

File: `banks/hidden-objectives-iter3.json`. It holds 12 scenarios from seeds 17, 23, 26, 50, 83, 87, 95, 98, 104, 121, 127 and 134. The first scenario ID is `1f1f46fb777e02dd2468d771509cc2e40bff54cbf7fffb868624a290fd9f3300`. The generator version string is `ledger-gen-v2res-1`. Scenario IDs hash that string, so it does not change. Each scenario is played with opening seat 1 or 2. The opening seat is applied when an episode starts, so the bank file stores 12 scenarios, not 24.

## What is not here

The study code that sits around this variant stays in the private study repository: the single-objective solver and its deterministic rollouts, the checks that certified scenario banks before play, the objective-inference and disclosure probes, forecast view builders and reasoning-text redaction, the inactive-assignment control arm, and all campaign drivers and analysis scripts. One consequence to know before you plan reproduction work: frozen decisions that came from solver play in the accompanying paper cannot be regenerated from this repository alone. Episode logs replay exactly, and scripted or model play runs as documented above.
