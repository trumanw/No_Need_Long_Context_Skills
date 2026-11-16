#!/usr/bin/env python3
"""Cursor hook: ask the agent to update STATE.md after it edits a workstream.

  context_state_hook.py record   afterFileEdit: log the edited path for this conversation
  context_state_hook.py stop     stop: if a workstream was edited after its STATE.md, send a follow-up

Workstreams are the `<dir>/STATE.md` paths in the AGENTS.md index table. Workstreams
without a STATE.md yet are ignored. Hooks fail open: any error yields an empty response.
"""
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

INDEX_PATH = re.compile(r"`([^`]*STATE\.md)`")
OWN_FILES = {"STATE.md", "LEDGER.md"}
LOG_DIR = Path(os.environ.get("CONTEXT_STATE_HOOK_DIR") or Path(tempfile.gettempdir()) / "context-state-hook")

FOLLOWUP = (
    "context-state: this turn edited files in {names}, but their STATE.md is older than those edits. "
    "Follow Workflow D of the context-state skill: run `date`, append the events to LEDGER.md, "
    "rewrite STATE.md, and update the status line in the AGENTS.md index. "
    "If the edits do not change what the next chat needs to know, say so in one sentence instead."
)


def log_path(conversation_id):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", conversation_id or "unknown")
    return LOG_DIR / f"{safe}.jsonl"


def record(data):
    path = data.get("file_path")
    if not path:
        return {}
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(log_path(data.get("conversation_id")), "a", encoding="utf-8") as f:
        f.write(json.dumps({"path": str(Path(path).resolve()), "t": time.time()}) + "\n")
    return {}


def workstreams(root):
    agents = root / "AGENTS.md"
    if not agents.exists():
        return []
    dirs = []
    for line in agents.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("|"):
            for p in INDEX_PATH.findall(line):
                if not p.endswith("STATE_TEMPLATE.md"):
                    dirs.append((root / p).parent.resolve())
    return dirs


def owner(path, dirs):
    """Deepest workstream directory containing path, or None."""
    best = None
    for d in dirs:
        if path == d or d in path.parents:
            if best is None or len(d.parts) > len(best.parts):
                best = d
    return best


def stop(data):
    log = log_path(data.get("conversation_id"))
    if not log.exists():
        return {}
    edits = [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    log.unlink()
    if data.get("status", "completed") != "completed" or data.get("loop_count", 0) >= 1:
        return {}

    roots = [Path(r) for r in data.get("workspace_roots") or []] or [Path.cwd()]
    stale = {}
    for root in roots:
        dirs = workstreams(root.resolve())
        for e in edits:
            p = Path(e["path"])
            d = owner(p, dirs)
            if d is None or p.name in OWN_FILES:
                continue
            state = d / "STATE.md"
            if state.exists() and state.stat().st_mtime < e["t"]:
                stale[d] = os.path.relpath(d, root)
    if not stale:
        return {}
    names = ", ".join(f"`{v}/`" for v in sorted(stale.values()))
    return {"followup_message": FOLLOWUP.format(names=names)}


def main(argv):
    mode = argv[1] if len(argv) > 1 else ""
    try:
        data = json.loads(sys.stdin.read() or "{}")
        out = {"record": record, "stop": stop}.get(mode, lambda _: {})(data)
    except Exception as exc:  # fail open
        sys.stderr.write(f"context_state_hook: {exc}\n")
        out = {}
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
