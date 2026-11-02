"""deliver: squash of the module branch without the journal, md for people, archive tag; in-place journal fold."""
import argparse
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from test_fixes import RepoCase, sh  # noqa: E402

from dpcli import gitx  # noqa: E402
from dpcli.commands import deliver  # noqa: E402
from dpcli.util import DpError  # noqa: E402


def jl(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def args(module, **kw):
    base = dict(module=module, into="main", message=None, in_place=False, rerender=False, from_=None, area=None,
                force=False, dry=False, by="main")
    base.update(kw)
    return argparse.Namespace(**base)


class DeliverBase(RepoCase):
    """Journal of module pay and a copy of its branch — no tests, base for subclasses."""
    MOD = "pay"

    def journal(self, root, accepted=True):
        home = root / "docs/plan" / self.MOD
        (home / "tasks").mkdir(parents=True)
        (root / "docs/plan" / f"{self.MOD}.md").write_text("# pay — оплата\n")
        jl(home / "events.jsonl", [
            {"t": "2026-10-01T10:00:00", "by": "coordinator", "task": "PY-2", "ev": "created"},
            {"t": "2026-10-01T10:00:00", "by": "coordinator", "task": "PY-10", "ev": "created"},
            {"t": "2026-10-02T10:00:00", "by": "coordinator", "task": "PY-2", "ev": "accepted" if accepted else "started"},
            {"t": "2026-10-02T10:00:00", "by": "coordinator", "task": "PY-10", "ev": "accepted"},
        ])
        jl(home / "decisions.jsonl", [
            {"t": "2026-10-01T09:00:00", "by": "user", "kind": "decision", "text": "Платим в USD", "why": "так проще"},
            {"t": "2026-10-01T09:30:00", "by": "coordinator", "kind": "question", "id": "Q1", "text": "Чек обязателен?"},
            {"t": "2026-10-01T09:40:00", "by": "user", "kind": "decision", "text": "Да, обязателен", "answers": "Q1"},
        ])
        (home / "module.json").write_text(json.dumps({"module": self.MOD, "branch": f"feature/{self.MOD}"}))
        for tid, title in (("PY-2", "Схема"), ("PY-10", "Метрики")):
            (home / "tasks" / f"{tid}.json").write_text(json.dumps({"id": tid, "title": title}, ensure_ascii=False))
            (home / "tasks" / f"{tid}.report.json").write_text(json.dumps(
                {"summary": f"{title} сделана", "not_done": [], "checks": [{"name": "jest", "pass": True}],
                 "uncertain": [{"where": "x.ts", "why": "не гонял format", "checked": "generate"}], "dp_feedback": "шум"},
                ensure_ascii=False))
        return home

    def module_copy(self):
        copy = self.main.parent / "pay"
        sh("worktree", "add", "-q", "-b", f"feature/{self.MOD}", str(copy), cwd=self.main)
        sh("config", "user.email", "t@t", cwd=copy)
        sh("config", "user.name", "t", cwd=copy)
        self.journal(copy)
        (copy / "code.py").write_text("x = 1\n")
        sh("add", ".", cwd=copy)
        sh("commit", "-q", "-m", "PY-2: код", cwd=copy)
        gitx.reset_worktrees()
        return copy

    def tracked(self, root, d="docs/plan"):
        return gitx.git("ls-files", "--", d, cwd=root).splitlines()


class Deliver(DeliverBase):

    def _squash(self, lang, ans, why, dec_h, chk, **over):
        self.cfg(**over)
        copy = self.module_copy()
        deliver.cmd_deliver(args(self.MOD))
        self.assertEqual(gitx.git("log", "-1", "--format=%s", cwd=self.main), "pay: pay — оплата")
        self.assertEqual(gitx.git("rev-list", "--count", "HEAD", cwd=self.main), "2")  # один squash-коммит
        self.assertTrue((self.main / "code.py").exists())
        self.assertEqual(sorted(self.tracked(self.main)),
                         ["docs/plan/pay.md", "docs/plan/pay/decisions.md", "docs/plan/pay/summary.md"])
        dec = (self.main / "docs/plan/pay/decisions.md").read_text()
        self.assertIn("### Q1", dec)
        self.assertIn(f"**{ans[0]}** ({ans[1]}, 2026-10-01): Да, обязателен", dec)
        self.assertIn(f"Платим в USD *{why}:* так проще", dec)
        self.assertNotIn(f"Да, обязателен *{why}", dec.split(dec_h)[1])  # ответ не дублируется в решениях
        summ = (self.main / "docs/plan/pay/summary.md").read_text()
        self.assertLess(summ.index("PY-2"), summ.index("PY-10"))
        self.assertIn(f"`x.ts` — не гонял format — {chk}: generate", summ)
        self.assertNotIn("шум", summ)
        self.assertNotIn("jest", summ)
        self.assertEqual(gitx.git("rev-parse", "archive/pay"), gitx.git("rev-parse", "feature/pay"))
        ev = (copy / "docs/plan/pay/events.jsonl").read_text().splitlines()[-1]
        self.assertEqual(json.loads(ev)["ev"], "delivered")

    def test_squash_keeps_frictions_once(self):
        from dpcli.commands import feedback
        self.cfg()
        copy = self.module_copy()
        with (copy / "docs/plan/pay/events.jsonl").open("a") as f:
            f.write(json.dumps({"t": "2026-10-02T11:00:00", "by": "coordinator", "ev": "note",
                                "note": "harness: zebra friction"}) + "\n")
        sh("commit", "-q", "-am", "note", cwd=copy)
        deliver.cmd_deliver(args(self.MOD))
        zebra = [i for i in feedback.items() if "zebra" in i["text"]]
        self.assertEqual(len(zebra), 1)  # the module copy still has the journal: ledger copy is not counted twice
        self.assertIn("zebra", feedback.ledger_path().read_text())

    def test_squash_drops_journal_and_keeps_md(self):
        self._squash("en", ("Answer", "user"), "Why", "## Decisions", "checked")

    def test_squash_ru(self):  # language.text ru: generated text stays Russian
        self._squash("ru", ("Ответ", "пользователь"), "Почему", "## Решения", "проверено",
                     language={"text": "ru", "commits": "ru"})

    def test_refuses_open_tasks(self):
        self.cfg()
        copy = self.main.parent / "pay"
        sh("worktree", "add", "-q", "-b", "feature/pay", str(copy), cwd=self.main)
        self.journal(copy, accepted=False)
        gitx.reset_worktrees()
        with self.assertRaises(DpError) as e:
            deliver.cmd_deliver(args(self.MOD))
        self.assertIn("PY-2", str(e.exception))

    def test_in_place(self):
        self.cfg()
        self.journal(self.main)
        sh("add", ".", cwd=self.main)
        sh("commit", "-q", "-m", "журнал", cwd=self.main)
        deliver.cmd_deliver(args(self.MOD, in_place=True))
        self.assertEqual(sorted(self.tracked(self.main)),
                         ["docs/plan/pay.md", "docs/plan/pay/decisions.md", "docs/plan/pay/summary.md"])
        self.assertEqual(sorted(p.name for p in (self.main / "docs/plan/pay").iterdir()), ["decisions.md", "summary.md"])
        self.assertEqual(gitx.dirty(self.main), [])


if __name__ == "__main__":
    unittest.main()
