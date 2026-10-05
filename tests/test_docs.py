import unittest

from helpers import Project

A = '---\ntype: guide\nstatus: active\nmodule: core\nupdated: 2026-01-01\nsummary: "Про альфа"\n---\n# A\n\nсм. [b](b.md)\n'
B = '---\ntype: research\nstatus: idea\nupdated: 2026-01-02\nsummary: "Бета"\nconclusion: "c"\ndata: x\napplied_in: y\n---\n# B\n## Sub\n'


class Docs(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.addCleanup(self.p.cleanup)
        d = self.p.root / "docs"
        d.mkdir()
        (d / "a.md").write_text(A, encoding="utf-8")
        (d / "b.md").write_text(B, encoding="utf-8")

    def test_check_ok(self):
        out = self.p.ok("docs", "check")
        self.assertIn("ошибок 0", out)

    def test_check_errors(self):
        d = self.p.root / "docs"
        (d / "nofm.md").write_text("текст\n", encoding="utf-8")
        (d / "bad.md").write_text('---\ntype: bogus\nstatus: active\nsummary: "s"\n---\n[x](nope.md)\n', encoding="utf-8")
        code, out, err = self.p.run("docs", "check")
        self.assertEqual(code, 1)
        self.assertIn("nofm.md: нет frontmatter", out)
        self.assertIn("bogus", out)
        self.assertIn("битая ссылка nope.md", out)

    def test_exclude_archive(self):
        arch = self.p.root / "docs" / "archive"
        arch.mkdir()
        (arch / "old.md").write_text("без frontmatter\n", encoding="utf-8")
        self.assertIn("ошибок 0", self.p.ok("docs", "check"))

    def test_index(self):
        out = self.p.ok("docs", "index")
        self.assertIn("INDEX.md", out)
        idx = (self.p.root / "docs" / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("a.md", idx)
        self.assertIn("b.md", idx)
        self.assertTrue((self.p.root / "docs" / "registry" / "research.md").is_file())

    # docs index создаёт заготовку registry/findings.md (на неё ссылается INDEX.md) — check сразу чистый
    def test_check_after_index(self):
        self.p.ok("docs", "index")
        code, out, err = self.p.run("docs", "check")
        self.assertEqual(code, 0, out)
        f = self.p.root / "docs" / "registry" / "findings.md"
        self.assertTrue(f.is_file())
        f.write_text(f.read_text(encoding="utf-8") + "## core\n- вывод\n", encoding="utf-8")
        self.p.ok("docs", "index")  # не перезаписывает
        self.assertIn("вывод", self.p.ok("docs", "findings"))

    def test_no_status_message(self):
        (self.p.root / "docs" / "c.md").write_text('---\ntype: guide\nsummary: "s"\n---\n# C\n', encoding="utf-8")
        code, out, _ = self.p.run("docs", "check")
        self.assertEqual(code, 1)
        self.assertIn("c.md: нет status", out)
        self.assertNotIn("None", out)

    def test_find(self):
        self.assertIn("docs/a.md", self.p.ok("docs", "find", "альфа"))
        out = self.p.ok("docs", "find", "--type", "research")
        self.assertIn("docs/b.md", out)
        self.assertNotIn("docs/a.md", out)
        self.assertIn("docs/a.md", self.p.ok("docs", "find", "--module", "core"))
        self.assertIn("docs/b.md", self.p.ok("docs", "find", "--status", "idea"))

    def test_show(self):
        out = self.p.ok("docs", "show", "docs/b.md")
        self.assertIn("research", out)
        self.assertIn("Sub", out)

    def test_no_docs_dir(self):
        p = Project()
        self.addCleanup(p.cleanup)
        code, _, err = p.run("docs", "check")
        self.assertEqual(code, 1)
        self.assertIn("docs", err)


if __name__ == "__main__":
    unittest.main()
