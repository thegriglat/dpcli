"""Commands agents lacked and replaced with hand edits of the journal: amend a report, revoke a wrong event."""
import json
import unittest

from helpers import Project


class Base(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.addCleanup(self.p.cleanup)
        self.p.ok("module", "init", "pf", "--code", "PF")
        self.p.ok("task", "new", "pf", "--type", "dp-engineer", "--title", "t", "--goal", "g", "--scope", "src",
                  "--check", "ok", "true", "exit=0", "--no-copy")
        self.home = self.p.root / "docs" / "plan" / "pf"

    def events(self):
        return [json.loads(x) for x in (self.home / "events.jsonl").read_text().splitlines() if x.strip()]


class AmendReport(Base):
    def setUp(self):
        super().setUp()
        r = {"id": "PF-1", "status": "partial", "summary": "half", "commits": ["abc1234 work"],
             "checks": [{"name": "ok", "value": "0", "pass": False}], "not_done": ["the rest"]}
        self.p.ok("report", "PF-1", "-", input=json.dumps(r))

    def stored(self):
        return json.loads((self.home / "tasks" / "PF-1.report.json").read_text())

    def test_set_fields_lists_and_checks(self):
        out = self.p.ok("report", "PF-1", "--set", "status=done", "summary=all of it", "commits+=def5678 more",
                        "not_done-=the rest", 'checks+={"name": "ok", "value": "1", "pass": true}')
        self.assertIn("amended", out)
        r = self.stored()
        self.assertEqual(r["status"], "done")
        self.assertEqual(r["summary"], "all of it")
        self.assertEqual(r["commits"], ["abc1234 work", "def5678 more"])
        self.assertEqual(r["not_done"], [])
        self.assertEqual(r["checks"], [{"name": "ok", "value": "1", "pass": True}])  # replaced by name
        ev = self.events()[-1]
        self.assertEqual(ev["ev"], "reported")
        self.assertIn("amended: status, summary, commits, not_done, checks", ev["note"])
        self.assertIn("def5678", ev["commits"])
        self.assertIn("all of it", self.p.ok("report", "PF-1", "--show"))

    def test_validated_like_a_new_report(self):
        code, _, err = self.p.run("report", "PF-1", "--set", "status=done")  # check "ok" still failing is fine,
        self.assertEqual(code, 0, err)                                         # but status needs commits:
        code, _, err = self.p.run("report", "PF-1", "--set", "commits=[]")
        self.assertEqual(code, 1)
        self.assertIn("rejected", err)
        for bad in ("id=PF-2", "nonsense", "not_done-=missing"):
            self.assertEqual(self.p.run("report", "PF-1", "--set", bad)[0], 1, bad)

    def test_no_report_yet(self):
        self.p.ok("task", "new", "pf", "--type", "dp-engineer", "--title", "t", "--goal", "g", "--scope", "src",
                  "--check", "ok", "true", "exit=0", "--no-copy")
        code, _, err = self.p.run("report", "PF-2", "--set", "status=done")
        self.assertEqual(code, 1)
        self.assertIn("no report yet", err)


class Revoke(Base):
    def test_revoke_last_event_restores_state(self):
        self.p.ok("event", "PF-1", "started")
        self.p.ok("event", "PF-1", "blocked", "--note", "oops")
        self.assertIn("blocked", self.p.ok("status", "pf"))
        out = self.p.ok("event", "PF-1", "revoke", "--note", "blocked by mistake")
        self.assertIn("revoked blocked", out)
        st = self.p.ok("status", "pf")
        self.assertNotIn("blocked", st.split("PF-1", 1)[1].splitlines()[0])
        self.assertIn("started", st.split("PF-1", 1)[1].splitlines()[0])
        evs = self.events()
        self.assertEqual([e["ev"] for e in evs if e.get("task") == "PF-1"][-3:], ["started", "blocked", "revoked"])
        self.assertIn("revoked (main) blocked of", self.p.ok("log", "PF-1"))

    def test_revoke_of_kind_and_errors(self):
        self.p.ok("event", "PF-1", "started")
        self.p.ok("event", "PF-1", "accepted", "--note", "by report")
        self.p.ok("event", "PF-1", "revoke", "--of", "started", "--note", "never started")
        self.assertEqual(self.p.run("event", "PF-1", "revoke", "--of", "started", "--note", "again")[0], 1)
        self.assertEqual(self.p.run("event", "PF-1", "revoke")[0], 1)  # --note required
        self.assertEqual(self.p.run("event", "pf", "revoke", "--note", "x")[0], 1)  # a task, not a module
        self.assertIn("accepted", self.p.ok("status", "pf"))


class Adopt(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.addCleanup(self.p.cleanup)
        self.p.ok("module", "new", "aa", "--code", "AA")
        self.mc = self.p.copies / "proj" / "aa"
        self.p.ok("decide", "aa", "module copy question", "--ask", cwd=self.mc)  # Q1 in the module journal
        local = {"DPCLI_LOCAL": "1"}  # the main copy writes its own (stray) journal
        self.p.ok("decide", "aa", "stray question", "--ask", env=local)
        self.p.ok("answer", "aa/Q1", "stray answer", env=local)
        self.p.ok("event", "aa", "note", "--note", "stray note", env=local)
        self.p.commit_all("stray journal")
        self.stray = self.p.root / "docs" / "plan" / "aa"

    def test_merge_renumber_remove(self):
        dry = self.p.ok("adopt", "aa", "--dry")
        self.assertIn("Q1→Q2", dry)
        self.assertTrue(self.stray.is_dir())
        out = self.p.ok("adopt", "aa")
        self.assertIn("events +1, decisions +2", out)
        self.assertIn("staged: git rm", out)
        self.assertFalse(self.stray.exists())
        decs = [json.loads(x) for x in (self.mc / "docs" / "plan" / "aa" / "decisions.jsonl").read_text().splitlines()]
        q2 = next(d for d in decs if d.get("text") == "stray question")
        self.assertEqual(q2["id"], "Q2")
        self.assertEqual(next(d for d in decs if d.get("text") == "stray answer")["answers"], "Q2")
        self.assertIn("stray note", self.p.ok("log", "aa", cwd=self.mc))
        self.assertEqual(self.p.run("adopt", "aa")[0], 1)  # nothing left to adopt

    def test_in_the_module_copy_refused(self):
        code, _, err = self.p.run("adopt", "aa", cwd=self.mc)
        self.assertEqual(code, 1)
        self.assertIn("module journal itself", err)


if __name__ == "__main__":
    unittest.main()
