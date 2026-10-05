"""Волна 3: бережный init, роли своих агентов, task brief, копия задачи из task new, проверка границ в accept."""
import json
import unittest

from helpers import Project, git

PROJ_AGENT = "---\nname: dp-engineer\ndescription: свой инженер проекта\nmodel: opus\n---\nМой текст\n"


class InitKeepsProject(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.addCleanup(self.p.cleanup)
        r = self.p.root
        (r / ".claude" / "agents").mkdir(parents=True)
        (r / ".claude" / "agents" / "dp-engineer.md").write_text(PROJ_AGENT, encoding="utf-8")
        (r / ".claude" / "skills" / "start-to-do").mkdir(parents=True)
        (r / ".claude" / "skills" / "start-to-do" / "SKILL.md").write_text("мой скилл\n", encoding="utf-8")
        (r / ".claude" / "dpcli-workflow.md").write_text("мой процесс\n", encoding="utf-8")

    def assert_kept(self):
        r = self.p.root
        self.assertEqual((r / ".claude" / "agents" / "dp-engineer.md").read_text(encoding="utf-8"), PROJ_AGENT)
        self.assertEqual((r / ".claude" / "skills" / "start-to-do" / "SKILL.md").read_text(encoding="utf-8"), "мой скилл\n")
        self.assertEqual((r / ".claude" / "dpcli-workflow.md").read_text(encoding="utf-8"), "мой процесс\n")

    def test_skips_project_files_even_with_force(self):
        out = self.p.ok("init")
        self.assertIn("агент проекта; роль: см. roles в конфиге", out)
        self.assertIn("скилл проекта", out)
        self.assert_kept()
        self.assertTrue((self.p.root / ".claude" / "agents" / "dp-writer.md").is_file())
        man = json.loads((self.p.root / ".claude" / ".dpcli-manifest.json").read_text())["files"]
        self.assertNotIn(".claude/agents/dp-engineer.md", man)
        self.p.ok("init", "--force")
        self.assert_kept()

    def test_force_only_for_manifest_files(self):
        self.p.ok("init")
        f = self.p.root / ".claude" / "agents" / "dp-writer.md"
        f.write_text(f.read_text(encoding="utf-8") + "правка\n", encoding="utf-8")
        self.assertIn("изменён вручную", self.p.ok("init"))
        self.assertIn("правка", f.read_text(encoding="utf-8"))
        self.p.ok("init", "--force")
        self.assertNotIn("правка", f.read_text(encoding="utf-8"))
        self.assert_kept()


class Roles(unittest.TestCase):
    def test_project_and_config_roles(self):
        p = Project({"roles": {"backend": {"role": "executor", "review": True}, "dp-writer": {"role": "status"}}})
        self.addCleanup(p.cleanup)
        d = p.root / ".claude" / "agents"
        d.mkdir(parents=True)
        (d / "backend.md").write_text("---\nname: backend\nmodel: sonnet\n---\nx\n", encoding="utf-8")
        (d / "fixer.md").write_text("---\nname: fixer\ndpcli_role: executor\n---\nx\n", encoding="utf-8")
        p.commit_all("агенты проекта")
        out = p.ok("agents")
        rows = {ln.split()[0]: ln.split() for ln in out.splitlines()[1:] if ln.strip()}
        self.assertEqual(rows["backend"][1:5], ["executor", "да", "config", "sonnet"])
        self.assertEqual(rows["fixer"][1:4], ["executor", "нет", "project"])
        self.assertEqual(rows["dp-writer"][1:4], ["status", "нет", "config"])
        self.assertEqual(rows["dp-engineer"][3], "dpcli")
        p.ok("module", "new", "aa", "--code", "AA")
        # агенты читаются от корня текущей копии: модуль-копия получила их из коммита
        p.ok("task", "new", "aa", "--type", "backend", "--title", "T", "--no-copy")
        code, _, err = p.run("task", "new", "aa", "--type", "dp-writer", "--title", "T", "--no-copy")
        self.assertNotEqual(code, 0)
        self.assertIn("не исполнитель", err)


class BriefAndCopy(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.addCleanup(self.p.cleanup)
        self.p.ok("module", "new", "aa", "--code", "AA")

    def new(self, *extra):
        return self.p.ok("task", "new", "aa", "--type", "dp-engineer", "--title", "Сделать X", *extra)

    def test_brief_refuses_incomplete(self):
        out = self.new("--no-copy")
        self.assertIn("brief откажет", out)
        code, _, err = self.p.run("task", "brief", "AA-1")
        self.assertEqual(code, 1)
        for k in ("goal", "scope", "accept"):
            self.assertIn(k, err)

    def test_brief_format(self):
        self.new("--goal", "цель", "--scope", "src/", "--dont-touch", "docs/contracts/", "--plan-ref", "§2",
                 "--check", "c", "true", "exit=0")
        out = self.p.ok("task", "brief", "AA-1")
        L = out.strip().splitlines()
        self.assertEqual(len(L), 6, out)
        self.assertEqual(L[0], "AA-1 dp-engineer: Сделать X")
        self.assertTrue(L[1].startswith("Копия: ") and "ветка: aa/AA-1 (от feature/aa)" in L[1])
        self.assertEqual(L[2], "Делать: .dpcli/dpcli task show AA-1  · план: .dpcli/dpcli plan aa §2")
        self.assertEqual(L[3], "Границы: только src/; не трогать docs/contracts/")
        self.assertTrue(L[4].startswith("Готово, когда: .dpcli/dpcli accept AA-1 --dry → PASS"))
        self.assertTrue(L[5].startswith("Ответ: одна строка «AA-1 reported»"))
        for ln in L:
            self.assertLessEqual(len(ln), 140, ln)  # формат строки «Готово, когда» задан — ~138
        rv = self.p.ok("task", "brief", "AA-1", "--review")
        self.assertTrue(rv.startswith("Ревью AA-1: копия "))
        self.assertIn(".dpcli/dpcli review AA-1 --verdict accept|rework --from r.json", rv)
        self.assertIn("«AA-1 review accept|rework <n>»", rv)

    def test_brief_long_scope_fits(self):
        args = []
        for i in range(30):
            args += ["--scope", f"src/very/long/path/module_{i}.py"]
        self.new("--goal", "g", "--check", "c", "true", "exit=0", "--no-copy", *args)
        line = [ln for ln in self.p.ok("task", "brief", "AA-1").splitlines() if ln.startswith("Границы")][0]
        self.assertLessEqual(len(line), 125)
        self.assertIn("task show", line)

    def test_task_new_creates_copy(self):
        out = self.new()
        tc = self.p.copies / "proj-aa-AA-1"
        self.assertIn("копия", out)
        self.assertEqual(git("rev-parse", "--abbrev-ref", "HEAD", cwd=tc), "aa/AA-1")
        # повтор (--force) — переиспользует копию
        self.assertIn("уже есть", self.p.ok("task", "new", "aa", "AA-1", "--type", "dp-engineer", "--force"))
        self.new("--no-copy")
        self.assertFalse((self.p.copies / "proj-aa-AA-2").exists())


class ScopeCheck(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.addCleanup(self.p.cleanup)
        self.p.ok("module", "new", "aa", "--code", "AA")

    def task(self, *extra):
        out = self.p.ok("task", "new", "aa", "--type", "dp-writer", "--title", "T", "--check", "c", "true", "exit=0", *extra)
        tid = out.split(":")[0]
        return tid, self.p.copies / f"proj-aa-{tid}"

    def write(self, tc, path, commit=True):
        f = tc / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x", encoding="utf-8")
        if commit:
            self.p.commit_all(path, cwd=tc)

    def test_in_scope_pass(self):
        tid, tc = self.task("--scope", "src/ — код модуля", "--scope", "*.md")
        self.write(tc, "src/a.py")
        self.write(tc, "NOTES.md", commit=False)
        code, out, _ = self.p.run("accept", tid)
        self.assertEqual(code, 0, out)
        self.assertIn("PASS scope", out)
        self.assertIn("accepted", self.p.ok("log", tid))

    def test_out_of_scope_fail(self):
        tid, tc = self.task("--scope", "src/")
        self.write(tc, "src/a.py")
        self.write(tc, "other/b.py")
        self.write(tc, "loose.txt", commit=False)
        code, out, _ = self.p.run("accept", tid)
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL scope", out)
        self.assertIn("other/b.py", out)
        self.assertIn("loose.txt", out)
        self.assertNotIn("src/a.py", out.split("FAIL scope")[1].splitlines()[0])
        self.assertNotIn("accepted", self.p.ok("log", tid))

    def test_dont_touch_fail(self):
        tid, tc = self.task("--scope", "src/**", "--dont-touch", "src/api/")
        self.write(tc, "src/api/x.py")
        code, out, _ = self.p.run("accept", tid, "--dry")
        self.assertEqual(code, 1)
        self.assertIn("в dont_touch: src/api/x.py", out)

    def test_empty_scope_skipped(self):
        tid, tc = self.task()
        self.write(tc, "anything.py")
        code, out, _ = self.p.run("accept", tid)
        self.assertEqual(code, 0, out)
        self.assertIn("SKIP scope", out)

    def test_journal_not_violation(self):
        tid, tc = self.task("--scope", "src/")
        self.write(tc, "docs/plan/aa/note.md")
        self.write(tc, "src/a.py")
        code, out, _ = self.p.run("accept", tid)
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
