"""Run the A/B token benchmark through the Cursor SDK.

Every run is a fresh chat in a fresh copy of the synthetic project. The
baseline copy has a plain AGENTS.md; the context copy also has the
context-state rules, the skill, the stop hook, and STATE.md files written by
one bootstrap run of the same model. Records are appended to a JSONL file as
they finish, and an interrupted benchmark resumes where it stopped.

    export CURSOR_API_KEY=...
    python3 benchmark/run.py --list-models
    python3 benchmark/run.py --suite resume --models composer-2.5 --reps 1 \\
        --out benchmark/results/pilot.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixture  # noqa: E402
from tasks import BOOTSTRAP, SUITES, Task  # noqa: E402

HERE = Path(__file__).resolve().parent
CONDITIONS = ("baseline", "context")
READ_HINTS = ("read", "grep", "glob", "search", "ls", "list")


def model_selection(spec: str) -> Any:
    """`id` or `id:param=value,param=value`."""
    from cursor_sdk import ModelParameterValue, ModelSelection

    if ":" not in spec:
        return spec
    mid, params = spec.split(":", 1)
    pairs = [p.split("=", 1) for p in params.split(",") if p]
    return ModelSelection(id=mid, params=[ModelParameterValue(id=k, value=v) for k, v in pairs])


def field(msg: Any, name: str) -> Any:
    if isinstance(msg, Mapping):
        return msg.get(name)
    return getattr(msg, name, None)


def strings_in(obj: Any) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, Mapping):
        return [s for v in obj.values() for s in strings_in(v)]
    if isinstance(obj, (list, tuple)):
        return [s for v in obj for s in strings_in(v)]
    return []


def run_agent(prompt: str, cwd: Path, model: str, timeout_s: int) -> dict[str, Any]:
    from cursor_sdk import Agent, LocalAgentOptions

    tools: list[dict[str, Any]] = []
    result_chars = 0
    summaries = 0
    turns = 0
    status_msgs: list[str] = []
    start = time.monotonic()
    with Agent.create(
        model=model_selection(model),
        api_key=os.environ["CURSOR_API_KEY"],
        local=LocalAgentOptions(cwd=str(cwd), setting_sources=["project"]),
    ) as agent:
        run = agent.send(prompt)
        run_id, agent_id = run.id, agent.agent_id
        timer = threading.Timer(timeout_s, lambda: run.status == "running" and run.cancel())
        timer.start()
        try:
            for msg in run.messages():
                kind = field(msg, "type")
                if kind == "tool_call" and field(msg, "status") in ("completed", "error"):
                    args = field(msg, "args")
                    tools.append({"name": field(msg, "name"),
                                  "args": [s[:300] for s in strings_in(args)][:6]})
                    result_chars += len(json.dumps(field(msg, "result"), default=str))
                elif kind == "summary" and field(msg, "status") == "completed":
                    summaries += 1
                elif kind == "usage":
                    turns += 1
                elif kind == "status" and field(msg, "message"):
                    status_msgs.append(f'{field(msg, "status")}: {field(msg, "message")}'[:500])
            result = run.wait()
        finally:
            timer.cancel()
        usage = result.usage
    arg_text = " ".join(s for t in tools for s in t["args"])
    allowed = (str(cwd), str(transcripts_dir(cwd)))
    # Listing an ancestor only shows this workspace and the locked vault.
    ancestors = {str(p) for p in cwd.parents}
    outside = sorted({s for t in tools for s in t["args"]
                      if s.startswith("/") and not s.startswith(allowed)
                      and s.rstrip("/") not in ancestors})
    return {
        "status": result.status,
        "error": None if result.status == "finished" else {
            "code": getattr(result, "error_code", None),
            "message": getattr(result, "error_message", None),
            "status_messages": status_msgs[-5:],
        },
        "answer": result.result or "",
        "duration_s": round(time.monotonic() - start, 1),
        "usage": None if usage is None else {
            "input": usage.input_tokens, "output": usage.output_tokens,
            "cache_read": usage.cache_read_tokens, "cache_write": usage.cache_write_tokens,
            "total": usage.total_tokens, "reasoning": usage.reasoning_tokens,
        },
        "turns": turns,
        "summaries": summaries,
        "tool_calls": len(tools),
        "read_like_calls": sum(any(h in str(t["name"]).lower() for h in READ_HINTS) for t in tools),
        "tool_result_chars": result_chars,
        "touched_state": "STATE.md" in arg_text,
        "outside_paths": outside[:20],
        "tools": tools,
        "run_id": run_id,
        "agent_id": agent_id,
        "model_resolved": resolved(getattr(result, "model", None)),
    }


def resolved(sel: Any) -> dict[str, Any] | None:
    """The model and parameters the run actually used, which decide its price."""
    if sel is None:
        return None
    params = field(sel, "params") or []
    return {"id": field(sel, "id"),
            "params": {str(field(p, "id")): str(field(p, "value")) for p in params}}


def check_state(root: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, str(fixture.SKILL_DIR / "scripts" / "check.py"), "--root", str(root),
         "--json"], capture_output=True, text=True)
    try:
        return json.loads(proc.stdout)
    except ValueError:
        return {"raw": proc.stdout[-2000:], "exit": proc.returncode}


class Abort(Exception):
    pass


PRIVATE_FIELDS = ("run_id", "agent_id")


def public(rec: Mapping[str, Any]) -> str:
    """One JSON line safe to publish: no account-linked ids, home directory as `~`."""
    line = json.dumps({k: v for k, v in rec.items() if k not in PRIVATE_FIELDS}, ensure_ascii=False)
    return line.replace(str(Path.home()), "~")


class Recorder:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.done: set[tuple] = set()
        self.errors_in_a_row = 0
        if path.exists():
            for line in path.read_text().splitlines():
                r = json.loads(line)
                if r.get("status") == "finished":
                    self.done.add(self.key(r))

    @staticmethod
    def key(r: Mapping[str, Any]) -> tuple:
        return (r["model"], r.get("scale", 1), r["suite"], r["condition"], r["rep"], r["task"])

    def write(self, rec: dict[str, Any]) -> None:
        with open(self.path, "a") as f:
            f.write(public(rec) + "\n")
        status = rec["status"]
        tok = (rec.get("usage") or {}).get("total")
        score = f'{rec["score"]}/{rec["facts_total"]}'
        print(f'[{rec["model"]} x{rec.get("scale", 1)}] {rec["suite"]:9} {rec["condition"]:8} rep{rec["rep"]} '
              f'{rec["task"]:14} {status:9} tokens={tok} score={score}', flush=True)
        if rec.get("error"):
            print(f'    error: {json.dumps(rec["error"], ensure_ascii=False)}', flush=True)
            self.errors_in_a_row += 1
        else:
            self.errors_in_a_row = 0
        if self.errors_in_a_row >= 2:
            raise Abort("two runs in a row failed; fix the error above and rerun")


def execute(task: Task, root: Path, model: str, meta: dict[str, Any], args, rec: Recorder) -> dict:
    out = run_agent(task.prompt, root, model, args.timeout)
    facts = task.grade(out["answer"], root)
    record = {
        **meta, "task": task.id, "model": model, "fixture": fixture_version(),
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **{k: v for k, v in out.items() if k != "answer"},
        "answer": out["answer"][:3000],
        "facts": [{"fact": f, "ok": ok} for f, ok in facts],
        "score": sum(ok for _, ok in facts), "facts_total": len(facts),
    }
    if meta["condition"] == "context":
        record["check"] = check_state(root)
    rec.write(record)
    return record


def transcripts_dir(cwd: Path) -> Path:
    """Where Cursor keeps this workspace's chat transcripts."""
    return Path.home() / ".cursor" / "projects" / re.sub(r"[^A-Za-z0-9]+", "-", str(cwd)).strip("-")


class Lab:
    """Keeps every project copy except the active one unreadable.

    Agents explore: given the chance they read sibling runs, the base copies,
    or this repository. Only one workspace exists at a time, under a path that
    says nothing about the benchmark, and everything else sits in a vault with
    mode 000 while an agent runs.
    """

    def __init__(self, work: Path):
        self.work = work
        self.vault = work / "vault"
        self.vault.mkdir(parents=True, exist_ok=True)
        self.lock()

    def lock(self) -> None:
        self.vault.chmod(0)

    def unlock(self) -> None:
        self.vault.chmod(0o700)

    def base(self, model: str, cond: str, scale: int) -> Path:
        return (self.vault / "bases" / fixture_version() / slug(model) / f"x{scale}" / cond
                / PROJECT)

    def checkout(self, src: Path | None, cond: str, scale: int) -> Path:
        """Copy src (or build a fresh fixture) into a new workspace."""
        root = self.work / "ws" / uuid.uuid4().hex[:8] / PROJECT
        self.unlock()
        try:
            if src is None:
                fixture.build(root, cond, scale)
            else:
                shutil.copytree(src, root, symlinks=True)
        finally:
            self.lock()
        if not (root / ".git").exists():
            subprocess.run(["git", "init", "-q", str(root)], check=True)
        return root

    def checkin(self, root: Path, dest: Path) -> None:
        """Move a finished workspace into the vault and drop its transcripts."""
        shutil.rmtree(transcripts_dir(root), ignore_errors=True)
        self.unlock()
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                shutil.rmtree(dest)
            shutil.move(str(root), str(dest))
        finally:
            self.lock()
        shutil.rmtree(root.parent, ignore_errors=True)

    def discard_workspaces(self) -> None:
        """Remove workspaces left behind by an interrupted run."""
        for root in (self.work / "ws").glob(f"*/{PROJECT}"):
            shutil.rmtree(transcripts_dir(root), ignore_errors=True)
        shutil.rmtree(self.work / "ws", ignore_errors=True)

    def exists(self, path: Path) -> bool:
        self.unlock()
        try:
            return path.exists()
        finally:
            self.lock()


PROJECT = "catalyst-study"


def fixture_version() -> str:
    """Hash of everything that shapes a base copy, so stale bases are never reused."""
    h = hashlib.sha256()
    files = [Path(fixture.__file__), fixture.HOOK_SCRIPT,
             *sorted(p for p in fixture.SKILL_DIR.rglob("*") if p.is_file()
                     and "__pycache__" not in p.parts)]
    for p in files:
        h.update(p.read_bytes())
    return h.hexdigest()[:10]


def slug(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9.-]+", "_", model)


def ensure_bases(model: str, scale: int, lab: Lab, args, rec: Recorder) -> None:
    if not lab.exists(lab.base(model, "baseline", scale)):
        root = lab.checkout(None, "baseline", scale)
        lab.checkin(root, lab.base(model, "baseline", scale))
    if not lab.exists(lab.base(model, "context", scale) / "dft-screen" / "STATE.md"):
        root = lab.checkout(None, "context", scale)
        r = execute(BOOTSTRAP, root, model, {"suite": "bootstrap", "condition": "context",
                                             "rep": 0, "scale": scale}, args, rec)
        if r["status"] != "finished" or r["score"] < r["facts_total"]:
            shutil.rmtree(root.parent, ignore_errors=True)
            shutil.rmtree(transcripts_dir(root), ignore_errors=True)
            raise Abort(f"bootstrap failed for {model}; the context condition has no STATE files")
        lab.checkin(root, lab.base(model, "context", scale))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--suite", choices=sorted(SUITES), action="append")
    ap.add_argument("--models", nargs="+", default=["composer-2.5"])
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--scales", type=int, nargs="+", default=[1],
                    help="project size multipliers, e.g. 1 3 6")
    ap.add_argument("--conditions", nargs="+", choices=CONDITIONS, default=list(CONDITIONS))
    ap.add_argument("--tasks", nargs="+", help="task ids to run (default: all in the suite)")
    ap.add_argument("--out", type=Path, default=HERE / "results" / "raw.jsonl")
    ap.add_argument("--work", type=Path, default=Path(tempfile.gettempdir()) / "cs-lab",
                    help="must be outside this repository, or the agent can read the graders")
    ap.add_argument("--timeout", type=int, default=900, help="seconds per run")
    ap.add_argument("--list-models", action="store_true")
    ap.add_argument("--probe", action="store_true",
                    help="check that each --models entry runs and can call a tool")
    ap.add_argument("--probe-runs", type=int, default=1, help="probe each model this many times")
    args = ap.parse_args()

    if not os.environ.get("CURSOR_API_KEY"):
        print("CURSOR_API_KEY is not set", file=sys.stderr)
        return 1
    if args.list_models:
        from cursor_sdk import Cursor
        for m in Cursor.models.list():
            if args.models != ap.get_default("models") and m.id not in args.models:
                continue
            print(m.id)
            for p in getattr(m, "parameters", None) or []:
                values = [getattr(v, "value", v) for v in (getattr(p, "values", None) or [])]
                print(f"    {p.id}: {values}")
            for v in getattr(m, "variants", None) or []:
                params = ",".join(f"{x.id}={x.value}" for x in (getattr(v, "params", None) or []))
                print(f"    variant {getattr(v, 'display_name', '') or ''}: {m.id}:{params}")
        return 0
    if args.probe:
        return probe([m for m in args.models for _ in range(args.probe_runs)])

    work = args.work.resolve()
    if work == fixture.REPO or fixture.REPO in work.parents:
        print(f"--work must be outside {fixture.REPO}", file=sys.stderr)
        return 1
    args.work = work
    os.environ["CONTEXT_STATE_HOOK_DIR"] = str(work / "hook-log")
    lab = Lab(work)
    rec = Recorder(args.out)
    try:
        benchmark(args, lab, rec)
    except Abort as err:
        print(f"stopped: {err}", file=sys.stderr)
        return 2
    finally:
        lab.discard_workspaces()
    return 0


def probe(models: list[str]) -> int:
    from cursor_sdk import Agent, LocalAgentOptions

    """A model passes only if it actually calls a tool: the answer is in a file."""
    failed = 0
    for model in models:
        with tempfile.TemporaryDirectory() as d:
            secret = uuid.uuid4().hex[:12]
            (Path(d) / "probe.txt").write_text(f"The code word is {secret}.\n")
            subprocess.run(["git", "init", "-q", d], check=True)
            with Agent.create(model=model_selection(model), api_key=os.environ["CURSOR_API_KEY"],
                              local=LocalAgentOptions(cwd=d)) as agent:
                result = agent.send("Read probe.txt in this folder and reply with only the code "
                                    "word it contains.").wait()
            shutil.rmtree(transcripts_dir(Path(d)), ignore_errors=True)
        answer = (result.result or "").strip()
        if result.status != "finished":
            verdict, detail = "unavailable", getattr(result, "error_message", "")
        elif secret in answer:
            verdict, detail = "tools work", answer[:40]
        else:
            verdict, detail = "no tool use", answer.replace("\n", " ")[:80]
        failed += verdict != "tools work"
        print(f"{model:24} {verdict:12} {detail}", flush=True)
    return 1 if failed else 0


def benchmark(args, lab: Lab, rec: Recorder) -> None:
    for model in args.models:
        for scale in args.scales:
            ensure_bases(model, scale, lab, args, rec)
            for suite in args.suite or ["resume"]:
                run_suite(model, scale, suite, lab, args, rec)


def run_suite(model: str, scale: int, suite: str, lab: Lab, args, rec: Recorder) -> None:
    runs = lab.vault / "runs" / slug(model) / f"x{scale}"
    tasks = [t for t in SUITES[suite] if not args.tasks or t.id in args.tasks]
    for rep in range(1, args.reps + 1):
        if suite == "resume":
            for task in tasks:
                for cond in args.conditions:
                    meta = {"suite": suite, "condition": cond, "rep": rep, "scale": scale}
                    if Recorder.key({**meta, "model": model, "task": task.id}) in rec.done:
                        continue
                    root = lab.checkout(lab.base(model, cond, scale), cond, scale)
                    execute(task, root, model, meta, args, rec)
                    lab.checkin(root, runs / f"{cond}-{task.id}-r{rep}")
        else:
            for cond in args.conditions:
                meta = {"suite": suite, "condition": cond, "rep": rep, "scale": scale}
                if all(Recorder.key({**meta, "model": model, "task": t.id}) in rec.done
                       for t in tasks):
                    continue
                root = lab.checkout(lab.base(model, cond, scale), cond, scale)
                for day, task in enumerate(tasks, 1):
                    for _ in range(task.days_before):
                        fixture.advance(root, scale)
                    execute(task, root, model, {**meta, "day": day}, args, rec)
                lab.checkin(root, runs / f"{cond}-multiday-r{rep}")


if __name__ == "__main__":
    sys.exit(main())
