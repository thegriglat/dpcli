"""task show prints addenda in full: executors must not miss instructions added after the brief."""
import unittest

from helpers import Project


class TaskShow(unittest.TestCase):
    def test_long_addendum_not_truncated(self):
        p = Project()
        self.addCleanup(p.cleanup)
        p.ok("module", "init", "web", "--code", "WB")
        p.ok("task", "new", "web", "--type", "dp-engineer", "--title", "t", "--goal", "g", "--scope", "src", "--no-copy")
        note = "Use the shared fixture. " * 30 + "THE END"
        p.ok("task", "note", "WB-1", note)
        out = p.ok("task", "show", "WB-1")
        self.assertIn("THE END", out)


if __name__ == "__main__":
    unittest.main()
