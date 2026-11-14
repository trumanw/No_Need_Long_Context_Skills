# Changelog

## 0.1.0 - 2026-11-14

- `context-state` skill: per-workstream `STATE.md` plus append-only `LEDGER.md`, managed `AGENTS.md` rules block, `zh` and `en` templates.
- `init.py`: scan for workstreams; idempotent `AGENTS.md` block and index; template and ledger scaffolding; warns about unmanaged rules.
- `check.py`: size limit, missing or future `updated:` time, ledger newer than state, unindexed state files.
