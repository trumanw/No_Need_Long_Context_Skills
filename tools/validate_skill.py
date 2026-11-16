#!/usr/bin/env python3
"""Validate .cursor-plugin/marketplace.json, each plugin's manifest, and its skills/*/SKILL.md."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = re.compile(r"^[a-z0-9-]{1,64}$")
LINK = re.compile(r"\]\(([^)#\s]+)\)")
PLUGIN_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
# Cursor's importer rejects "." and "./dir" sources without an error; it needs a bare directory name.
SOURCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


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


def plugin_dirs():
    """Plugin directories listed in the marketplace manifest, plus errors in that manifest."""
    manifest = ROOT / ".cursor-plugin" / "marketplace.json"
    if not manifest.exists():
        return [], [f"{manifest}: missing"]
    data = json.loads(manifest.read_text(encoding="utf-8"))
    errors, dirs = [], []
    if not PLUGIN_NAME.match(data.get("name", "")):
        errors.append(f"{manifest}: name {data.get('name')!r} must be lowercase kebab-case")
    if not (data.get("owner") or {}).get("name"):
        errors.append(f"{manifest}: owner.name is required")
    base = ROOT / (data.get("metadata") or {}).get("pluginRoot", "")
    for entry in data.get("plugins") or []:
        source = entry.get("source", "")
        if not isinstance(source, str) or not SOURCE.match(source):
            errors.append(f"{manifest}: source {source!r} must be a bare directory name, not '.' or './dir'")
            continue
        d = base / source
        if not (d / ".cursor-plugin" / "plugin.json").exists():
            errors.append(f"{manifest}: {d.relative_to(ROOT)}/.cursor-plugin/plugin.json missing")
            continue
        name = json.loads((d / ".cursor-plugin" / "plugin.json").read_text(encoding="utf-8")).get("name")
        if entry.get("name") != name:
            errors.append(f"{manifest}: entry name {entry.get('name')!r} differs from plugin name {name!r}")
        dirs.append(d)
    if not dirs and not errors:
        errors.append(f"{manifest}: no plugins listed")
    return dirs, errors


def validate_plugin(plugin_dir: Path):
    """Checks from the Cursor plugin submission list: kebab-case name, relative paths."""
    errors = []
    manifest = plugin_dir / ".cursor-plugin" / "plugin.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if not PLUGIN_NAME.match(data.get("name", "")):
        errors.append(f"{manifest}: name {data.get('name')!r} must be lowercase kebab-case")
    for key in ("skills", "rules", "agents", "commands", "hooks", "logo"):
        for p in ([data[key]] if isinstance(data.get(key), str) else data.get(key) or []):
            if not isinstance(p, str):
                continue
            if p.startswith("/") or ".." in Path(p).parts:
                errors.append(f"{manifest}: {key} path {p!r} must be relative without '..'")
            elif not (plugin_dir / p).exists():
                errors.append(f"{manifest}: {key} path {p!r} does not exist")
    if not (plugin_dir / "README.md").exists():
        errors.append(f"{plugin_dir}: README.md missing")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if f"## {data.get('version')} " not in changelog:
        errors.append(f"CHANGELOG.md: no entry for version {data.get('version')}")
    return errors


def main():
    dirs, errors = plugin_dirs()
    skills = sorted(s for d in dirs for s in (d / "skills").glob("*/SKILL.md"))
    if dirs and not skills:
        errors.append("no skills found")
    errors += [e for s in skills for e in validate(s)] + [e for d in dirs for e in validate_plugin(d)]
    for e in errors:
        print(e)
    print(f"{len(dirs)} plugin(s), {len(skills)} skill(s) checked, {len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
