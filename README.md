# LEDGER

LEDGER is a research environment for language-model agents. Two agents run one venture together, make contracts, spend a shared budget, and finish jobs before a deadline. You can use it to study whether one agent can predict what another agent will do next. In the accompanying paper, LEDGER is called Contracting.

## How the game works

Numbers below are the default game. Full rules are in [docs/ENVIRONMENT_DESIGN.md](docs/ENVIRONMENT_DESIGN.md).

- Two seats, P1 and P2, take turns. Each turn has one action. The default game lasts 24 turns.
- The board has 8 jobs. Each job has a public cost for each seat and a private value for each seat. A seat sees only its own values.
- Some jobs need another job finished first. A finished job pays each seat its own value for that job.
- Jobs are paid from a shared pot of 100. Money left in the pot at the end is lost.
- Seats make contracts that assign jobs and set payments. An accepted contract binds at once.
- A seat can take money from the pot alone, without the partner's consent. The partner sees it at once.
- A seat can break a contract, but it pays a penalty. A job that is never finished also costs a penalty.
- Seats can send short messages to each other.
- A seat's score is the value of finished jobs for that seat, plus payments and penalties in its account.
- There is no shell, network, or file access inside the game.

## Quick start

You need Python 3.10 or later.

```powershell
git clone https://github.com/lmmontoya-ai/ledger
cd ledger
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest -q
```

The clone makes a folder named `ledger`. The next lines make a `.venv` folder for this project and install LEDGER and the test tools into it. The last line runs the tests: expect 215 tests to pass. On Linux or macOS, use `.venv/bin/python` in place of `.venv\Scripts\python`. Run a free scripted game with the next command.

```powershell
.venv\Scripts\python scripts\run_episode.py --bank v1-e0 --index 0 --p1 scripted:always-cooperate --p2 scripted:tit-for-tat --out data\runs\smoke
```

Expect scores (117, 87), agreement True, and $0.0000 over 0 calls. It needs no key and no network.

Run with a model through OpenRouter. Copy the example model file and edit the model names and prices in `models.json` first. The key comes from the `OPENROUTER_API_KEY` environment variable. Do not put a key in any file.

```powershell
.venv\Scripts\python -m pip install -e ".[runtime]"
Copy-Item models.example.json models.json
$env:OPENROUTER_API_KEY = "your key here"
.venv\Scripts\python scripts\run_episode.py --variant hidden-objectives --index 0 --opening 1 --objectives cash,materials --models models.json --p1 model:sonnet --p2 model:gpt --cap-usd 2 --out data\runs\pilot
```

Without a key, the runner stops before any call with `no API key: pass api_key or set OPENROUTER_API_KEY`.

## What an agent sees

The mover reads rules and a board that shows jobs, deals, accounts, and past turns. The board shows only the mover's own private values. The block below is real output. It is part of the board for P1 at turn 9, cut after job 6. The full prompt is in [tests/golden/worked_tick9_p1.txt](tests/golden/worked_tick9_p1.txt).

```text
LEDGER · turn 9 of 24 · your move · you are P1

## Position
POT shared budget: 73 of 100 left · destroyed after turn 24
DRAWS taken alone: you 0 of 25 · them 0 of 25
SLOTS    you 2/3 left · them 3/3 left
ACCOUNT  you 0 · them 0

## Jobs
JOB  YOUR-COST  THEIR-COST  YOUR-VALUE  NEEDS FIRST  STATUS
 1       14         21           0            -  open
 2       27         13          30            -  open
 3       12         22          30            -  DONE by you, turn 7
 4       19         19           8            -  open
 5       27         14           0            3  open
 6       28         15          35            3  open            <- them must do this (deal 1)
```

## Use in the accompanying paper

The paper used the hidden-objectives variant. Each job pays in three resources: cash, materials, and standing. Each seat is told in private which one resource counts for it, and the other seat is not told. Games last 48 turns, and the score uses turns 1 to 24. One point needs care: the rules text in the prompt states 24 turns and penalties of 6 and 8, while the studied game used 48 turns and penalties of 2 and 3. The full statement is in [docs/VARIANTS.md](docs/VARIANTS.md#the-rules-text-and-the-enforced-parameters).

Run the variant at no cost with scripted seats:

```powershell
.venv\Scripts\python scripts\run_episode.py --variant hidden-objectives --index 0 --opening 1 --objectives cash,standing --p1 scripted:greedy-optimal --p2 scripted:tit-for-tat --out data\runs\smoke
```

Expect assigned payoff (2, 0) and final tick 5. Full usage is in [docs/VARIANTS.md](docs/VARIANTS.md).

## Reproducibility

The game is deterministic. The same scenario and the same actions always give the same prompts and the same scores, and any recorded game replays exactly. This release was checked against the recorded runs behind the accompanying paper, with zero mismatches. All counts and log details are in [docs/REPRODUCIBILITY.md](docs/REPRODUCIBILITY.md).

## Documentation

- [docs/VARIANTS.md](docs/VARIANTS.md): exact usage for the hidden-objectives variant and its observer view.
- [docs/ENVIRONMENT_DESIGN.md](docs/ENVIRONMENT_DESIGN.md): the full design of the default game.
- [docs/REPRODUCIBILITY.md](docs/REPRODUCIBILITY.md): determinism, replay, log format, equivalence counts, token budget, and repository layout.
- [docs/EXPERIMENT_PLAN.md](docs/EXPERIMENT_PLAN.md), [docs/RETUNE_PLAN.md](docs/RETUNE_PLAN.md), [docs/M0_VALIDATION.md](docs/M0_VALIDATION.md), [docs/M0_DECISIONS.md](docs/M0_DECISIONS.md), [docs/M0_SPEC_FINDINGS.md](docs/M0_SPEC_FINDINGS.md), [docs/M0_SAMPLE_BOARDS.md](docs/M0_SAMPLE_BOARDS.md): dated plans and first-build records, kept as written.

## Known limitations

- The rules text for the studied variant states 24 turns and penalties of 6 and 8, while the game uses 48 turns and penalties of 2 and 3. The text is kept as studied so replay stays exact. See [docs/VARIANTS.md](docs/VARIANTS.md#the-rules-text-and-the-enforced-parameters).
- Only OpenRouter works as a provider. Model names and prices in `models.example.json` are examples. Check current OpenRouter pricing before a run.
- Short messages are cut by token count with tiktoken. The episode runner refuses model seats if tiktoken is missing.
- Some core functions describe the default game only. For the variant, use `acting_prompt` and `outcome` from `ledger.variants.hidden_objectives`.
- The full equivalence check needs the private research code. Public users can run the frozen-fixture tests in `tests/test_hidden_objectives.py`.

## Related environments

All three native environments in the accompanying paper are public:

- LEDGER, called Contracting in the accompanying paper: [https://github.com/lmmontoya-ai/ledger](https://github.com/lmmontoya-ai/ledger).
- FORGE, called Engineering in the accompanying paper: [https://github.com/lmmontoya-ai/forge](https://github.com/lmmontoya-ai/forge).
- Commons, called Office in the accompanying paper: [https://github.com/lmmontoya-ai/commons](https://github.com/lmmontoya-ai/commons).

## Citation

Placeholder. The owner will add the citation for the accompanying paper here.

```bibtex
% TODO(owner): replace with the paper citation.
```

## License

Not yet chosen. The owner will add a LICENSE file.
