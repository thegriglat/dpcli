"""Self-improvement: feedback ledger (collect, dedup, clusters, triage, fix, regression after fix) and stats."""
import json
import unittest

from helpers import Project


def ev(t, task, kind, **kw):
    return json.dumps({"t": t, "by": "executor", "task": task, "ev": kind, **kw}, ensure_ascii=False)


class Feedback(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.addCleanup(self.p.cleanup)
        self.p.ok("module", "init", "web", "--code", "WB")
        home = self.p.root / "docs" / "plan" / "web"
        lines = [
            ev("2026-10-01T10:00:00", "WB-1", "created"),
            ev("2026-10-01T12:00:00", "WB-1", "reported", dp_feedback="accept --dry runs 10 min in foreground"),
            ev("2026-10-01T12:30:00", "WB-1", "reviewed", verdict="rework", issues={"major": 1}),
            ev("2026-10-01T13:00:00", "WB-1", "accepted", durs={"unit": 40, "e2e": 300}),
            ev("2026-10-02T10:00:00", "WB-2", "created"),
            ev("2026-10-02T11:00:00", "WB-2", "reported", dp_feedback="Accept --dry runs 10 min in foreground."),
            ev("2026-10-02T11:30:00", "WB-2", "reported", dp_feedback="task show truncates addenda"),
            ev("2026-10-02T12:00:00", "WB-2", "accepted", durs={"unit": 60, "e2e": 500}),
            ev("2026-10-02T12:10:00", None, "note", by="coordinator", note="harness: plan section with spaces not found → accept quotes"),
            ev("2026-10-02T12:20:00", None, "note", by="coordinator", note="status: 2 accepted"),
            ev("2026-10-03T09:00:00", "WB-3", "reported", dp_feedback="none"),
        ]
        (home / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_collect_dedup_and_group_unclustered(self):
        out = self.p.ok("feedback")
        self.assertIn("frictions 4", out)  # 3 unique + the duplicate; "none" and plain notes ignored
        self.assertRegex(out, r"accept\s+×2")  # case/punctuation-insensitive dedup, grouped by command
        self.assertIn("task show", out)
        self.assertIn("plan", out)
        self.assertNotIn("2 accepted", out)

    def test_list_feedback_is_one_item_per_entry(self):
        with (self.p.root / "docs" / "plan" / "web" / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(ev("2026-10-03T10:00:00", "WB-4", "reported", dp_feedback=["task show truncates addenda", "none"]) + "\n")
        self.assertIn("frictions 5", self.p.ok("feedback"))

    def test_show_lists_unique_texts_with_tasks(self):
        out = self.p.ok("feedback", "show", "accept")
        self.assertIn("×2", out)
        self.assertIn("WB-1", out)
        self.assertIn("WB-2", out)

    def test_triage_fix_and_regression(self):
        out = self.p.ok("feedback", "new", "Slow foreground accept", "--match", r"accept --dry", "--scope", "dpcli")
        self.assertIn("F-1", out)
        self.assertTrue((self.p.root / ".dpcli-local" / "feedback.jsonl").is_file())
        listed = self.p.ok("feedback")
        self.assertRegex(listed, r"F-1\s+×2\s+\[dpcli\] open")
        self.p.ok("feedback", "fix", "F-1", "--where", "dpcli v6", "--pr", "https://github.com/o/r/pull/7")
        self.assertRegex(self.p.ok("feedback"), r"F-1\s+×2\s+\[dpcli\] fixed")
        # the same friction reported after the fix → flagged
        home = self.p.root / "docs" / "plan" / "web"
        with open(home / "events.jsonl", "a", encoding="utf-8") as f:
            f.write(ev("2099-01-01T00:00:00", "WB-9", "reported", dp_feedback="accept --dry still slow") + "\n")
        self.assertIn("⚠1 after fix", self.p.ok("feedback"))
        self.p.ok("feedback", "wontfix", "F-1", "--why", "out of scope")
        self.assertRegex(self.p.ok("feedback", "--all"), r"F-1 .*wontfix")
        code, _, err = self.p.run("feedback", "new", "x", "--match", "(", "--scope", "dpcli")
        self.assertEqual(code, 1)
        self.assertIn("regex", err)

    def test_stats(self):
        out = self.p.ok("stats", "web")
        self.assertIn("tasks 3", out)
        self.assertIn("accepted 2", out)
        self.assertIn("rework 1", out)
        self.assertRegex(out, r"e2e 400/500")  # median/max seconds
        self.assertIn("frictions 4", out)


if __name__ == "__main__":
    unittest.main()
