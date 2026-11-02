"""Agents read less: task show carries the rules executors need; a re-review looks only at what changed."""
import json
import unittest

from helpers import Project, git


class TokenEconomy(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.addCleanup(self.p.cleanup)
        self.p.ok("init")
        self.p.commit_all("init")
        self.p.ok("module", "new", "aa", "--code", "AA")
        self.mc = self.p.copies / "proj" / "aa"
        self.p.ok("task", "new", "aa", "--type", "dp-engineer", "--title", "T", "--goal", "g", "--scope", "src/",
                  "--check", "ok", "true", "exit=0", cwd=self.mc)
        self.tc = self.p.copies / "proj" / "aa-AA-1"

    def test_task_show_prints_general_rules_only(self):
        out = self.p.ok("task", "show", "AA-1", cwd=self.tc)
        self.assertIn("Never `git stash`", out)  # from "General rules"
        self.assertNotIn("## Roles", out)  # not the whole process description
        self.assertIn("Read (offset/limit), Edit, Write", out)  # files through the built-in tools, not heredocs
        self.assertIn("`ast-grep`", out)

    def test_re_review_points_to_previous_issues_and_new_changes(self):
        first = self.p.ok("task", "brief", "AA-1", "--review", cwd=self.mc)
        self.assertNotIn("Re-review", first)
        rv = {"verdict": "rework", "summary": "s", "issues": [{"file": "src/a.py", "severity": "major", "what": "w", "fix": "f"}]}
        self.p.ok("review", "AA-1", "--verdict", "rework", "--from", "-", input=json.dumps(rv), cwd=self.mc)
        head = git("rev-parse", "--short", "HEAD", cwd=self.tc)
        out = self.p.ok("task", "brief", "AA-1", "--review", cwd=self.mc)
        self.assertIn("Re-review", out)
        self.assertIn(f"{head}..HEAD", out)


if __name__ == "__main__":
    unittest.main()
