"""contribute: a dpcli-scope friction goes to the hub as a PR (origin or fork), a +1 on a similar open one, or an issue."""
import json
import os
import stat
import unittest

from helpers import Project, git

FAKE_GH = r"""#!/usr/bin/env python3
import json, os, subprocess, sys
a = sys.argv[1:]
open(os.environ["FAKE_LOG"], "a").write(json.dumps(a) + "\n")
if a[:2] == ["auth", "status"]: sys.exit(0)
if a[:1] == ["api"] and a[1].startswith("repos/"): print(os.environ.get("FAKE_PUSH", "true")); sys.exit(0)
if a[:2] == ["api", "user"]: print("alice"); sys.exit(0)
if a[:2] == ["search", "issues"]: print(os.environ.get("FAKE_SEARCH", "[]")); sys.exit(0)
if a[:2] == ["repo", "fork"]:
    subprocess.run(["git", "remote", "add", "fork", os.environ["FAKE_FORK"]], check=True); sys.exit(0)
if a[:2] == ["pr", "create"]: print("https://github.com/o/r/pull/12"); sys.exit(0)
if a[:2] == ["issue", "create"]: print("https://github.com/o/r/issues/13"); sys.exit(0)
if a[:2] == ["issue", "comment"]: print("https://github.com/o/r/issues/5#c1"); sys.exit(0)
sys.exit(3)
"""


class Contribute(unittest.TestCase):
    def setUp(self):
        self.p = Project({"hub": "o/r"})
        self.addCleanup(self.p.cleanup)
        d = self.dist = self.p.root / ".dpcli"
        self.origin = self.p.tmp / "origin.git"
        self.fork = self.p.tmp / "fork.git"
        git("init", "-q", "--bare", str(self.origin), cwd=self.p.tmp)
        git("init", "-q", "--bare", str(self.fork), cwd=self.p.tmp)
        git("init", "-q", "-b", "main", cwd=d)
        git("add", "-A", cwd=d)
        git("commit", "-q", "-m", "dist", cwd=d)
        git("remote", "add", "origin", str(self.origin), cwd=d)
        git("push", "-q", "origin", "main", cwd=d)
        bin_ = self.p.tmp / "bin"
        bin_.mkdir()
        gh = bin_ / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        self.log = self.p.tmp / "gh.log"
        self.env = {"PATH": f"{bin_}:{os.environ['PATH']}", "FAKE_LOG": str(self.log), "FAKE_FORK": str(self.fork)}
        self.p.ok("module", "init", "web", "--code", "WB")
        ev = {"t": "2026-10-01T12:00:00", "by": "executor", "task": "WB-1", "ev": "reported",
              "dp_feedback": "accept --dry runs 10 min in foreground"}
        (self.p.root / "docs/plan/web/events.jsonl").write_text(json.dumps(ev) + "\n")
        self.p.ok("feedback", "new", "Long accept blocks the agent", "--match", "accept --dry", "--scope", "dpcli")

    def calls(self):
        return [json.loads(l) for l in self.log.read_text().splitlines()] if self.log.exists() else []

    def improve(self):
        git("switch", "-q", "-c", "improve/F-1-bg-accept", cwd=self.dist)
        (self.dist / "x.txt").write_text("x")
        git("add", "x.txt", cwd=self.dist)
        git("commit", "-q", "-m", "accept: go to background when slow", cwd=self.dist)

    def test_pr_from_origin(self):
        self.improve()
        out = self.p.ok("contribute", "F-1", env=self.env)
        self.assertIn("https://github.com/o/r/pull/12", out)
        pr = next(c for c in self.calls() if c[:2] == ["pr", "create"])
        self.assertIn("feedback", pr)
        body = pr[pr.index("--body") + 1]
        self.assertIn("accept: go to background when slow", body)
        self.assertNotIn("WB-1", body)  # anonymized: no task IDs or quotes
        self.assertNotIn("10 min in foreground", body)
        self.assertIn("improve/F-1-bg-accept", git("branch", "-r", cwd=self.dist) + git("ls-remote", str(self.origin), cwd=self.dist))
        self.assertIn("pull/12", self.p.ok("feedback", env=self.env))

    def test_pr_from_fork_without_push_rights(self):
        self.improve()
        self.p.ok("contribute", "F-1", env={**self.env, "FAKE_PUSH": "false"})
        cs = self.calls()
        self.assertTrue(any(c[:2] == ["repo", "fork"] for c in cs))
        pr = next(c for c in cs if c[:2] == ["pr", "create"])
        self.assertEqual(pr[pr.index("--head") + 1], "alice:improve/F-1-bg-accept")
        self.assertIn("improve/F-1-bg-accept", git("ls-remote", str(self.fork), cwd=self.dist))

    def test_plus_one_instead_of_duplicate(self):
        self.improve()
        similar = json.dumps([{"number": 5, "title": "Long accept blocks agents", "url": "https://github.com/o/r/issues/5"}])
        out = self.p.ok("contribute", "F-1", env={**self.env, "FAKE_SEARCH": similar})
        self.assertIn("+1", out)
        cs = self.calls()
        self.assertTrue(any(c[:2] == ["issue", "comment"] and "5" in c for c in cs))
        self.assertFalse(any(c[:2] == ["pr", "create"] for c in cs))

    def test_issue_without_commits(self):
        out = self.p.ok("contribute", "F-1", env=self.env)
        self.assertIn("issues/13", out)

    def test_refuses_project_scope_and_main_branch(self):
        self.p.ok("feedback", "new", "Local rule", "--match", "zzz", "--scope", "project")
        code, _, err = self.p.run("contribute", "F-2", env=self.env)
        self.assertEqual(code, 1)
        self.assertIn(".dpcli-local", err)
        (self.dist / "y.txt").write_text("y")
        git("add", "y.txt", cwd=self.dist)
        git("commit", "-q", "-m", "on main", cwd=self.dist)
        code, _, err = self.p.run("contribute", "F-1", env=self.env)
        self.assertEqual(code, 1)
        self.assertIn("improve/", err)
        git("switch", "-q", "-c", "improve/F-10-other", cwd=self.dist)  # another cluster's branch: its commits, not F-1's
        code, _, err = self.p.run("contribute", "F-1", env=self.env)
        self.assertEqual(code, 1)
        self.assertIn("improve/F-1-", err)
        (self.dist / "z.txt").write_text("F-1's edit")  # uncommitted edits on top: F-10's commits must not ride along
        code, _, err = self.p.run("contribute", "F-1", env=self.env)
        self.assertEqual(code, 1)
        self.assertEqual(git("branch", "--show-current", cwd=self.dist), "improve/F-10-other")

    def test_uncommitted_edits_get_their_branch_and_commit(self):
        # agents may run dpcli but not git in .dpcli: contribute makes the improve/* branch and the commit itself
        (self.dist / "x.txt").write_text("x")
        out = self.p.ok("contribute", "F-1", env=self.env)
        self.assertIn("pull/12", out)
        self.assertIn("committed on improve/F-1-long-accept-blocks-the-agent: x.txt", out)
        self.assertEqual(git("branch", "--show-current", cwd=self.dist), "improve/F-1-long-accept-blocks-the-agent")
        self.assertEqual(git("log", "-1", "--format=%s", cwd=self.dist), "Long accept blocks the agent")
        self.assertIn("improve/F-1-long-accept-blocks-the-agent", git("ls-remote", str(self.origin), cwd=self.dist))

    def test_no_gh_writes_patch(self):
        self.improve()
        nogh = self.p.tmp / "nogh"
        nogh.mkdir()
        (nogh / "gh").write_text("#!/bin/sh\nexit 1\n")  # a gh that is not logged in, whatever the machine has
        (nogh / "gh").chmod(0o755)
        env = {**self.env, "PATH": f"{nogh}:{os.environ['PATH']}"}
        out = self.p.ok("contribute", "F-1", env=env)
        self.assertIn("gh", out)
        d = self.p.root / "build" / "dpcli" / "contribute-F-1"
        self.assertTrue((d / "issue.md").is_file())
        self.assertTrue(list(d.glob("*.patch")))
        self.assertIn("F-1 not sent to the dpcli hub", self.p.ok("update", "--prs-only", env=env))  # the user sees it
        self.p.ok("contribute", "F-1", env=self.env)
        self.assertFalse(d.exists())
        self.assertNotIn("not sent", self.p.ok("update", "--prs-only", env=self.env))


if __name__ == "__main__":
    unittest.main()
