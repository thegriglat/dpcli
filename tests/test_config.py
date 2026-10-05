import json
import sys
import unittest

from helpers import LIB, Project

sys.path.insert(0, str(LIB))
from dpcli import config  # noqa: E402


class Pure(unittest.TestCase):
    def test_defaults(self):
        D = config.DEFAULTS
        self.assertEqual(D["main_branch"], "main")
        self.assertEqual(D["module_branch"], "feature/{module}")
        self.assertEqual(D["task_branch"], "{module}/{task}")
        self.assertEqual(D["plan_dir"], "docs/plan")
        self.assertEqual(D["checks"]["log_dir"], "build/dpcli")
        self.assertEqual(D["jobs"]["tmux_session"], "dp")

    def test_deep_merge(self):
        m = config.merge(config.DEFAULTS, {"checks": {"tests": "pytest {filter}"}, "gc": {"ignore_globs": ["*.uid"]}})
        self.assertEqual(m["checks"]["tests"], "pytest {filter}")
        self.assertEqual(m["checks"]["log_dir"], "build/dpcli")  # соседние ключи сохранены
        self.assertEqual(m["gc"]["ignore_dirs"], ["build", "__pycache__"])
        self.assertEqual(m["gc"]["ignore_globs"], ["*.uid"])
        self.assertEqual(config.DEFAULTS["checks"]["tests"], None)  # исходник не изменён

    def test_merge_none_keeps_default(self):
        m = config.merge(config.DEFAULTS, {"main_branch": None})
        self.assertEqual(m["main_branch"], "main")

    def test_branch_fields(self):
        self.assertEqual(config.branch_fields("feature/{module}", "feature/ui"), {"module": "ui"})
        self.assertIsNone(config.branch_fields("feature/{module}", "other/ui"))
        self.assertEqual(config.branch_fields("{module}/{task}", "ui/UI-1"), {"module": "ui", "task": "UI-1"})


class InProject(unittest.TestCase):
    """Через CLI в временном проекте: приоритет файлов и шаблоны."""

    def test_json_beats_yml(self):
        p = Project()
        self.addCleanup(p.cleanup)
        (p.root / "dpcli.yml").write_text("module_branch: yml/{module}\n", encoding="utf-8")
        cfg = json.loads((p.root / "dpcli.json").read_text())
        cfg["module_branch"] = "json/{module}"
        (p.root / "dpcli.json").write_text(json.dumps(cfg))
        out = p.ok("module", "new", "aa", "--code", "AA")
        self.assertIn("json/aa", out)

    def test_yml_only_and_templates(self):
        p = Project()
        self.addCleanup(p.cleanup)
        (p.root / "dpcli.json").unlink()
        (p.root / "dpcli.yml").write_text(
            f"project: pr\ncopies_dir: {p.copies}\nmodule_branch: \"mod/{{module}}\"\n"
            f"module_copy: \"{{copies}}/m-{{project}}-{{module}}\"\ntask_branch: \"t/{{module}}-{{task}}\"\n"
            f"jobs:\n  dir: {p.cache}/jobs\n", encoding="utf-8")
        p.commit_all("cfg")
        out = p.ok("module", "new", "aa", "--code", "AA")
        self.assertIn("mod/aa", out)
        self.assertTrue((p.copies / "m-pr-aa").is_dir())
        out = p.ok("task", "new", "aa", "--type", "dp-writer", "--title", "T")
        self.assertIn("AA-1", out)
        card = json.loads(next((p.copies / "m-pr-aa").rglob("AA-1.json")).read_text())
        self.assertEqual(card["branch"], "t/aa-AA-1")
        self.assertEqual(card["base"], "mod/aa")
        self.assertTrue(card["copy"].endswith("task-copy") or "pr-aa-AA-1" in card["copy"])

    def test_config_from_subdir(self):
        p = Project()
        self.addCleanup(p.cleanup)
        sub = p.root / "a" / "b"
        sub.mkdir(parents=True)
        out = p.ok("module", "new", "aa", "--code", "AA", cwd=sub)
        self.assertIn(str(p.copies), out)

    def test_bad_config(self):
        p = Project()
        self.addCleanup(p.cleanup)
        (p.root / "dpcli.json").write_text("{bad", encoding="utf-8")
        code, out, err = p.run("status")
        self.assertNotEqual(code, 0)
        self.assertIn("dpcli.json", err)


if __name__ == "__main__":
    unittest.main()
