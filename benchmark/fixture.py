"""Synthetic multi-day research project used by the token benchmark.

The project is a catalyst-screening study with three workstreams. Facts the
benchmark asks about are spread across long reports and logs, the way they are
in a real project after a few days of work. Everything is generated from a fixed
seed, so every run of the benchmark sees identical files.

    python3 benchmark/fixture.py build DEST --condition baseline|context [--scale N]
    python3 benchmark/fixture.py advance DEST [--scale N]   # simulate the next day
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import random
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO / "no-need-long-context" / "skills" / "context-state"
HOOK_SCRIPT = REPO / "no-need-long-context" / "hooks" / "context_state_hook.py"

SEED = 20261114
WORKSTREAMS = ("dft-screen", "ml-surrogate", "kinetics")
STATE_WORKSTREAMS = ("dft-screen", "ml-surrogate")

HOSTS = ["Pt", "Pd", "Ni", "Cu", "Ag", "Au", "Co", "Rh"]
DOPANTS = ["Ni", "Cu", "Zn", "Fe", "Co", "Sn", "Ga", "Ir", "Ru", "Mo"]
FAILED = "Pt3Ni(111)"
RUNNING_JOB = "88123"
RERUN_JOB = "88200"
TARGET_CO, TARGET_O = -0.75, -1.20

BASE_AGENTS = """# AGENTS.md

Catalyst screening study for CO oxidation on bimetallic surfaces.

Workstreams live in `dft-screen/`, `ml-surrogate/`, and `kinetics/`. Each has a
`PLAN.md`; results and reports are inside each directory. Cluster jobs:
`dft-screen/scripts/check_jobs.sh` shows the queue and
`dft-screen/scripts/submit.sh NAME` submits a job. Jobs take about a day.
"""


def candidates() -> list[str]:
    rng = random.Random(SEED)
    names: list[str] = []
    while len(names) < 48:
        host, dop = rng.choice(HOSTS), rng.choice(DOPANTS)
        if host == dop:
            continue
        name = f"{host}3{dop}(111)" if rng.random() < 0.6 else f"{host}{dop}(111)"
        if name not in names and name != FAILED:
            names.append(name)
    names[29] = FAILED
    return names


def energies(name: str) -> tuple[float, float]:
    if name == FAILED:
        return -0.76, -1.18
    rng = random.Random(f"{SEED}-{name}")
    return round(rng.uniform(-1.6, -0.2), 2), round(rng.uniform(-2.4, -0.4), 2)


def batch_of(index: int) -> int:
    return index // 12 + 1


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


_scale = 1


def filler(rng: random.Random, topic: str, n: int) -> str:
    """Plausible but irrelevant lab-notebook paragraphs, n per unit of scale."""
    n *= _scale
    verbs = ["checked", "re-ran", "compared", "plotted", "tabulated", "inspected"]
    things = ["the slab thickness", "the vacuum gap", "dipole corrections",
              "smearing width", "the k-point mesh", "the relaxation threshold",
              "surface energies", "the magnetic moments", "Bader charges"]
    out = []
    for i in range(n):
        a, b = rng.choice(verbs), rng.choice(things)
        val = rng.uniform(0.001, 0.09)
        out.append(
            f"{topic} note {i + 1}: we {a} {b} for a subset of surfaces. The change in "
            f"adsorption energy stayed below {val:.3f} eV, so no setting was changed. "
            f"Wall time per relaxation was {rng.randint(18, 95)} minutes on "
            f"{rng.choice([32, 64, 128])} cores; {rng.randint(0, 3)} relaxations needed "
            f"a restart from the last ionic step."
        )
    return "\n\n".join(out)


def csv_rows(names: list[str], indices: range) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    for i in indices:
        if names[i] == FAILED:
            continue
        e_co, e_o = energies(names[i])
        w.writerow([names[i], f"{e_co:.2f}", f"{e_o:.2f}", "RPBE", f"batch{batch_of(i)}"])
    return buf.getvalue()


def batch_log(rng: random.Random, names: list[str], batch: int) -> str:
    lines = [f"# batch{batch} driver log (VASP 6.4, RPBE, ENCUT=450, KPOINTS 4x4x1)"]
    for i in range((batch - 1) * 12, batch * 12):
        name = names[i]
        for step in range(1, 40 * _scale + 1):
            lines.append(
                f"{name} ionic {step:02d} E={-rng.uniform(180, 420):.5f} "
                f"dE={rng.uniform(1e-5, 1e-2):.2e} Fmax={rng.uniform(0.01, 0.4):.3f}"
            )
        if name == FAILED:
            lines.append(f"ERROR {name}: SCF not converged after 120 electronic steps "
                         "(ALGO=Fast). Relaxation aborted.")
        else:
            e_co, e_o = energies(name)
            lines.append(f"DONE {name}: E_ads(CO)={e_co:.2f} eV E_ads(O)={e_o:.2f} eV")
    return "\n".join(lines) + "\n"


def dft_screen(root: Path, rng: random.Random) -> None:
    names = candidates()
    ws = root / "dft-screen"
    table = "\n".join(f"| {i + 1} | {n} | batch{batch_of(i)} |" for i, n in enumerate(names))
    write(ws / "PLAN.md", f"""# dft-screen plan

## Objective

Screen 48 bimetallic (111) surfaces for CO oxidation and report the three
candidates closest to the volcano optimum, E_ads(CO) = {TARGET_CO} eV and
E_ads(O) = {TARGET_O} eV. Done when `reports/FINAL.md` lists the top three with
their energies and the functional used.

## Method

PBE+D3, ENCUT and k-points fixed after the convergence tests in
`reports/REPORT_day1.md`. Four batches of 12 surfaces, one cluster job each.

## Stages

1. Convergence tests.
2. Batches 1 to 4 (`scripts/submit.sh batchN`).
3. Rerun every failed surface with a more robust electronic minimizer:
   `scripts/submit.sh rerun_<surface> ALGO=All` (extra arguments are INCAR overrides).
   Its energies are appended to `results/adsorption.csv` when the job completes.
4. Volcano analysis: `python3 scripts/volcano.py` writes `results/volcano.json`.
5. Final write-up in `reports/FINAL.md`.

## Candidates

| # | surface | batch |
|---|---|---|
{table}

## Background

{filler(rng, "Planning", 8)}
""")
    write(ws / "reports" / "REPORT_day1.md", f"""# Day 1: convergence tests

{filler(rng, "Convergence", 10)}

## Settings chosen

ENCUT = 450 eV and a 4x4x1 Monkhorst-Pack mesh changed CO adsorption energies by
less than 0.01 eV relative to 600 eV and 8x8x1. Batch 1 was submitted with PBE.

{filler(rng, "Setup", 8)}
""")
    write(ws / "reports" / "REPORT_day2.md", f"""# Day 2: batches 1 to 3

{filler(rng, "Batch", 12)}

## Decision D2: functional

PBE overbinds CO on Pt(111) by about 0.3 eV against the experimental reference,
which would shift every candidate along the volcano. From batch 2 on we use
RPBE, and batch 1 was recomputed with RPBE. This supersedes the PBE+D3 line in
PLAN.md.

{filler(rng, "Analysis", 10)}

## Failures

Batch 3 finished except {FAILED}: the SCF did not converge with ALGO=Fast (see
`logs/batch3.log`). It must be rerun with ALGO=All before the volcano analysis.
Batch 4 (surfaces 37 to 48) was submitted as job {RUNNING_JOB}.

{filler(rng, "Outlook", 6)}
""")
    for b in (1, 2, 3):
        write(ws / "logs" / f"batch{b}.log", batch_log(rng, names, b))
    write(ws / "results" / "adsorption.csv",
          "surface,E_CO,E_O,functional,batch\n" + csv_rows(names, range(0, 36)))
    write(ws / "jobs" / "queue.txt",
          f"88101 batch1 COMPLETED\n88107 batch2 COMPLETED\n88115 batch3 COMPLETED\n"
          f"{RUNNING_JOB} batch4 RUNNING\n")
    write(ws / "scripts" / "check_jobs.sh",
          '#!/bin/sh\ncat "$(dirname "$0")/../jobs/queue.txt"\n')
    write(ws / "scripts" / "submit.sh", f"""#!/bin/sh
# Submit a job to the cluster queue: submit.sh NAME [KEY=VALUE ...] (INCAR overrides).
[ -n "$1" ] || {{ echo "usage: submit.sh NAME [KEY=VALUE ...]" >&2; exit 1; }}
d="$(dirname "$0")/../jobs"
if grep -q " $1 " "$d/queue.txt"; then echo "already submitted: $1"; exit 0; fi
echo "{RERUN_JOB} $1 RUNNING" >> "$d/queue.txt"
name="$1"; shift
echo "{RERUN_JOB} $name $*" >> "$d/submitted.txt"
echo "Submitted job {RERUN_JOB} ($name${{*:+, $*}})"
""")
    write(ws / "scripts" / "volcano.py", f"""import csv, json, pathlib
root = pathlib.Path(__file__).resolve().parent.parent
rows = list(csv.DictReader(open(root / "results" / "adsorption.csv")))
def dist(r):
    return abs(float(r["E_CO"]) - ({TARGET_CO})) + abs(float(r["E_O"]) - ({TARGET_O}))
rows.sort(key=dist)
top = [{{"surface": r["surface"], "E_CO": float(r["E_CO"]), "E_O": float(r["E_O"]),
        "distance": round(dist(r), 3)}} for r in rows[:3]]
out = {{"n_surfaces": len(rows), "top3": top}}
(root / "results" / "volcano.json").write_text(json.dumps(out, indent=2))
print(json.dumps(out, indent=2))
""")
    for p in (ws / "scripts").glob("*.sh"):
        p.chmod(0o755)


def ml_surrogate(root: Path, rng: random.Random) -> None:
    ws = root / "ml-surrogate"
    write(ws / "PLAN.md", f"""# ml-surrogate plan

## Objective

Train a surrogate that predicts E_ads(CO) from composition and slab features
with MAE below 0.12 eV on held-out surfaces, so later screening can skip DFT.

## Approach

Compare GNN-small (2 message-passing layers) with GNN-large (6 layers) on
learning curves at n = 100, 250, 500, 1000.

{filler(rng, "Data", 8)}
""")
    curve = {"split": "v1-random", "runs": []}
    for model, base in (("GNN-small", 0.11), ("GNN-large", 0.14)):
        for n in (100, 250, 500, 1000):
            curve["runs"].append({"model": model, "n": n,
                                  "val_mae": round(base + 0.3 / n ** 0.5 + rng.uniform(0, .01), 3)})
    write(ws / "results" / "learning_curve.json", json.dumps(curve, indent=2))
    write(ws / "reports" / "REPORT.md", f"""# ml-surrogate report

{filler(rng, "Training", 12)}

## Model choice

At n = 1000, GNN-small reaches a validation MAE of 0.11 eV against 0.14 eV for
GNN-large, which overfits below n = 500. We keep GNN-small.

{filler(rng, "Ablation", 10)}

## Open issue

The v1 split is random over surfaces, so the same composition can appear in
train and validation: we suspect data leakage. Next step: build split v2 grouped
by composition and retrain GNN-small on it.

{filler(rng, "Misc", 6)}
""")


def kinetics(root: Path, rng: random.Random) -> None:
    ws = root / "kinetics"
    write(ws / "PLAN.md", f"""# kinetics plan

Mean-field microkinetic model for CO oxidation; starts after dft-screen
delivers its top three surfaces. Nothing has been run yet.

{filler(rng, "Kinetics", 10)}
""")
    write(ws / "NOTES.md", filler(rng, "Reading", 14) + "\n")


def older_notes(root: Path, rng: random.Random) -> None:
    """Earlier notebooks that a larger, longer-running project accumulates."""
    for k in range(2, _scale + 1):
        write(root / "dft-screen" / "reports" / "notes" / f"NOTES_{k:02d}.md",
              f"# Lab notes, week {k}\n\n{filler(rng, f'Week {k}', 3)}\n")
        write(root / "ml-surrogate" / "reports" / f"ablation_{k:02d}.md",
              f"# Ablation round {k}\n\n{filler(rng, f'Ablation {k}', 3)}\n")
        write(root / "kinetics" / f"reading_{k:02d}.md",
              f"# Reading list {k}\n\n{filler(rng, f'Reading {k}', 3)}\n")


def set_scale(scale: int) -> None:
    global _scale
    if scale < 1:
        raise ValueError("scale must be at least 1")
    _scale = scale


def build(dest: Path, condition: str, scale: int = 1) -> None:
    set_scale(scale)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    rng = random.Random(SEED)
    dft_screen(dest, rng)
    ml_surrogate(dest, rng)
    kinetics(dest, rng)
    older_notes(dest, rng)
    write(dest / "AGENTS.md", BASE_AGENTS)
    if condition == "context":
        add_context_state(dest)
    elif condition != "baseline":
        raise ValueError(f"unknown condition: {condition}")


def add_context_state(dest: Path) -> None:
    args = [sys.executable, str(SKILL_DIR / "scripts" / "init.py"), "--root", str(dest),
            "--lang", "en"]
    for ws in WORKSTREAMS:
        args += ["--workstream", f"{ws}={ws}"]
    subprocess.run(args, check=True, capture_output=True, text=True)
    shutil.copytree(SKILL_DIR, dest / ".cursor" / "skills" / "context-state")
    (dest / ".cursor" / "hooks").mkdir(parents=True, exist_ok=True)
    shutil.copy2(HOOK_SCRIPT, dest / ".cursor" / "hooks" / HOOK_SCRIPT.name)
    cmd = f"python3 .cursor/hooks/{HOOK_SCRIPT.name}"
    hooks = {"version": 1, "hooks": {
        "afterFileEdit": [{"command": f"{cmd} record", "timeout": 10}],
        "stop": [{"command": f"{cmd} stop", "timeout": 10, "loop_limit": 1}],
    }}
    write(dest / ".cursor" / "hooks.json", json.dumps(hooks, indent=2) + "\n")


def advance(dest: Path, scale: int = 1) -> None:
    """Move the project one day forward: every running job completes."""
    set_scale(scale)
    ws = dest / "dft-screen"
    queue = ws / "jobs" / "queue.txt"
    lines = queue.read_text().splitlines()
    names = candidates()
    out = []
    for line in lines:
        job, name, status = line.split()
        if status == "RUNNING":
            status = "COMPLETED"
            if name == "batch4":
                write(ws / "logs" / "batch4.log", batch_log(random.Random(SEED + 4), names, 4))
                with open(ws / "results" / "adsorption.csv", "a") as f:
                    f.write(csv_rows(names, range(36, 48)))
            elif FAILED.split("(")[0].lower() in name.lower():
                e_co, e_o = energies(FAILED)
                with open(ws / "results" / "adsorption.csv", "a") as f:
                    f.write(f"{FAILED},{e_co:.2f},{e_o:.2f},RPBE,rerun\n")
                write(ws / "logs" / f"{name}.log",
                      f"DONE {FAILED} (ALGO=All): E_ads(CO)={e_co:.2f} eV E_ads(O)={e_o:.2f} eV\n")
        out.append(f"{job} {name} {status}")
    queue.write_text("\n".join(out) + "\n")


def true_top3() -> list[str]:
    names = candidates()
    scored = sorted(names, key=lambda n: abs(energies(n)[0] - TARGET_CO)
                    + abs(energies(n)[1] - TARGET_O))
    return scored[:3]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("dest", type=Path)
    b.add_argument("--condition", choices=["baseline", "context"], default="baseline")
    a = sub.add_parser("advance")
    a.add_argument("dest", type=Path)
    for p in (a, b):
        p.add_argument("--scale", type=int, default=1, help="project size multiplier")
    args = ap.parse_args()
    if args.cmd == "build":
        build(args.dest, args.condition, args.scale)
        print(f"built {args.condition} fixture at {args.dest}")
    else:
        advance(args.dest, args.scale)
        print(f"advanced {args.dest} by one day")
    return 0


if __name__ == "__main__":
    sys.exit(main())
