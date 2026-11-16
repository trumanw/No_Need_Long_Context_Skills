import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "benchmark"))

import fixture  # noqa: E402
import report  # noqa: E402
import run  # noqa: E402
import tasks  # noqa: E402


def tree(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): p.read_text() for p in sorted(root.rglob("*"))
            if p.is_file() and ".cursor" not in p.parts}


class FixtureTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_build_is_deterministic(self):
        fixture.build(self.tmp / "a", "baseline")
        fixture.build(self.tmp / "b", "baseline")
        self.assertEqual(tree(self.tmp / "a"), tree(self.tmp / "b"))

    def test_conditions_differ_only_by_context_state_files(self):
        fixture.build(self.tmp / "a", "baseline")
        fixture.build(self.tmp / "b", "context")
        a, b = tree(self.tmp / "a"), tree(self.tmp / "b")
        extra = set(b) - set(a)
        self.assertEqual(set(a) - set(b), set())
        self.assertEqual(extra, {".agents/STATE_TEMPLATE.md", "dft-screen/LEDGER.md",
                                 "ml-surrogate/LEDGER.md", "kinetics/LEDGER.md"})
        self.assertIn("context-state:begin", b["AGENTS.md"])
        self.assertTrue(b["AGENTS.md"].startswith(a["AGENTS.md"].rstrip()))
        for name in set(a) - {"AGENTS.md"}:
            self.assertEqual(a[name], b[name], name)
        hooks = json.loads((self.tmp / "b" / ".cursor" / "hooks.json").read_text())
        self.assertEqual(set(hooks["hooks"]), {"afterFileEdit", "stop"})
        self.assertTrue((self.tmp / "b" / ".cursor" / "skills" / "context-state" / "SKILL.md").exists())

    def test_project_has_no_hint_of_the_benchmark(self):
        fixture.build(self.tmp / "b", "context")
        for p in (self.tmp / "b").rglob("*"):
            if not p.is_file() or "skills" in p.parts:
                continue
            text = p.read_text().lower()
            for word in ("benchmark", "simulat", "fixture", str(fixture.REPO).lower()):
                self.assertNotIn(word, text, f"{word!r} in {p}")
        hooks = json.loads((self.tmp / "b" / ".cursor" / "hooks.json").read_text())
        cmd = hooks["hooks"]["stop"][0]["command"]
        self.assertTrue(cmd.startswith("python3 .cursor/hooks/"), cmd)
        self.assertTrue((self.tmp / "b" / ".cursor" / "hooks" / "context_state_hook.py").exists())

    def test_scale_grows_the_project_but_keeps_the_facts(self):
        fixture.build(self.tmp / "s1", "baseline", 1)
        fixture.build(self.tmp / "s3", "baseline", 3)
        size = {s: sum(len(t) for t in tree(self.tmp / f"s{s}").values()) for s in (1, 3)}
        self.assertGreater(size[3], 2.5 * size[1])
        for s in ("s1", "s3"):
            day2 = (self.tmp / s / "dft-screen" / "reports" / "REPORT_day2.md").read_text()
            self.assertIn("overbinds CO on Pt(111) by about 0.3 eV", day2)
            self.assertIn(f"submitted as job {fixture.RUNNING_JOB}", day2)
        fixture.advance(self.tmp / "s3", 3)
        csv = (self.tmp / "s3" / "dft-screen" / "results" / "adsorption.csv").read_text()
        self.assertEqual(len(csv.splitlines()), 48)
        fixture.set_scale(1)

    def test_failed_surface_is_the_best_candidate(self):
        self.assertEqual(fixture.true_top3()[0], fixture.FAILED)

    def test_days_follow_the_agent_actions(self):
        root = self.tmp / "p"
        fixture.build(root, "baseline")
        csv = root / "dft-screen" / "results" / "adsorption.csv"
        self.assertEqual(len(csv.read_text().splitlines()), 36)
        fixture.advance(root)
        self.assertEqual(len(csv.read_text().splitlines()), 48)
        subprocess.run(["sh", str(root / "dft-screen" / "scripts" / "submit.sh"), "rerun_Pt3Ni",
                        "ALGO=All"], check=True, capture_output=True)
        self.assertEqual([ok for _, ok in tasks.day2_grade("", root)], [True, True])
        fixture.advance(root)
        self.assertEqual(len(csv.read_text().splitlines()), 49)
        subprocess.run([sys.executable, str(root / "dft-screen" / "scripts" / "volcano.py")],
                       check=True, capture_output=True)
        self.assertEqual([ok for _, ok in tasks.day3_grade("", root)], [True, True])

    def test_rerun_without_algo_gets_partial_credit(self):
        root = self.tmp / "p"
        fixture.build(root, "baseline")
        subprocess.run(["sh", str(root / "dft-screen" / "scripts" / "submit.sh"), "pt3ni_rerun"],
                       check=True, capture_output=True)
        self.assertEqual([ok for _, ok in tasks.day2_grade("", root)], [True, False])

    def test_without_rerun_the_failure_stays_missing(self):
        root = self.tmp / "p"
        fixture.build(root, "baseline")
        fixture.advance(root)
        fixture.advance(root)
        self.assertNotIn(fixture.FAILED, (root / "dft-screen" / "results" / "adsorption.csv").read_text())


class LabTest(unittest.TestCase):
    def test_vault_is_locked_between_runs(self):
        with tempfile.TemporaryDirectory() as d:
            lab = run.Lab(Path(d))
            try:
                root = lab.checkout(None, "baseline", 1)
                self.assertEqual(root.name, run.PROJECT)
                self.assertTrue((root / ".git").exists())
                self.assertEqual(lab.vault.stat().st_mode & 0o777, 0)
                dest = lab.base("m", "baseline", 1)
                lab.checkin(root, dest)
                self.assertFalse(root.parent.exists())
                self.assertTrue(lab.exists(dest / "AGENTS.md"))
                again = lab.checkout(dest, "baseline", 1)
                self.assertTrue((again / "dft-screen" / "PLAN.md").exists())
                self.assertNotEqual(again.parent, root.parent)
            finally:
                lab.unlock()

    def test_transcripts_dir_slug(self):
        self.assertEqual(run.transcripts_dir(Path("/tmp/cs-lab/ws/ab12/catalyst-study")).name,
                         "tmp-cs-lab-ws-ab12-catalyst-study")


class GraderTest(unittest.TestCase):
    def test_resume_graders(self):
        r1 = {t.id: t for t in tasks.RESUME}["R1-status"]
        good = "Batch 4 is running as job 88123; then rerun Pt3Ni(111) with ALGO=All."
        self.assertTrue(all(ok for _, ok in r1.grade(good, Path("."))))
        self.assertFalse(any(ok for _, ok in r1.grade("All done.", Path("."))))

    def test_final_report_grader(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            final = root / "dft-screen" / "reports" / "FINAL.md"
            final.parent.mkdir(parents=True)
            final.write_text("Top: " + ", ".join(fixture.true_top3()) + " (RPBE)")
            self.assertTrue(all(ok for _, ok in tasks.day4_grade("", root)))


class ReportTest(unittest.TestCase):
    def record(self, cond, task, total, score=4, suite="resume"):
        return {"model": "m", "suite": suite, "condition": cond, "rep": 1, "task": task,
                "status": "finished", "score": score, "facts_total": 4,
                "usage": {"input": total - 100, "output": 100, "cache_read": 0,
                          "cache_write": 0, "total": total}}

    def test_tables_and_readme_block(self):
        recs = [self.record("baseline", "R1", 40000), self.record("context", "R1", 10000),
                self.record("context", "B0-bootstrap", 30000, suite="bootstrap")]
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d) / "raw.jsonl"
            raw.write_text("\n".join(json.dumps(r) for r in recs))
            summary = report.summarize(report.load([raw]), (1, 0.1, 1.25, 5))
            body = report.tables(summary)
            self.assertIn("| m | x1 | resume | 40.0K | 10.0K | 75% | n/a | 74%* |", body)
            self.assertIn("| R1 | 40.0K ± 0.0K | 10.0K ± 0.0K | 75% |", body)
            self.assertIn("repaid after about 1.0 resumes", body)
            readme = Path(d) / "README.md"
            readme.write_text(f"intro\n{report.BEGIN}\nold\n{report.END}\nouter\n")
            report.update_readme(readme, body)
            text = readme.read_text()
            self.assertNotIn("old", text)
            self.assertTrue(text.startswith("intro\n") and text.endswith("outer\n"))


class PriceTest(unittest.TestCase):
    table = report.load_prices(REPO / "benchmark" / "prices.json")

    def test_variant_decides_the_price(self):
        u = {"input": 1_000_000, "cache_read": 600_000, "cache_write": 0, "output": 100_000}
        std = report.price_for({"model": "grok-4.7:fast=false"}, self.table)
        fast = report.price_for({"model": "grok-4.7",
                                 "model_resolved": {"id": "grok-4.7", "params": {"fast": "true"}}},
                                self.table)
        self.assertEqual((std["label"], fast["label"]), ("Grok 4.7", "Grok 4.7 (Fast)"))
        self.assertAlmostEqual(report.usd(u, std), 0.4 * 2 + 0.6 * 0.5 + 0.1 * 6)
        self.assertAlmostEqual(report.usd(u, fast), 2 * report.usd(u, std))
        big = report.price_for({"model": "grok-4.7:context=500k,reasoning_effort=high,fast=false"},
                               self.table)
        self.assertEqual(big["label"], "Grok 4.7 500k")

    def test_unrecorded_variant_has_no_price(self):
        self.assertIsNone(report.price_for({"model": "composer-2.5"}, self.table))
        self.assertEqual(report.price_for({"model": "kimi-k3"}, self.table)["label"], "Kimi K3")


if __name__ == "__main__":
    unittest.main()
