# Evidence behind the rules

Source: P. Belcak et al., "You don't need long context", arXiv 2611.05306 (2026).

## What the paper measured

- **Long-horizon tasks.** End-of-conversation compaction (EoCC) at 16K–48K total context changed accuracy by −3.7 to +5.6 points (Claude Opus 4.5) and −3.3 to +4.4 points (GPT 5.6 Sol) against full history, at 2.2–8.8× lower estimated cost.
- **Long-input tasks.** Storing documents as files and reading them selectively (`grep` to locate, bounded reads of about 6000 characters) matched or beat pasting the full input, by up to +40 points, at 4.4–233× lower estimated cost. Conversation length stayed roughly flat as document size grew by orders of magnitude.
- **Single-action compaction (SAC).** Compacting after every action kept peak context at 15–37K tokens. Accuracy held for Opus and fell 2–3 points for GPT. The best EoCC setting beat SAC in all four reported comparisons.

## What a good compaction contains (Appendix A)

Not a faithful summary. Summaries weight all facts equally and over-weight repeated trace segments. The best compactions are briefs for the remaining work:

1. the task, verbatim or nearly so;
2. the current activity, intentions, and next steps;
3. artifacts relevant to future work: the decomposed plan, the completion requirements, and pointers to files holding further detail.

The paper's compaction prompt (Appendix G.1) asks for: objective; established facts, with observations separate from unverified ideas; applied changes and their verification status; checks run and their outcomes; dead ends; and the remaining plan with the immediate next command and the completion condition. Truncated output is replaced by a narrow command that retrieves it. Observations are never invented.

For human-in-the-loop work, the compaction must also keep the human's instructions and preferences.

## Why this skill uses event-triggered EoCC, not SAC

- Interactive IDE chats cannot discard history after every action; only a harness can.
- SAC was tested only on autonomous tasks; EoCC scored higher where both were measured.
- In experiment-driven work, one action may be a multi-day job. Actions are few and expensive, so per-action rewrites save little and add output tokens.
- A scheduled, unattended job (read STATE, check jobs, append LEDGER, update STATE, exit) is a natural SAC step and can be added on top.

## Why history goes to a ledger

Compaction is lossy, and compacting an earlier compaction loses more. Any fact a later step might need exactly (the i-th coin toss in the paper's example) must stay retrievable. The ledger keeps every event on disk; the agent searches it instead of carrying it.

## Measuring savings in your project

Static estimate: count the tokens a fresh chat would read without STATE (the documents, scripts, and results it needs) against `AGENTS.md` plus one STATE. Multiply by the number of turns, since loaded context is re-sent every turn (usually cached at a lower price).

A/B test: run the same resume prompt in two fresh chats, one with STATE and one with `AGENTS.md` and STATE temporarily renamed. Compare input, cached, and output tokens in the usage dashboard, and score both answers against a fixed checklist of facts the next step depends on.
