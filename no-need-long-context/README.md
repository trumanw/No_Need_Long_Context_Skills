# No Need Long Context

Keeps agent context short on long-running projects. Based on Belcak et al., ["You don't need long context"](https://arxiv.org/abs/2611.05306) (2026).

Each workstream keeps a `STATE.md` of about 4000 characters as its compacted state and writes full history to an append-only `LEDGER.md`. A new chat reads one STATE and searches the rest only when needed. In a benchmark on a synthetic multi-day project, resuming in a new chat cost 34% to 59% less with no loss in answer accuracy; see the [repository README](https://github.com/trumanw/No_Need_Long_Context_Skills#readme).

## Contents

- Skill `context-state`: sets up a project, writes the first STATE from existing documents, resumes in a new chat, updates state after events, and hands off.
- Hooks: `afterFileEdit` records files the agent edits; `stop` sends one follow-up when a workstream with a `STATE.md` was edited after that `STATE.md`. The hook runs only local `python3`, makes no network calls, and does nothing when it fails.

## Usage

In a chat in any project, say "initialize this project with context-state". The skill runs `scripts/init.py`, which adds a managed rules block to `AGENTS.md` between `<!-- context-state:begin -->` and `<!-- context-state:end -->` and leaves the rest of the file unchanged. The agent then writes the first `STATE.md` for each workstream.

Requires Python 3.10+ (standard library only). No configuration is needed.

## License

MIT
