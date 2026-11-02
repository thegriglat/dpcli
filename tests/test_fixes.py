"""dpcli fixes: paths with spaces/Cyrillic, docs check, contract links, copies (git-crypt, gc)."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from dpcli import config, copies, gitx  # noqa: E402
from dpcli.commands import accept, branches, docs, task  # noqa: E402
from dpcli.util import DpError  # noqa: E402


def sh(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


class RepoCase(unittest.TestCase):
    """Temporary main repository in tmp/main; the process cwd is inside it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.main = Path(self.tmp.name).resolve() / "main"
        self.main.mkdir()
        sh("init", "-q", "-b", "main", cwd=self.main)
        sh("config", "user.email", "t@t", cwd=self.main)
        sh("config", "user.name", "t", cwd=self.main)
        (self.main / ".gitignore").write_text(".gen\n")
        (self.main / "a.txt").write_text("a")
        sh("add", ".", cwd=self.main)
        sh("commit", "-q", "-m", "i", cwd=self.main)
        self.old_cwd = os.getcwd()
        os.chdir(self.main)
        self.addCleanup(os.chdir, self.old_cwd)
        config.reset()
        gitx.reset_worktrees()
        gitx._TOP = None
        self.addCleanup(config.reset)

    def cfg(self, **over):
        config._CFG = config.merge(config.DEFAULTS, over)


class ScopePaths(RepoCase):
    NAME = "docs/Мои заметки/Контракт.md"

    def test_pat_whole_path_with_spaces(self):
        pats = accept._pat(self.NAME)
        self.assertTrue(accept.path_in(self.NAME, pats))

    def test_pat_with_note(self):
        self.assertTrue(accept.path_in("src/x.py", accept._pat("src/x.py — функция f")))
        self.assertTrue(accept.path_in("src/x.py", accept._pat("src/x.py функция f")))
        self.assertTrue(accept.path_in(self.NAME, accept._pat(f"{self.NAME} — раздел 2")))
        self.assertTrue(accept.path_in(self.NAME, accept._pat(f"`{self.NAME}` (раздел)")))
        self.assertFalse(accept.path_in("src/y.py", accept._pat("src/x.py — функция f")))

    def test_changed_files_unquoted(self):
        f = self.main / self.NAME
        f.parent.mkdir(parents=True)
        f.write_text("x")
        (self.main / "q r.md").write_text("y")
        got = accept.changed_files(self.main, "main")
        self.assertIn(self.NAME, got)
        self.assertIn("q r.md", got)
        scope = [p for e in [self.NAME, "q r.md"] for p in accept._pat(e)]
        self.assertTrue(all(accept.path_in(g, scope) for g in got))

    def test_changed_files_committed(self):
        sh("checkout", "-q", "-b", "t", cwd=self.main)
        f = self.main / self.NAME
        f.parent.mkdir(parents=True)
        f.write_text("x")
        sh("add", ".", cwd=self.main)
        sh("commit", "-q", "-m", "c", cwd=self.main)
        self.assertEqual(accept.changed_files(self.main, "main"), [self.NAME])

    def test_status_rename(self):
        sh("mv", "a.txt", "б в.txt", cwd=self.main)
        self.assertEqual(accept.changed_files(self.main, "main"), ["б в.txt"])


class DocsFrontmatter(unittest.TestCase):
    def test_related_block_list(self):
        fm, body = docs.split_fm("---\ntype: plan\nupdated: 2026-10-07\nrelated:\n  - docs/a.md\n  - docs/b c.md\n---\n\nтело\n")
        self.assertEqual(fm["related"], ["docs/a.md", "docs/b c.md"])
        self.assertEqual(fm["updated"], "2026-10-07")
        self.assertEqual(body.strip(), "тело")

    def test_related_inline_list(self):
        fm, _ = docs.split_fm('---\ntype: plan\nrelated: [docs/a.md, docs/b.md]\n---\nx')
        self.assertEqual(fm["related"], ["docs/a.md", "docs/b.md"])
        fm, _ = docs.split_fm('---\nrelated: ["docs/a.md"]\n---\nx')
        self.assertEqual(fm["related"], ["docs/a.md"])

    def test_flat_fallback(self):
        fm, _ = docs.split_fm('---\nsummary: "Вывод: что-то"\nrelated: []\n---\nx')
        self.assertEqual(fm["related"], [])
        self.assertEqual(fm["summary"], "Вывод: что-то")

    def test_no_frontmatter(self):
        self.assertIsNone(docs.split_fm("текст")[0])


class DocsCheckPaths(RepoCase):
    def test_explicit_paths(self):
        (self.main / "docs" / "sub").mkdir(parents=True)
        for n in ("docs/a.md", "docs/sub/b.md", "docs/sub/c.md"):
            (self.main / n).write_text("x")

        class X:
            root = self.main
        scope = ["docs/a.md", "docs/sub/b.md", "docs/sub/c.md"]
        self.assertEqual(docs.explicit_paths(X, ["docs/a.md"], scope), ["docs/a.md"])
        self.assertEqual(docs.explicit_paths(X, ["docs/sub"], scope), ["docs/sub/b.md", "docs/sub/c.md"])
        self.assertEqual(docs.explicit_paths(X, ["docs/a.md", "docs/a.md"], scope), ["docs/a.md"])
        with self.assertRaises(DpError):
            docs.explicit_paths(X, ["docs/none.md"], scope)

    def test_check_only_given(self):
        (self.main / "docs").mkdir()
        good = "---\ntype: plan\nstatus: active\nupdated: 2026-01-01\nsummary: ok\nrelated:\n  - docs/good.md\n---\nt\n"
        (self.main / "docs/good.md").write_text(good)
        (self.main / "docs/bad.md").write_text("без frontmatter")
        self.cfg()
        ctx = docs.Ctx()

        class A:
            paths = ["docs/good.md"]
        self.assertEqual(docs.cmd_check(ctx, A), 0)
        A.paths = []
        self.assertEqual(docs.cmd_check(ctx, A), 1)


class ContractRef(unittest.TestCase):
    def test_other_module(self):
        meta = {"module": "pro-x", "contracts": "docs/contracts/pro-x.md"}
        self.assertEqual(task.contract_ref("billing.C5", meta), "docs/contracts/billing.md")
        self.assertEqual(task.contract_ref("C5", meta), "docs/contracts/pro-x.md")
        self.assertEqual(task.contract_ref("pro-x.C1", meta), "docs/contracts/pro-x.md")
        self.assertEqual(task.contract_ref("billing.C5", meta, "docs/contracts/pro-x.md"), "docs/contracts/billing.md")


class Copies(RepoCase):
    def make_copy(self, name="wt"):
        path = self.main.parent / name
        copies.create(path, f"br-{name}", base="main")
        return path

    def test_git_crypt_keys_copied(self):
        keys = self.main / ".git" / "git-crypt" / "keys"
        keys.mkdir(parents=True)
        (keys / "default").write_text("k")
        path = self.make_copy()
        gd = Path(subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-dir"], cwd=path,
                                 capture_output=True, text=True).stdout.strip())
        self.assertTrue((gd / "git-crypt" / "keys" / "default").is_file())
        self.assertFalse((gd / "git-crypt").is_symlink())

    def test_setup_copies_generated_and_runs_command(self):
        (self.main / "app").mkdir()
        (self.main / "app" / ".gitignore").write_text(".gen\n")
        (self.main / "app" / "p.json").write_text("{}")
        sh("add", ".", cwd=self.main)
        sh("commit", "-q", "-m", "app", cwd=self.main)
        (self.main / "app" / ".gen").mkdir()
        (self.main / "app" / ".gen" / "tsconfig.json").write_text("{}")
        self.cfg(worktree={"copy": [".gen"], "link": [], "setup": "test -d app/.gen && touch setup-ran"})
        path = self.make_copy()
        lines = copies.setup(path)
        self.assertTrue((path / "app/.gen/tsconfig.json").is_file(), lines)
        self.assertTrue((path / "setup-ran").exists(), lines)

    def test_remove_copy_with_ignored_and_generated(self):
        (self.main / "app").mkdir()
        (self.main / "app" / ".gitignore").write_text(".gen\n")
        sh("add", ".", cwd=self.main)
        sh("commit", "-q", "-m", "app", cwd=self.main)
        self.cfg(gc={"ignore_dirs": ["build", ".gen"], "ignore_globs": ["*.uid"]})
        path = self.make_copy()
        (path / "app/.gen").mkdir()
        (path / "app/.gen/f").write_text("1")
        (path / ".gen").mkdir()
        (path / ".gen/f").write_text("1")
        (path / "x.uid").write_text("1")
        why, _ign = branches.remove_copy(path)
        self.assertIsNone(why)
        self.assertFalse(path.exists())

    def test_remove_copy_only_ignored(self):
        self.cfg()
        path = self.make_copy()
        (path / ".gen").mkdir()
        (path / ".gen/f").write_text("1")
        why, ign = branches.remove_copy(path)
        self.assertIsNone(why)
        self.assertFalse(path.exists())

    def test_remove_copy_refuses_work(self):
        self.cfg()
        path = self.make_copy()
        (path / "new.txt").write_text("работа")
        why, _ = branches.remove_copy(path)
        self.assertIn("untracked files", why)
        (path / "new.txt").unlink()
        (path / "a.txt").write_text("changed")
        why, _ = branches.remove_copy(path)
        self.assertIn("dirty copy", why)
        self.assertTrue(path.exists())

    def test_remove_copy_status_noise_without_changes(self):
        # a pre-commit hook restored the file: status says MM, content equals HEAD
        self.cfg()
        path = self.make_copy()
        (path / "a.txt").write_text("b")
        sh("add", "a.txt", cwd=path)
        (path / "a.txt").write_text("a")
        why, _ = branches.remove_copy(path)
        self.assertIsNone(why)
        self.assertFalse(path.exists())

    def test_remove_copy_with_submodule(self):
        sub = self.main.parent / "sub"
        sub.mkdir()
        sh("init", "-q", "-b", "main", cwd=sub)
        (sub / "s.txt").write_text("s")
        sh("add", ".", cwd=sub)
        sh("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "s", cwd=sub)
        sh("-c", "protocol.file.allow=always", "submodule", "add", "-q", str(sub), "lib", cwd=self.main)
        sh("commit", "-q", "-m", "sub", cwd=self.main)
        self.cfg()
        path = self.make_copy()
        sh("-c", "protocol.file.allow=always", "submodule", "update", "-q", "--init", cwd=path)
        (path / "lib" / "work.txt").write_text("работа")
        why, _ = branches.remove_copy(path)
        self.assertIn("submodules", why)
        sh("add", "work.txt", cwd=path / "lib")
        sh("-c", "user.email=t@t", "-c", "user.name=t", "stash", "-q", cwd=path / "lib")
        why, _ = branches.remove_copy(path)
        self.assertIn("submodules", why)
        sh("stash", "pop", "-q", cwd=path / "lib")
        # a commit only in the copy's submodule repository would be lost with it
        sh("add", "work.txt", cwd=path / "lib")
        sh("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "w", cwd=path / "lib")
        sh("add", "lib", cwd=path)
        sh("commit", "-q", "-m", "pointer", cwd=path)
        why, _ = branches.remove_copy(path)
        self.assertIn("submodules", why)
        sh("reset", "-q", "--hard", "HEAD~1", cwd=path)
        sh("submodule", "update", "-q", cwd=path)
        # the check itself fails: block, do not assume clean
        dotgit = path / "lib" / ".git"
        good = dotgit.read_text()
        dotgit.write_text("gitdir: /nonexistent\n")
        why, _ = branches.remove_copy(path)
        self.assertIn("cannot check submodules", why)
        dotgit.write_text(good)
        sh("branch", "-q", "-D", "main", cwd=path / "lib")
        why, _ = branches.remove_copy(path)
        self.assertIsNone(why)
        self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
