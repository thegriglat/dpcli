import sys
import unittest
from pathlib import Path

from helpers import DIST, LIB

sys.path.insert(0, str(LIB))
from dpcli import yamlmini  # noqa: E402


def L(text):
    return yamlmini.loads(text, use_pyyaml=False)


class Scalars(unittest.TestCase):
    def test_types(self):
        d = L("a: 1\nb: -2.5\nc: true\nd: false\ne: null\nf: ~\ng: text here\nh:\n")
        self.assertEqual(d, {"a": 1, "b": -2.5, "c": True, "d": False, "e": None, "f": None, "g": "text here", "h": None})

    def test_quotes(self):
        d = L("a: \"x: y # not comment\"\nb: 'it''s'\nc: \"12\"\nd: '#x'\n")
        self.assertEqual(d, {"a": "x: y # not comment", "b": "it's", "c": "12", "d": "#x"})

    def test_comments(self):
        d = L("# top\na: 1  # tail\nb: x#y\n\n# end\n")
        self.assertEqual(d, {"a": 1, "b": "x#y"})

    def test_unclosed_quote(self):
        with self.assertRaises(yamlmini.YamlError):
            L("a: 'oops\n")


class Structures(unittest.TestCase):
    def test_nested(self):
        d = L("a:\n  b:\n    c: 1\n  d: 2\ne: 3\n")
        self.assertEqual(d, {"a": {"b": {"c": 1}, "d": 2}, "e": 3})

    def test_lists(self):
        self.assertEqual(L("a:\n  - x\n  - 2\n  - true\n"), {"a": ["x", 2, True]})
        self.assertEqual(L("a:\n- x\n- y\nb: 1\n"), {"a": ["x", "y"], "b": 1})

    def test_list_of_dicts(self):
        d = L("a:\n  - name: x\n    n: 1\n  - name: y\n    sub:\n      k: v\n")
        self.assertEqual(d, {"a": [{"name": "x", "n": 1}, {"name": "y", "sub": {"k": "v"}}]})

    def test_inline(self):
        d = L("a: [x, 'y z', 3]\nb: {k: v, n: 1}\nc: []\nd: {}\ne: [[1, 2], {a: b}]\n")
        self.assertEqual(d, {"a": ["x", "y z", 3], "b": {"k": "v", "n": 1}, "c": [], "d": {}, "e": [[1, 2], {"a": "b"}]})

    def test_block_strings(self):
        d = L("a: |\n  l1\n  l2\nb: >\n  f1\n  f2\nc: 1\n")
        self.assertEqual(d["a"], "l1\nl2\n")
        self.assertEqual(d["b"], "f1 f2\n")
        self.assertEqual(d["c"], 1)

    def test_empty(self):
        self.assertIn(L(""), (None, {}))


class RealFiles(unittest.TestCase):
    def test_example_config(self):
        d = L((DIST / "dpcli.example.yml").read_text(encoding="utf-8"))
        self.assertEqual(d["main_branch"], "main")
        self.assertEqual(d["module_branch"], "feature/{module}")
        self.assertEqual(d["checks"]["log_dir"], "build/dpcli")
        self.assertEqual(d["reserved_codes"], [])
        self.assertEqual(d["gc"]["ignore_dirs"], ["build", "__pycache__"])
        self.assertEqual(d["sem"]["globs"], ["docs/**/*.md", "CHANGELOG.md"])
        self.assertEqual(d["docs"]["exclude"], ["docs/archive/**"])
        self.assertEqual(d["jobs"]["tmux_session"], "dp")

    def test_agents_frontmatter(self):
        files = sorted((DIST / "agents").glob("*.md"))
        self.assertTrue(files)
        for f in files:
            meta, body = yamlmini.frontmatter(f.read_text(encoding="utf-8"))
            self.assertTrue(meta.get("name"), f)
            self.assertTrue(meta.get("description"), f)
            self.assertIn(meta.get("dpcli_role"), ("coordinator", "executor", "reviewer", "status"), f)
            self.assertTrue(body.strip(), f)

    def test_frontmatter_none(self):
        self.assertEqual(yamlmini.frontmatter("text\n"), ({}, "text\n"))

    def test_frontmatter_unclosed(self):
        with self.assertRaises(yamlmini.YamlError):
            yamlmini.frontmatter("---\na: 1\n")

    def test_frontmatter_body(self):
        meta, body = yamlmini.frontmatter("---\na: 1\ntools: [Read, Bash]\n---\nBody\n")
        self.assertEqual(meta, {"a": 1, "tools": ["Read", "Bash"]})
        self.assertEqual(body, "Body\n")


if __name__ == "__main__":
    unittest.main()
