"""UserPromptSubmit hook: a main session whose context grew past the limit is told to start a fresh one; stats
--tokens shows what main sessions spent."""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import DIST, Project

GUARD = DIST / "hooks" / "context_guard.py"


def turn(ctx, side=False, t="2026-10-02T10:00:00Z"):
    return {"type": "assistant", "isSidechain": side, "timestamp": t,
            "message": {"usage": {"input_tokens": 1, "cache_read_input_tokens": ctx, "cache_creation_input_tokens": 0}}}


def write(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")


class ContextGuard(unittest.TestCase):
    def run_guard(self, rows, env=None):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "s.jsonl"
            write(log, rows)
            r = subprocess.run([sys.executable, str(GUARD)], input=json.dumps({"transcript_path": str(log)}),
                               capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", **(env or {})})
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_warns_by_the_last_main_turn(self):
        self.assertIn("/clear", self.run_guard([turn(100_000), turn(400_000)]))
        self.assertEqual(self.run_guard([turn(400_000), turn(100_000)]), "")  # after compaction: quiet
        self.assertEqual(self.run_guard([turn(100_000), turn(900_000, side=True)]), "")  # a subagent's turn
        self.assertEqual(self.run_guard([turn(200_000)], {"DPCLI_CONTEXT_MAX": "100000"})[:6], "dpcli:")

    def test_bad_input_fails_open(self):
        r = subprocess.run([sys.executable, str(GUARD)], input="{}", capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_init_installs_the_hook_once(self):
        p = Project()
        self.addCleanup(p.cleanup)
        p.ok("init")
        p.ok("init")
        st = json.loads((p.root / ".claude" / "settings.json").read_text())
        cmds = [h["command"] for e in st["hooks"]["UserPromptSubmit"] for h in e["hooks"]]
        self.assertEqual(sum("context_guard.py" in c for c in cmds), 1)

    def test_stats_tokens_shows_main_sessions(self):
        p = Project()
        self.addCleanup(p.cleanup)
        p.ok("module", "init", "web", "--code", "WB")
        logs = p.tmp / "home" / ".claude" / "projects" / re.sub(r"[/_.]", "-", str(p.root))
        logs.mkdir(parents=True)
        write(logs / "s1.jsonl", [turn(300_000, t="2026-09-01T00:00:00Z"), turn(500_000), turn(700_000)])
        write(logs / "s2.jsonl", [turn(1_000_000)])
        self.assertIn("main sessions (all modules): 2.5M in 2, largest turn 1000k", p.ok("stats", "--tokens"))
        self.assertIn("2.2M in 2", p.ok("stats", "--tokens", "--since", "2026-10-01"))


if __name__ == "__main__":
    unittest.main()
