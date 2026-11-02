"""tools/sync.py and tools/metrics.py: the CI merges main into a PR and never raises budgets on its own."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import REPO, git

sys.path.insert(0, str(REPO / "tools"))
import metrics  # noqa: E402
import sync  # noqa: E402

INIT = '"""doc."""\n\nVERSION = {}  # bump\n'
LOG = "# Changelog\n\n{}## 29\n- a.\n\n## 28\n- b.\n\n## 27\n- c.\n"


class Sync(unittest.TestCase):
    """A bare origin, a base clone (the CI checkout), a PR head at refs/pull/7/head; gh stubbed."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.calls = []
        origin, self.base = self.tmp / "origin.git", self.tmp / "base"
        git("init", "-q", "--bare", "-b", "main", str(origin), cwd=self.tmp)
        git("clone", "-q", str(origin), str(self.base), cwd=self.tmp)
        for k, v in (("user.name", "t"), ("user.email", "t@example.com")):
            git("config", k, v, cwd=self.base)
        self.write({sync.INIT: INIT.format(29), sync.LOG: LOG.format(""), "lib/a.py": "x = 1\n"}, "base")
        git("push", "-q", "origin", "HEAD:main", cwd=self.base)
        os.environ["RUNNER_TEMP"] = str(self.tmp)
        sync.gh = lambda *a, **k: self.calls.append(a) or json.dumps({"headRefName": "pr", "isCrossRepository": False})
        sync.label = lambda *a: self.calls.append(("label",) + a)
        self.cwd = os.getcwd()
        os.chdir(self.base)

    def tearDown(self):
        os.chdir(self.cwd)
        os.environ.pop("RUNNER_TEMP", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, files, msg):
        for f, text in files.items():
            (self.base / f).parent.mkdir(parents=True, exist_ok=True)
            (self.base / f).write_text(text, encoding="utf-8")
        git("add", "-A", cwd=self.base)
        git("commit", "-q", "-m", msg, cwd=self.base)

    def pr(self, files):
        git("switch", "-q", "-c", "pr", "origin/main", cwd=self.base)
        self.write(files, "pr")
        git("push", "-q", "origin", "HEAD:pr", "HEAD:refs/pull/7/head", cwd=self.base)
        git("switch", "-q", "--detach", "origin/main", cwd=self.base)

    def main_moves(self, files):
        git("switch", "-q", "--detach", "origin/main", cwd=self.base)
        self.write(files, "main")
        git("push", "-q", "origin", "HEAD:main", cwd=self.base)

    def sync(self):
        try:
            sync.main("7")
            return 0
        except SystemExit as e:
            return e.code

    def pushed(self, f):
        return git("show", f"origin/pr:{f}", cwd=self.base) + "\n"

    def test_parallel_bump_resolved_and_the_prs_other_edits_kept(self):
        self.pr({sync.INIT: '"""doc, edited."""\n\nVERSION = 30  # bump\n',
                 sync.LOG: LOG.format("## 30\n- mine.\n\n").replace("- c.", "- c, fixed.")})
        self.main_moves({sync.INIT: INIT.format(31), sync.LOG: LOG.format("## 31\n- y.\n\n## 30\n- x.\n\n")})
        self.assertEqual(self.sync(), 0)
        git("fetch", "-q", "origin", cwd=self.base)
        self.assertEqual(self.pushed(sync.INIT), '"""doc, edited."""\n\nVERSION = 32  # bump\n')
        self.assertEqual(self.pushed(sync.LOG), LOG.format("## 32\n- mine.\n\n## 31\n- y.\n\n## 30\n- x.\n\n")
                         .replace("- c.", "- c, fixed."))
        self.assertIn(("workflow", "run", "test.yml", "--ref", "pr", "-f", "ref=pr"), self.calls)

    def test_code_conflict_sends_back(self):
        self.pr({"lib/a.py": "x = 2\n"})
        self.main_moves({"lib/a.py": "x = 3\n"})
        self.assertIn("lib/a.py", self.sync())
        self.assertIn(("label", "7", "rework", ["rejected"]), self.calls)
        body = next(c[-1] for c in self.calls if c[:2] == ("pr", "comment"))
        self.assertTrue(body.startswith("VERDICT: rework\n"), body)  # dpcli update reads the reason from it

    def test_fork_merging_cleanly_goes_to_review_unpushed(self):
        self.pr({"lib/a.py": "x = 2\n"})
        self.main_moves({"lib/b.py": "y = 1\n"})
        sync.gh = lambda *a, **k: self.calls.append(a) or json.dumps({"headRefName": "pr", "isCrossRepository": True})
        self.assertEqual(self.sync(), 0)
        self.assertEqual([c for c in self.calls if c[0] != "pr"], [])  # no label, no test dispatch
        git("fetch", "-q", "origin", cwd=self.base)
        self.assertEqual(git("rev-parse", "origin/pr", cwd=self.base), git("rev-parse", "refs/pull/7/head", cwd=str(self.tmp / "origin.git")))

    def test_symlinked_changelog_is_not_written_through(self):
        self.pr({sync.INIT: INIT.format(30), sync.LOG: LOG.format("## 30\n- mine.\n\n")})
        self.main_moves({sync.INIT: INIT.format(31)})  # VERSION collides, CHANGELOG.md merges in as the PR's symlink
        git("switch", "-q", "pr", cwd=self.base)
        os.remove(self.base / sync.LOG)
        os.symlink("/etc/hostname", self.base / sync.LOG)
        git("commit", "-q", "-am", "link", cwd=self.base)
        git("push", "-q", "-f", "origin", "HEAD:pr", "HEAD:refs/pull/7/head", cwd=self.base)
        git("switch", "-q", "--detach", "origin/main", cwd=self.base)
        self.assertIn("symlink", self.sync())
        self.assertIn(("label", "7", "rework", ["rejected"]), self.calls)

    def test_up_to_date_does_nothing(self):
        self.pr({"lib/a.py": "x = 2\n"})
        self.assertEqual(self.sync(), 0)
        self.assertNotIn("workflow", [c[0] for c in self.calls])

    def test_main_changed_workflows_is_not_called_a_conflict(self):
        self.pr({"lib/a.py": "x = 2\n"})
        self.main_moves({".github/workflows/t.yml": "on: push\n"})
        self.assertIn("not a conflict", self.sync())

    def test_author_push_during_sync_is_left_alone(self):
        self.pr({"lib/a.py": "x = 2\n"})
        self.main_moves({"lib/b.py": "y = 1\n"})
        real = sync.git

        def racing(*a, **k):
            if a[0] == "push":  # the author pushes right before the CI does
                git("push", "-q", "-f", "origin", "origin/main:pr", cwd=self.base)
            return real(*a, **k)
        sync.git = racing
        try:
            self.assertIn("branch moved", self.sync())
        finally:
            sync.git = real
        self.assertNotIn("label", [c[0] for c in self.calls])


class Budgets(unittest.TestCase):
    def test_write_budgets_never_raises(self):
        m = {"code_lines": 10, "prompt_tokens": 5, "prompt_max": 3, "duplicate_windows": 0, "risky": {"push": 5, "new": 1}}
        b = {"code_lines": 8, "prompt_tokens": 9, "prompt_max": 3, "duplicate_windows": 0, "risky": {"push": 4}}
        self.assertEqual(metrics.lowered(m, b), {"code_lines": 8, "prompt_tokens": 5, "prompt_max": 3,
                                                 "duplicate_windows": 0, "risky": {"push": 4, "new": 1}})


if __name__ == "__main__":
    unittest.main()
