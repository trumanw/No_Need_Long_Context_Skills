import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "context_state_hook.py"


class HookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root = base / "repo"
        self.logs = base / "logs"
        (self.root / "exp" / "a" / "sub").mkdir(parents=True)
        (self.root / "exp" / "b").mkdir(parents=True)
        (self.root / "AGENTS.md").write_text(
            "# A\n\nRead `exp/c/STATE.md` first.\n\n| w | d | s | x |\n|---|---|---|---|\n"
            "| A | `exp/a/` | `exp/a/STATE.md` | x |\n| B | `exp/b/` | `exp/b/STATE.md` | x |\n",
            encoding="utf-8")
        self.state = self.root / "exp/a/STATE.md"
        self.state.write_text("updated: 2000-01-01 00:00\n", encoding="utf-8")
        old = time.time() - 3600
        os.utime(self.state, (old, old))

    def tearDown(self):
        self.tmp.cleanup()

    def hook(self, mode, payload):
        env = dict(os.environ, CONTEXT_STATE_HOOK_DIR=str(self.logs))
        out = subprocess.run([sys.executable, str(HOOK), mode], input=json.dumps(payload),
                             capture_output=True, text=True, env=env, check=True).stdout
        return json.loads(out)

    def edit(self, rel, conv="c1"):
        self.assertEqual(self.hook("record", {"conversation_id": conv, "file_path": str(self.root / rel)}), {})

    def stop(self, conv="c1", **extra):
        return self.hook("stop", dict({"conversation_id": conv, "status": "completed", "loop_count": 0,
                                       "workspace_roots": [str(self.root)]}, **extra))

    def test_edit_after_state_triggers_followup(self):
        self.edit("exp/a/sub/run.sh")
        msg = self.stop().get("followup_message", "")
        self.assertIn("`exp/a/`", msg)

    def test_state_updated_after_edit_is_quiet(self):
        self.edit("exp/a/run.sh")
        self.state.write_text("updated: 2000-01-01 00:01\n", encoding="utf-8")
        self.assertEqual(self.stop(), {})

    def test_editing_state_or_ledger_only_is_quiet(self):
        self.edit("exp/a/LEDGER.md")
        self.edit("exp/a/STATE.md")
        self.assertEqual(self.stop(), {})

    def test_workstream_without_state_is_ignored(self):
        self.edit("exp/b/x.py")
        self.assertEqual(self.stop(), {})

    def test_file_outside_workstreams_is_quiet(self):
        self.edit("README.md")
        self.assertEqual(self.stop(), {})

    def test_no_second_followup_in_loop(self):
        self.edit("exp/a/run.sh")
        self.assertEqual(self.stop(loop_count=1), {})

    def test_aborted_turn_is_quiet_and_log_cleared(self):
        self.edit("exp/a/run.sh")
        self.assertEqual(self.stop(status="aborted"), {})
        self.assertEqual(self.stop(), {})

    def test_conversations_are_separate(self):
        self.edit("exp/a/run.sh", conv="other")
        self.assertEqual(self.stop(conv="c1"), {})

    def test_bad_input_fails_open(self):
        env = dict(os.environ, CONTEXT_STATE_HOOK_DIR=str(self.logs))
        out = subprocess.run([sys.executable, str(HOOK), "stop"], input="not json",
                             capture_output=True, text=True, env=env)
        self.assertEqual((out.returncode, json.loads(out.stdout)), (0, {}))


if __name__ == "__main__":
    unittest.main()
