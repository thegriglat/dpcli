"""Module areas, decision reasons, closing plan and contracts on delivery, INDEX.md by area, deliver --rerender."""
import argparse
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from test_deliver import DeliverBase, args  # noqa: E402
from test_fixes import RepoCase, sh  # noqa: E402

from dpcli import gitx  # noqa: E402
from dpcli.commands import deliver, docs  # noqa: E402
from dpcli.journal import check_area, guard_main  # noqa: E402
from dpcli.util import DpError  # noqa: E402

PLAN = """---
type: plan
status: active
module: pay
updated: 2026-10-01
summary: Оплата плана
related:
  - docs/contracts/pay.md
---

# pay — оплата
"""
CONTRACT = """---
type: "contract"
status: "active"
module: "pay"
updated: 2026-10-01
summary: "Стыки pay"
related: []
contracts: []
---

# Контракты pay
"""


class Why(unittest.TestCase):
    def test_source_only_becomes_approved(self):
        for w in ("", "ответ пользователя 2026-10-09", "указание пользователя", "ответ на вопрос", "сообщения пользователя",
                  "уточнение пользователя 2026-10-06", "приёмка 2026-10-07"):
            self.assertEqual(deliver.why_of({"by": "user", "why": w}), deliver.APPROVED, w)

    def test_real_reason_kept(self):
        for w in ("уточнение пользователя 2026-10-06: Todo Tree у всех", "постановка задачи CU-12487v2f0pu", "так проще"):
            self.assertEqual(deliver.why_of({"by": "user", "why": w}), w)

    def test_not_user_kept(self):
        self.assertEqual(deliver.why_of({"by": "coordinator", "why": ""}), "")
        self.assertEqual(deliver.why_of({"by": "main", "why": "ответ пользователя"}), "ответ пользователя")


class Area(RepoCase):
    def test_required_when_configured(self):
        self.cfg(areas=["web", "api"])
        with self.assertRaises(DpError) as e:
            check_area(None)
        self.assertIn("ask the developer", str(e.exception))
        with self.assertRaises(DpError):
            check_area("other")
        check_area("web")

    def test_not_used_without_config(self):
        self.cfg()
        check_area(None)
        check_area("anything")

    def test_docs_check(self):
        self.cfg(areas=["web"])
        d = self.main / "docs/plan"
        d.mkdir(parents=True)
        (d / "pay.md").write_text(PLAN)
        (d / "cat.md").write_text(PLAN.replace("module: pay", "module: cat\narea: nope"))
        out = self.check()
        self.assertIn("docs/plan/pay.md: module document has no area", out)
        self.assertIn("docs/plan/cat.md: area 'nope'", out)

    def check(self):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            docs.cmd_check(docs.Ctx(), type("A", (), {"paths": []})())
        return buf.getvalue()


class SetFm(unittest.TestCase):
    def test_keeps_yaml_and_inserts_area_after_module(self):
        out = deliver.set_fm(PLAN, status="closed", area="web")
        self.assertIn("status: closed\nmodule: pay\narea: web\nupdated: 2026-10-01", out)
        self.assertIn('status: "closed"\nmodule: "pay"\narea: "web"', deliver.set_fm(CONTRACT, status="closed", area="web"))
        self.assertIn("related:\n  - docs/contracts/pay.md\n---", out)
        fm, body = docs.split_fm(out)
        self.assertEqual((fm["status"], fm["area"], fm["related"]), ("closed", "web", ["docs/contracts/pay.md"]))
        self.assertEqual(body, "\n# pay — оплата\n")

    def test_no_frontmatter(self):
        self.assertIsNone(deliver.set_fm("# x\n", status="closed"))


class DeliverArea(DeliverBase):
    def journal(self, root, accepted=True):
        home = super().journal(root, accepted)
        (root / "docs/plan/pay.md").write_text(PLAN)
        (root / "docs/contracts").mkdir(parents=True, exist_ok=True)
        (root / "docs/contracts/pay.md").write_text(CONTRACT)
        m = json.loads((home / "module.json").read_text())
        m["area"] = "web"
        (home / "module.json").write_text(json.dumps(m))
        return home

    def test_squash_closes_plan_and_builds_index(self):
        self.cfg(areas=["web", "api"])
        self.module_copy()
        deliver.cmd_deliver(args(self.MOD))
        plan, _ = docs.split_fm((self.main / "docs/plan/pay.md").read_text())
        self.assertEqual((plan["status"], plan["area"]), ("closed", "web"))
        contract, _ = docs.split_fm((self.main / "docs/contracts/pay.md").read_text())
        self.assertEqual((contract["status"], contract["area"]), ("closed", "web"))
        dec, body = docs.split_fm((self.main / "docs/plan/pay/decisions.md").read_text())
        self.assertEqual((dec["area"], dec["archive"]), ("web", "archive/pay"))
        self.assertIn("in git: `archive/pay`", body)
        idx = (self.main / "docs/INDEX.md").read_text()
        self.assertIn("## web\n", idx)
        self.assertNotIn("## api", idx)  # пустые подпроекты не выводятся
        self.assertIn("- **pay** — Оплата плана [closed", idx)
        self.assertIn("[decisions](plan/pay/decisions.md) · [summary](plan/pay/summary.md) · full journal: `archive/pay`", idx)
        self.assertIn("docs/INDEX.md", gitx.git("ls-files", "--", "docs", cwd=self.main).splitlines())
        self.assertEqual(gitx.dirty(self.main), [])

    def test_refuses_module_without_area(self):
        self.cfg(areas=["web"])
        copy = self.module_copy()
        home = copy / "docs/plan/pay"
        (home / "module.json").write_text(json.dumps({"module": "pay", "branch": "feature/pay"}))
        with self.assertRaises(DpError):
            deliver.cmd_deliver(args(self.MOD))

    def test_rerender_from_tag(self):
        self.cfg(areas=["web"])
        self.journal(self.main)
        m = self.main / "docs/plan/pay/module.json"
        m.write_text(json.dumps({"module": "pay", "branch": "feature/pay"}))  # старый журнал: area нет
        sh("add", ".", cwd=self.main)
        sh("commit", "-q", "-m", "журнал", cwd=self.main)
        sh("tag", "archive/old", cwd=self.main)
        sh("rm", "-q", "-r", "docs/plan/pay", cwd=self.main)
        sh("commit", "-q", "-m", "свёрнут", cwd=self.main)
        with self.assertRaises(DpError):  # area не задан ни в журнале, ни флагом
            deliver.cmd_deliver(args(self.MOD, rerender=True, from_="archive/old"))
        deliver.cmd_deliver(args(self.MOD, rerender=True, from_="archive/old", area="web"))
        dec, body = docs.split_fm((self.main / "docs/plan/pay/decisions.md").read_text())
        self.assertEqual((dec["area"], dec["archive"]), ("web", "archive/old"))
        self.assertIn("- 2026-10-01 — Платим в USD *Why:* так проще", body)
        self.assertEqual(sorted(p.name for p in (self.main / "docs/plan/pay").iterdir()), ["decisions.md", "summary.md"])
        self.cfg(areas=["web"], deliver={"keep": ["decisions.md", "summary.md"], "archive_tag": False})
        deliver.cmd_deliver(args(self.MOD, rerender=True, from_="archive/old", area="web"))
        dec, body = docs.split_fm((self.main / "docs/plan/pay/decisions.md").read_text())
        self.assertNotIn("archive", dec)  # теги выключены — ссылки на журнал нет
        self.assertNotIn("Full journal", body)
        plan = docs.split_fm((self.main / "docs/plan/pay.md").read_text())[0]
        self.assertEqual((plan["status"], plan["updated"]), ("closed", "2026-10-02"))  # последняя запись журнала
        self.assertTrue((self.main / "docs/INDEX.md").exists())
        self.assertFalse((self.main / "build/dpcli/rerender-pay").exists())


class IndexConflict(RepoCase):
    """Two branches add a module each — INDEX.md conflicts; dpcli merge rebuilds it itself."""

    def plan(self, mod, upd):
        p = self.main / "docs/plan" / f"{mod}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(PLAN.replace("module: pay", f"module: {mod}\narea: web").replace("2026-10-01", upd))
        docs.cmd_index(docs.Ctx(), None)
        sh("add", ".", cwd=self.main)
        sh("commit", "-q", "-m", mod, cwd=self.main)

    def test_merge_regenerates_index(self):
        self.cfg(areas=["web"])
        self.plan("base", "2026-10-01")
        sh("checkout", "-q", "-b", "b", cwd=self.main)
        self.plan("bbb", "2026-10-03")
        sh("checkout", "-q", "main", cwd=self.main)
        self.plan("aaa", "2026-10-02")
        h, n, kind = gitx.do_merge(self.main, "b", "merge b")
        self.assertEqual(kind, "merged")
        idx = (self.main / "docs/INDEX.md").read_text()
        for m in ("base", "aaa", "bbb"):
            self.assertIn(f"- **{m}**", idx)
        self.assertNotIn("<<<<<<<", idx)
        docs.cmd_index(docs.Ctx(), None)  # дата — из документов: повторная сборка файл не меняет
        self.assertEqual((self.main / "docs/INDEX.md").read_text(), idx)
        self.assertEqual(gitx.dirty(self.main), [])

    def test_other_conflict_aborts(self):
        self.cfg()
        (self.main / "a.txt").write_text("main")
        sh("commit", "-q", "-am", "m", cwd=self.main)
        sh("checkout", "-q", "-b", "c", "HEAD~1", cwd=self.main)
        (self.main / "a.txt").write_text("c")
        sh("commit", "-q", "-am", "c", cwd=self.main)
        sh("checkout", "-q", "main", cwd=self.main)
        with self.assertRaises(DpError):
            gitx.do_merge(self.main, "c", "merge c")
        self.assertEqual((self.main / "a.txt").read_text(), "main")


class FeatureBase(DeliverBase):
    """Usual path: module created from a feature branch and delivered into it; dpcli never merges into main by itself."""

    def setUp(self):
        super().setUp()
        sh("checkout", "-q", "-b", "feat", cwd=self.main)  # главная копия — на фичеветке задачи

    def journal(self, root, accepted=True):
        home = super().journal(root, accepted)
        (home / "module.json").write_text(json.dumps({"module": self.MOD, "branch": "feature/pay", "base": "feat"}))
        return home

    def test_deliver_defaults_to_base(self):
        self.cfg()
        self.module_copy()
        deliver.cmd_deliver(args(self.MOD, into=None))
        self.assertEqual(gitx.git("log", "-1", "--format=%s", "feat"), "pay: pay — оплата")
        self.assertEqual(gitx.git("rev-list", "--count", "main"), "1")  # main не тронут

    def test_deliver_into_main_refused(self):
        self.cfg(protect_main=True)
        self.module_copy()
        with self.assertRaises(DpError) as e:
            deliver.cmd_deliver(args(self.MOD, into="main"))
        self.assertIn("only via a feature-branch MR", str(e.exception))

    def test_merge_task_defaults_to_module_branch(self):
        from dpcli.commands import branches
        self.cfg()
        copy = self.module_copy()
        home = copy / "docs/plan/pay"
        (home / "tasks/PY-2.json").write_text(json.dumps({"id": "PY-2", "title": "Схема", "base": "feature/pay"}))
        self.assertEqual(branches.base_of("pay/PY-2"), "feature/pay")
        self.assertEqual(branches.base_of("feature/pay"), "feat")
        self.assertIsNone(branches.base_of("feat"))
        merge = dict(into=None, message=None, trailer=None, push=False, no_index=True)
        with self.assertRaises(DpError) as e:  # ветка не dpcli и --into нет — не угадываем
            branches.cmd_merge(argparse.Namespace(branch="feat", **merge))
        self.assertIn("--into", str(e.exception))
        guard_main("main", False)  # protect_main выключен — в main можно
        self.cfg(protect_main=True)
        with self.assertRaises(DpError) as e:  # в main — только явным --into main
            guard_main("main", False)
        self.assertIn("explicit --into main", str(e.exception))

    def test_module_new_from_current_branch(self):
        from dpcli.commands import branches
        self.cfg(module_copy=str(self.main.parent / "{module}"))
        new = dict(code=None, area=None, by="main")
        branches.cmd_module_new(argparse.Namespace(module="cat", from_=None, **new))
        meta = json.loads((self.main.parent / "cat/docs/plan/cat/module.json").read_text())
        self.assertEqual(meta["base"], "feat")  # база — текущая ветка главной копии (фичеветка)
        with self.assertRaises(DpError) as e:  # модуль не заводят от ветки другого модуля
            branches.cmd_module_new(argparse.Namespace(module="dog", from_="feature/cat", **new))
        self.assertIn("feature branch", str(e.exception))



if __name__ == "__main__":
    unittest.main()
