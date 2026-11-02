"""Parallel copies: distinct check slots/ports; accept --baseline tells pre-existing failures from new ones."""
import subprocess
import unittest

from helpers import Project


class Slots(unittest.TestCase):
    def setUp(self):
        self.p = Project(config={"checks": {"env": {"DB": "app_{slot}", "APP_PORT": "{port}"}, "bg_after": 0}})
        self.addCleanup(self.p.cleanup)
        self.p.ok("module", "init", "pf", "--code", "PF")
        self.out = self.p.tmp / "seen"
        self.out.mkdir()
        for _ in range(3):  # each check records its env, then holds the slot a moment
            self.p.ok("task", "new", "pf", "--type", "dp-engineer", "--title", "t", "--goal", "g", "--scope", "src",
                      "--check", "env", f'echo "$DB $APP_PORT $DPCLI_SLOT" > {self.out}/$DPCLI_TASK; sleep 1', "exit=0",
                      "--no-copy")

    def test_parallel_accepts_get_distinct_slots(self):
        procs = [subprocess.Popen([self.p.cli, "accept", f"PF-{i}", "--dry", "--fg"], cwd=self.p.root, env=self.p.env(),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in (1, 2, 3)]
        for pr in procs:
            pr.communicate(timeout=60)
        seen = [(self.out / f"PF-{i}").read_text().split() for i in (1, 2, 3)]
        self.assertEqual(len({s[2] for s in seen}), 3, seen)
        for db, port, slot in seen:
            self.assertEqual(db, f"app_{slot}")
            self.assertEqual(port, str(20000 + 10 * int(slot)))
        self.p.ok("accept", "PF-1", "--dry", "--fg")  # released after exit: slot 0 again
        self.assertEqual((self.out / "PF-1").read_text().split()[2], "0")


class Baseline(unittest.TestCase):
    def setUp(self):
        self.p = Project(config={"checks": {"bg_after": 0}})
        self.addCleanup(self.p.cleanup)
        (self.p.root / "old_bug").write_text("x")  # fails on the base already
        self.p.commit_all("base with a known failure")
        self.p.ok("module", "new", "aa", "--code", "AA")
        self.mc = self.p.copies / "proj" / "aa"
        tid = self.p.ok("task", "new", "aa", "--type", "dp-writer", "--title", "T", "--scope", "src/",
                        "--check", "legacy", "test ! -e old_bug", "exit=0",
                        "--check", "mine", "test ! -e src/broken", "exit=0", cwd=self.mc).split(":")[0]
        self.tid, self.tc = tid, self.p.copies / "proj" / f"aa-{tid}"
        (self.tc / "src").mkdir()
        (self.tc / "src" / "broken").write_text("x")
        self.p.commit_all("break", cwd=self.tc)

    def test_marks_pre_existing_and_new(self):
        code, out, err = self.p.run("accept", self.tid, "--baseline", "--fg", cwd=self.tc)
        self.assertEqual(code, 1, out + err)  # still FAIL: baseline informs, does not excuse
        legacy = next(ln for ln in out.splitlines() if " legacy " in ln)
        mine = next(ln for ln in out.splitlines() if " mine " in ln)
        self.assertIn("FAIL too — pre-existing", legacy)
        self.assertIn("PASS — new", mine)
        self.assertIn("pre-existing on base", self.p.ok("log", self.tid, cwd=self.mc))
        wts = subprocess.run(["git", "worktree", "list"], cwd=self.p.root, capture_output=True, text=True).stdout
        self.assertNotIn("dpcli-base", wts)  # the temporary copy is removed


if __name__ == "__main__":
    unittest.main()
