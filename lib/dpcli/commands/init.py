"""init: set up Claude Code in a project from the .dpcli distribution (idempotent).

Renders agents (<agents_dir>/*.md -> .claude/agents/<name>.md), skills (.dpcli/skills/** -> .claude/skills/**),
the workflow (templates/workflow.md -> <workflow>), the CLAUDE.md block between markers, the permission in
.claude/settings.json and .gitignore lines; creates dpcli.yml from the example if there is no config. Placeholders
{{cli}} {{workflow}} {{plan_dir}} {{contracts_dir}} {{docs_dir}} {{main_branch}} {{module_branch}} {{project}}
are filled from the config.
Manual edits to generated files are detected via the manifest .claude/.dpcli-manifest.json (sha256 of what was
written): without --force such files are neither overwritten nor deleted. Files absent from the manifest (agents,
skills, workflow of the project with the same names) are never touched by init, even with --force: the dpcli agent
is skipped, a project agent's role is set by the roles key in the config.
"""
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from .. import config, gitx, yamlmini
from ..agents import ROLES
from ..util import DpError

DIST = Path(__file__).resolve().parents[3]  # .dpcli (next to lib/)
MANIFEST = ".claude/.dpcli-manifest.json"
BEGIN, END = "<!-- dpcli:begin -->", "<!-- dpcli:end -->"
PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")
SKIPPED = "edited by hand; edit the source in {src} or use --force"


def sha(b):
    return hashlib.sha256(b).hexdigest()


def git_root():
    t = gitx.git("rev-parse", "--show-toplevel")
    if not t:
        raise DpError("not in a git working copy: run `git init` (and a first commit) first, then `.dpcli/dpcli init`")
    return Path(t).resolve()


def relp(p, root):
    try:
        return str(Path(p).resolve().relative_to(root))
    except ValueError:
        return str(Path(p).resolve())


LANG_NAMES = {"en": "English", "ru": "Russian", "de": "German", "fr": "French", "es": "Spanish", "zh": "Chinese",
              "ja": "Japanese", "pt": "Portuguese", "it": "Italian", "uk": "Ukrainian"}


def lang_name(code):
    """Language code from the config → name for agent instructions (unknown codes pass through)."""
    c = str(code or "en").strip()
    return LANG_NAMES.get(c.lower(), c)


LOCAL_README = """# Project layer for dpcli

Committed with the project; `dpcli init` renders it on top of the dpcli distribution (`.dpcli`), so updates of dpcli never overwrite it.

- `agents/<name>.append.md` — appended to the dpcli agent `<name>` (preferred: the agent keeps receiving updates).
- `agents/<name>.md` — your own agent, or a full replacement of a dpcli agent with that name.
- `skills/<name>/` — project skills; a skill with a dpcli skill's name replaces it.
- `workflow.md` — project rules, appended to the process description as "Project rules".
- `claude-md.md` — lines appended to the dpcli block in `CLAUDE.md`.
- `feedback.jsonl` — friction ledger (`dpcli feedback`).

After editing: `.dpcli/dpcli init`, then commit this directory and `.claude/`.
"""


class Init:
    def __init__(self, a):
        self.a = a
        self.root = git_root()
        self.rows = []  # (path, status, note)
        self.warn = []
        self.dry = a.dry_run or a.check
        self.cli = relp(DIST / "dpcli", self.root)
        self.local = config.repo_path(config.get("local_dir", ".dpcli-local"), root=self.root)

    # ---------- output ----------
    def row(self, path, status, note=""):
        self.rows.append((path, status, note))

    # ---------- config ----------
    def ensure_config(self):
        for n in config.NAMES:
            if (self.root / n).is_file():
                self.row(n, "unchanged", "config")
                return
        example = DIST / "dpcli.example.yml"
        if self.a.json or not example.is_file():
            name = "dpcli.json"
            text = json.dumps(config.DEFAULTS, ensure_ascii=False, indent=2) + "\n"
            data = {}
        else:
            name = "dpcli.yml"
            text = example.read_text(encoding="utf-8")
            data = config.parse_file(example)
        self.row(name, "created", "config" + ("" if name == "dpcli.json" else " from dpcli.example.yml"))
        if not self.dry:
            (self.root / name).write_text(text, encoding="utf-8")
            config.reset()
        else:  # no config on disk: values from what would be created
            config._CFG = config.merge(config.DEFAULTS, data)
            config._PATH = None

    def values(self):
        return {
            "cli": self.cli,
            "workflow": str(config.get("workflow")),
            "plan_dir": config.plan_dir(),
            "contracts_dir": config.contracts_dir(),
            "docs_dir": config.docs_dir(),
            "main_branch": config.main_branch(),
            "module_branch": config.subst(config.get("module_branch"), module="<module>"),
            "project": config.project(),
            "language_text": lang_name(config.get("language.text", "en")),
            "language_commits": lang_name(config.get("language.commits", "en")),
        }

    def render(self, text, where):
        unknown = set()

        def rep(m):
            if m[1] in self.vals:
                return self.vals[m[1]]
            unknown.add(m[1])
            return m[0]
        out = PLACEHOLDER.sub(rep, text)
        if unknown:
            self.warn.append(f"{where}: unknown placeholders " + ", ".join("{{%s}}" % u for u in sorted(unknown)))
        return out

    # ---------- plan of generated files ----------
    def plan_agents(self):
        d = config.repo_path(config.get("agents_dir", ".dpcli/agents"), root=self.root)
        src_rel = relp(d, self.root)
        files = sorted(d.glob("*.md")) if d.is_dir() else []
        if not files:
            raise DpError(f"no agent definitions in {src_rel}/*.md")
        ld = self.local / "agents"
        own = [f for f in sorted(ld.glob("*.md")) if not f.name.endswith(".append.md")] if ld.is_dir() else []
        files = [f for f in files if f.name not in {o.name for o in own}] + own
        errors, names, roles = [], {}, set()
        out = []
        for f in files:
            fr = relp(f, self.root)
            text = self.render(f.read_text(encoding="utf-8"), fr)
            try:
                meta, _ = yamlmini.frontmatter(text)
            except yamlmini.YamlError as e:
                errors.append(f"{fr}: frontmatter not parsed ({e})")
                continue
            if not meta:
                errors.append(f"{fr}: no frontmatter (--- … ---)")
                continue
            name, role = meta.get("name"), meta.get("dpcli_role")
            if not name or not re.fullmatch(r"[\w.-]+", str(name)):
                errors.append(f"{fr}: no name (or invalid characters)")
                continue
            if role not in ROLES:
                errors.append(f"{fr}: dpcli_role \"{role}\", expected one of {', '.join(ROLES)}")
                continue
            if name in names:
                errors.append(f"{fr}: name \"{name}\" already in {names[name]}")
                continue
            names[name] = fr
            roles.add(role)
            app = ld / f"{name}.append.md"
            if app.is_file():  # project addition to an agent: the distribution body keeps updating
                text = text.rstrip("\n") + "\n\n" + self.render(app.read_text(encoding="utf-8"), relp(app, self.root)).strip() + "\n"
            out.append((f".claude/agents/{name}.md", text.encode(), f, relp(f.parent, self.root)))
        if errors:
            raise DpError("errors in agent definitions:\n  " + "\n  ".join(errors))
        for r in ("executor", "reviewer"):
            if r not in roles:
                self.warn.append(f"{src_rel}: no agent with dpcli_role: {r}")
        return out

    def plan_skills(self):
        out = []
        local = self.local / "skills"
        mine = {x.name for x in local.iterdir() if x.is_dir()} if local.is_dir() else set()
        for d in (DIST / "skills", local):
            out += self._skill_files(d, skip=mine if d != local else set())
        return out

    def _skill_files(self, d, skip):
        out = []
        for f in sorted(d.rglob("*")) if d.is_dir() else []:
            if not f.is_file() or "__pycache__" in f.parts or f.relative_to(d).parts[0] in skip:
                continue
            b = f.read_bytes()
            try:
                b = self.render(b.decode("utf-8"), relp(f, self.root)).encode()
            except UnicodeDecodeError:
                pass
            out.append((".claude/skills/" + f.relative_to(d).as_posix(), b, f, relp(f.parent, self.root)))
        return out

    def plan_workflow(self):
        f = DIST / "templates" / "workflow.md"
        if not f.is_file():
            raise DpError(f"no workflow template {relp(f, self.root)}")
        dest = relp(config.repo_path(config.get("workflow"), root=self.root), self.root)
        text = self.render(f.read_text(encoding="utf-8"), relp(f, self.root)).rstrip("\n") + "\n"
        rules = self.local_text("workflow.md")
        if rules:
            text += f"\n## Project rules\n\nFrom `{relp(self.local, self.root)}/workflow.md`.\n\n{rules}\n"
        return [(dest, text.encode(), f, relp(f, self.root))]

    def local_text(self, name):
        f = self.local / name
        return self.render(f.read_text(encoding="utf-8"), relp(f, self.root)).strip() if f.is_file() else ""

    def local_readme(self):
        p = self.local / "README.md"
        if p.exists():
            return
        self.row(relp(p, self.root), "created", "project layer")
        if not self.dry:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(LOCAL_README, encoding="utf-8")

    # ---------- writing with manifest ----------
    def sync_generated(self, plan):
        mp = self.root / MANIFEST
        try:
            old = json.loads(mp.read_text()).get("files", {}) if mp.is_file() else {}
        except (json.JSONDecodeError, AttributeError):
            self.warn.append(f"{MANIFEST}: not parsed, treating as empty")
            old = {}
        new = {}
        foreign = self.foreign_groups(plan, old)
        shown = set()
        for dest, data, src, src_rel in plan:
            p = self.root / dest
            h = sha(data)
            cur = p.read_bytes() if p.is_file() else None
            g = self.group(dest)
            if g in foreign:  # project file/skill (not created by init): never touched, even with --force
                if g not in shown:
                    shown.add(g)
                    self.row(g, "skipped", foreign[g])
                continue
            if cur is None:
                st, write = "created", True
            elif cur == data:
                st, write = "unchanged", False
            elif old.get(dest) == sha(cur) or self.a.force:
                st, write = "updated" + (" (--force)" if old.get(dest) != sha(cur) else ""), True
            else:
                self.row(dest, "skipped", SKIPPED.format(src=src_rel))
                if dest in old:
                    new[dest] = old[dest]
                continue
            new[dest] = h
            self.row(dest, st)
            if write and not self.dry:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
                os.chmod(p, (src.stat().st_mode & 0o777) | 0o600)
        for dest in sorted(set(old) - {d for d, *_ in plan}):
            p = self.root / dest
            if not p.is_file():
                continue
            if sha(p.read_bytes()) != old[dest] and not self.a.force:
                self.row(dest, "skipped", "gone from source but edited by hand: delete it yourself or use --force")
                new[dest] = old[dest]
                continue
            self.row(dest, "removed", "gone from source")
            if not self.dry:
                p.unlink()
                d = p.parent
                while d != self.root / ".claude" and d.is_dir() and not any(d.iterdir()):
                    d.rmdir()
                    d = d.parent
        if not self.dry and new != old:
            mp.parent.mkdir(parents=True, exist_ok=True)
            mp.write_text(json.dumps({"files": dict(sorted(new.items()))}, ensure_ascii=False, indent=2) + "\n")

    @staticmethod
    def group(dest):
        """Ownership unit: a skill is the dir .claude/skills/<name>/, anything else is a file."""
        parts = dest.split("/")
        if parts[:2] == [".claude", "skills"] and len(parts) > 3:
            return "/".join(parts[:3]) + "/"
        return dest

    def foreign_groups(self, plan, old):
        """{group: note} for what already exists in the project, is not in the init manifest and differs from what init would write."""
        want = {d: data for d, data, *_ in plan}
        out = {}
        for dest in want:
            g = self.group(dest)
            if g in out:
                continue
            if g.endswith("/"):
                d = self.root / g
                files = [f for f in d.rglob("*") if f.is_file()] if d.is_dir() else []
                if any(relp(f, self.root) not in old and want.get(relp(f, self.root)) != f.read_bytes() for f in files):
                    out[g] = "project skill (not created by init), leaving it"
                continue
            p = self.root / dest
            if p.is_file() and dest not in old and p.read_bytes() != want[dest]:
                out[g] = ("project agent; role: see roles in config" if dest.startswith(".claude/agents/")
                          else "project file (not created by init), leaving it")
        return out

    # ---------- merging into foreign files ----------
    def put_text(self, rel, old, new, note=""):
        if old == new:
            self.row(rel, "unchanged", note)
            return
        self.row(rel, "created" if old is None else "updated", note)
        if not self.dry:
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(new, encoding="utf-8")

    def claude_md(self):
        f = DIST / "templates" / "claude-md.md"
        body = self.render(f.read_text(encoding='utf-8'), relp(f, self.root)).strip()
        extra = self.local_text("claude-md.md")
        block = f"{BEGIN}\n{body}" + (f"\n{extra}" if extra else "") + f"\n{END}"
        p = self.root / "CLAUDE.md"
        old = p.read_text(encoding="utf-8") if p.is_file() else None
        if old is None:
            new = block + "\n"
        else:
            i, j = old.find(BEGIN), old.find(END)
            if i >= 0 and j > i:
                new = old[:i] + block + old[j + len(END):]
            else:
                if (i >= 0) != (j >= 0) or i > j >= 0:
                    self.warn.append(f"CLAUDE.md: markers {BEGIN}/{END} unpaired, block appended at the end")
                new = old.rstrip("\n") + ("\n\n" if old.strip() else "") + block + "\n"
        self.put_text("CLAUDE.md", old, new, "dpcli block")

    def settings(self):
        p = self.root / ".claude" / "settings.json"
        old = p.read_text(encoding="utf-8") if p.is_file() else None
        try:
            data = json.loads(old) if old and old.strip() else {}
        except json.JSONDecodeError as e:
            raise DpError(f".claude/settings.json: invalid JSON ({e}), fix the file")
        if not isinstance(data, dict):
            raise DpError(".claude/settings.json: object expected")
        perm = f"Bash({self.cli} *)"
        allow = data.setdefault("permissions", {}).setdefault("allow", [])
        hook = f"{self.cli} update --auto"
        starts = data.setdefault("hooks", {}).setdefault("SessionStart", [])
        has_hook = any(hook in str(h.get("command", "")) for e in starts if isinstance(e, dict) for h in e.get("hooks") or [])
        # fail open: without the script (a copy without the submodule) python would exit 2 = "blocked" for every call
        def script(name):
            return (f'f="$CLAUDE_PROJECT_DIR/{relp(DIST / "hooks" / name, self.root)}"; '
                    f'[ -f "$f" ] || exit 0; exec python3 "$f"')

        def has(event, name):
            return any(name in str(h.get("command", "")) for e in data["hooks"].setdefault(event, [])
                       if isinstance(e, dict) for h in e.get("hooks") or [])
        has_guard, has_ctx = has("PreToolUse", "bash_guard.py"), has("UserPromptSubmit", "context_guard.py")
        add = ([perm] if perm not in allow else []) + ([] if has_hook else ["SessionStart: update --auto"]) \
            + ([] if has_guard else ["PreToolUse: bash_guard"]) + ([] if has_ctx else ["UserPromptSubmit: context_guard"])
        if not add:
            self.row(".claude/settings.json", "unchanged", perm)
            return
        if perm not in allow:
            allow.append(perm)
        if not has_hook:
            starts.append({"hooks": [{"type": "command", "command": hook}]})
        if not has_guard:  # file edits through the shell → Edit/Write (agents made them by the hundred)
            data["hooks"]["PreToolUse"].append({"matcher": "Bash", "hooks": [{"type": "command", "command": script("bash_guard.py")}]})
        if not has_ctx:  # the main session's context grows unnoticed: it paid most of a module's tokens
            data["hooks"]["UserPromptSubmit"].append({"hooks": [{"type": "command", "command": script("context_guard.py")}]})
        self.put_text(".claude/settings.json", old, json.dumps(data, ensure_ascii=False, indent=2) + "\n", ", ".join(add))

    def gitignore(self):
        want = [".read_*"]
        log = str(config.get("checks.log_dir") or "").strip().rstrip("/")
        if log and not os.path.isabs(os.path.expanduser(log)):
            want.append(log + "/")
        want.append("__pycache__/")
        p = self.root / ".gitignore"
        old = p.read_text(encoding="utf-8") if p.is_file() else None
        have = {ln.strip().strip("/") for ln in (old or "").splitlines()}
        add = [w for w in want if w.strip("/") not in have]
        if not add:
            self.row(".gitignore", "unchanged")
            return
        base = old or ""
        new = base + ("\n" if base and not base.endswith("\n") else "") + "\n".join(add) + "\n"
        self.put_text(".gitignore", old, new, "+ " + " ".join(add))

    # ---------- run ----------
    def run(self):
        self.ensure_config()
        self.vals = self.values()
        plan = self.plan_agents() + self.plan_skills() + self.plan_workflow()
        self.sync_generated(plan)
        self.local_readme()
        self.claude_md()
        self.settings()
        self.gitignore()
        for w in self.warn:
            print(f"dpcli: warning: {w}", file=sys.stderr)
        if self.a.check:
            bad = [r for r in self.rows if r[1] != "unchanged"]
            for path, st, note in bad:
                print(f"{path}: {st}" + (f" — {note}" if note else ""))
            print(f"init --check: {'needs ' + self.cli + ' init' if bad else '.claude is up to date'}")
            return 1 if bad else 0
        w = max(len(r[0]) for r in self.rows)
        if self.dry:
            print("init --dry-run: nothing written, would do:")
        for path, st, note in self.rows:
            print(f"{path.ljust(w)}  {st}" + (f" — {note}" if note else ""))
        counts = {}
        for _, st, _ in self.rows:
            k = st.split(" (")[0]
            counts[k] = counts.get(k, 0) + 1
        print("Total: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
        print(f"\nCommit .dpcli/, .claude/, CLAUDE.md and the config to {self.vals['main_branch']}: module and task copies "
              "are created from branches and will see neither dpcli nor the agents without a commit.")
        print(f"Next: the main session reads {self.vals['workflow']}; module: "
              f"`{self.cli} module new <module> --code XX`, then tasks: `{self.cli} task new …` "
              f"(help: `{self.cli} -h`). Edit agents and workflow in .dpcli/, then run `{self.cli} init` again.")
        return 0


def cmd_init(a):
    return Init(a).run()


def register(sp):
    q = sp.add_parser("init", help="set up Claude Code in the project: agents, skills, workflow, CLAUDE.md, permissions (idempotent)")
    q.add_argument("--dry-run", action="store_true", help="write nothing, only show the action table")
    q.add_argument("--force", action="store_true", help="overwrite/delete hand-edited files from the init manifest too (project files: never)")
    q.add_argument("--check", action="store_true", help="only check that .claude is up to date (exit 1: init needed; for CI)")
    g = q.add_mutually_exclusive_group()
    g.add_argument("--yaml", action="store_true", help="create config dpcli.yml from the example (default)")
    g.add_argument("--json", action="store_true", help="create config dpcli.json from defaults")
    q.set_defaults(func=cmd_init)
