# Changelog

## 0.2.1 - 2026-11-16

- Rules block and resume workflow: a request names a workstream when it mentions its name, its directory, or any file under it. Re-run `init.py` to update an existing `AGENTS.md`.
- Resuming no longer rewrites STATE when a job check matches it, and routine resumes do not read the full skill. Both were the main fixed cost of a resume in the benchmark pilot.
- Compaction rules: the next step must be a command or script that exists in the project; unconfirmed steps go under hypotheses. Rewrites keep the existing STATE layout instead of rereading the template.
- The 4000-character STATE size is a target, not a hard limit: up to 25% over needs no rewrite, and `check.py` warns only above that. Grok 4.7 treated it as hard and spent most of a day's tokens trimming a few hundred characters.
- STATE is written in one whole-file write. When it is over the limit, one stable section moves to a report in a single edit, instead of trimming and rechecking in a loop; routine updates skip `check.py` and do not edit the moved-out sections afterwards. The trim loop was most of the bootstrap cost for Grok 4.7.
- The skill description no longer asks to be loaded for routine resumes and job updates, which contradicted the rules block; the block no longer names the template, which only a first STATE needs.
- `benchmark/`: A/B token benchmark on a synthetic multi-day project, run through the Cursor SDK.

## 0.2.0 - 2026-11-14

- Stop reminder hook (`hooks/`): `afterFileEdit` logs files the agent edits; `stop` sends one follow-up when a workstream with a STATE.md was edited after that STATE.md. Fails open; at most one follow-up per turn.

## 0.1.0 - 2026-11-14

- `context-state` skill: per-workstream `STATE.md` plus append-only `LEDGER.md`, managed `AGENTS.md` rules block, `zh` and `en` templates.
- `init.py`: scan for workstreams; idempotent `AGENTS.md` block and index; template and ledger scaffolding; warns about unmanaged rules.
- `check.py`: size limit, missing or future `updated:` time, ledger newer than state, unindexed state files.
