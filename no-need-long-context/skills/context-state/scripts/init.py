#!/usr/bin/env python3
"""Set up context-state files in a repository. Safe to re-run.

  init.py --root REPO --scan
  init.py --root REPO [--lang zh|en] [--workstream DIR[=NAME] ...] [--dry-run] [--force-template]
"""
import argparse
import os
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATES = SKILL_DIR / "templates"

BEGIN = "<!-- context-state:begin -->"
END = "<!-- context-state:end -->"
INDEX_HEADING = {"zh": "## 工作线索引", "en": "## Workstream index"}
INDEX_TABLE = {
    "zh": "| 工作线 | 目录 | 状态文件 | 现状 |\n|---|---|---|---|",
    "en": "| Workstream | Directory | State file | Status |\n|---|---|---|---|",
}
NOT_STARTED = {"zh": "未建立", "en": "not started"}
TEMPLATE_DEST = Path(".agents") / "STATE_TEMPLATE.md"

SKIP_DIRS = {"node_modules", "__pycache__", "venv", "build", "dist", "target", "site-packages"}
DOC_FILE = re.compile(r"^(README|PLAN|HANDOFF.*|REPORT.*|NOTES|STATE)\.md$", re.IGNORECASE)
UNMANAGED_HINT = re.compile(r"STATE\.md|LEDGER\.md")


def scan(root: Path, max_depth: int):
    """Directories below root that hold planning or report documents."""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel = Path(dirpath).relative_to(root)
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        if len(rel.parts) >= max_depth:
            dirnames[:] = []
        if not rel.parts:
            continue
        docs = sorted(f for f in filenames if DOC_FILE.match(f))
        if docs:
            found.append((rel.as_posix(), docs))
    return found


def managed_block(lang: str) -> str:
    body = (TEMPLATES / lang / "agents_block.md").read_text(encoding="utf-8").strip()
    return f"{BEGIN}\n{body}\n{END}"


def upsert_block(text: str, block: str) -> str:
    if BEGIN in text and END in text:
        pre, rest = text.split(BEGIN, 1)
        _, post = rest.split(END, 1)
        return pre + block + post
    if not text.strip():
        return f"# AGENTS.md\n\n{block}\n"
    return text.rstrip() + "\n\n" + block + "\n"


def unmanaged_state_lines(text: str):
    outside = text
    if BEGIN in text and END in text:
        pre, rest = text.split(BEGIN, 1)
        outside = pre + rest.split(END, 1)[1]
    return [ln for ln in outside.splitlines() if UNMANAGED_HINT.search(ln) and not ln.lstrip().startswith("|")]


def ensure_index(text: str, lang: str) -> str:
    if any(h in text for h in INDEX_HEADING.values()):
        return text
    return text.rstrip() + f"\n\n{INDEX_HEADING[lang]}\n\n{INDEX_TABLE[lang]}\n"


def add_index_rows(text: str, rows):
    """Insert rows at the end of the table that follows the index heading."""
    heading = next(h for h in INDEX_HEADING.values() if h in text)
    lines = text.split("\n")
    i = next(k for k, ln in enumerate(lines) if ln.strip() == heading)
    j = i + 1
    while j < len(lines) and not lines[j].startswith("|"):
        j += 1
    while j < len(lines) and lines[j].startswith("|"):
        j += 1
    lines[j:j] = rows
    return "\n".join(lines)


def parse_workstream(spec: str):
    path, _, name = spec.partition("=")
    path = path.strip().rstrip("/")
    return path, (name.strip() or Path(path).name)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".", help="repository root (default: current directory)")
    ap.add_argument("--lang", choices=["zh", "en"], default="en")
    ap.add_argument("--workstream", action="append", default=[], metavar="DIR[=NAME]",
                    help="directory relative to root; repeatable")
    ap.add_argument("--scan", action="store_true", help="list candidate workstreams and exit")
    ap.add_argument("--max-depth", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true", help="print planned changes, write nothing")
    ap.add_argument("--force-template", action="store_true", help="overwrite .agents/STATE_TEMPLATE.md")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        sys.exit(f"error: {root} is not a directory")

    if args.scan:
        for rel, docs in scan(root, args.max_depth):
            print(f"{rel}/  ({', '.join(docs)})")
        return 0

    actions = []
    agents = root / "AGENTS.md"
    old = agents.read_text(encoding="utf-8") if agents.exists() else ""
    new = ensure_index(upsert_block(old, managed_block(args.lang)), args.lang)

    rows = []
    for spec in args.workstream:
        path, name = parse_workstream(spec)
        if not (root / path).is_dir():
            sys.exit(f"error: workstream directory {root / path} does not exist")
        state = f"{path}/STATE.md"
        if f"`{state}`" in new:
            continue
        rows.append(f"| {name} | `{path}/` | `{state}` | {NOT_STARTED[args.lang]} |")
        ledger = root / path / "LEDGER.md"
        if not ledger.exists():
            actions.append(("write", ledger,
                            (TEMPLATES / args.lang / "LEDGER.md").read_text(encoding="utf-8").replace("{name}", name)))
    if rows:
        new = add_index_rows(new, rows)
    if new != old:
        actions.insert(0, ("write", agents, new))

    tmpl = root / TEMPLATE_DEST
    if not tmpl.exists() or args.force_template:
        actions.append(("write", tmpl, (TEMPLATES / args.lang / "STATE.md").read_text(encoding="utf-8")))

    for _, path, content in actions:
        rel = path.relative_to(root)
        if args.dry_run:
            print(f"would write {rel} ({len(content)} chars)")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"wrote {rel}")
    if not actions:
        print("nothing to change")

    leftovers = unmanaged_state_lines(new)
    if leftovers:
        print("\nwarning: AGENTS.md mentions STATE/LEDGER outside the managed block; "
              "these lines may duplicate the managed rules:", file=sys.stderr)
        for ln in leftovers:
            print(f"  {ln.strip()[:120]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
