#!/usr/bin/env python3
"""Validate skills/*/SKILL.md (frontmatter, length, links) and .cursor-plugin/plugin.json."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = re.compile(r"^[a-z0-9-]{1,64}$")
LINK = re.compile(r"\]\(([^)#\s]+)\)")
PLUGIN_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")


def validate(skill_md: Path):
    errors = []
    text = skill_md.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not m:
        return [f"{skill_md}: missing YAML frontmatter"]
    meta = dict(re.findall(r"^(\w[\w-]*):\s*(.*)$", m.group(1), re.MULTILINE))
    body = m.group(2)
    name, desc = meta.get("name", ""), meta.get("description", "")
    if not NAME.match(name):
        errors.append(f"{skill_md}: name {name!r} must be 1-64 chars of a-z, 0-9, '-'")
    if name != skill_md.parent.name:
        errors.append(f"{skill_md}: name {name!r} differs from directory {skill_md.parent.name!r}")
    if not 0 < len(desc) <= 1024:
        errors.append(f"{skill_md}: description must be 1-1024 chars (got {len(desc)})")
    if len(body.splitlines()) >= 500:
        errors.append(f"{skill_md}: body must stay under 500 lines")
    for target in LINK.findall(body):
        if "://" not in target and not (skill_md.parent / target).exists():
            errors.append(f"{skill_md}: broken link {target}")
    return errors


def validate_plugin():
    """Checks from the Cursor plugin submission list: kebab-case name, relative paths."""
    errors = []
    manifest = ROOT / ".cursor-plugin" / "plugin.json"
    if not manifest.exists():
        return [f"{manifest}: missing"]
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if not PLUGIN_NAME.match(data.get("name", "")):
        errors.append(f"{manifest}: name {data.get('name')!r} must be lowercase kebab-case")
    for key in ("skills", "rules", "agents", "commands", "hooks", "logo"):
        for p in ([data[key]] if isinstance(data.get(key), str) else data.get(key) or []):
            if not isinstance(p, str):
                continue
            if p.startswith("/") or ".." in Path(p).parts:
                errors.append(f"{manifest}: {key} path {p!r} must be relative without '..'")
            elif not (ROOT / p).exists():
                errors.append(f"{manifest}: {key} path {p!r} does not exist")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if f"## {data.get('version')} " not in changelog:
        errors.append(f"CHANGELOG.md: no entry for version {data.get('version')}")
    return errors


def main():
    skills = sorted((ROOT / "skills").glob("*/SKILL.md"))
    if not skills:
        print("no skills found")
        return 1
    errors = [e for s in skills for e in validate(s)] + validate_plugin()
    for e in errors:
        print(e)
    print(f"{len(skills)} skill(s) checked, {len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
