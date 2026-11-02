import unittest

from helpers import Project


class SemDisabled(unittest.TestCase):
    """sem.enabled is false by default: search --sem and index -> exit 1; no Ollama needed."""

    def setUp(self):
        self.p = Project()
        self.addCleanup(self.p.cleanup)

    def test_search_sem_off(self):
        code, out, err = self.p.run("search", "--sem", "x")
        self.assertEqual(code, 1)
        self.assertIn("is off", err)

    def test_index_off(self):
        code, out, err = self.p.run("index")
        self.assertEqual(code, 1)
        self.assertIn("is off", err)

    def test_merge_main_does_not_index(self):
        self.p.ok("module", "new", "aa", "--code", "AA")
        out = self.p.ok("merge", "aa")
        self.assertIn("merged feature/aa", out)
        self.assertNotIn("индекс", out)
        self.assertFalse((self.p.cache / "sem").exists())

    def test_plain_search_works(self):
        self.p.ok("module", "new", "aa", "--code", "AA")
        self.p.ok("task", "new", "aa", "--type", "dp-writer", "--title", "Уникальное название")
        self.assertIn("AA-1", self.p.ok("search", "Уникальное"))


if __name__ == "__main__":
    unittest.main()
