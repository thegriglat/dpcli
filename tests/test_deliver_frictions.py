"""deliver keeps the module's frictions (they live in the journal it deletes) and links the plan only if it exists."""
import unittest

from helpers import Project


class DeliverFrictions(unittest.TestCase):
    def test_in_place_keeps_frictions_and_no_dangling_plan_link(self):
        p = Project()
        self.addCleanup(p.cleanup)
        p.ok("module", "init", "aa", "--code", "AA")
        p.ok("event", "aa", "note", "--note", "harness: zebra friction in the journal")
        p.commit_all("journal")
        p.ok("deliver", "aa", "--in-place")
        self.assertIn("zebra friction", p.ok("feedback", "--full"))
        self.assertIn("zebra friction", p.ok("feedback", "--full", "--module", "aa"))
        md = (p.root / "docs" / "plan" / "aa" / "summary.md").read_text()
        self.assertNotIn("docs/plan/aa.md", md.split("---")[1])  # no plan file: no related link to it
        _, out, err = p.run("docs", "check")
        self.assertNotIn("plan/aa/", out + err)


if __name__ == "__main__":
    unittest.main()
