import json
import unittest

from helpers import DIST, Project

HAS_INIT = (DIST / "lib" / "dpcli" / "commands" / "init.py").is_file()


@unittest.skipUnless(HAS_INIT, "commands/init.py ещё нет")
class Init(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.addCleanup(self.p.cleanup)
        self.p.ok("init")

    def snapshot(self):
        snap = {}
        for sub in (".claude", "CLAUDE.md", ".gitignore", "dpcli.yml", "dpcli.json"):
            base = self.p.root / sub
            files = [base] if base.is_file() else sorted(base.rglob("*")) if base.is_dir() else []
            for f in files:
                if f.is_file():
                    snap[str(f.relative_to(self.p.root))] = f.read_bytes()
        return snap

    def test_creates(self):
        r = self.p.root
        for n in (r / ".dpcli" / "agents").glob("*.md"):
            self.assertTrue((r / ".claude" / "agents" / n.name).is_file(), n.name)
        for s in (DIST / "skills").iterdir():
            self.assertTrue((r / ".claude" / "skills" / s.name / "SKILL.md").is_file(), s.name)
        self.assertTrue((r / ".claude" / "dpcli-workflow.md").is_file())
        md = (r / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("<!-- dpcli:begin", md)
        self.assertIn("<!-- dpcli:end", md)
        st = json.loads((r / ".claude" / "settings.json").read_text())
        self.assertIn("Bash(.dpcli/dpcli *)", st["permissions"]["allow"])

    def test_no_placeholders(self):
        r = self.p.root
        files = list((r / ".claude").rglob("*.md")) + [r / "CLAUDE.md"]
        self.assertTrue(files)
        for f in files:
            self.assertNotIn("{{", f.read_text(encoding="utf-8"), str(f))

    def test_idempotent(self):
        before = self.snapshot()
        self.p.ok("init")
        self.assertEqual(before, self.snapshot())

    def test_preserves_claude_md(self):
        p = Project()
        self.addCleanup(p.cleanup)
        (p.root / "CLAUDE.md").write_text("# Мой проект\nправила\n", encoding="utf-8")
        p.ok("init")
        md = (p.root / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertTrue(md.startswith("# Мой проект\nправила"))
        self.assertEqual(md.count("<!-- dpcli:begin"), 1)

    def test_dry_run(self):
        p = Project()
        self.addCleanup(p.cleanup)
        p.ok("init", "--dry-run")
        self.assertFalse((p.root / ".claude").exists())


if __name__ == "__main__":
    unittest.main()
