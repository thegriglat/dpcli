"""install.sh: clean project, vendored copy with an own agent, idempotent rerun."""
import os
import re
import shutil
import subprocess
import unittest

from helpers import DIST, Project, git


class Install(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.addCleanup(self.p.cleanup)
        src = self.p.tmp / "src"
        shutil.copytree(DIST, src, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        git("init", "-q", "-b", "main", cwd=src)
        git("add", "-A", cwd=src)
        git("commit", "-q", "-m", "dist", cwd=src)
        git("tag", "v99", cwd=src)
        self.origin = self.p.tmp / "dpcli.git"
        git("clone", "-q", "--bare", str(src), str(self.origin), cwd=self.p.tmp)
        self.env = {**self.p.env(), "DPCLI_REPO": str(self.origin), "GIT_CONFIG_COUNT": "1",
                    "GIT_CONFIG_KEY_0": "protocol.file.allow", "GIT_CONFIG_VALUE_0": "always"}

    def install(self, *args):
        r = subprocess.run(["bash", str(DIST / "install.sh"), "--yes", *args], cwd=self.p.root, env=self.env,
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return r.stdout

    def drop_vendored(self):
        git("rm", "-r", "-q", "--cached", ".dpcli", cwd=self.p.root)
        shutil.rmtree(self.p.root / ".dpcli")
        (self.p.root / "dpcli.json").unlink()
        self.p.commit_all("no dpcli")

    def test_clean_project(self):
        self.drop_vendored()
        out = self.install("--lang", "ru", "--commit-lang", "en")
        r = self.p.root
        self.assertIn("submodule .dpcli added", out)
        self.assertIn("version v99", out)
        self.assertIn(".dpcli", (r / ".gitmodules").read_text())
        cfg = (r / "dpcli.yml").read_text()
        self.assertRegex(cfg, r"language:\n  text: ru\n  commits: en")
        self.assertIn("git submodule update --init .dpcli", cfg)
        self.assertIn("in Russian", (r / ".claude" / "dpcli-workflow.md").read_text())
        self.assertIn("update --auto", (r / ".claude" / "settings.json").read_text())
        self.assertIn("commit: git add", out)

    def test_vendored_copy_migrates_own_agent_and_rerun_is_idempotent(self):
        (self.p.root / ".dpcli" / "agents" / "dp-dba.md").write_text(
            "---\nname: dp-dba\ndescription: \"db\"\ndpcli_role: executor\n---\nDB.\n")
        self.p.commit_all("own agent in the vendored copy")
        out = self.install("--lang", "en", "--commit-lang", "en")
        r = self.p.root
        self.assertIn("own agent dp-dba.md", out)
        self.assertTrue((r / ".dpcli-local" / "agents" / "dp-dba.md").is_file())
        self.assertTrue((r / ".claude" / "agents" / "dp-dba.md").is_file())
        self.assertIn("160000", git("ls-files", "-s", ".dpcli", cwd=r))  # a gitlink, not files
        cfg = (r / "dpcli.json").read_text()
        self.assertIn('"commits": "en"', cfg)
        git("add", "-A", cwd=r)
        git("commit", "-q", "-m", "dpcli", cwd=r)
        again = self.install("--lang", "en", "--commit-lang", "en")
        self.assertIn("nothing changed", again)

    def test_vendored_copy_deleted_from_disk(self):
        shutil.rmtree(self.p.root / ".dpcli")  # tracked in git, gone from the working tree
        out = self.install("--lang", "en", "--commit-lang", "ru")
        self.assertIn("replaced by the submodule", out)
        self.assertIn("160000", git("ls-files", "-s", ".dpcli", cwd=self.p.root))

    def test_gitlink_without_gitmodules(self):
        self.drop_vendored()
        r = self.p.root
        sha = git("rev-parse", "HEAD", cwd=self.p.tmp / "src")
        git("update-index", "--add", "--cacheinfo", f"160000,{sha},.dpcli", cwd=r)  # a gitlink, no .gitmodules
        git("commit", "-q", "-m", "broken submodule", cwd=r)
        out = self.install("--lang", "en", "--commit-lang", "en")
        self.assertIn("registered", out)
        self.assertTrue((r / ".dpcli" / "dpcli").is_file())
        self.assertIn(".dpcli", (r / ".gitmodules").read_text())

    def test_gitlink_to_unknown_commit_is_re_added(self):
        self.drop_vendored()
        r = self.p.root
        git("update-index", "--add", "--cacheinfo", f"160000,{'1' * 40},.dpcli", cwd=r)  # commit the hub doesn't have
        git("commit", "-q", "-m", "stale submodule", cwd=r)
        out = self.install("--lang", "en", "--commit-lang", "en")
        self.assertIn("registered", out)
        self.assertTrue((r / ".dpcli" / "dpcli").is_file())
        self.assertNotIn("1" * 40, git("ls-files", "-s", ".dpcli", cwd=r))


if __name__ == "__main__":
    unittest.main()
