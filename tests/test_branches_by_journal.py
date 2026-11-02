"""dpcli branches are told by the journal, not by the name templates; check durations come from the journal too."""
import json
import unittest

from helpers import Project, git


class BranchesByJournal(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.addCleanup(self.p.cleanup)
        self.p.ok("init")
        self.p.commit_all("init")
        self.p.ok("module", "new", "aa", "--code", "AA")
        self.mc = self.p.copies / "proj" / "aa"
        self.p.ok("task", "new", "aa", "--type", "dp-writer", "--title", "T", "--scope", "src",
                  "--check", "slow", "true", "exit=0", cwd=self.mc)

    def test_module_new_from_feature_branch_matching_templates(self):
        for br in ("feature/split", "work/x"):  # look like module_branch / task_branch, are not dpcli's
            git("branch", br, cwd=self.p.root)
            self.p.ok("module", "new", br.replace("/", "-"), "--from", br)
        for br in ("feature/aa", "aa/AA-1"):
            code, _, err = self.p.run("module", "new", "bb" + br[-1].lower(), "--from", br)
            self.assertEqual(code, 1, err)
            self.assertIn("dpcli module or task branch", err)

    def test_accept_here_knows_durations_from_journal(self):
        ev = {"t": "2026-01-01T00:00:00", "by": "executor", "task": "AA-1", "ev": "checked", "durs": {"slow": 500}}
        with (self.mc / "docs" / "plan" / "aa" / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(ev) + "\n")
        out = self.p.ok("accept", "AA-1", "--here", "--dry", cwd=self.mc)  # no results.json in this copy
        self.assertIn("background", out)
        self.p.ok("job", "wait", "dp-accept-AA-1", "60", cwd=self.mc)


if __name__ == "__main__":
    unittest.main()
