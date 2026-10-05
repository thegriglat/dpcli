import sys
import unittest

from helpers import DIST, LIB, Project

sys.path.insert(0, str(LIB))
from dpcli import yamlmini  # noqa: E402


def expected():
    ex, rev = set(), set()
    for f in (DIST / "agents").glob("*.md"):
        meta, _ = yamlmini.frontmatter(f.read_text(encoding="utf-8"))
        if meta.get("dpcli_role") == "executor":
            ex.add(meta.get("name") or f.stem)
            if str(meta.get("dpcli_review")).lower() == "true":
                rev.add(meta.get("name") or f.stem)
    return ex, rev


NEW_AGENT = "---\nname: dp-custom\ndescription: свой\ndpcli_role: executor\ndpcli_review: true\n---\nТекст\n"


class Agents(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.addCleanup(self.p.cleanup)
        self.p.ok("module", "new", "aa", "--code", "AA")

    def new(self, typ, *extra):
        return self.p.run("task", "new", "aa", "--type", typ, "--title", "T", "--goal", "g", *extra)

    def test_executor_types_from_files(self):
        ex, _ = expected()
        self.assertTrue(ex)
        code, out, err = self.new("nope")
        self.assertNotEqual(code, 0)
        listed = err.split("есть:")[1].split(";")[0]
        self.assertEqual({x.strip() for x in listed.split(",")}, ex)

    def test_non_executor_rejected(self):
        for t in ("dp-reviewer", "dp-coordinator", "dp-status"):
            code, _, err = self.new(t)
            self.assertNotEqual(code, 0, t)
            self.assertIn("не исполнитель", err)

    def test_missing_type(self):
        code, _, err = self.p.run("task", "new", "aa", "--title", "T")
        self.assertNotEqual(code, 0)
        self.assertIn("--type", err)

    def test_review_flag_per_agent(self):
        ex, rev = expected()
        self.assertTrue(rev and ex - rev)
        # по одному типу: accept PASS → checked (review) или accepted
        for typ in sorted(ex):
            out = self.p.ok("task", "new", "aa", "--type", typ, "--title", typ, "--check", "c", "true", "exit=0")
            tid = out.split(":")[0]
            self.p.ok("accept", tid)
            log = self.p.ok("log", tid)
            self.assertIn("accepted" if typ not in rev else "checked", log, typ)

    def test_custom_agent(self):
        (self.p.root / ".dpcli" / "agents" / "dp-custom.md").write_text(NEW_AGENT, encoding="utf-8")
        mc = self.p.copies / "proj-aa"
        # агенты читаются от корня текущей копии: кладём и туда
        (mc / ".dpcli" / "agents").mkdir(parents=True, exist_ok=True)
        (mc / ".dpcli" / "agents" / "dp-custom.md").write_text(NEW_AGENT, encoding="utf-8")
        code, out, err = self.new("dp-custom")
        self.assertEqual(code, 0, err)
        code, _, err = self.new("nope")
        self.assertIn("dp-custom", err)

    def test_custom_agents_dir(self):
        p = Project({"agents_dir": "myagents"})
        self.addCleanup(p.cleanup)
        d = p.root / "myagents"
        d.mkdir()
        (d / "solo.md").write_text("---\nname: solo\ndpcli_role: executor\n---\nx\n", encoding="utf-8")
        (d / "boss.md").write_text("---\nname: boss\ndpcli_role: coordinator\n---\nx\n", encoding="utf-8")
        p.commit_all("agents")
        p.ok("module", "new", "aa", "--code", "AA")
        code, _, err = p.run("task", "new", "aa", "--type", "dp-engineer", "--title", "T")
        self.assertNotEqual(code, 0)
        self.assertIn("solo", err)
        self.assertNotIn("boss", err.split("есть:")[1].split(";")[0])


if __name__ == "__main__":
    unittest.main()
