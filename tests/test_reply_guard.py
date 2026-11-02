"""SubagentStop hook reply_guard: dpcli agents answer with one protocol line; a wrong reply is sent back once."""
import json
import subprocess
import sys
import unittest

from helpers import DIST, Project

GUARD = DIST / "hooks" / "reply_guard.py"


class ReplyGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = Project()
        cls.p.ok("init")

    @classmethod
    def tearDownClass(cls):
        cls.p.cleanup()

    def stop(self, agent, msg, active=False):
        data = {"hook_event_name": "SubagentStop", "agent_type": agent, "last_assistant_message": msg,
                "stop_hook_active": active, "cwd": str(self.p.root)}
        r = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(data), capture_output=True, text=True,
                           env=self.p.env(), timeout=30)
        return r.returncode, r.stderr

    def test_protocol_lines_pass(self):
        for agent, msg in (("dp-engineer", "PF-1 reported"), ("dp-engineer", "PF-2a blocked: no access to the db"),
                           ("dp-writer", "DS-P3 contract: add field x"), ("dp-reviewer", "PF-1 review rework 3"),
                           ("dp-reviewer", "`PF-1 review accept`"), ("dp-coordinator", "billing: wave 2 done"),
                           ("dp-coordinator", "billing done"), ("dp-engineer", "PF-1: which table holds tariffs?")):
            self.assertEqual(self.stop(agent, msg)[0], 0, (agent, msg))

    def test_long_or_wrong_replies_sent_back_once(self):
        for agent, msg in (("dp-engineer", "PF-1 reported\n\nI changed a.py and b.py, all tests pass."),
                           ("dp-engineer", "Done! The task is complete."), ("dp-reviewer", "PF-1 looks good"),
                           ("dp-coordinator", "Here is a summary of the module:\n- a\n- b")):
            code, err = self.stop(agent, msg)
            self.assertEqual(code, 2, (agent, msg))
            self.assertIn("one protocol line", err)
            self.assertEqual(self.stop(agent, msg, active=True)[0], 0)  # the retry is not blocked again

    def test_other_agents_and_garbage_pass(self):
        self.assertEqual(self.stop("Explore", "a long free-form\nreport")[0], 0)
        self.assertEqual(self.stop("dp-engineer", "")[0], 0)  # nothing to judge
        self.assertEqual(self.stop("dp-status", "status:\n- x")[0], 0)  # no protocol line for status
        r = subprocess.run([sys.executable, str(GUARD)], input="nope", capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
