"""update: fast-forward the .dpcli submodule to the latest tag, re-render with the project layer, commit the pointer;
skip when dirty / on improve/*; pin; once a day with --auto; report the fate of own PRs."""
import json
import os
import re
import shutil
import stat
import unittest

from helpers import Project, git

FAKE_GH = r"""#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
if a[:2] == ["auth", "status"]: sys.exit(0)
if a[:2] in (["pr", "view"], ["issue", "view"]): print(json.dumps(json.loads(os.environ["FAKE_PR"])[a[2].rstrip("/").rsplit("/", 1)[-1]])); sys.exit(0)
sys.exit(3)
"""


def gitc(*args, cwd):
    return git("-c", "protocol.file.allow=always", *args, cwd=cwd)


class Update(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.addCleanup(self.p.cleanup)
        r = self.p.root
        # the distribution as a real hub repository with a tag, installed as a submodule
        self.origin = self.p.tmp / "dpcli.git"
        src = self.p.tmp / "src"
        shutil.copytree(r / ".dpcli", src)
        git("init", "-q", "-b", "main", cwd=src)
        git("add", "-A", cwd=src)
        git("commit", "-q", "-m", "dist", cwd=src)
        self.v0 = int(re.search(r"VERSION = (\d+)", (src / "lib/dpcli/__init__.py").read_text())[1])
        git("tag", f"v{self.v0}", cwd=src)
        git("clone", "-q", "--bare", str(src), str(self.origin), cwd=self.p.tmp)
        self.src = src
        git("remote", "add", "origin", str(self.origin), cwd=src)
        git("rm", "-r", "-q", "--cached", ".dpcli", cwd=r)
        shutil.rmtree(r / ".dpcli")
        gitc("submodule", "add", "-q", str(self.origin), ".dpcli", cwd=r)
        gitc("-C", ".dpcli", "checkout", "-q", f"v{self.v0}", cwd=r)
        (r / ".dpcli-local" / "agents").mkdir(parents=True)
        (r / ".dpcli-local" / "agents" / "dp-engineer.append.md").write_text("- LOCAL RULE\n")
        self.p.ok("init")
        self.p.commit_all("install")
        self.env = {}

    def release(self, n, agent_text="RELEASED"):
        f = self.src / "agents" / "dp-engineer.md"
        f.write_text(f.read_text().replace("You are a", f"{agent_text}: you are a", 1))
        w = self.src / "templates" / "workflow.md"
        w.write_text(w.read_text() + f"\n<!-- {agent_text} -->\n")
        v = self.src / "lib/dpcli/__init__.py"
        v.write_text(re.sub(r"VERSION = \d+", f"VERSION = {n}", v.read_text()))
        c = self.src / "CHANGELOG.md"
        c.write_text(c.read_text().replace("# Changelog\n", f"# Changelog\n\n## {n}\n- Something new in {n}.\n", 1))
        git("commit", "-q", "-am", f"v{n}", cwd=self.src)
        git("tag", f"v{n}", cwd=self.src)
        git("push", "-q", "origin", "main", f"v{n}", cwd=self.src)

    def head_version(self):
        return int(re.search(r"VERSION = (\d+)", (self.p.root / ".dpcli/lib/dpcli/__init__.py").read_text())[1])

    def test_updates_rerenders_and_commits(self):
        n = self.v0 + 1
        self.release(n)
        out = self.p.ok("update", env=self.env)
        self.assertIn(f"v{self.v0} → v{n}", out)
        self.assertIn(f"Something new in {n}", out)
        self.assertEqual(self.head_version(), n)
        eng = (self.p.root / ".claude/agents/dp-engineer.md").read_text()
        self.assertIn("RELEASED: you are a", eng)
        self.assertIn("LOCAL RULE", eng)
        self.assertEqual(git("status", "--porcelain", "--", ".dpcli", ".claude", "CLAUDE.md", cwd=self.p.root), "")
        self.assertIn(f"dpcli v{n}", git("log", "-1", "--format=%s", cwd=self.p.root))
        self.assertIn("up to date", self.p.ok("update", env=self.env))

    def test_dpcli_sits_on_main_and_stale_remote_branches_go(self):
        d = self.p.root / ".dpcli"
        self.p.ok("update", env=self.env)  # up to date, detached on its tag → branch main
        self.assertEqual(git("branch", "--show-current", cwd=d), "main")
        git("push", "-q", "origin", "main:improve/F-9-gone", cwd=self.src)
        git("fetch", "-q", "origin", cwd=d)
        git("push", "-q", "origin", ":improve/F-9-gone", cwd=self.src)
        self.release(self.v0 + 1)
        self.p.ok("update", env=self.env)
        self.assertEqual(git("branch", "--show-current", cwd=d), "main")
        self.assertEqual(git("rev-parse", "main", cwd=d), git("rev-parse", f"v{self.v0 + 1}^{{commit}}", cwd=d))
        self.assertNotIn("F-9-gone", git("branch", "-r", cwd=d))

    def test_current_version_but_stale_claude_is_rerendered(self):
        (self.p.root / ".claude" / "dpcli-workflow.md").unlink()
        self.p.commit_all("lost the rendered workflow")
        out = self.p.ok("update", env=self.env)
        self.assertIn(".claude re-rendered", out)
        self.assertTrue((self.p.root / ".claude" / "dpcli-workflow.md").is_file())
        self.assertEqual(git("status", "--porcelain", "--", ".claude", cwd=self.p.root), "")

    def test_hand_edited_generated_file_is_reported_not_rerendered_in_a_loop(self):
        f = self.p.root / ".claude" / "agents" / "dp-engineer.md"
        f.write_text(f.read_text() + "\nhand edit\n")
        self.p.commit_all("hand edit")
        out = self.p.ok("update", env=self.env)
        self.assertIn("stays stale after init", out)
        self.assertIn("hand edit", f.read_text())  # init never overwrites a hand edit

    def test_init_failure_at_current_version_is_reported_with_its_cause(self):
        (self.p.root / ".claude" / "dpcli-workflow.md").unlink()
        bad = self.p.root / ".dpcli-local" / "agents" / "dp-broken.md"
        bad.write_text("---\nname: dp-broken\ndpcli_role: nonsense\n---\nx\n")
        self.p.commit_all("broken local agent")
        out = self.p.ok("update", env=self.env)
        self.assertIn("init failed", out)
        self.assertIn("dpcli_role", out)

    def test_skips_dirty_and_improve_branch(self):
        self.release(self.v0 + 1)
        (self.p.root / ".dpcli" / "x.txt").write_text("wip")
        self.assertIn("uncommitted", self.p.ok("update", env=self.env))
        os.remove(self.p.root / ".dpcli" / "x.txt")
        git("switch", "-q", "-c", "improve/F-1-x", cwd=self.p.root / ".dpcli")
        self.assertIn("improve/F-1-x", self.p.ok("update", env=self.env))
        self.assertEqual(self.head_version(), self.v0)

    def test_same_version_off_the_tag_moves_to_the_tag(self):
        # an own PR was squash-merged: .dpcli sits on the branch commit with the release's VERSION, not on the tag
        d = self.p.root / ".dpcli"
        v = d / "lib/dpcli/__init__.py"
        v.write_text(re.sub(r"VERSION = \d+", f"VERSION = {self.v0 + 1}", v.read_text()))
        git("commit", "-q", "-am", "improve", cwd=d)
        self.release(self.v0 + 1)
        out = self.p.ok("update", env=self.env)
        self.assertIn(f"v{self.v0 + 1}", out)
        self.assertEqual(git("rev-parse", "HEAD", cwd=d), git("rev-parse", f"v{self.v0 + 1}^{{commit}}", cwd=d))
        self.assertIn(".dpcli", git("show", "--stat", "HEAD", cwd=self.p.root))  # the pointer at the tag is committed

    def test_pin(self):
        self.release(self.v0 + 1)
        self.release(self.v0 + 2, "SECOND")
        self.p.ok("update", "--pin", f"v{self.v0 + 1}", env=self.env)
        self.p.ok("update", env=self.env)
        self.assertEqual(self.head_version(), self.v0 + 1)
        self.assertIn("pinned", self.p.ok("update", env=self.env))
        self.p.ok("update", "--unpin", env=self.env)
        self.p.ok("update", env=self.env)
        self.assertEqual(self.head_version(), self.v0 + 2)

    def test_auto_once_a_day(self):
        self.p.ok("update", "--auto", env=self.env)
        self.release(self.v0 + 1)
        self.assertEqual(self.p.ok("update", "--auto", env=self.env).strip(), "")
        self.assertEqual(self.head_version(), self.v0)

    def test_own_pr_merged_marks_fixed_and_rework_reported(self):
        self.p.ok("module", "init", "web", "--code", "WB")
        self.p.ok("feedback", "new", "Slow accept", "--match", "accept", "--scope", "dpcli")
        self.p.ok("feedback", "new", "Plan sections", "--match", "plan", "--scope", "dpcli")
        self.p.ok("feedback", "new", "Closed one", "--match", "zzz", "--scope", "dpcli")
        led = self.p.root / ".dpcli-local" / "feedback.jsonl"
        with open(led, "a") as f:
            f.write(json.dumps({"t": "2026-10-01T00:00:00", "id": "F-1", "kind": "pr", "url": "https://github.com/o/r/pull/1"}) + "\n")
            f.write(json.dumps({"t": "2026-10-01T00:00:00", "id": "F-2", "kind": "pr", "url": "https://github.com/o/r/pull/2"}) + "\n")
            f.write(json.dumps({"t": "2026-10-01T00:00:00", "id": "F-3", "kind": "pr", "url": "https://github.com/o/r/pull/3"}) + "\n")
        bin_ = self.p.tmp / "bin"
        bin_.mkdir()
        gh = bin_ / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        states = {"1": {"state": "MERGED", "labels": [], "comments": []},
                  "2": {"state": "OPEN", "labels": [{"name": "rework"}],
                        "comments": [{"body": "VERDICT: rework\n- no test reproduces the friction", "url": "c2"}]},
                  "3": {"state": "CLOSED", "labels": [{"name": "rejected"}], "comments": []}}
        env = {**self.env, "PATH": f"{bin_}:{os.environ['PATH']}", "FAKE_PR": json.dumps(states)}
        d = self.p.root / ".dpcli"
        git("branch", "improve/F-2-plan", cwd=d)
        git("branch", "improve/F-3-closed", cwd=d)
        git("switch", "-q", "-c", "improve/F-1-slow", cwd=d)  # still on the merged PR's branch: update would skip forever
        out = self.p.ok("update", "--prs-only", env=env)
        branches = git("branch", "--format=%(refname:short)", cwd=d)
        self.assertNotIn("improve/F-1-slow", branches)  # merged: gone
        self.assertIn("improve/F-2-plan", branches)  # rework: kept
        self.assertIn("improve/F-3-closed", branches)  # closed unmerged: may be the only copy, kept
        self.assertIn("pull/1 merged → F-1 fixed", out)
        self.assertIn("pull/2 rework", out)
        self.assertIn("no test reproduces the friction", out)
        listed = self.p.ok("feedback")
        self.assertRegex(listed, r"F-1 .*fixed")
        self.assertRegex(listed, r"F-2 .*rework")


if __name__ == "__main__":
    unittest.main()
