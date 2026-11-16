import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "no-need-long-context" / "skills" / "context-state" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import check  # noqa: E402
import init  # noqa: E402


def run(fn, *argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = fn(list(argv))
    return code, out.getvalue(), err.getvalue()


class InitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "exp" / "a").mkdir(parents=True)
        (self.root / "exp" / "a" / "REPORT_stage1.md").write_text("x")

    def tearDown(self):
        self.tmp.cleanup()

    def agents(self):
        return (self.root / "AGENTS.md").read_text(encoding="utf-8")

    def test_new_repo(self):
        run(init.main, "--root", str(self.root), "--lang", "zh", "--workstream", "exp/a=实验A")
        text = self.agents()
        self.assertIn(init.BEGIN, text)
        self.assertIn("## 工作线索引", text)
        self.assertIn("| 实验A | `exp/a/` | `exp/a/STATE.md` | 未建立 |", text)
        self.assertTrue((self.root / "exp/a/LEDGER.md").read_text(encoding="utf-8").startswith("# LEDGER：实验A"))
        self.assertTrue((self.root / ".agents/STATE_TEMPLATE.md").exists())
        self.assertFalse((self.root / "exp/a/STATE.md").exists())

    def test_rerun_is_idempotent(self):
        args = ("--root", str(self.root), "--workstream", "exp/a")
        run(init.main, *args)
        first = self.agents()
        _, out, _ = run(init.main, *args)
        self.assertEqual(first, self.agents())
        self.assertIn("nothing to change", out)

    def test_existing_content_kept_and_block_replaced(self):
        (self.root / "AGENTS.md").write_text(
            f"# Project\n\nBuild with make.\n\n{init.BEGIN}\nold rules\n{init.END}\n", encoding="utf-8")
        run(init.main, "--root", str(self.root))
        text = self.agents()
        self.assertIn("Build with make.", text)
        self.assertNotIn("old rules", text)
        self.assertEqual(text.count(init.BEGIN), 1)

    def test_warns_on_unmanaged_rules(self):
        (self.root / "AGENTS.md").write_text("# P\n\nAlways update STATE.md first.\n", encoding="utf-8")
        _, _, err = run(init.main, "--root", str(self.root))
        self.assertIn("outside the managed block", err)

    def test_dry_run_writes_nothing(self):
        _, out, _ = run(init.main, "--root", str(self.root), "--dry-run", "--workstream", "exp/a")
        self.assertIn("would write AGENTS.md", out)
        self.assertFalse((self.root / "AGENTS.md").exists())

    def test_scan(self):
        _, out, _ = run(init.main, "--root", str(self.root), "--scan")
        self.assertIn("exp/a/  (REPORT_stage1.md)", out)


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "w").mkdir()
        run(init.main, "--root", str(self.root), "--workstream", "w")

    def tearDown(self):
        self.tmp.cleanup()

    def write_state(self, body="", updated="2000-01-01 00:00"):
        (self.root / "w/STATE.md").write_text(f"# STATE\n\nupdated: {updated} UTC+8\n{body}", encoding="utf-8")

    def levels(self):
        return {(f["level"], f["path"]) for f in check.check(self.root, 4000)}

    def test_missing_state_is_info(self):
        self.assertIn(("INFO", "w/STATE.md"), self.levels())
        self.assertEqual(run(check.main, "--root", str(self.root))[0], 0)

    def test_clean_state_ok(self):
        self.write_state()
        self.assertIn(("OK", "w/STATE.md"), self.levels())

    def test_missing_updated_is_error(self):
        (self.root / "w/STATE.md").write_text("# STATE\n", encoding="utf-8")
        self.assertIn(("ERROR", "w/STATE.md"), self.levels())
        self.assertEqual(run(check.main, "--root", str(self.root))[0], 1)

    def test_slightly_over_is_ok(self):
        self.write_state("x" * 4800)
        self.assertIn(("OK", "w/STATE.md"), self.levels())

    def test_oversize_warns(self):
        self.write_state("x" * 5300)
        self.assertIn(("WARN", "w/STATE.md"), self.levels())
        self.assertEqual(run(check.main, "--root", str(self.root))[0], 0)
        self.assertEqual(run(check.main, "--root", str(self.root), "--strict")[0], 1)

    def test_ledger_newer_than_state_warns(self):
        self.write_state(updated="2026-11-14 15:00")
        with open(self.root / "w/LEDGER.md", "a", encoding="utf-8") as f:
            f.write("2026-11-14 16:05 | change | x | y\n")
        msgs = [f["message"] for f in check.check(self.root, 4000) if f["path"] == "w/STATE.md"]
        self.assertTrue(any("newer than STATE" in m for m in msgs))

    def test_future_updated_time_warns(self):
        self.write_state(updated="2999-01-01 00:00")
        msgs = [f["message"] for f in check.check(self.root, 4000) if f["path"] == "w/STATE.md"]
        self.assertTrue(any("later than the file's modification time" in m for m in msgs))

    def test_prose_mentions_are_not_index_entries(self):
        with open(self.root / "AGENTS.md", "a", encoding="utf-8") as f:
            f.write("\nAlways read `STATE.md` first.\n")
        self.assertNotIn("STATE.md", {f["path"] for f in check.check(self.root, 4000)})

    def test_unindexed_state_warns(self):
        (self.root / "other").mkdir()
        (self.root / "other/STATE.md").write_text("updated: 2026-11-14 10:00\n", encoding="utf-8")
        self.assertIn(("WARN", "other/STATE.md"), self.levels())


if __name__ == "__main__":
    unittest.main()
