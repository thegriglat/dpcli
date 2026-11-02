"""Frictions: a plan section named in a card is not found; reports written to a shared file reach the wrong task."""
import json
import unittest

from helpers import Project

PLAN = """# Plan
## 1. Goal
Ship it.
## 4. Tasks (PF-5)
### PF-5 Billing
Do billing.
## 5. Задачи
### DS-0 Дизайн
Сделать дизайн.
"""


def report(task):
    return {"id": task, "status": "done", "summary": "done", "commits": ["abc1234 work"],
            "checks": [{"name": "ok", "value": "1", "pass": True}]}


class PlanSections(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.addCleanup(self.p.cleanup)
        self.p.ok("module", "init", "pf", "--code", "PF")
        (self.p.root / "docs" / "plan" / "pf.md").write_text(PLAN, encoding="utf-8")

    def test_unquoted_multiword_section(self):
        self.assertIn("Do billing.", self.p.ok("plan", "pf", "4.", "Tasks", "(PF-5)"))

    def test_section_with_task_id_suffix(self):
        self.assertIn("Сделать дизайн.", self.p.ok("plan", "pf", "5. Задачи / DS-0"))
        self.assertIn("Do billing.", self.p.ok("plan", "pf", "4. Tasks (PF-5)"))

    def test_plan_edit_still_takes_target_and_section(self):
        self.p.ok("plan", "edit", "pf", "1. Goal", "--append", "Fast.")
        self.assertIn("Fast.", self.p.ok("plan", "pf", "1"))

    def test_plan_ref_checked_at_task_new(self):
        args = ["task", "new", "pf", "--type", "dp-engineer", "--title", "t", "--goal", "g", "--scope", "src", "--no-copy"]
        for bad in ("7. Nowhere", "7. Nowhere (x)", "Goal (1)"):
            code, _, err = self.p.run(*args, "--plan-ref", bad)
            self.assertEqual(code, 1, bad)
            self.assertIn("plan_ref", err)
        self.p.ok(*args, "--plan-ref", "4. Tasks (PF-5)")


class ReportFile(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.addCleanup(self.p.cleanup)
        self.p.ok("module", "init", "pf", "--code", "PF")
        for _ in range(2):
            self.p.ok("task", "new", "pf", "--type", "dp-engineer", "--title", "t", "--goal", "g", "--scope", "src",
                      "--check", "ok", "true", "exit=0", "--no-copy")

    def test_default_per_task_path(self):
        f = self.p.root / "build" / "dpcli" / "PF-1" / "report.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(report("PF-1")))
        self.assertIn("PF-1: report done", self.p.ok("report", "PF-1"))
        self.assertIn("build/dpcli/PF-1/report.json", self.p.ok("task", "brief", "PF-1"))

    def test_no_file_and_no_stdin_fails_fast(self):
        code, _, err = self.p.run("report", "PF-1", timeout=10)
        self.assertEqual(code, 1)
        self.assertIn("no report file", err)

    def test_explicit_input_beats_stale_task_file(self):
        f = self.p.root / "build" / "dpcli" / "PF-1" / "report.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({**report("PF-1"), "summary": "STALE"}))
        fresh = self.p.root / "fresh.json"
        fresh.write_text(json.dumps({**report("PF-1"), "summary": "FRESH"}))
        with open(fresh) as stdin:
            import subprocess, sys
            subprocess.run([sys.executable, self.p.cli, "report", "PF-1"], cwd=self.p.root, env=self.p.env(),
                           stdin=stdin, capture_output=True, check=True)
        self.assertIn("FRESH", self.p.ok("report", "PF-1", "--show"))

    def test_report_of_another_task_rejected(self):
        code, _, err = self.p.run("report", "PF-2", "-", input=json.dumps(report("PF-1")))
        self.assertEqual(code, 1)
        self.assertIn("PF-1", err)


if __name__ == "__main__":
    unittest.main()
