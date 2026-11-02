"""install.sh: clean project, vendored copy with an own agent, submodule converted, idempotent rerun."""
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
        self.src = src
        self.origin = self.p.tmp / "dpcli.git"
        git("clone", "-q", "--bare", str(src), str(self.origin), cwd=self.p.tmp)
        self.env = {**self.p.env(), "DPCLI_REPO": str(self.origin), "GIT_CONFIG_COUNT": "1",
                    "GIT_CONFIG_KEY_0": "protocol.file.allow", "GIT_CONFIG_VALUE_0": "always"}

    def run_install(self, *args):
        return subprocess.run(["bash", str(DIST / "install.sh"), "--yes", *args], cwd=self.p.root, env=self.env,
                              capture_output=True, text=True, timeout=120)

    def install(self, *args):
        r = self.run_install(*args)
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
        self.assertIn("(v99)", out)
        self.assertFalse((r / ".gitmodules").exists())
        self.assertTrue((r / ".dpcli" / "dpcli").is_file())
        self.assertTrue((r / ".dpcli" / "hooks" / "bash_guard.py").is_file())
        self.assertFalse((r / ".dpcli" / "tests").exists())  # only the distribution
        self.assertFalse((r / ".dpcli" / ".git").exists())
        cfg = (r / "dpcli.yml").read_text()
        self.assertRegex(cfg, r"language:\n  text: ru\n  commits: en")
        self.assertNotIn("submodule", cfg)
        self.assertIn("in Russian", (r / ".claude" / "dpcli-workflow.md").read_text())
        st = (r / ".claude" / "settings.json").read_text()
        self.assertIn("bash_guard.py", st)
        self.assertNotIn("update --auto", st)
        self.assertIn("commit: git add", out)

    def test_vendored_copy_keeps_own_agent_and_rerun_is_idempotent(self):
        (self.p.root / ".dpcli" / "agents" / "dp-dba.md").write_text(
            "---\nname: dp-dba\ndescription: \"db\"\ndpcli_role: executor\n---\nDB.\n")
        self.p.commit_all("own agent in the vendored copy")
        out = self.install("--lang", "en", "--commit-lang", "en")
        r = self.p.root
        self.assertIn("own agent dp-dba.md", out)
        self.assertTrue((r / ".dpcli-local" / "agents" / "dp-dba.md").is_file())
        self.assertTrue((r / ".claude" / "agents" / "dp-dba.md").is_file())
        self.assertNotIn("160000", git("ls-files", "-s", ".dpcli", cwd=r))
        self.assertIn('"commits": "en"', (r / "dpcli.json").read_text())
        git("add", "-A", cwd=r)
        git("commit", "-q", "-m", "dpcli", cwd=r)
        again = self.install("--lang", "en", "--commit-lang", "en")
        self.assertIn("nothing changed", again)

    def test_uncommitted_changes_in_dpcli_block(self):
        (self.p.root / ".dpcli" / "agents" / "dp-engineer.md").write_text("edited by hand\n")
        r = self.run_install("--lang", "en", "--commit-lang", "en")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("uncommitted changes in .dpcli", r.stderr)
        self.assertEqual((self.p.root / ".dpcli" / "agents" / "dp-engineer.md").read_text(), "edited by hand\n")

    def test_vendored_copy_deleted_from_disk(self):
        shutil.rmtree(self.p.root / ".dpcli")  # tracked in git, gone from the working tree
        r = subprocess.run(["git", "checkout", "-q", "--", ".dpcli"], cwd=self.p.root)  # status must be clean first
        self.assertEqual(r.returncode, 0)
        shutil.rmtree(self.p.root / ".dpcli")
        git("rm", "-r", "-q", "--cached", ".dpcli", cwd=self.p.root)
        git("commit", "-q", "-m", "drop", cwd=self.p.root)
        self.install("--lang", "en", "--commit-lang", "ru")
        self.assertTrue((self.p.root / ".dpcli" / "dpcli").is_file())

    def test_submodule_is_converted_to_a_folder(self):
        self.drop_vendored()
        r = self.p.root
        git("-c", "protocol.file.allow=always", "submodule", "add", "-q", str(self.origin), ".dpcli", cwd=r)
        (r / "dpcli.yml").write_text('worktree:\n  setup: "git submodule update --init .dpcli"\n')
        self.p.commit_all("dpcli as a submodule")
        out = self.install("--lang", "en", "--commit-lang", "en")
        self.assertIn("converted to a folder", out)
        self.assertNotIn("160000", git("ls-files", "-s", ".dpcli", cwd=r))
        self.assertTrue((r / ".dpcli" / "dpcli").is_file())
        self.assertFalse((r / ".dpcli" / ".git").exists())
        self.assertNotIn(".dpcli", (r / ".gitmodules").read_text() if (r / ".gitmodules").exists() else "")
        self.assertNotIn("submodule", (r / "dpcli.yml").read_text())

    def test_ref_picks_a_branch(self):
        self.drop_vendored()
        git("checkout", "-q", "-b", "next", cwd=self.src)
        (self.src / "agents" / "dp-new.md").write_text("---\nname: dp-new\ndescription: \"n\"\ndpcli_role: executor\n---\nN.\n")
        git("add", "-A", cwd=self.src)
        git("commit", "-q", "-m", "next", cwd=self.src)
        git("push", "-q", str(self.origin), "next", cwd=self.src)
        self.install("--lang", "en", "--commit-lang", "en", "--ref", "next")
        self.assertTrue((self.p.root / ".dpcli" / "agents" / "dp-new.md").is_file())


if __name__ == "__main__":
    unittest.main()
