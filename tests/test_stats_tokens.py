"""stats --tokens: what agents spent per module and task, read from Claude Code's subagent logs (their first message
is a dpcli brief, so the task ID is there)."""
import json
import re
import unittest

from helpers import Project


def turn(ctx, out):
    return {"type": "assistant", "message": {"usage": {"input_tokens": 0, "cache_read_input_tokens": ctx,
                                                       "cache_creation_input_tokens": 0, "output_tokens": out}}}


class StatsTokens(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.addCleanup(self.p.cleanup)
        self.p.ok("module", "init", "web", "--code", "WB")
        for _ in range(2):
            self.p.ok("task", "new", "web", "--type", "dp-engineer", "--title", "T", "--goal", "g", "--scope", "src",
                      "--check", "c", "true", "exit=0", "--no-copy")
        logs = self.p.tmp / "home" / ".claude" / "projects" / re.sub(r"[/_.]", "-", str(self.p.root)) / "s1" / "subagents"
        logs.mkdir(parents=True)

        def agent(name, first, turns):
            rows = [{"type": "user", "message": {"role": "user", "content": first}}] + turns
            (logs / f"agent-{name}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        agent("e1", "WB-1 dp-engineer: T\nCopy: …", [turn(100_000, 1_000), turn(200_000, 2_000)])
        agent("r1", "Review WB-1: no task copy …", [turn(50_000, 500)])
        agent("e2", "WB-2 dp-engineer: T", [turn(300_000, 3_000)])
        agent("c1", "Module web: copy …, branch feature/web. Plan: …", [turn(400_000, 4_000)])
        agent("x", "Translate the README", [turn(999_000, 9_000)])  # not dpcli work: not counted
        agent("c2", "Модуль web: копия …", [turn(25_000_000, 1)])  # the Russian protocol of older journals

    def test_tokens_per_module_role_and_task(self):
        out = self.p.ok("stats", "web", "--tokens")
        self.assertIn("tokens", out)
        self.assertIn("executors 0.6M (2)", out)
        self.assertIn("reviewers 0.05M (1)", out)
        self.assertIn("coordinators 25M (2)", out)  # 0.4M + 25M, printed without scientific notation
        self.assertIn("per task median 0.33M", out)  # WB-1: executor 0.3M + review 0.05M; WB-2: 0.3M


if __name__ == "__main__":
    unittest.main()
