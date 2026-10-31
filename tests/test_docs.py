import unittest

from helpers import Project

A = '---\ntype: guide\nstatus: active\nmodule: core\nupdated: 2026-01-01\nsummary: "About alpha"\n---\n# A\n\nsee [b](b.md)\n'
B = '---\ntype: research\nstatus: idea\nupdated: 2026-01-02\nsummary: "Beta"\nconclusion: "c"\ndata: x\napplied_in: y\n---\n# B\n## Sub\n'


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
        self.assertIn("errors 0", out)

    def test_check_errors(self):
        d = self.p.root / "docs"
        (d / "nofm.md").write_text("text\n", encoding="utf-8")
        (d / "bad.md").write_text('---\ntype: bogus\nstatus: active\nsummary: "s"\n---\n[x](nope.md)\n', encoding="utf-8")
        code, out, err = self.p.run("docs", "check")
        self.assertEqual(code, 1)
        self.assertIn("nofm.md: no frontmatter", out)
        self.assertIn("bogus", out)
        self.assertIn("broken link nope.md", out)

    def test_exclude_archive(self):
        arch = self.p.root / "docs" / "archive"
        arch.mkdir()
        (arch / "old.md").write_text("no frontmatter\n", encoding="utf-8")
        self.assertIn("errors 0", self.p.ok("docs", "check"))

    def test_index(self):
        out = self.p.ok("docs", "index")
        self.assertIn("INDEX.md", out)
        idx = (self.p.root / "docs" / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("a.md", idx)
        self.assertIn("b.md", idx)
        self.assertTrue((self.p.root / "docs" / "registry" / "research.md").is_file())

    # docs index creates a registry/findings.md stub (INDEX.md links to it), so check is clean right away
    def test_check_after_index(self):
        self.p.ok("docs", "index")
        code, out, err = self.p.run("docs", "check")
        self.assertEqual(code, 0, out)
        f = self.p.root / "docs" / "registry" / "findings.md"
        self.assertTrue(f.is_file())
        f.write_text(f.read_text(encoding="utf-8") + "## core\n- finding\n", encoding="utf-8")
        self.p.ok("docs", "index")  # does not overwrite
        self.assertIn("finding", self.p.ok("docs", "findings"))

    def test_no_status_message(self):
        (self.p.root / "docs" / "c.md").write_text('---\ntype: guide\nsummary: "s"\n---\n# C\n', encoding="utf-8")
        code, out, _ = self.p.run("docs", "check")
        self.assertEqual(code, 1)
        self.assertIn("c.md: no status", out)
        self.assertNotIn("None", out)

    def test_find(self):
        self.assertIn("docs/a.md", self.p.ok("docs", "find", "alpha"))
        out = self.p.ok("docs", "find", "--type", "research")
        self.assertIn("docs/b.md", out)
        self.assertNotIn("docs/a.md", out)
        self.assertIn("docs/a.md", self.p.ok("docs", "find", "--module", "core"))
        self.assertIn("docs/b.md", self.p.ok("docs", "find", "--status", "idea"))

    def test_show(self):
        out = self.p.ok("docs", "show", "docs/b.md")
        self.assertIn("research", out)
        self.assertIn("Sub", out)

    # ---------- docs section ----------
    def _sec_doc(self):
        (self.p.root / "docs" / "s.md").write_text(
            '---\ntype: guide\nstatus: active\nsummary: "s"\n---\n# Title\nintro\n## Results\nresults-text\n### Details\ndetail\n'
            '## Results of run\nsecond\n## Data\ntable\n```\n# not a heading\n```\n', encoding="utf-8")

    def test_section_toc(self):
        self._sec_doc()
        out = self.p.ok("docs", "section", "docs/s.md")
        self.assertIn("  1 Title", out)
        self.assertIn("  2   Results", out)
        self.assertIn("Data", out)
        self.assertNotIn("not a heading", out)
        self.assertNotIn("type:", out)

    def test_section_by_number_and_text(self):
        self._sec_doc()
        out = self.p.ok("docs", "section", "docs/s.md", "2")
        self.assertTrue(out.startswith("## Results\n"), out)
        self.assertIn("detail", out)  # with subsections
        self.assertNotIn("second", out)
        self.assertNotIn("summary", out)
        out = self.p.ok("docs", "section", "docs/s.md", "dat")
        self.assertIn("table", out)
        self.assertIn("# not a heading", out)
        self.assertNotIn("results-text", out)
        # exact match beats prefix; path#section form
        self.assertIn("results-text", self.p.ok("docs", "section", "docs/s.md", "results"))
        self.assertIn("second", self.p.ok("docs", "section", "docs/s.md#Results of run"))

    def test_section_ambiguous_and_missing(self):
        self._sec_doc()
        code, out, _ = self.p.run("docs", "section", "docs/s.md", "Res")
        self.assertEqual(code, 1)
        self.assertIn("ambiguous", out)
        self.assertIn("  2", out)
        self.assertIn("  4", out)
        code, _, err = self.p.run("docs", "section", "docs/s.md", "no such")
        self.assertEqual(code, 1)
        self.assertIn("not found", err)

    # ---------- size and summary ----------
    def _big(self, path, extra=""):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'---\ntype: guide\nstatus: active\nsummary: "s"\n{extra}---\n' + "x" * 3000 + "\n", encoding="utf-8")

    def test_size_error_and_warn(self):
        p = Project({"docs": {"max_kb": 2, "exclude": []}})
        self.addCleanup(p.cleanup)
        self._big(p.root / "docs" / "big.md")
        self._big(p.root / "docs" / "archive" / "old.md")
        self._big(p.root / "docs" / "gen.md", "generated: true\n")
        code, out, _ = p.run("docs", "check")
        self.assertEqual(code, 1, out)
        self.assertIn("ERROR    docs/big.md", out)
        self.assertIn("split into section files or move data out", out)
        self.assertNotIn("old.md: 3 KB", out)
        self.assertNotIn("gen.md: 3 KB", out)
        q = Project({"docs": {"max_kb": 2, "max_kb_mode": "warn"}})
        self.addCleanup(q.cleanup)
        self._big(q.root / "docs" / "big.md")
        out = q.ok("docs", "check")
        self.assertIn("warning  docs/big.md", out)

    def test_summary_rules(self):
        d = self.p.root / "docs"
        (d / "long.md").write_text('---\ntype: guide\nstatus: active\nsummary: "' + "a" * 141 + '"\n---\n', encoding="utf-8")
        (d / "todo.md").write_text('---\ntype: guide\nstatus: active\nsummary: "TODO"\n---\n', encoding="utf-8")
        (d / "none.md").write_text('---\ntype: guide\nstatus: active\n---\n', encoding="utf-8")
        code, out, _ = self.p.run("docs", "check")
        self.assertEqual(code, 1)
        self.assertIn("long.md: summary 141 chars > 140", out)
        self.assertIn("todo.md: summary TODO — fill in summary: conclusion/purpose in one line", out)
        self.assertIn("none.md: no summary", out)
        p = Project({"docs": {"summary_max": 200}})
        self.addCleanup(p.cleanup)
        (p.root / "docs").mkdir()
        (p.root / "docs" / "long.md").write_text((d / "long.md").read_text(encoding="utf-8"), encoding="utf-8")
        p.ok("docs", "check")

    def test_init_summary_todo(self):
        (self.p.root / "docs" / "raw.md").write_text("# Raw\n\nA long first paragraph of text that used to become the summary.\n",
                                                     encoding="utf-8")
        self.p.ok("docs", "init")
        txt = (self.p.root / "docs" / "raw.md").read_text(encoding="utf-8")
        self.assertIn('summary: "TODO"', txt)
        self.assertNotIn("A long first paragraph of text that", txt.split("---")[1])
        code, out, _ = self.p.run("docs", "check")
        self.assertEqual(code, 1)
        self.assertIn("raw.md: summary TODO", out)

    # ---------- compact index, registries ----------
    def test_index_compact(self):
        arch = self.p.root / "docs" / "archive"
        arch.mkdir()
        (arch / "x.md").write_text("old\n", encoding="utf-8")
        (arch / "y.md").write_text("old\n", encoding="utf-8")
        self.p.ok("docs", "index")
        idx = (self.p.root / "docs" / "INDEX.md").read_text(encoding="utf-8")
        body = idx.split("---", 2)[2]
        self.assertNotRegex(body, r"(?m)^\|")  # no tables
        self.assertIn("- [docs/a.md](a.md) — About alpha\n", idx)
        self.assertIn("- [docs/b.md](b.md) — Beta [idea]", idx)
        self.assertIn("## System guides (guide)", idx)
        self.assertIn("archive: 2 docs — `.dpcli/dpcli docs find --status closed`", idx)
        self.assertNotIn("x.md", idx)
        for w in ("docs find", "docs section", "docs findings"):
            self.assertIn(w, idx)
        self.assertFalse((self.p.root / "docs" / "registry" / "decisions.md").exists())
        self.assertTrue((self.p.root / "docs" / "registry" / "contracts.md").is_file())
        self.assertIn("- [docs/b.md](../b.md) — c", (self.p.root / "docs" / "registry" / "research.md").read_text(encoding="utf-8"))
        self.assertEqual(self.p.run("docs", "check")[0], 0)

    def test_registries_config(self):
        p = Project({"docs": {"registries": ["decisions"]}})
        self.addCleanup(p.cleanup)
        (p.root / "docs").mkdir()
        (p.root / "docs" / "a.md").write_text(A, encoding="utf-8")
        out = p.ok("docs", "index")
        self.assertIn("decisions", out)
        reg = p.root / "docs" / "registry"
        self.assertTrue((reg / "decisions.md").is_file())
        self.assertFalse((reg / "research.md").exists())

    def test_find_format(self):
        out = self.p.ok("docs", "find", "alpha")
        self.assertEqual(out.strip(), "docs/a.md — About alpha")
        self.assertIn("docs/a.md — guide — active — About alpha", self.p.ok("docs", "find", "--long", "alpha"))
        arch = self.p.root / "docs" / "archive"
        arch.mkdir()
        (arch / "old.md").write_text('---\ntype: plan\nstatus: closed\nsummary: "old"\n---\n', encoding="utf-8")
        self.assertNotIn("old.md", self.p.ok("docs", "find"))
        self.assertIn("docs/archive/old.md — old", self.p.ok("docs", "find", "--status", "closed"))

    def test_no_docs_dir(self):
        p = Project()
        self.addCleanup(p.cleanup)
        code, _, err = p.run("docs", "check")
        self.assertEqual(code, 1)
        self.assertIn("docs", err)


if __name__ == "__main__":
    unittest.main()
