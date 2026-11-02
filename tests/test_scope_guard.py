"""PreToolUse hook scope_guard: in a task copy an edit outside scope / inside dont_touch is refused at once."""
import json
import subprocess
import sys
import unittest

from helpers import DIST, Project

GUARD = DIST / "hooks" / "scope_guard.py"


class ScopeGuard(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.addCleanup(self.p.cleanup)
        self.p.ok("module", "new", "aa", "--code", "AA")
        self.mc = self.p.copies / "proj" / "aa"

    def task(self, *extra):
        tid = self.p.ok("task", "new", "aa", "--type", "dp-writer", "--title", "T", "--check", "c", "true", "exit=0",
                        *extra, cwd=self.mc).split(":")[0]
        return tid, self.p.copies / "proj" / f"aa-{tid}"

    def edit(self, path, tool="Edit", cwd=None):
        data = {"tool_name": tool, "tool_input": {"file_path": str(path)}, "cwd": str(cwd or path.parent)}
        r = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(data), capture_output=True, text=True,
                           env=self.p.env(), timeout=30)
        return r.returncode, r.stderr

    def test_scope_and_dont_touch(self):
        tid, tc = self.task("--scope", "src/", "--dont-touch", "src/api/", "--dont-touch", "!src/api/ok.py")
        self.assertEqual(self.edit(tc / "src" / "a.py")[0], 0)
        self.assertEqual(self.edit(tc / "src" / "new" / "b.py", tool="Write")[0], 0)  # dir does not exist yet
        self.assertEqual(self.edit(tc / "src" / "api" / "ok.py")[0], 0)
        code, err = self.edit(tc / "README.md")
        self.assertEqual(code, 2)
        self.assertIn(f"README.md is outside scope of {tid}", err)
        self.assertIn(f"{tid} blocked: needs README.md", err)
        code, err = self.edit(tc / "src" / "api" / "x.py")
        self.assertEqual(code, 2)
        self.assertIn("dont_touch", err)
        rel = self.edit(tc / "README.md", cwd=tc)  # relative path resolved against cwd
        self.assertEqual(rel[0], 2)

    def test_free_places_pass(self):
        tid, tc = self.task("--scope", "src/")
        self.assertEqual(self.edit(tc / "build" / "dpcli" / tid / "report.json", tool="Write")[0], 0)  # log dir
        self.assertEqual(self.edit(self.p.tmp / "scratch.txt", tool="Write")[0], 0)  # outside the copy

    def test_not_a_task_copy_or_empty_scope_passes(self):
        self.assertEqual(self.edit(self.p.root / "README.md")[0], 0)  # main copy
        self.assertEqual(self.edit(self.mc / "README.md")[0], 0)  # module copy
        _tid, tc = self.task()
        self.assertEqual(self.edit(tc / "anything.txt")[0], 0)

    def test_garbage_input_fails_open(self):
        r = subprocess.run([sys.executable, str(GUARD)], input="not json", capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
