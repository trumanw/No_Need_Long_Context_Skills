#!/usr/bin/env python3
"""Check context-state files in a repository.

  check.py --root REPO [--limit 4000] [--strict] [--json]

Exit status: 1 if any ERROR (or any WARN with --strict), else 0.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

BEGIN = "<!-- context-state:begin -->"
AGENTS_LIMIT = 6000
CLOCK_SLACK_S = 600
SKIP_DIRS = {"node_modules", "__pycache__", "venv", "build", "dist", "target", "site-packages"}
STAMP = re.compile(r"(\d{4}-\d{2}-\d{2})[ T_](\d{2}:\d{2})")
INDEX_PATH = re.compile(r"`([^`]*STATE\.md)`")


def parse_time(s: str):
    m = STAMP.search(s)
    return datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M") if m else None


def find_states(root: Path):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        if "STATE.md" in filenames:
            out.append((Path(dirpath) / "STATE.md").relative_to(root).as_posix())
    return out


def check(root: Path, limit: int):
    findings = []

    def add(level, path, msg):
        findings.append({"level": level, "path": path, "message": msg})

    agents = root / "AGENTS.md"
    indexed = []
    if not agents.exists():
        add("ERROR", "AGENTS.md", "missing; run init.py")
    else:
        text = agents.read_text(encoding="utf-8")
        if BEGIN not in text:
            add("WARN", "AGENTS.md", "no managed context-state block; run init.py")
        if len(text) > AGENTS_LIMIT:
            add("WARN", "AGENTS.md", f"{len(text)} chars; it is loaded every chat, keep it under {AGENTS_LIMIT}")
        indexed = [p for ln in text.splitlines() if ln.lstrip().startswith("|")
                   for p in INDEX_PATH.findall(ln) if not p.endswith("STATE_TEMPLATE.md")]

    on_disk = find_states(root)
    for rel in sorted(set(indexed) | set(on_disk)):
        path = root / rel
        if not path.exists():
            add("INFO", rel, "listed in the index but not created yet")
            continue
        if rel not in indexed:
            add("WARN", rel, "not listed in the AGENTS.md index")
        text = path.read_text(encoding="utf-8")
        n = len(text)
        if n > limit * 1.5:
            add("ERROR", rel, f"{n} chars, far over the {limit} limit; move stable facts to a report")
        elif n > limit * 1.05:
            add("WARN", rel, f"{n} chars, over the {limit} limit")
        updated_line = next((ln for ln in text.splitlines() if ln.lower().startswith("updated:")), None)
        updated = parse_time(updated_line) if updated_line else None
        if updated is None:
            add("ERROR", rel, "no parsable 'updated: YYYY-MM-DD HH:MM' line")
        else:
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            if (updated - mtime).total_seconds() > CLOCK_SLACK_S:
                add("WARN", rel, f"updated {updated:%Y-%m-%d %H:%M} is later than the file's "
                                 f"modification time {mtime:%Y-%m-%d %H:%M}; take the time from `date`")
        ledger = path.parent / "LEDGER.md"
        if not ledger.exists():
            add("WARN", rel, "no LEDGER.md beside it")
        elif updated is not None:
            newer = [t for t in (parse_time(ln) for ln in ledger.read_text(encoding="utf-8").splitlines()
                                 if ln[:1].isdigit()) if t and t > updated]
            if newer:
                add("WARN", rel, f"LEDGER has {len(newer)} entries newer than STATE (latest {max(newer):%Y-%m-%d %H:%M}); rewrite STATE")
        if not findings or findings[-1]["path"] != rel:
            add("OK", rel, f"{n} chars, updated {updated:%Y-%m-%d %H:%M}")
    return findings


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".")
    ap.add_argument("--limit", type=int, default=4000, help="STATE.md character limit")
    ap.add_argument("--strict", action="store_true", help="treat warnings as failures")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    findings = check(Path(args.root).resolve(), args.limit)
    if args.json:
        print(json.dumps(findings, ensure_ascii=False, indent=1))
    else:
        for f in findings:
            print(f"{f['level']:5} {f['path']}: {f['message']}")
    levels = {f["level"] for f in findings}
    return 1 if "ERROR" in levels or (args.strict and "WARN" in levels) else 0


if __name__ == "__main__":
    sys.exit(main())
