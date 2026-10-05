"""Полный цикл: module new -> task new -> report -> accept -> review -> merge -> gc (последовательные шаги одного проекта)."""
import json
import unittest

from helpers import Project, git


def report(checks, status="done"):
    return json.dumps({"status": status, "summary": "сделано", "commits": ["abc1234 работа"],
                       "checks": [{"name": n, "value": "1", "pass": True} for n in checks]})


class Flow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = Project()
        cls.mc = cls.p.copies / "proj-demo"

    @classmethod
    def tearDownClass(cls):
        cls.p.cleanup()

    def mk_task(self, typ, *extra):
        out = self.p.ok("task", "new", "demo", "--type", typ, "--title", f"Задача {typ}", "--goal", "цель", *extra)
        tid = out.split(":")[0]
        tc = self.p.copies / f"proj-demo-{tid}"  # копию и ветку задачи создаёт task new
        self.assertEqual(git("rev-parse", "--abbrev-ref", "HEAD", cwd=tc), f"demo/{tid}")
        (tc / f"{tid}.txt").write_text("x", encoding="utf-8")
        self.p.commit_all(f"работа {tid}", cwd=tc)
        return tid, tc

    def test_full_cycle(self):
        p = self.p
        # module new
        out = p.ok("module", "new", "demo", "--code", "DM")
        self.assertIn("feature/demo", out)
        self.assertTrue(self.mc.is_dir())
        self.assertEqual(git("rev-parse", "--abbrev-ref", "HEAD", cwd=self.mc), "feature/demo")
        self.assertEqual(p.run("module", "new", "demo", "--code", "DM")[0], 1)  # повтор — ошибка

        # task new с проверками (engineer: review=true; writer: нет)
        eng, eng_c = self.mk_task("dp-engineer", "--scope", "*.txt", "--check", "echo", "echo hi", "re:hi",
                                  "--check", "bad", "false", "exit=0")
        wri, wri_c = self.mk_task("dp-writer", "--check", "ok", "true", "exit=0")
        self.assertEqual((eng, wri), ("DM-1", "DM-2"))
        show = p.ok("task", "show", eng)
        for s in (eng, "Задача dp-engineer", "echo", "bad", "demo/DM-1"):
            self.assertIn(s, show)
        self.assertEqual(json.loads(p.ok("task", "show", eng, "--json"))["accept"][0]["name"], "echo")

        # started
        p.ok("event", eng, "started")
        self.assertIn("started", p.ok("log", eng))

        # report: невалидные отклоняются, валидный принимается; шаблон
        tpl = json.loads(p.ok("report", "--template"))
        self.assertEqual(set(tpl) >= {"status", "summary", "commits", "checks"}, True)
        for bad in ('{"status": "wat"}', "не json", report(["echo"])):  # последний: нет результата проверки bad
            self.assertNotEqual(p.run("report", eng, input=bad)[0], 0, bad)
        p.ok("report", eng, input=report(["echo", "bad"]))
        self.assertIn("done", p.ok("report", eng, "--show"))

        # accept: FAIL при падающей проверке
        code, out, _ = p.run("accept", eng)
        self.assertEqual(code, 1)
        self.assertIn("FAIL bad", out)
        self.assertIn("PASS echo", out)
        self.assertIn("checked", p.ok("log", eng))
        # чиним карточку -> PASS; для review=true статус checked, не accepted
        p.ok("task", "set", eng, "--drop-check", "bad")
        out = p.ok("accept", eng)
        self.assertIn("PASS echo", out)
        self.assertIn("dp-reviewer", out)
        self.assertNotIn("accepted", p.ok("log", eng, "-n", "1"))
        self.assertIn("checked", p.ok("status"))

        # review rework без причины/некорректно -> отказ; accept -> ok
        self.assertNotEqual(p.run("review", eng, "--verdict", "accept")[0], 0)
        p.ok("review", eng, "--verdict", "accept", "--note", "всё хорошо")
        self.assertIn("accept", p.ok("review", eng, "--show"))
        p.ok("event", eng, "accepted")
        self.assertIn("accepted", p.ok("log", eng, "-n", "1"))

        # writer: review=false -> сразу accepted
        p.ok("report", wri, input=report(["ok"]))
        p.ok("accept", wri)
        self.assertIn("accepted", p.ok("log", wri, "-n", "1"))

        # status/log/render/digest/search содержат ID
        self.assertIn(eng, p.ok("status", "--full"))
        self.assertIn(eng, p.ok("log", "demo"))
        self.assertIn(eng, p.ok("render", "demo", "--out", "-"))
        self.assertIn(eng, p.ok("search", "Задача dp-engineer"))

        # merge веток задач в модуль, модуля в main
        out = p.ok("merge", f"demo/{eng}", "--into", "feature/demo", cwd=self.mc)
        self.assertIn("слияние", out)
        self.assertIn("уже влита", p.ok("merge", f"demo/{eng}", "--into", "feature/demo", cwd=self.mc))
        p.ok("merge", f"demo/{wri}", "--into", "feature/demo", cwd=self.mc)
        self.assertTrue((self.mc / f"{eng}.txt").is_file())
        self.assertFalse((p.root / f"{eng}.txt").exists())
        p.ok("merge", "demo")
        self.assertTrue((p.root / f"{eng}.txt").is_file())
        self.assertIn(eng, p.ok("digest"))

        # gc: список, потом удаление
        out = p.ok("gc")
        for b in ("feature/demo", f"demo/{eng}", f"demo/{wri}"):
            self.assertIn(b, out)
        self.assertTrue(self.mc.exists())
        p.ok("gc", "--remove")
        self.assertFalse(self.mc.exists())
        self.assertNotIn("demo/", git("branch", "--format=%(refname:short)", cwd=p.root).replace("feature/demo", ""))
        self.assertIn("влитых веток нет", p.ok("gc"))
        # журнал остался в main
        self.assertIn(eng, p.ok("log", "demo"))

    # было: `search AA-1` (по ID задачи) ничего не находил
    def test_search_by_id(self):
        p = Project()
        self.addCleanup(p.cleanup)
        p.ok("module", "new", "aa", "--code", "AA")
        p.ok("task", "new", "aa", "--type", "dp-writer", "--title", "Заголовок")
        self.assertIn("AA-1", p.ok("search", "AA-1"))


class Questions(unittest.TestCase):
    def test_ask_answer_inbox(self):
        p = Project()
        self.addCleanup(p.cleanup)
        p.ok("module", "new", "aa", "--code", "AA")
        self.assertIn("Q1", p.ok("decide", "aa", "Брать A или B?", "--ask"))
        self.assertIn("Брать A или B?", p.ok("questions"))
        self.assertIn("Q1", p.ok("status"))
        self.assertIn("Брать A или B?", p.ok("inbox", "aa"))
        p.ok("answer", "Q1", "берём B")
        self.assertIn("открытых вопросов нет", p.ok("questions"))
        self.assertIn("берём B", p.ok("questions", "--all"))
        self.assertIn("берём B", p.ok("inbox", "aa", "--by", "other"))
        self.assertNotEqual(p.run("answer", "Q9", "нет такого")[0], 0)
        p.ok("decide", "aa", "Решили так", "--why", "потому")
        self.assertIn("Решили так", p.ok("log", "aa"))

    def test_task_note_and_set(self):
        p = Project()
        self.addCleanup(p.cleanup)
        p.ok("module", "new", "aa", "--code", "AA")
        p.ok("task", "new", "aa", "--type", "dp-writer", "--title", "T")
        p.ok("task", "note", "AA-1", "новое правило")
        self.assertIn("новое правило", p.ok("task", "show", "AA-1"))
        p.ok("task", "set", "AA-1", "goal=другая цель")
        self.assertIn("другая цель", p.ok("task", "show", "AA-1"))
        self.assertNotEqual(p.run("task", "set", "AA-1", "type=dp-reviewer")[0], 0)
        self.assertNotEqual(p.run("task", "show", "ZZ-9")[0], 0)


class AcceptExpect(unittest.TestCase):
    def test_expect_kinds(self):
        p = Project()
        self.addCleanup(p.cleanup)
        p.ok("module", "new", "aa", "--code", "AA")
        p.ok("task", "new", "aa", "--type", "dp-writer", "--title", "T",
             "--check", "re", "echo hello", "re:hel+o",
             "--check", "notre", "echo hello", "!re:bye",
             "--check", "num", "echo score 5.5", "num:score ([\\d.]+) >=5",
             "--check", "exit3", "exit 3", "exit=3")
        code, out, _ = p.run("accept", "AA-1")
        self.assertEqual(code, 0, out)
        p.ok("task", "set", "AA-1", "--check", "numbad", "echo score 2", "num:score ([\\d.]+) >=5")
        self.assertEqual(p.run("accept", "AA-1")[0], 1)

    # непонятный expect — отказ уже в task new / task set, а не в accept
    def test_bad_expect_rejected_early(self):
        p = Project()
        self.addCleanup(p.cleanup)
        p.ok("module", "new", "aa", "--code", "AA")
        code, _, err = p.run("task", "new", "aa", "--type", "dp-writer", "--check", "x", "true", "garbage")
        self.assertNotEqual(code, 0)
        self.assertIn("garbage", err)
        self.assertFalse(list((p.copies / "proj-aa" / "docs" / "plan" / "aa" / "tasks").glob("*.json")))
        p.ok("task", "new", "aa", "--type", "dp-writer", "--check", "x", "true", "exit=0")
        self.assertNotEqual(p.run("task", "set", "AA-1", "--check", "y", "true", "num:x")[0], 0)
        self.assertNotEqual(p.run("task", "set", "AA-1", "--check", "y", "true", "re:(")[0], 0)
        self.assertIn('"x"', p.ok("task", "show", "AA-1", "--json"))
        self.assertNotIn('"y"', p.ok("task", "show", "AA-1", "--json"))

    def test_tests_check_needs_template(self):
        p = Project({"checks": {"tests": "echo running {filter}"}})
        self.addCleanup(p.cleanup)
        p.ok("module", "new", "aa", "--code", "AA")
        p.ok("task", "new", "aa", "--type", "dp-writer", "--title", "T", "--test", "foo")
        self.assertEqual(p.run("accept", "AA-1")[0], 0)
        p2 = Project()
        self.addCleanup(p2.cleanup)
        p2.ok("module", "new", "aa", "--code", "AA")
        p2.ok("task", "new", "aa", "--type", "dp-writer", "--title", "T", "--test", "foo")
        code, out, _ = p2.run("accept", "AA-1")
        self.assertEqual(code, 1)
        self.assertIn("недоступна", out)


class Jobs(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.addCleanup(self.p.cleanup)

    def test_job_ok(self):
        self.p.ok("job", "start", "j1", "20", "echo", "hello")
        out = self.p.ok("job", "wait", "j1", "20")
        self.assertIn("код 0", out)
        self.assertIn("hello", out)
        self.assertIn("j1", self.p.ok("job", "status"))

    def test_job_fail_code(self):
        self.p.ok("job", "start", "j2", "20", "bash", "-c", "echo boom; exit 3")
        code, out, _ = self.p.run("job", "wait", "j2", "20")
        self.assertNotEqual(code, 0)
        self.assertIn("boom", out)

    def test_job_timeout(self):
        self.p.ok("job", "start", "j3", "1", "sleep", "30")
        code, out, err = self.p.run("job", "wait", "j3", "10", timeout=40)
        self.assertNotEqual(code, 0)
        self.p.run("job", "stop", "j3")

    def test_lock(self):
        self.assertIn("свободен", self.p.ok("lock", "status"))
        self.assertIn("locked", self.p.ok("lock", "cpu", "me", "--", "echo", "locked"))
        self.assertIn("свободен", self.p.ok("lock", "status"))

    def test_accept_bg(self):
        self.p.ok("module", "new", "aa", "--code", "AA")
        self.p.ok("task", "new", "aa", "--type", "dp-writer", "--title", "T", "--check", "c", "true", "exit=0")
        self.p.ok("accept", "AA-1", "--bg", "--no-tmux")
        self.p.ok("job", "wait", "dp-accept-AA-1", "30")
        self.assertIn("accepted", self.p.ok("log", "AA-1"))


if __name__ == "__main__":
    unittest.main()
