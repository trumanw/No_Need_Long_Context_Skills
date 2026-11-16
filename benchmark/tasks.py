"""Benchmark prompts and their graders.

Each grader returns a list of (fact, passed) pairs. Answer checks are regular
expressions over the agent's final reply; disk checks look at the workspace the
agent ran in, so an agent that only claims to have acted gets no credit.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from fixture import FAILED, RERUN_JOB, RUNNING_JOB, STATE_WORKSTREAMS, true_top3

Grader = Callable[[str, Path], list[tuple[str, bool]]]


def has(pattern: str) -> Callable[[str], bool]:
    rx = re.compile(pattern, re.IGNORECASE | re.DOTALL)
    return lambda text: bool(rx.search(text))


def answer_facts(facts: dict[str, str]) -> Grader:
    def grade(answer: str, _root: Path) -> list[tuple[str, bool]]:
        return [(name, has(rx)(answer)) for name, rx in facts.items()]
    return grade


PT3NI = r"Pt\s*3\s*Ni"


@dataclass
class Task:
    id: str
    prompt: str
    grade: Grader
    days_before: int = 0
    tags: list[str] = field(default_factory=list)


RESUME = [
    Task("R1-status", "Continue the dft-screen work: where does it stand and what is the next step? "
         "Do not submit jobs in this chat.",
         answer_facts({"job 88123 running": RUNNING_JOB, "batch 4": r"batch\s*4",
                       "Pt3Ni rerun": PT3NI, "ALGO=All": r"ALGO\s*=?\s*All"})),
    Task("R2-functional", "Which functional does dft-screen use now, and why?",
         answer_facts({"RPBE": r"\bRPBE\b", "PBE overbinds CO": r"overbind",
                       "about 0.3 eV": r"0\.3\s*eV"})),
    Task("R3-surrogate", "ml-surrogate: which model was chosen, on what evidence, and what is the open issue?",
         answer_facts({"GNN-small": r"GNN.?small", "MAE 0.11": r"0\.11",
                       "leakage": r"leak", "split v2 by composition": r"split\s*v?2|by composition|grouped"})),
    Task("R4-failures", "What has failed so far in dft-screen, and what has to happen about it?",
         answer_facts({"batch 3": r"batch\s*3", "Pt3Ni": PT3NI,
                       "SCF not converged": r"SCF|converg", "ALGO=All": r"ALGO\s*=?\s*All"})),
]


def day2_grade(answer: str, root: Path) -> list[tuple[str, bool]]:
    """By the end of day 2 the Pt3Ni rerun must be submitted, with ALGO=All.

    Agents may do it on day 1 already, which is fine; only the disk is checked.
    """
    jobs = root / "dft-screen" / "jobs"
    queue = (jobs / "queue.txt").read_text()
    submitted = (jobs / "submitted.txt").read_text() if (jobs / "submitted.txt").exists() else ""
    rerun = re.compile(rf"^{RERUN_JOB} \S*pt\s*3\s*ni", re.I | re.M)
    return [
        ("Pt3Ni rerun submitted (disk)", bool(rerun.search(queue))),
        ("rerun requested ALGO=All (disk)",
         any(rerun.search(line) and re.search(r"ALGO\s*=\s*All", line, re.I)
             for line in submitted.splitlines())),
    ]


def day3_grade(answer: str, root: Path) -> list[tuple[str, bool]]:
    vol = root / "dft-screen" / "results" / "volcano.json"
    data: dict = {}
    if vol.exists():
        try:
            data = json.loads(vol.read_text())
        except ValueError:
            pass
    top = [t.get("surface", "") for t in data.get("top3", [])] if isinstance(data, dict) else []
    return [("volcano.json over all 48 surfaces (disk)", data.get("n_surfaces") == 48),
            ("volcano.json ranks Pt3Ni first (disk)", bool(top) and top[0] == FAILED)]


def day4_grade(answer: str, root: Path) -> list[tuple[str, bool]]:
    final = root / "dft-screen" / "reports" / "FINAL.md"
    text = final.read_text() if final.exists() else ""
    facts = [("FINAL.md written (disk)", bool(text))]
    for name in true_top3():
        pattern = re.escape(name.split("(")[0]).replace(r"3", r"\s*3\s*")
        facts.append((f"FINAL.md lists {name}", has(pattern)(text)))
    facts.append(("FINAL.md names RPBE", has(r"\bRPBE\b")(text)))
    return facts


def day1_grade(answer: str, root: Path) -> list[tuple[str, bool]]:
    return answer_facts({"job 88123 still running": RUNNING_JOB,
                         "Pt3Ni rerun pending": PT3NI})(answer, root)


CONTINUE = ("Continue the dft-screen work. If nothing can move forward until a running job "
            "finishes, say so and stop; do not wait for jobs.")
MULTIDAY = [
    Task("D1", CONTINUE, day1_grade),
    Task("D2", CONTINUE, day2_grade, days_before=1),
    Task("D3", CONTINUE, day3_grade, days_before=1),
    Task("D4", "dft-screen: give me the final top three candidates and the functional used, "
         "and write them to dft-screen/reports/FINAL.md.", day4_grade, days_before=1),
]

BOOTSTRAP = Task(
    "B0-bootstrap",
    "Use the context-state skill to bootstrap STATE.md for the "
    + " and ".join(STATE_WORKSTREAMS)
    + " workstreams from the existing material. Do not create one for kinetics.",
    lambda answer, root: [(f"{ws}/STATE.md written", (root / ws / "STATE.md").exists())
                          for ws in STATE_WORKSTREAMS],
)

SUITES = {"resume": RESUME, "multiday": MULTIDAY}
