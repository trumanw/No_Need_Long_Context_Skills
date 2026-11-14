## Context state rules (context-state)

Long-running work restores context from each workstream's `STATE.md`, not by re-reading every document. Workstreams are listed in the index below.

**New chat**: read only the requested workstream's `STATE.md`. If it lists running jobs, run their check commands and update STATE first. Read other files only through STATE's pointers: locate with `rg -n`, then read a bounded window (about 200 lines or 6000 characters). Never read whole reports, plans, or logs. When STATE is missing, stale, or contradicted by files on disk, trust the files and fix STATE.

**Records**: `STATE.md` is overwritten, at most about 4000 characters, and is a brief for the remaining work; its layout is in `.agents/STATE_TEMPLATE.md`. `LEDGER.md` is append-only, one line per event: `time | event type | content and key values | path or job ID`; search it with `rg`. Reports are for humans; STATE points to their headings.

**When to update** (append to LEDGER first, then rewrite STATE; take every timestamp from `date`, never estimate): after submitting, cancelling, or finding a failed long job; after a result yields a conclusion; after a decision is made or reversed; when the user states a new constraint (record it verbatim); when the chat ends or is handed off; when the chat has grown long (update, then suggest a new chat).

**Compaction rules**: keep only facts relevant to the remaining work, not a narrative; copy the objective verbatim with its completion criterion; separate verified facts (each with a source) from hypotheses; record failed approaches as dead ends; make the next step a concrete command; list every source of a multi-file fact, and record disagreements between files with both sources and the current choice; record what has been read; replace long output with a narrow retrieval command; rewrite from the old STATE, new LEDGER lines, and files on disk, never by summarizing the old STATE; when too long, move stable conclusions into a report and keep a pointer; then update the index status line.

**Parallel chats**: only one chat rewrites a given STATE at a time. Before writing, compare the `updated` line; if it is newer, merge first. Other chats only append to LEDGER.
