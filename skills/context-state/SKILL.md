---
name: context-state
description: Maintains a compact per-workstream STATE.md plus an append-only LEDGER.md so that new chats resume long-running, multi-day work without re-reading the whole project. Use when setting up context handoff in a repository, resuming or handing off an experiment or workstream, after submitting or finishing long jobs, when a chat has grown long, or when the user mentions STATE.md, LEDGER.md, handoff, context compaction, or saving tokens.
---

# Context State

Long work spans many chats. Each chat restores context from one short state file instead of re-reading the project. The method follows Belcak et al., "You don't need long context" (arXiv 2611.05306): frequent compaction keeps accuracy when the compaction is a brief for the remaining work, and full history stays on disk for selective retrieval. See [reference.md](reference.md) for the evidence behind each rule.

Scripts live in this skill's `scripts/` directory. Run them with `python3 <this-skill-dir>/scripts/<name>.py`; they need only the Python 3.8+ standard library.

Write STATE and LEDGER in the language the project's own documents use. Templates exist for `zh` and `en`.

## Files in a target repository

| File | Rule |
|---|---|
| `AGENTS.md` | Managed rules block between `<!-- context-state:begin -->` and `<!-- context-state:end -->`, plus a workstream index. Loaded every chat, so keep it short. |
| `<workstream>/STATE.md` | Overwritten on each update. At most about 4000 characters. |
| `<workstream>/LEDGER.md` | Append-only. One line per event: `time | event type | content and key values | path or job ID`. Never read whole; search with `rg`. |
| `.agents/STATE_TEMPLATE.md` | Section layout for STATE.md. |

## Workflow A: initialize a repository

1. List candidate workstreams: `python3 scripts/init.py --root <repo> --scan`
2. Ask the user which candidates to track and which language to use.
3. Write the managed block, index rows, template, and empty ledgers:
   `python3 scripts/init.py --root <repo> --lang zh --workstream <dir>[=<name>] ...`
   Use `--dry-run` first on repositories that already have an `AGENTS.md`.
4. If `init.py` warns about existing unmanaged state rules in `AGENTS.md`, show the user the overlapping lines and remove them only with their approval.
5. Bootstrap STATE files (Workflow B) only when the user asks: it costs one full read of each workstream.

## Workflow B: bootstrap STATE.md from existing material

1. Read the workstream's own documents and result files once. Do not read other workstreams.
2. Check live jobs (scheduler, systemd, process list, log tails) before writing anything about them.
3. Fill `.agents/STATE_TEMPLATE.md`. Mark facts taken from reports but not checked against result files.
4. Backfill LEDGER.md from documents and file times. Mark inferred times as inferred.
5. Compare documents with each other and with the code that runs. Record every disagreement under contradictions.
6. Update the workstream's status line in the `AGENTS.md` index, then run `scripts/check.py`.

## Workflow C: resume in a new chat

1. Read only the requested workstream's STATE.md.
2. If it lists running jobs, run their check commands first and update STATE.
3. Read other files only through STATE's pointers: locate with `rg -n`, then read a bounded window (about 200 lines or 6000 characters).
4. When STATE is missing, stale, or contradicted by files on disk, trust the files and fix STATE.

## Workflow D: update after an event

Triggers: a long job is submitted, cancelled, or found failed; a result yields a conclusion; a decision is made or reversed; the user states a new constraint (record it verbatim); the chat is ending; the chat has grown long (update, then suggest a new chat).

1. Run `date` and use its output for every timestamp; never estimate the time. Append the event to LEDGER.md.
2. Rewrite STATE.md from three inputs: the old STATE, the new LEDGER lines, and the files on disk. Do not summarize the old STATE again.
3. Apply the compaction rules below.
4. Update the index status line and run `python3 scripts/check.py --root <repo>`.

## Compaction rules

- Select facts relevant to the remaining work. Do not narrate history or give every fact equal weight.
- Copy the objective verbatim and state the completion criterion.
- Keep verified facts and unverified hypotheses apart. Every verified fact names its source (path, heading, line, or job ID). A check that was not run is not verified.
- Record failed approaches under dead ends, with the reason and evidence path.
- Make the next step concrete: a command or an edit.
- List every source when a fact comes from several files. When files disagree, record both sources and the current choice; never silently pick one.
- Record coverage: which files and sections were read and what they yielded, and what was not read.
- Do not paste long output. Write a narrow command that retrieves it.
- Remove a verified fact only when it is overturned, and log the reversal in LEDGER. When STATE exceeds the limit, move stable conclusions into a report and leave a one-line pointer.

## Parallel chats

Only one chat rewrites a given STATE at a time. Before writing, compare the `updated:` line with the value read at the start of the chat; if it is newer, merge first. Other chats only append to LEDGER.

## Validation

`python3 scripts/check.py --root <repo>` reports, per STATE file: missing files, size over the limit, a missing `updated:` line, LEDGER entries newer than STATE, and STATE files absent from the index. It exits 1 on errors, and also on warnings with `--strict`.
