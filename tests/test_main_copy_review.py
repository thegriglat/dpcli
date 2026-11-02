"""Frictions from reviewing uncommitted work in the main copy: brief names a missing copy, scope skipped,
logs named by position, feedback --module noise."""
import json
import unittest

from helpers import Project


class MainCopyReview(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.addCleanup(self.p.cleanup)
        self.p.ok("module", "init", "aa", "--code", "AA")
        self.p.ok("task", "new", "aa", "--type", "dp-engineer", "--title", "T", "--goal", "g", "--scope", "src/",
                  "--check", "one", "true", "exit=0", "--check", "two", "true", "exit=0", "--no-copy")

    def test_brief_without_copy_points_to_the_current_copy(self):
        for args in (("--review",), ()):
            out = self.p.ok("task", "brief", "AA-1", *args)
            self.assertNotIn("proj-aa-AA-1", out, args)
            self.assertIn("no task copy", out, args)

    def test_scope_checked_on_uncommitted_work(self):
        (self.p.root / "src").mkdir()
        (self.p.root / "src" / "a.py").write_text("x")
        code, out, _ = self.p.run("accept", "AA-1", "--here", "--dry")
        self.assertEqual(code, 0, out)
        self.assertIn("PASS scope", out)
        (self.p.root / "other.py").write_text("x")
        code, out, _ = self.p.run("accept", "AA-1", "--here", "--dry")
        self.assertEqual(code, 1, out)
        self.assertIn("other.py", out)

    def test_logs_named_by_check(self):
        self.p.run("accept", "AA-1", "--here", "--dry")
        self.p.run("accept", "AA-1", "--here", "--dry", "--only", "two")
        logs = sorted(f.name for f in (self.p.root / "build" / "dpcli" / "AA-1").glob("*.log"))
        self.assertEqual(logs, ["one.log", "two.log"])

    def test_duplicate_check_names_rejected(self):
        code, _, err = self.p.run("task", "new", "aa", "--type", "dp-engineer", "--title", "T", "--goal", "g",
                                  "--scope", "src/", "--check", "x", "true", "exit=0", "--check", "x", "false", "exit=0",
                                  "--no-copy")
        self.assertEqual(code, 1)
        self.assertIn("duplicate check names: x", err)

    def test_feedback_module_shows_only_matching_clusters(self):
        self.p.ok("module", "init", "bb", "--code", "BB")
        self.p.ok("feedback", "new", "Only in bb", "--match", "zzz", "--scope", "dpcli")
        self.p.ok("event", "aa", "note", "--note", "harness: accept is slow")
        out = self.p.ok("feedback", "--module", "aa")
        self.assertNotIn("Only in bb", out)
        self.assertIn("accept", out)


if __name__ == "__main__":
    unittest.main()
