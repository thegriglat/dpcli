"""PreToolUse hook: file edits through Bash are refused with a pointer to Edit/Write; programs and reads pass."""
import json
import subprocess
import sys
import unittest

from helpers import DIST, Project

GUARD = DIST / "hooks" / "bash_guard.py"


def run(cmd):
    r = subprocess.run([sys.executable, str(GUARD)], input=json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}}),
                       capture_output=True, text=True)
    return r.returncode, r.stderr


class BashGuard(unittest.TestCase):
    def test_blocks_shell_edits(self):
        for cmd in ("sed -i 's/a/b/' src/x.ts", "sed -Ei.bak 's/a/b/' f", "perl -pi -e 's/a/b/' f",
                    "cd src\nsed -i 's/a/b/' x.ts", "set -e\nperl -pi -e 's/a/b/' f",
                    "sed -i 's/a/b/' f  # bulk-edit",  # only a comment: there is no bypass marker
                    "cat <<'EOF'\ntext\nEOF\nsed -i 's/a/b/' f",  # after a closed heredoc
                    "grep x <<< word\nsed -i 's/a/b/' f",  # a here-string is not a heredoc
                    "sed -n -i 's/a/b/' f", "sed -e 's/a/b/' -i f", "perl -e 's/a/b/' -pi f",  # -i anywhere
                    "echo \"<<EOF\"\nsed -i 's/a/b/' f",  # a quoted "<<EOF" opens no heredoc
                    "sed -i s/a/b/ src/x.ts; rm /tmp/y", "sed -i s/a/b/ src/x.ts && rm /tmp/z",  # target of its own segment
                    "cat > src/x.ts <<'EOF'\nx\nEOF", "python3 - <<'EOF'\nfrom pathlib import Path\nPath('a').write_text('x')\nEOF",
                    "python3 - <<'EOF'\nopen('a', 'w').write('x')\nEOF"):
            code, err = run(cmd)
            self.assertEqual(code, 2, cmd)
            self.assertIn("Edit", err)

    def test_allows_programs_reads_and_quoted_text(self):
        for cmd in ("rg -n foo src", "sed -n '1,20p' f", "python3 - <<'EOF'\nprint(1)\nEOF", "cat f | jq .",
                    "pnpm exec vitest run", ".dpcli/dpcli review X --from - <<'JSON'\n{}\nJSON",
                    "python3 - <<'EOF'\nimport sys\nsys.stdout.write('x')\nEOF", "git commit -m 'sed -i is gone'",
                    "cat <<'EOF'\nsed -i is text here\nEOF",
                    "cat > /tmp/fixture.json <<'EOF'\n{}\nEOF", "sed -i 's/a/b/' /tmp/x.log",
                    "cat > \"$TMPDIR/r.json\" <<'EOF'\n{}\nEOF", "sed -i s/a/b/ /tmp/x && git add .",
                    "perl -MList::Util=sum -e 'print 1'", "perl -Mstrict -e 1", "perl script.pl -fail",
                    "python3 - <<'EOF'\nopen('/tmp/a', 'w').write('x')\nEOF"):
            self.assertEqual(run(cmd)[0], 0, cmd)

    def test_missing_script_fails_open(self):
        p = Project()
        self.addCleanup(p.cleanup)
        p.ok("init")
        st = json.loads((p.root / ".claude" / "settings.json").read_text())
        cmd = next(h["command"] for e in st["hooks"]["PreToolUse"] for h in e["hooks"] if "bash_guard" in h["command"])
        r = subprocess.run(["bash", "-c", cmd], input="{}", env={"CLAUDE_PROJECT_DIR": str(p.tmp / "nowhere"),
                           "PATH": "/usr/bin:/bin"}, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)  # a copy without .dpcli must not block every Bash call

    def test_init_installs_the_hook_once(self):
        p = Project()
        self.addCleanup(p.cleanup)
        p.ok("init")
        p.ok("init")
        st = json.loads((p.root / ".claude" / "settings.json").read_text())
        pre = [h["command"] for e in st["hooks"]["PreToolUse"] if e.get("matcher") == "Bash" for h in e["hooks"]]
        self.assertEqual(sum("bash_guard.py" in c for c in pre), 1)


if __name__ == "__main__":
    unittest.main()
