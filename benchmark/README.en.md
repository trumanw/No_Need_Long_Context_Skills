# Token benchmark

[中文](README.md) | English

The Cursor SDK compares two conditions on the same synthetic project. It records the token usage the SDK reports and whether the answers are correct, and converts usage to dollars at Cursor list prices.

- **baseline**: the project has only a plain `AGENTS.md` (project description and layout).
- **context-state**: baseline plus the context-state rules block, the skill, the stop hook, and a `STATE.md` and `LEDGER.md` written by one bootstrap run of the same model. The cost of the bootstrap run is recorded separately as a one-time cost.

Apart from these, the project files of the two conditions are byte-for-byte identical (`tests/test_benchmark.py` checks this). Every run is a new chat in a fresh copy of the project. Only project-level settings are loaded (`setting_sources=["project"]`), not the user rules and plugins on the local machine.

## Synthetic project

`fixture.py` generates a catalyst-screening study that has run for two days: three workstreams, plans and reports, job logs, a job queue, and a submit script. The facts to be answered are scattered through the middle of long reports and in logs, and the plan contradicts a later report in one place (the functional changed from PBE to RPBE). `advance` simulates the passing of a day: running jobs complete, and rerun results appear only if the agent actually submitted the rerun the day before.

`--scales` sets the project size. The facts stay the same; only report paragraphs, log length, and old notes grow:

| Size | Files | Characters |
|---|---|---|
| x1 | 17 | about 119K |
| x3 | 23 | about 355K |
| x6 | 32 | about 748K |

## Tasks

| Suite | Tasks | Grading |
|---|---|---|
| `resume` | R1 current status and next step, R2 functional and why, R3 surrogate model choice and open issues, R4 failures and how they were handled | Key facts in the answer (regular expressions) |
| `multiday` | Four days in a row, one new chat per day: "Continue the dft-screen work."; day four asks for `FINAL.md` | Answer facts plus disk checks (whether the rerun was really submitted with the right parameters, `volcano.json` was produced, `FINAL.md` was written) |

## Running

```bash
python3 -m venv .venv && .venv/bin/pip install -r benchmark/requirements.txt
export CURSOR_API_KEY=...                      # Cursor Dashboard → Integrations
.venv/bin/python benchmark/run.py --list-models --models grok-4.7 composer-2.5
.venv/bin/python benchmark/run.py --probe --models "composer-2.5:fast=false"

.venv/bin/python benchmark/run.py --suite resume --suite multiday \
    --models "grok-4.7:context=256k,reasoning_effort=high,fast=false" "composer-2.5:fast=false" \
    --scales 1 3 6 --reps 3 --out benchmark/results/raw.jsonl

.venv/bin/python benchmark/report.py benchmark/results/raw.jsonl
```

- Give models with all parameters (`--list-models` lists the values). Without them the SDK uses the default variant, which may be priced as the Fast tier. Every record stores the model and parameters actually used (`model_resolved`).
- `--probe` asks the model to read a code word from a file, to confirm that tool calls work. Answering only "OK" does not pass.
- Finished records are skipped automatically, so after an interruption rerun the same command to continue. Two errors in a row abort the run.
- `report.py` writes `results/summary.md` and `results/figures/*.png`.

## Isolation

The agent can read any absolute path, so a working directory alone does not keep it from seeing the answers. The current measures:

- The project contains no text or path that hints it is in a test. The hook script is copied into the project and called by a relative path.
- Run copies live outside the repository (by default `/tmp/cs-lab`), only one copy exists at a time, and its path does not reveal the condition. All other copies sit in a directory with permissions 000.
- After each run, that copy's chat transcripts under `~/.cursor/projects/` are deleted.
- Paths outside the working directory that the agent read are recorded (`outside_paths`), and the report excludes those runs.

## Prices

`prices.json` is copied from [Cursor models and pricing](https://cursor.com/docs/models-and-pricing) (2026-11-15), in US dollars per million tokens. Cost = uncached input × input price + cache reads × cache-read price + output × output price. These two models have no separate cache-write price, so cache writes are billed at the input price. Runs whose variant is not in the price table fall back to relative weights (`--prices`) and are marked `*` in the table. On paid plans, Composer 2.5 and Grok 4.7 draw on the weekly included usage first, so the actual charge may be lower than list price.

## Caveats

- Token counts are the values the SDK reports at run time. The system prompt and tool set inside the IDE differ, so absolute numbers will differ; the ratios are more meaningful.
- Each task is repeated only 3 times, and a single task can vary by ±50%. Look at suite totals and trends across sizes, not at single runs.
- The method itself was corrected during pilot runs with Grok 4.7 at x1: repeated trimming of STATE and reading the skill on routine resumes were fixed (see `CHANGELOG.md` 0.2.1). After the corrections the method was frozen; all formal data uses the frozen version, and project copies are regenerated from a hash of the skill files.
- Only Grok 4.7 and Composer 2.5 were tested. Claude, GPT, and Gemini were not available through the SDK in the region where the tests ran; Kimi K3 could not make tool calls through the SDK.
- The largest synthetic project is about 748K characters, still smaller than many real long-running projects. The more material there is, the more baseline reads, and the larger the gap usually becomes.
