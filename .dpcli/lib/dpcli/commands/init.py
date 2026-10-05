"""init: настройка Claude Code в проекте из дистрибутива .dpcli (идемпотентно).

Рендерит агентов (<agents_dir>/*.md → .claude/agents/<name>.md), скиллы (.dpcli/skills/** → .claude/skills/**),
процесс (templates/workflow.md → <workflow>), блок CLAUDE.md между маркерами, разрешение в .claude/settings.json,
строки .gitignore; создаёт dpcli.yml из примера, если конфига нет. Плейсхолдеры {{cli}} {{workflow}} {{plan_dir}}
{{contracts_dir}} {{main_branch}} {{module_branch}} {{project}} подставляются из конфига.
Ручные правки сгенерированных файлов видны по манифесту .claude/.dpcli-manifest.json (sha256 записанного) —
без --force такие файлы не перезаписываются и не удаляются. Файлы, которых нет в манифесте (агенты, скиллы, процесс
проекта с теми же именами), init не трогает никогда, даже с --force: агент dpcli пропускается, роль своего агента —
ключ roles в конфиге.
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

DIST = Path(__file__).resolve().parents[3]  # .dpcli (рядом с lib/)
MANIFEST = ".claude/.dpcli-manifest.json"
BEGIN, END = "<!-- dpcli:begin -->", "<!-- dpcli:end -->"
PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")
SKIPPED = "изменён вручную; правьте источник в {src} или --force"


def sha(b):
    return hashlib.sha256(b).hexdigest()


def git_root():
    t = gitx.git("rev-parse", "--show-toplevel")
    if not t:
        raise DpError("не в рабочей копии git — сначала `git init` (и первый коммит), затем `.dpcli/dpcli init`")
    return Path(t).resolve()


def relp(p, root):
    try:
        return str(Path(p).resolve().relative_to(root))
    except ValueError:
        return str(Path(p).resolve())


class Init:
    def __init__(self, a):
        self.a = a
        self.root = git_root()
        self.rows = []  # (путь, статус, примечание)
        self.warn = []
        self.dry = a.dry_run or a.check
        self.cli = relp(DIST / "dpcli", self.root)

    # ---------- вывод ----------
    def row(self, path, status, note=""):
        self.rows.append((path, status, note))

    # ---------- конфиг ----------
    def ensure_config(self):
        for n in config.NAMES:
            if (self.root / n).is_file():
                self.row(n, "без изменений", "конфиг")
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
        self.row(name, "создан", "конфиг" + ("" if name == "dpcli.json" else " из dpcli.example.yml"))
        if not self.dry:
            (self.root / name).write_text(text, encoding="utf-8")
            config.reset()
        else:  # конфига нет на диске — значения из того, что был бы создан
            config._CFG = config.merge(config.DEFAULTS, data)
            config._PATH = None

    def values(self):
        return {
            "cli": self.cli,
            "workflow": str(config.get("workflow")),
            "plan_dir": config.plan_dir(),
            "contracts_dir": config.contracts_dir(),
            "main_branch": config.main_branch(),
            "module_branch": config.subst(config.get("module_branch"), module="<модуль>"),
            "project": config.project(),
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
            self.warn.append(f"{where}: неизвестные плейсхолдеры " + ", ".join("{{%s}}" % u for u in sorted(unknown)))
        return out

    # ---------- план генерируемых файлов ----------
    def plan_agents(self):
        d = config.repo_path(config.get("agents_dir", ".dpcli/agents"), root=self.root)
        src_rel = relp(d, self.root)
        files = sorted(d.glob("*.md")) if d.is_dir() else []
        if not files:
            raise DpError(f"нет определений агентов в {src_rel}/*.md")
        errors, names, roles = [], {}, set()
        out = []
        for f in files:
            fr = relp(f, self.root)
            text = self.render(f.read_text(encoding="utf-8"), fr)
            try:
                meta, _ = yamlmini.frontmatter(text)
            except yamlmini.YamlError as e:
                errors.append(f"{fr}: frontmatter не разобран ({e})")
                continue
            if not meta:
                errors.append(f"{fr}: нет frontmatter (--- … ---)")
                continue
            name, role = meta.get("name"), meta.get("dpcli_role")
            if not name or not re.fullmatch(r"[\w.-]+", str(name)):
                errors.append(f"{fr}: нет name (или недопустимые символы)")
                continue
            if role not in ROLES:
                errors.append(f"{fr}: dpcli_role «{role}» — нужно одно из {', '.join(ROLES)}")
                continue
            if name in names:
                errors.append(f"{fr}: name «{name}» уже в {names[name]}")
                continue
            names[name] = fr
            roles.add(role)
            out.append((f".claude/agents/{name}.md", text.encode(), f, src_rel))
        if errors:
            raise DpError("ошибки в определениях агентов:\n  " + "\n  ".join(errors))
        for r in ("executor", "reviewer"):
            if r not in roles:
                self.warn.append(f"{src_rel}: нет ни одного агента с dpcli_role: {r}")
        return out

    def plan_skills(self):
        d = DIST / "skills"
        out = []
        for f in sorted(d.rglob("*")) if d.is_dir() else []:
            if not f.is_file() or "__pycache__" in f.parts:
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
            raise DpError(f"нет шаблона процесса {relp(f, self.root)}")
        dest = relp(config.repo_path(config.get("workflow"), root=self.root), self.root)
        return [(dest, self.render(f.read_text(encoding="utf-8"), relp(f, self.root)).encode(), f,
                 relp(f, self.root))]

    # ---------- запись с манифестом ----------
    def sync_generated(self, plan):
        mp = self.root / MANIFEST
        try:
            old = json.loads(mp.read_text()).get("files", {}) if mp.is_file() else {}
        except (json.JSONDecodeError, AttributeError):
            self.warn.append(f"{MANIFEST}: не разобран — считаю пустым")
            old = {}
        new = {}
        foreign = self.foreign_groups(plan, old)
        shown = set()
        for dest, data, src, src_rel in plan:
            p = self.root / dest
            h = sha(data)
            cur = p.read_bytes() if p.is_file() else None
            g = self.group(dest)
            if g in foreign:  # файл/скилл проекта (не создан init): не трогаем никогда, даже с --force
                if g not in shown:
                    shown.add(g)
                    self.row(g, "пропущен", foreign[g])
                continue
            if cur is None:
                st, write = "создан", True
            elif cur == data:
                st, write = "без изменений", False
            elif old.get(dest) == sha(cur) or self.a.force:
                st, write = "обновлён" + (" (--force)" if old.get(dest) != sha(cur) else ""), True
            else:
                self.row(dest, "пропущен", SKIPPED.format(src=src_rel))
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
                self.row(dest, "пропущен", "нет в источнике, но изменён вручную — удалите сами или --force")
                new[dest] = old[dest]
                continue
            self.row(dest, "удалён", "нет в источнике")
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
        """Единица владения: скилл — каталог .claude/skills/<имя>/, остальное — файл."""
        parts = dest.split("/")
        if parts[:2] == [".claude", "skills"] and len(parts) > 3:
            return "/".join(parts[:3]) + "/"
        return dest

    def foreign_groups(self, plan, old):
        """{группа: примечание} — уже есть в проекте, не в манифесте init и отличается от того, что init записал бы."""
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
                    out[g] = "скилл проекта (не создан init) — не трогаю"
                continue
            p = self.root / dest
            if p.is_file() and dest not in old and p.read_bytes() != want[dest]:
                out[g] = ("агент проекта; роль: см. roles в конфиге" if dest.startswith(".claude/agents/")
                          else "файл проекта (не создан init) — не трогаю")
        return out

    # ---------- слияние с чужими файлами ----------
    def put_text(self, rel, old, new, note=""):
        if old == new:
            self.row(rel, "без изменений", note)
            return
        self.row(rel, "создан" if old is None else "обновлён", note)
        if not self.dry:
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(new, encoding="utf-8")

    def claude_md(self):
        f = DIST / "templates" / "claude-md.md"
        block = f"{BEGIN}\n{self.render(f.read_text(encoding='utf-8'), relp(f, self.root)).strip()}\n{END}"
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
                    self.warn.append(f"CLAUDE.md: маркеры {BEGIN}/{END} не парны — блок дописан в конец")
                new = old.rstrip("\n") + ("\n\n" if old.strip() else "") + block + "\n"
        self.put_text("CLAUDE.md", old, new, "блок dpcli")

    def settings(self):
        p = self.root / ".claude" / "settings.json"
        old = p.read_text(encoding="utf-8") if p.is_file() else None
        try:
            data = json.loads(old) if old and old.strip() else {}
        except json.JSONDecodeError as e:
            raise DpError(f".claude/settings.json: неверный JSON ({e}) — поправьте файл")
        if not isinstance(data, dict):
            raise DpError(".claude/settings.json: ожидался объект")
        perm = f"Bash({self.cli} *)"
        allow = data.setdefault("permissions", {}).setdefault("allow", [])
        if perm in allow:
            self.row(".claude/settings.json", "без изменений", perm)
            return
        allow.append(perm)
        self.put_text(".claude/settings.json", old, json.dumps(data, ensure_ascii=False, indent=2) + "\n", perm)

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
            self.row(".gitignore", "без изменений")
            return
        base = old or ""
        new = base + ("\n" if base and not base.endswith("\n") else "") + "\n".join(add) + "\n"
        self.put_text(".gitignore", old, new, "+ " + " ".join(add))

    # ---------- запуск ----------
    def run(self):
        self.ensure_config()
        self.vals = self.values()
        plan = self.plan_agents() + self.plan_skills() + self.plan_workflow()
        self.sync_generated(plan)
        self.claude_md()
        self.settings()
        self.gitignore()
        for w in self.warn:
            print(f"dpcli: предупреждение: {w}", file=sys.stderr)
        if self.a.check:
            bad = [r for r in self.rows if r[1] != "без изменений"]
            for path, st, note in bad:
                print(f"{path}: {st}" + (f" — {note}" if note else ""))
            print(f"init --check: {'нужен ' + self.cli + ' init' if bad else '.claude актуален'}")
            return 1 if bad else 0
        w = max(len(r[0]) for r in self.rows)
        if self.dry:
            print("init --dry-run: ничего не записано, что было бы сделано:")
        for path, st, note in self.rows:
            print(f"{path.ljust(w)}  {st}" + (f" — {note}" if note else ""))
        counts = {}
        for _, st, _ in self.rows:
            k = st.split(" (")[0]
            counts[k] = counts.get(k, 0) + 1
        print("Итого: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
        print(f"\nДальше: главная сессия читает {self.vals['workflow']}; модуль — "
              f"`{self.cli} module new <модуль> --code XX`, затем задачи — `{self.cli} task new …` "
              f"(справка `{self.cli} -h`). Агенты и процесс правятся в .dpcli/, затем снова `{self.cli} init`.")
        return 0


def cmd_init(a):
    return Init(a).run()


def register(sp):
    q = sp.add_parser("init", help="настроить Claude Code в проекте: агенты, скиллы, процесс, CLAUDE.md, разрешения (идемпотентно)")
    q.add_argument("--dry-run", action="store_true", help="ничего не писать, только показать таблицу действий")
    q.add_argument("--force", action="store_true", help="перезаписать/удалить и вручную изменённые файлы из манифеста init (файлы проекта — никогда)")
    q.add_argument("--check", action="store_true", help="только проверить, что .claude актуален (код 1 — нужен init; для CI)")
    g = q.add_mutually_exclusive_group()
    g.add_argument("--yaml", action="store_true", help="создать конфиг dpcli.yml из примера (по умолчанию)")
    g.add_argument("--json", action="store_true", help="создать конфиг dpcli.json из значений по умолчанию")
    q.set_defaults(func=cmd_init)
