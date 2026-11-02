"""dpcli docs: documentation registry and checks (frontmatter, index, registries, search).

  docs check                          frontmatter, summary, live md links, size (exit 1 on errors)
  docs index                          build {docs_dir}/INDEX.md and registries {docs_dir}/registry/<docs.registries>.md
  docs find [--type T] [--status S] [--module M] [--long] [text]   one line per document: path - summary
  docs show <path>                    frontmatter + table of contents (no body)
  docs section <path> [section]       numbered table of contents or section text (number or heading prefix)
  docs findings [text] [--module M]   excerpts from {docs_dir}/registry/findings.md and *-findings.md
  docs init [--dry]                   add frontmatter to files without it (heuristics from path and text)

Frontmatter schema (YAML, values are JSON strings/lists):
  type: guide|plan|contract|research|reference|journal|registry   (config key docs.types)
  status: active|idea|postponed|closed|superseded                 (docs.statuses)
  module, area (from the areas key; required for plan/contract/journal of a module if areas is set),
  updated (YYYY-MM-DD), summary (finding/purpose, 1 line <= docs.summary_max), related: []
  research: conclusion, data, applied_in;  contract: contracts: [{id, version}]
  generated: true - file is built by a command (size check skipped, do not edit by hand)
  archive - on a journal from deliver: git tag/ref with the module's full journal
Size: > docs.max_kb is an error (docs.max_kb_mode: warn makes it a warning); archive and generated are not checked.
Check scope: {docs_dir}/**/*.md + docs.extra (globs from root), minus docs.exclude (default {docs_dir}/archive/**)
and dpcli module directories in plan_dir (with module.json).
"""
import datetime
import fnmatch
import json
import re
import subprocess
from pathlib import Path

from .. import config, yamlmini
from ..mdsec import headings, match_sections, section_body, toc
from ..util import CLI, DpError, lang_text, short

DEFAULT_TYPES = ["guide", "plan", "contract", "research", "reference", "journal", "registry"]
DEFAULT_STATUSES = ["active", "idea", "postponed", "closed", "superseded"]
DEFAULT_MAX_KB = 40
DEFAULT_SUMMARY_MAX = 140
DEFAULT_REGISTRIES = ["research", "contracts"]
KNOWN_REGISTRIES = ["research", "contracts", "decisions"]
SUMMARY_TODO = "TODO"


# ---------- config and root ----------
def _cfg():
    """docs settings as a dict with defaults; project root is the git toplevel (or cwd)."""
    c = {}
    if config is not None:
        try:
            c = config.load() or {}
        except DpError:
            raise
        except Exception:
            c = {}
    d = c.get("docs") if isinstance(c.get("docs"), dict) else {}

    def lst(v, default):
        if v is None:
            return list(default)
        return [v] if isinstance(v, str) else list(v)

    docs_dir = str(c.get("docs_dir") or "docs").strip("/")
    return {
        "docs_dir": docs_dir,
        "plan_dir": str(c.get("plan_dir") or f"{docs_dir}/plan").strip("/"),
        "contracts_dir": str(c.get("contracts_dir") or f"{docs_dir}/contracts").strip("/"),
        "extra": lst(d.get("extra"), []),
        "exclude": lst(d.get("exclude"), [f"{docs_dir}/archive/**"]),
        "types": lst(d.get("types"), DEFAULT_TYPES),
        "statuses": lst(d.get("statuses"), DEFAULT_STATUSES),
        "max_kb": float(d.get("max_kb") or DEFAULT_MAX_KB),
        "max_kb_mode": str(d.get("max_kb_mode") or "error").strip().lower(),
        "summary_max": int(d.get("summary_max") or DEFAULT_SUMMARY_MAX),
        "registries": lst(d.get("registries"), DEFAULT_REGISTRIES),
        "areas": lst(c.get("areas"), []),
    }


def _root():
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else Path.cwd()


class Ctx:
    def __init__(self, root=None):
        self.c = _cfg()
        self.root = Path(root) if root else _root()
        self.docs = self.root / self.c["docs_dir"]
        if self.c["max_kb_mode"] not in ("error", "warn"):
            raise DpError(f"docs.max_kb_mode: '{self.c['max_kb_mode']}' - must be error or warn")

    @property
    def index_path(self):
        return f"{self.c['docs_dir']}/INDEX.md"

    @property
    def reg(self):
        return f"{self.c['docs_dir']}/registry"

    @property
    def archive(self):
        return f"{self.c['docs_dir']}/archive"

    def need_docs(self):
        if not self.docs.is_dir():
            raise DpError(f"no docs directory {self.c['docs_dir']}/ (key docs_dir) in {self.root}")


# ---------- frontmatter ----------
def split_fm(text):
    """-> (dict|None, body). YAML via yamlmini (block and inline lists); if that fails, flat parse of 'key: JSON|string'."""
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---", 4)
    if end < 0:
        return None, text
    fm = _yaml_fm(text[4:end])
    if fm is None:
        fm = _flat_fm(text[4:end])
    rest = text[end + 4:]
    return fm, rest[1:] if rest.startswith("\n") else rest


def _yaml_fm(block):
    try:
        fm = yamlmini.loads(block, use_pyyaml=False)  # no PyYAML: dates stay strings
    except (yamlmini.YamlError, ValueError):
        return None
    return fm if isinstance(fm, dict) else None


def _flat_fm(block):
    fm = {}
    for line in block.split("\n"):
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if not m:
            continue
        v = m.group(2).strip()
        try:
            fm[m.group(1)] = json.loads(v) if v else ""
        except ValueError:
            fm[m.group(1)] = v.strip("'\"")
    return fm


ORDER = ["type", "status", "module", "area", "updated", "summary", "related", "conclusion", "data", "applied_in", "contracts", "archive", "generated"]


def dump_fm(fm):
    keys = [k for k in ORDER if k in fm] + [k for k in fm if k not in ORDER]
    return "---\n" + "".join(f"{k}: {json.dumps(fm[k], ensure_ascii=False)}\n" for k in keys) + "---\n"


def read(p):
    return Path(p).read_text(encoding="utf-8")


# ---------- scope ----------
def scope(x, archive=False):
    """Files under check; archive=True adds {docs_dir}/archive/** (even if excluded)."""
    seen, out = set(), []
    cands = sorted(x.docs.rglob("*.md"))
    for g in x.c["extra"]:
        cands += sorted(x.root.glob(g))
    plan = x.c["plan_dir"]
    for p in cands:
        if not p.is_file():
            continue
        try:
            r = p.relative_to(x.root).as_posix()
        except ValueError:
            continue
        if r in seen or not r.endswith(".md"):
            continue
        seen.add(r)
        if any(fnmatch.fnmatch(r, g) for g in x.c["exclude"]) and not (archive and _under(r, x.archive)):
            continue
        parts = r.split("/")
        pp = plan.split("/")
        if r.startswith(plan + "/") and len(parts) > len(pp) + 1 and (x.root / plan / parts[len(pp)] / "module.json").exists():
            continue  # dpcli module data directory
        out.append(r)
    return out


def docs_all(x, archive=False):
    return [(r, *split_fm(read(x.root / r))) for r in scope(x, archive)]


# ---------- check ----------
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE = re.compile(r"```.*?```", re.S)


def check_links(x, r, body):
    bad = []
    body = FENCE.sub("", body)
    body = re.sub(r"`[^`\n]*`", "", body)
    for t in LINK.findall(body):
        if re.match(r"^[a-z][a-z0-9+.-]*:|^#", t):
            continue
        p = t.split("#")[0].split("?")[0]
        if not p:
            continue
        tgt = x.root / p[1:] if p.startswith("/") else (x.root / r).parent / p
        if not tgt.exists():
            bad.append(t)
    return bad


def contract_ids(body):
    res = []
    for l in body.split("\n"):
        m = re.match(r"^##\s+([A-ZА-ЯЁ]+\d+[a-z]*)[.\s].*?(?:\bv|версия\s+|version\s+)(\d+)", l)
        if m:
            res.append({"id": m.group(1), "version": int(m.group(2))})
    return res


SUMMARY_HINT = "fill in summary: finding/purpose in one line"


def explicit_paths(x, args, in_scope):
    """Command-line paths (relative to cwd or root) -> root-relative paths: a file as is, a directory expands to scope files under it."""
    out = []
    for arg in args:
        p = Path(arg)
        cands = [p.resolve()] if p.is_absolute() else [(Path.cwd() / p).resolve(), (x.root / p).resolve()]
        found = next((c for c in cands if c.exists()), None)
        if found is None:
            raise DpError(f"docs check: no such path {arg}")
        try:
            r = found.relative_to(x.root.resolve()).as_posix()
        except ValueError:
            raise DpError(f"docs check: {arg} is outside the repo")
        got = [r] if found.is_file() else [f for f in in_scope if f.startswith(r.rstrip("/") + "/")] if r != "." else list(in_scope)
        if found.is_file() and not r.endswith(".md"):
            raise DpError(f"docs check: {arg} is not .md")
        out += [g for g in got if g not in out]
    return out


def cmd_check(x, a):
    x.need_docs()
    types, statuses, max_kb = x.c["types"], x.c["statuses"], x.c["max_kb"]
    err, warn = [], []
    items = docs_all(x)
    only = getattr(a, "paths", None)
    if only:
        items = [(r, *split_fm(read(x.root / r))) for r in explicit_paths(x, only, [i[0] for i in items])]
    for r, fm, body in items:
        if fm is None:
            err.append(f"{r}: no frontmatter")
            continue
        t, s = fm.get("type"), fm.get("status")
        if t is None:
            err.append(f"{r}: no type (one of {sorted(types)})")
        elif t not in types:
            err.append(f"{r}: type '{t}' not in {sorted(types)}")
        if s is None:
            err.append(f"{r}: no status (one of {sorted(statuses)})")
        elif s not in statuses:
            err.append(f"{r}: status '{s}' not in {sorted(statuses)}")
        summ = str(fm.get("summary", "")).strip()
        if not summ:
            err.append(f"{r}: no summary - {SUMMARY_HINT}")
        elif summ.upper() == SUMMARY_TODO:
            err.append(f"{r}: summary TODO — {SUMMARY_HINT}")
        elif "\n" in summ:
            err.append(f"{r}: summary spans several lines - {SUMMARY_HINT}")
        elif len(summ) > x.c["summary_max"]:
            err.append(f"{r}: summary {len(summ)} chars > {x.c['summary_max']} - shorten to a one-line finding/purpose")
        if not fm.get("updated"):
            warn.append(f"{r}: no updated")
        areas, area = x.c["areas"], fm.get("area")
        if areas and area and area not in areas:
            err.append(f"{r}: area '{area}' not in {areas}")
        elif areas and not area and fm.get("module") and t in ("plan", "contract", "journal"):
            err.append(f"{r}: module document has no area (one of {areas})")
        if not isinstance(fm.get("related", []), list):
            err.append(f"{r}: related is not a list")
        if t == "research":
            for k in ("conclusion", "data", "applied_in"):
                if k not in fm:
                    warn.append(f"{r}: research has no key {k}")
        if t == "contract":
            c = fm.get("contracts")
            if not isinstance(c, list):
                err.append(f"{r}: contract has no contracts list")
            else:
                live = {y["id"]: y["version"] for y in contract_ids(body)}
                have = {y.get("id"): y.get("version") for y in c if isinstance(y, dict)}
                if live and live != have:
                    warn.append(f"{r}: frontmatter contracts differ from headings (docs init --refresh-contracts)")
        for rel in fm.get("related", []) if isinstance(fm.get("related"), list) else []:
            if not (x.root / rel).exists():
                err.append(f"{r}: related -> no file {rel}")
        for t_ in check_links(x, r, body):
            err.append(f"{r}: broken link {t_}")
        kb = (x.root / r).stat().st_size / 1024
        if kb > max_kb and not fm.get("generated") and not _under(r, x.archive):
            (warn if x.c["max_kb_mode"] == "warn" else err).append(
                f"{r}: {kb:.0f} KB > {max_kb:g} KB - split into section files or move the data out")
    for e in err:
        print("ERROR    " + e)
    for w in warn:
        print("WARNING  " + w)
    print(f"docs check: files {len(items)}, errors {len(err)}, warnings {len(warn)}")
    return 1 if err else 0


# ---------- init (heuristics) ----------
def first_para(body):
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    for para in re.split(r"\n\s*\n", body):
        lines = [l.strip() for l in para.strip().split("\n")]
        if not lines or not lines[0] or lines[0].startswith(("#", "|", "```", "---", "![", "<", "- [")):
            continue
        t = " ".join(l.lstrip("> ").lstrip("-* ").strip() for l in lines)
        t = re.sub(r"\*\*|`|\[([^\]]*)\]\([^)]*\)", lambda m: m.group(1) or "", t)
        t = re.sub(r"\s+", " ", t).strip()
        if len(t) < 12 or re.match(r"^(План\b|Внутренний документ|Статус:|Ветка |Задача |Требования:|[0-9.]+\s+Статус|Plan\b|Internal document|Status:|Branch |Task |Requirements:|[0-9.]+\s+Status)", t):
            continue
        m = re.match(r"(.{40,}?[.!?])(\s|$)", t)
        t = m.group(1) if m and len(m.group(1)) <= 230 else t
        return (t[:227] + "…") if len(t) > 230 else t
    return ""


def conclusion_of(body):
    m = re.search(r"^#{2,4}\s+[^\n]*(?:Итог|Вывод|Резюме|Заключение|Результат|Summary|Conclusion|Result|Outcome|Takeaway)[^\n]*\n(.*?)(?=^#{1,4}\s|\Z)", body, re.S | re.M | re.I)
    return first_para(m.group(1)) if m else ""


def git_date(x, r):
    try:
        return subprocess.run(["git", "log", "-1", "--format=%cs", "--", r], cwd=x.root, capture_output=True, text=True).stdout.strip()
    except OSError:
        return ""


def _under(r, d):
    return r.startswith(d.rstrip("/") + "/")


def default_fm(x, r, body):
    dd, c = x.c["docs_dir"], x.c
    name = Path(r).name
    if _under(r, c["contracts_dir"]):
        t = "contract"
    elif _under(r, f"{dd}/guide"):
        t = "guide"
    elif _under(r, f"{dd}/research") or "research" in Path(r).parts[:-1]:
        t = "research"
    elif _under(r, c["plan_dir"]):
        t = "journal" if name.endswith("_progress.md") else "plan"
    elif _under(r, f"{dd}/registry") or r == f"{dd}/INDEX.md":
        t = "registry"
    else:
        t = "guide"
    t = t if t in c["types"] else (c["types"][0] if c["types"] else t)
    st = "active" if t in ("guide", "contract", "reference", "registry") else "closed"
    st = st if st in c["statuses"] else (c["statuses"][0] if c["statuses"] else st)
    fm = {"type": t, "status": st}
    mod = ""
    if _under(r, c["contracts_dir"]):
        mod = Path(r).stem
    elif _under(r, c["plan_dir"]):
        sub = r[len(c["plan_dir"]) + 1:].split("/")
        mod = sub[0] if len(sub) > 1 else ""
    fm["module"] = mod
    fm["updated"] = git_date(x, r) or datetime.date.today().isoformat()
    fm["summary"] = SUMMARY_TODO  # do not invent from the text: the author fills it in (docs check flags TODO)
    fm["related"] = []
    if t == "research":
        fm["conclusion"] = conclusion_of(body)
        fm["data"] = ""
        fm["applied_in"] = ""
    if t == "contract":
        fm["contracts"] = contract_ids(body)
    if r == x.index_path or _under(r, x.reg):
        fm["generated"] = r != f"{x.reg}/findings.md"
        if not fm["generated"]:
            del fm["generated"]
    return fm


def cmd_init(x, a):
    x.need_docs()
    n = 0
    for r in scope(x):
        p = x.root / r
        fm, body = split_fm(read(p))
        if fm is not None:
            if a.refresh_contracts and fm.get("type") == "contract":
                fm["contracts"] = contract_ids(body)
                p.write_text(dump_fm(fm) + body, encoding="utf-8")
            continue
        fm = default_fm(x, r, body)
        n += 1
        if a.dry:
            print(r, fm["type"], fm["status"], fm["module"] or "-")
        else:
            p.write_text(dump_fm(fm) + body, encoding="utf-8")
    print(f"frontmatter added: {n}" + (f"; fill in summary (now TODO), list: {CLI} docs check" if n and not a.dry else ""))
    return 0


# ---------- find / show / section / findings ----------
FIND_WIDTH = 160


def cmd_find(x, a):
    x.need_docs()
    q = (a.text or "").lower()
    n = 0
    arch = a.archive or a.status in ("closed", "superseded")  # closed docs are searched in the archive too
    for r, fm, body in docs_all(x, arch):
        if fm is None:
            continue
        if a.type and fm.get("type") != a.type or a.status and fm.get("status") != a.status or a.module and fm.get("module") != a.module:
            continue
        if a.area and fm.get("area") != a.area:
            continue
        hay = " ".join([r, str(fm.get("summary", "")), str(fm.get("conclusion", "")), str(fm.get("module", ""))]).lower()
        if q and not all(w in hay for w in q.split()):
            continue
        summ = str(fm.get("summary", ""))
        if a.long:
            print(f"{r} — {fm.get('type')} — {fm.get('status')} — {summ[:160]}")
        else:
            print(short(f"{r} — {summ}", FIND_WIDTH))
        n += 1
    if not n:
        print("nothing found")
    return 0


def _doc_path(x, path):
    p = Path(path)
    if not p.is_absolute() and not p.exists():
        p = x.root / path
    if not p.is_file():
        raise DpError("no such file: " + path)
    return p


def cmd_show(x, a):
    p = _doc_path(x, a.path)
    fm, body = split_fm(read(p))
    print(dump_fm(fm).rstrip() if fm else "(no frontmatter)")
    print()
    for i, l in enumerate(body.split("\n"), 1):
        if re.match(r"^#{1,4}\s", l):
            print(f"{l}   (line {i})")
    return 0


def cmd_section(x, a):
    path, sec = a.path, a.section
    if sec is None and "#" in path and not Path(path).exists():
        path, sec = path.split("#", 1)  # reference of the form path#section
    p = _doc_path(x, path)
    _, body = split_fm(read(p))
    lines, heads = headings(body)
    if not sec:
        print(f"{path}: {len(lines)} lines; {CLI} docs section {path} <number|heading prefix>")
        for t in toc(lines, heads, a.depth):
            print(t)
        if not heads:
            print("(no headings)")
        return 0
    cands = match_sections(heads, sec)
    if not cands:
        raise DpError(f"section '{sec.strip()}' not found; table of contents: {CLI} docs section {path}")
    if len(cands) > 1:
        print(f"section '{sec.strip()}' is ambiguous, give a number:")
        for n in cands:
            _, lvl, t = heads[n]
            print(f"{n + 1:>3} {'  ' * (lvl - 1)}{short(t, 90)}")
        return 1
    print("\n".join(section_body(lines, heads, cands[0], a.max)))
    return 0


def cmd_findings(x, a):
    rel = f"{x.reg}/findings.md"
    p = x.root / rel
    if not p.exists():
        raise DpError(f"no {rel} (the findings registry is written by hand)")
    # the registry hits the size limit, so sections move to <name>-findings.md alongside; read those too
    q, n = (a.text or "").lower(), 0
    for f in [p] + sorted(p.parent.glob("*-findings.md")):
        fm, body = split_fm(read(f))
        mod = "" if f == p else str(fm.get("module") or "")  # before the first '## ' the module comes from frontmatter
        for l in body.split("\n"):
            if l.startswith("## "):
                mod = l[3:].strip()
            elif l.startswith("- ") and (not a.module or mod == a.module) and (not q or all(w in l.lower() for w in q.split())):
                print(f"[{mod}] {l[2:]}")
                n += 1
    if not n:
        print("nothing found")
    return 0


# ---------- index ----------
GEN_HEAD = lang_text("File built by `docs index`; do not edit by hand.\n\n", "Файл собран `docs index` — руками не править.\n\n")
TYPE_TITLES = {"guide": lang_text("System guides", "Описания систем"), "plan": lang_text("Plans", "Планы"),
               "contract": lang_text("Interface contracts", "Контракты стыков"), "research": lang_text("Research", "Исследования"),
               "reference": lang_text("Reference", "Справка"), "journal": lang_text("Journals", "Журналы"),
               "registry": lang_text("Registries", "Реестры")}


def write_gen(x, path, title, summary, body, head=GEN_HEAD, updated=None):
    """updated is the latest date of the source documents, not today: two branches with the same documents
    build the same file, so merges do not conflict for nothing."""
    fm = {"type": "registry", "status": "active", "module": "", "updated": updated or datetime.date.today().isoformat(),
          "summary": summary, "related": [], "generated": True}
    (x.root / path).parent.mkdir(parents=True, exist_ok=True)
    (x.root / path).write_text(dump_fm(fm) + f"\n# {title}\n\n" + head + body, encoding="utf-8")


def _link(frm, r):
    """Relative link from file frm (root-relative) to r (root-relative)."""
    import os.path
    return os.path.relpath(r, os.path.dirname(frm) or ".")


def index_line(x, r, fm):
    st = fm.get("status")
    mark = f" [{st}]" if st and st != "active" else ""
    summ = " ".join(str(fm.get("summary", "")).split())
    return f"- [{r}]({_link(x.index_path, r)}) — {summ}{mark}"


def module_groups(x, items):
    """Modules by plans {plan_dir}/<m>.md: {module: {plan, docs: [(r, fm)], area}}; a module document has module in frontmatter
    or a path {plan_dir}/<m>/...; area comes from the plan, else from any module document."""
    plan = x.c["plan_dir"]
    mods = {}
    for r, fm, _ in items:
        if r.startswith(plan + "/") and r.count("/") == plan.count("/") + 1 and fm.get("type") == "plan":
            mods[Path(r).stem] = {"plan": (r, fm), "docs": []}
    for r, fm, _ in items:
        m = fm.get("module")
        if m not in mods and r.startswith(plan + "/"):
            m = r[len(plan) + 1:].split("/")[0]
        if m in mods and r != mods[m]["plan"][0]:
            mods[m]["docs"].append((r, fm))
    for m, g in mods.items():
        g["area"] = g["plan"][1].get("area") or next((fm.get("area") for _, fm in g["docs"] if fm.get("area")), None)
    return mods


def module_line(x, mod, g):
    """Module line: plan summary, status and date; links to plan, contracts, decisions, summary; journal archive tag."""
    r, fm = g["plan"]
    plan, contracts = x.c["plan_dir"], x.c["contracts_dir"]
    named = {f"{plan}/{mod}/decisions.md": "decisions", f"{plan}/{mod}/summary.md": "summary", f"{contracts}/{mod}.md": "contracts"}
    labels = {"contracts": lang_text("contracts", "контракты"), "decisions": lang_text("decisions", "решения"),
              "summary": lang_text("summary", "сводка")}
    links = [f"[{lang_text('plan', 'план')}]({_link(x.index_path, r)})"]
    rest, archive = [], None
    for k in ("contracts", "decisions", "summary"):
        links += [f"[{labels[k]}]({_link(x.index_path, d)})" for d, _ in g["docs"] if named.get(d) == k]
    for d, dfm in g["docs"]:
        archive = archive or dfm.get("archive")
        if d not in named:
            rest.append(index_line(x, d, dfm))
    st = " ".join(x_ for x_ in (fm.get("status") or "", str(fm.get("updated") or "")) if x_)
    summ = " ".join(str(fm.get("summary", "")).split())
    line = f"- **{mod}** — {summ} [{st}] — " + " · ".join(links) + (f" · " + lang_text(f"full journal: `{archive}`", f"полный журнал: `{archive}`") if archive else "")
    return [line] + [f"  {l}" for l in rest]


def cmd_index(x, a):
    x.need_docs()
    dd = x.c["docs_dir"]
    fp = x.root / x.reg / "findings.md"
    if not fp.exists():  # INDEX.md links to the findings registry: a stub (written by hand afterwards)
        fm = {"type": "registry", "status": "active", "module": "", "updated": datetime.date.today().isoformat(),
              "summary": lang_text("Findings registry: what we know, by module (written by hand).", "Реестр выводов: что мы знаем, по модулям (пишется вручную)."), "related": []}
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(dump_fm(fm) + lang_text(
            "\n# Findings registry\n\nPer module: a `## <module>` section; a finding is a `- ...` item "
            "(one line: the finding with numbers and a `path#section` link). Search: `docs findings`.\n",
            "\n# Реестр выводов\n\nПо модулю — раздел `## <модуль>`, вывод — пункт `- …` "
            "(одна строка: вывод с числами и ссылка `путь#раздел`). Поиск — `docs findings`.\n"), encoding="utf-8")
    regs = [k for k in x.c["registries"] if k in KNOWN_REGISTRIES]
    items = [(r, fm, body) for r, fm, body in docs_all(x) if fm is not None and r not in generated_paths(x)]
    upd = max((str(fm.get("updated") or "") for _, fm, _ in items), default="") or None

    out = []
    mods = module_groups(x, items)
    in_mod = {r for g in mods.values() for r in [g["plan"][0]] + [d for d, _ in g["docs"]]}
    found = {g["area"] for g in mods.values()}
    order = [ar for ar in x.c["areas"] if ar in found] + sorted(ar for ar in found if ar and ar not in x.c["areas"])
    order += [None] if None in found else []
    if mods:
        out.append(lang_text("Modules by area, then by plan date: one line per module, its other documents below.\n",
                             "Модули — по подпроектам (area), внутри — по дате плана: строка на модуль, под ней — его прочие документы.\n"))
    for ar in order:
        rows = sorted(((m, g) for m, g in mods.items() if g["area"] == ar), key=lambda mg: (str(mg[1]["plan"][1].get("updated") or ""), mg[0]))
        out.append(f"## {ar or lang_text('Modules without area', 'Модули без area')}\n")
        for m, g in rows:
            out += module_line(x, m, g)
        out.append("")

    types = list(x.c["types"])
    groups = {}
    for r, fm, _ in items:
        if r in in_mod:
            continue
        t = fm.get("type")
        groups.setdefault(t if t in types else None, []).append((r, fm))
    if groups and mods:
        out.append(lang_text("## Other documents\n", "## Прочие документы\n"))
    lvl = "###" if mods else "##"
    for t in types + [None]:
        rows = groups.get(t)
        if not rows:
            continue
        out.append(f"{lvl} {TYPE_TITLES.get(t, t) + f' ({t})' if t in TYPE_TITLES else (t or lang_text('Other', 'Прочее'))}\n")
        out += [index_line(x, r, fm) for r, fm in rows]
        out.append("")
    arch = x.root / x.archive
    if arch.is_dir():
        n = len(list(arch.rglob("*.md")))
        out.append(lang_text(f"archive: {n} documents: `{CLI} docs find --status closed`\n", f"архив: {n} документов — `{CLI} docs find --status closed`\n"))
    findings = _link(x.index_path, f"{x.reg}/findings.md")
    head = lang_text(
        f"Entry point; do not edit by hand (`{CLI} docs index`). Read piece by piece, not whole:\n"
        f"- find: `{CLI} docs find <words>` (path - summary), findings: `{CLI} docs findings <words>` "
        f"([findings registry]({findings})), module journals: `{CLI} search`;\n"
        f"- read: `{CLI} docs section <path>` (table of contents), then `{CLI} docs section <path> <number|heading>`.\n\n",
        f"Точка входа; руками не править (`{CLI} docs index`). Читать по кусочку, не целиком:\n"
        f"- найти — `{CLI} docs find <слова>` (путь — summary), выводы — `{CLI} docs findings <слова>` "
        f"([реестр выводов]({findings})), журналы модулей — `{CLI} search`;\n"
        f"- читать — `{CLI} docs section <путь>` (оглавление), затем `{CLI} docs section <путь> <номер|заголовок>`.\n\n")
    write_gen(x, x.index_path, lang_text("Documentation index", "Индекс документации"),
              lang_text(f"Entry point: {dd}/ modules by area, other documents by type.",
                        f"Точка входа: модули {dd}/ по подпроектам, прочие документы по типам."),
              "\n".join(out), head, upd)
    made = ["INDEX.md"]

    if "research" in regs:
        rows = []
        for r, fm, body in items:
            if fm.get("type") != "research":
                continue
            concl = " ".join(str(fm.get("conclusion") or fm.get("summary", "")).split())
            extra = "; ".join(f"{k}: {short(fm[k], 80)}" for k in ("data", "applied_in") if str(fm.get(k, "")).strip())
            rows.append(f"- [{r}]({_link(x.reg + '/research.md', r)}) — {short(concl, 200)}" + (f" ({extra})" if extra else ""))
        write_gen(x, f"{x.reg}/research.md", lang_text("Research registry", "Реестр исследований"),
                  lang_text("Research: finding, data, where applied.", "Исследования: вывод, данные, где применено."),
                  "\n".join(rows) + "\n", updated=upd)
        made.append("research")

    if "contracts" in regs:
        rows = []
        for r, fm, body in items:
            if fm.get("type") == "contract":
                cs = ", ".join(f"{k['id']} v{k['version']}" for k in fm.get("contracts", []) if isinstance(k, dict))
                rows.append(f"- {fm.get('module') or '-'}: {cs or '—'} — [{r}]({_link(x.reg + '/contracts.md', r)})")
        write_gen(x, f"{x.reg}/contracts.md", lang_text("Contracts registry", "Реестр контрактов"),
                  lang_text("Interface contracts by module: ids and versions from headings.", "Контракты стыков по модулям: id и версии из заголовков."),
                  "\n".join(rows) + "\n", updated=upd)
        made.append("contracts")

    total = 0
    if "decisions" in regs:  # duplicates module journals; off by default (decisions are found with `search`)
        drows = []
        for d in sorted((x.root / x.c["plan_dir"]).glob("*/decisions.jsonl")):
            recs = []
            for l in d.read_text(encoding="utf-8").splitlines():
                try:
                    recs.append(json.loads(l))
                except ValueError:
                    pass
            recs = [k for k in recs if isinstance(k, dict)]
            if not recs:
                continue
            drows.append(f"## {d.parent.name}\n")
            for k in sorted(recs, key=lambda k: str(k.get("t", ""))):
                txt = " ".join(str(k.get("text", "")).split())
                why = " ".join(str(k.get("why", "")).split())
                drows.append(f"- {str(k.get('t', ''))[:10]} {k.get('kind', 'decision')}: {txt[:400]}" + (f" - {lang_text('why', 'почему')}: {why[:240]}" if why else ""))
                total += 1
            drows.append("")
        write_gen(x, f"{x.reg}/decisions.md", lang_text("Decisions registry", "Реестр решений"),
                  lang_text(f"Module decisions from decisions.jsonl ({total} records).", f"Решения модулей из decisions.jsonl ({total} записей)."), "\n".join(drows),
                  updated=upd)
        made.append(f"decisions ({total})")
    print(f"docs index: {', '.join(made)}")
    return 0


def generated_paths(x):
    """Files built by docs index (root-relative)."""
    return {x.index_path} | {f"{x.reg}/{k}.md" for k in KNOWN_REGISTRIES}


def resolve_generated(root, files):
    """Merge conflict only in docs index files -> rebuild them, git add; -> True. Otherwise touch nothing -> False.
    The index is a function of the documents: with parallel branches (coordinators in one feature branch, feature
    branches into main) it always conflicts, and the only right resolution is to rebuild from the merged documents."""
    files = [f for f in files if f]
    x = Ctx(root)
    if not files or not set(files) <= generated_paths(x) or not x.docs.is_dir():
        return False
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        cmd_index(x, None)
    gen = sorted(set(files) | {g for g in generated_paths(x) if (x.root / g).exists()})
    r = subprocess.run(["git", "add", "--", *gen], cwd=root, capture_output=True, text=True)
    return r.returncode == 0


# ---------- registration ----------
def _run(fn):
    def run(a):
        return fn(Ctx(), a) or 0
    return run


def register(sp):
    p = sp.add_parser("docs", help="documentation registry and checks: check|index|find|show|section|findings|init")
    ds = p.add_subparsers(dest="docs_cmd", required=True)
    q = ds.add_parser("check", help="frontmatter, summary, links, size (optionally only given files/directories)")
    q.add_argument("paths", nargs="*", metavar="PATH", help="check only these files (a directory means all documents under it)")
    q.set_defaults(func=_run(cmd_check))
    ds.add_parser("index", help="build INDEX.md and registries (docs.registries)").set_defaults(func=_run(cmd_index))
    q = ds.add_parser("find", help="find documents: line 'path - summary'")
    q.add_argument("text", nargs="?")
    q.add_argument("--type")
    q.add_argument("--status", help="closed/superseded are searched in the archive too")
    q.add_argument("--module")
    q.add_argument("--area")
    q.add_argument("--archive", action="store_true", help="search the archive too")
    q.add_argument("--long", action="store_true", help="path - type - status - summary")
    q.set_defaults(func=_run(cmd_find))
    q = ds.add_parser("show", help="frontmatter and table of contents")
    q.add_argument("path")
    q.set_defaults(func=_run(cmd_show))
    q = ds.add_parser("section", help="document table of contents or a section (number or heading prefix)")
    q.add_argument("path", metavar="PATH[#SECTION]")
    q.add_argument("section", nargs="?")
    q.add_argument("--depth", type=int, default=3, help="heading levels in the table of contents (3)")
    q.add_argument("--max", type=int, default=0, help="section lines (0 for all)")
    q.set_defaults(func=_run(cmd_section))
    q = ds.add_parser("findings", help="findings from registry/findings.md and *-findings.md")
    q.add_argument("text", nargs="?")
    q.add_argument("--module")
    q.set_defaults(func=_run(cmd_findings))
    q = ds.add_parser("init", help="add frontmatter to files without it (summary: TODO)")
    q.add_argument("--dry", action="store_true")
    q.add_argument("--refresh-contracts", action="store_true")
    q.set_defaults(func=_run(cmd_init))
    return p
