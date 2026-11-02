import json
import unittest

from helpers import DIST, Project

HAS_INIT = (DIST / "lib" / "dpcli" / "commands" / "init.py").is_file()


@unittest.skipUnless(HAS_INIT, "no commands/init.py yet")
class Init(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.addCleanup(self.p.cleanup)
        self.p.ok("init")

    def snapshot(self):
        snap = {}
        for sub in (".claude", "CLAUDE.md", ".gitignore", "dpcli.yml", "dpcli.json"):
            base = self.p.root / sub
            files = [base] if base.is_file() else sorted(base.rglob("*")) if base.is_dir() else []
            for f in files:
                if f.is_file():
                    snap[str(f.relative_to(self.p.root))] = f.read_bytes()
        return snap

    def test_creates(self):
        r = self.p.root
        for n in (r / ".dpcli" / "agents").glob("*.md"):
            self.assertTrue((r / ".claude" / "agents" / n.name).is_file(), n.name)
        for s in (DIST / "skills").iterdir():
            self.assertTrue((r / ".claude" / "skills" / s.name / "SKILL.md").is_file(), s.name)
        self.assertTrue((r / ".claude" / "dpcli-workflow.md").is_file())
        md = (r / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("<!-- dpcli:begin", md)
        self.assertIn("<!-- dpcli:end", md)
        st = json.loads((r / ".claude" / "settings.json").read_text())
        self.assertIn("Bash(.dpcli/dpcli *)", st["permissions"]["allow"])

    def test_no_placeholders(self):
        r = self.p.root
        files = list((r / ".claude").rglob("*.md")) + [r / "CLAUDE.md"]
        self.assertTrue(files)
        for f in files:
            self.assertNotIn("{{", f.read_text(encoding="utf-8"), str(f))

    def test_idempotent(self):
        before = self.snapshot()
        self.p.ok("init")
        self.assertEqual(before, self.snapshot())

    def test_preserves_claude_md(self):
        p = Project()
        self.addCleanup(p.cleanup)
        (p.root / "CLAUDE.md").write_text("# Мой проект\nправила\n", encoding="utf-8")
        p.ok("init")
        md = (p.root / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertTrue(md.startswith("# Мой проект\nправила"))
        self.assertEqual(md.count("<!-- dpcli:begin"), 1)

    def test_dry_run(self):
        p = Project()
        self.addCleanup(p.cleanup)
        p.ok("init", "--dry-run")
        self.assertFalse((p.root / ".claude").exists())


if __name__ == "__main__":
    unittest.main()


class LocalLayer(unittest.TestCase):
    """Project layer .dpcli-local/: survives distribution updates, rendered on top of it."""

    def setUp(self):
        self.p = Project()
        self.addCleanup(self.p.cleanup)
        self.loc = self.p.root / ".dpcli-local"
        (self.loc / "agents").mkdir(parents=True)
        (self.loc / "skills" / "start-to-do").mkdir(parents=True)
        (self.loc / "skills" / "deploy").mkdir(parents=True)
        (self.loc / "agents" / "dp-engineer.append.md").write_text("- Project rule: run `make lint` before accept.\n")
        (self.loc / "agents" / "dp-dba.md").write_text(
            "---\nname: dp-dba\ndescription: \"database migrations for {{project}}\"\nmodel: sonnet\n"
            "dpcli_role: executor\ndpcli_review: true\n---\nYou write migrations.\n")
        (self.loc / "skills" / "start-to-do" / "SKILL.md").write_text("---\nname: start-to-do\ndescription: \"local\"\n---\nLOCAL\n")
        (self.loc / "skills" / "deploy" / "SKILL.md").write_text("---\nname: deploy\ndescription: \"deploy\"\n---\nDeploy.\n")
        (self.loc / "workflow.md").write_text("- Staging DB is shared: always `lock cpu db`.\n")
        (self.loc / "claude-md.md").write_text("- Ask before touching billing.\n")
        self.p.ok("init")

    def read(self, rel):
        return (self.p.root / rel).read_text()

    def test_agent_append_and_own_agent(self):
        eng = self.read(".claude/agents/dp-engineer.md")
        self.assertIn("You are a", eng)  # distribution body kept
        self.assertTrue(eng.rstrip().endswith("run `make lint` before accept."))
        self.assertIn("database migrations for proj", self.read(".claude/agents/dp-dba.md"))
        self.assertIn("dp-dba", self.p.ok("agents"))
        self.assertIn("local", [l.split()[3] for l in self.p.ok("agents").splitlines() if l.startswith("dp-dba")])

    def test_skills_override_and_add(self):
        self.assertIn("LOCAL", self.read(".claude/skills/start-to-do/SKILL.md"))
        self.assertIn("Deploy.", self.read(".claude/skills/deploy/SKILL.md"))

    def test_project_rules_in_workflow_and_claude_md(self):
        wf = self.read(".claude/dpcli-workflow.md")
        self.assertIn("## Project rules", wf)
        self.assertIn("always `lock cpu db`", wf)
        cm = self.read("CLAUDE.md")
        self.assertIn("Ask before touching billing.", cm.split("<!-- dpcli:end -->")[0])

    def test_survives_distribution_update_and_is_idempotent(self):
        # simulate an update of the distribution: agent text changes upstream
        f = self.p.root / ".dpcli" / "agents" / "dp-engineer.md"
        f.write_text(f.read_text().replace("You are a", "UPDATED: you are a"))
        self.p.ok("init")
        eng = self.read(".claude/agents/dp-engineer.md")
        self.assertIn("UPDATED: you are a", eng)
        self.assertIn("make lint", eng)
        self.assertIn("up to date", self.p.ok("init", "--check"))

    def test_readme_created_once(self):
        readme = self.loc / "README.md"
        self.assertTrue(readme.is_file())
        readme.write_text("mine\n")
        self.p.ok("init")
        self.assertEqual(readme.read_text(), "mine\n")


class Hook(unittest.TestCase):
    def test_session_start_update_hook_added_once(self):
        p = Project()
        self.addCleanup(p.cleanup)
        p.ok("init")
        p.ok("init")
        st = json.loads((p.root / ".claude" / "settings.json").read_text())
        cmds = [h["command"] for e in st["hooks"]["SessionStart"] for h in e["hooks"]]
        self.assertEqual(sum("update --auto" in c for c in cmds), 1)
