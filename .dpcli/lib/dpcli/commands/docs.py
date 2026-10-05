"""dpcli docs — реестр и проверка документации (frontmatter, индекс, реестры, поиск).

  docs check                          frontmatter, живые md-ссылки, размер (код 1 при ошибках)
  docs index                          собрать {docs_dir}/INDEX.md и {docs_dir}/registry/{research,contracts,decisions}.md
  docs find [--type T] [--status S] [--module M] [текст]   строка на документ
  docs show <путь>                    frontmatter + оглавление (без тела)
  docs findings [текст] [--module M]  выдержки из {docs_dir}/registry/findings.md
  docs init [--dry]                   дописать frontmatter файлам без него (эвристики по пути и тексту)

Схема frontmatter (YAML, значения — JSON-строки/списки):
  type: guide|plan|contract|research|reference|journal|registry   (ключ конфига docs.types)
  status: active|idea|postponed|closed|superseded                 (docs.statuses)
  module, updated (ГГГГ-ММ-ДД), summary (1 строка), related: []
  research: conclusion, data, applied_in;  contract: contracts: [{id, version}]
  generated: true — файл собирается командой (проверка размера пропускается, руками не править)
Область проверки: {docs_dir}/**/*.md + docs.extra (globs от корня), минус docs.exclude (по умолчанию {docs_dir}/archive/**)
и каталоги модулей dpcli в plan_dir (с module.json).
"""
import datetime
import fnmatch
import json
import re
import subprocess
from pathlib import Path

try:
    from .. import config
except ImportError:  # ядро пакета ещё не готово
    config = None
try:
    from ..util import DpError
except ImportError:
    class DpError(Exception):
        pass

DEFAULT_TYPES = ["guide", "plan", "contract", "research", "reference", "journal", "registry"]
DEFAULT_STATUSES = ["active", "idea", "postponed", "closed", "superseded"]
DEFAULT_MAX_KB = 40


# ---------- конфиг и корень ----------
def _cfg():
    """Настройки docs в виде словаря с умолчаниями; корень проекта — toplevel git (или cwd)."""
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
    }


def _root():
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else Path.cwd()


class Ctx:
    def __init__(self):
        self.c = _cfg()
        self.root = _root()
        self.docs = self.root / self.c["docs_dir"]

    @property
    def index_path(self):
        return f"{self.c['docs_dir']}/INDEX.md"

    @property
    def reg(self):
        return f"{self.c['docs_dir']}/registry"

    def need_docs(self):
        if not self.docs.is_dir():
            raise DpError(f"нет каталога документов {self.c['docs_dir']}/ (ключ docs_dir) в {self.root}")


# ---------- frontmatter ----------
def split_fm(text):
    """-> (dict|None, тело). Только плоский YAML: key: JSON-значение или голая строка."""
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---", 4)
    if end < 0:
        return None, text
    fm = {}
    for line in text[4:end].split("\n"):
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if not m:
            continue
        v = m.group(2).strip()
        try:
            fm[m.group(1)] = json.loads(v) if v else ""
        except ValueError:
            fm[m.group(1)] = v.strip("'\"")
    rest = text[end + 4:]
    return fm, rest[1:] if rest.startswith("\n") else rest


ORDER = ["type", "status", "module", "updated", "summary", "related", "conclusion", "data", "applied_in", "contracts", "generated"]


def dump_fm(fm):
    keys = [k for k in ORDER if k in fm] + [k for k in fm if k not in ORDER]
    return "---\n" + "".join(f"{k}: {json.dumps(fm[k], ensure_ascii=False)}\n" for k in keys) + "---\n"


def read(p):
    return Path(p).read_text(encoding="utf-8")


# ---------- область ----------
def scope(x):
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
        if any(fnmatch.fnmatch(r, g) for g in x.c["exclude"]):
            continue
        parts = r.split("/")
        pp = plan.split("/")
        if r.startswith(plan + "/") and len(parts) > len(pp) + 1 and (x.root / plan / parts[len(pp)] / "module.json").exists():
            continue  # каталог данных модуля dpcli
        out.append(r)
    return out


def title_of(body, fallback):
    for l in body.split("\n"):
        if l.startswith("# "):
            return l[2:].strip()
    return fallback


def docs_all(x):
    return [(r, *split_fm(read(x.root / r))) for r in scope(x)]


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
        m = re.match(r"^##\s+([A-ZА-ЯЁ]+\d+[a-z]*)[.\s].*?(?:\bv|версия\s+)(\d+)", l)
        if m:
            res.append({"id": m.group(1), "version": int(m.group(2))})
    return res


def cmd_check(x, a):
    x.need_docs()
    types, statuses, max_kb = x.c["types"], x.c["statuses"], x.c["max_kb"]
    err, warn = [], []
    items = docs_all(x)
    for r, fm, body in items:
        if fm is None:
            err.append(f"{r}: нет frontmatter")
            continue
        t, s = fm.get("type"), fm.get("status")
        if t is None:
            err.append(f"{r}: нет type (одно из {sorted(types)})")
        elif t not in types:
            err.append(f"{r}: type '{t}' не из {sorted(types)}")
        if s is None:
            err.append(f"{r}: нет status (одно из {sorted(statuses)})")
        elif s not in statuses:
            err.append(f"{r}: status '{s}' не из {sorted(statuses)}")
        if not str(fm.get("summary", "")).strip():
            err.append(f"{r}: пустой summary")
        if "\n" in str(fm.get("summary", "")):
            err.append(f"{r}: summary в несколько строк")
        if not fm.get("updated"):
            warn.append(f"{r}: нет updated")
        if not isinstance(fm.get("related", []), list):
            err.append(f"{r}: related — не список")
        if t == "research":
            for k in ("conclusion", "data", "applied_in"):
                if k not in fm:
                    warn.append(f"{r}: у research нет ключа {k}")
        if t == "contract":
            c = fm.get("contracts")
            if not isinstance(c, list):
                err.append(f"{r}: у contract нет списка contracts")
            else:
                live = {y["id"]: y["version"] for y in contract_ids(body)}
                have = {y.get("id"): y.get("version") for y in c if isinstance(y, dict)}
                if live and live != have:
                    warn.append(f"{r}: contracts во frontmatter ≠ заголовкам (docs init --refresh-contracts)")
        for rel in fm.get("related", []) if isinstance(fm.get("related"), list) else []:
            if not (x.root / rel).exists():
                err.append(f"{r}: related → нет файла {rel}")
        for t_ in check_links(x, r, body):
            err.append(f"{r}: битая ссылка {t_}")
        kb = (x.root / r).stat().st_size / 1024
        if kb > max_kb and not fm.get("generated"):
            warn.append(f"{r}: {kb:.0f} КБ > {max_kb:g} КБ — разбить или вынести данные")
    for e in err:
        print("ОШИБКА  " + e)
    for w in warn:
        print("предупр. " + w)
    print(f"docs check: файлов {len(items)}, ошибок {len(err)}, предупреждений {len(warn)}")
    return 1 if err else 0


# ---------- init (эвристики) ----------
def first_para(body):
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    for para in re.split(r"\n\s*\n", body):
        lines = [l.strip() for l in para.strip().split("\n")]
        if not lines or not lines[0] or lines[0].startswith(("#", "|", "```", "---", "![", "<", "- [")):
            continue
        t = " ".join(l.lstrip("> ").lstrip("-* ").strip() for l in lines)
        t = re.sub(r"\*\*|`|\[([^\]]*)\]\([^)]*\)", lambda m: m.group(1) or "", t)
        t = re.sub(r"\s+", " ", t).strip()
        if len(t) < 12 or re.match(r"^(План\b|Внутренний документ|Статус:|Ветка |Задача |Требования:|[0-9.]+\s+Статус)", t):
            continue
        m = re.match(r"(.{40,}?[.!?])(\s|$)", t)
        t = m.group(1) if m and len(m.group(1)) <= 230 else t
        return (t[:227] + "…") if len(t) > 230 else t
    return ""


def conclusion_of(body):
    m = re.search(r"^#{2,4}\s+[^\n]*(?:Итог|Вывод|Резюме|Заключение|Результат)[^\n]*\n(.*?)(?=^#{1,4}\s|\Z)", body, re.S | re.M | re.I)
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
    ttl = re.sub(r"\s+", " ", re.sub(r"`|\*\*", "", title_of(body, Path(r).stem)))
    para = first_para(body)
    fm["summary"] = (ttl + (" — " + para if para and para.lower() not in ttl.lower() else ""))[:300]
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
            print(r, fm["type"], fm["status"], fm["module"], "|", fm["summary"][:80])
        else:
            p.write_text(dump_fm(fm) + body, encoding="utf-8")
    print(f"frontmatter добавлен: {n}")
    return 0


# ---------- find / show / findings ----------
def cmd_find(x, a):
    x.need_docs()
    q = (a.text or "").lower()
    n = 0
    for r, fm, body in docs_all(x):
        if fm is None:
            continue
        if a.type and fm.get("type") != a.type or a.status and fm.get("status") != a.status or a.module and fm.get("module") != a.module:
            continue
        hay = " ".join([r, str(fm.get("summary", "")), str(fm.get("conclusion", "")), str(fm.get("module", ""))]).lower()
        if q and not all(w in hay for w in q.split()):
            continue
        print(f"{r} — {fm.get('type')} — {fm.get('status')} — {fm.get('summary', '')[:160]}")
        n += 1
    if not n:
        print("ничего не найдено")
    return 0


def cmd_show(x, a):
    p = Path(a.path)
    p = p if p.is_absolute() else x.root / a.path
    if not p.is_file():
        raise DpError("нет файла: " + a.path)
    fm, body = split_fm(read(p))
    print(dump_fm(fm).rstrip() if fm else "(нет frontmatter)")
    print()
    for i, l in enumerate(body.split("\n"), 1):
        if re.match(r"^#{1,4}\s", l):
            print(f"{l}   (строка {i})")
    return 0


def cmd_findings(x, a):
    rel = f"{x.reg}/findings.md"
    p = x.root / rel
    if not p.exists():
        raise DpError(f"нет {rel} (реестр выводов пишется вручную)")
    _, body = split_fm(read(p))
    mod, q, n = "", (a.text or "").lower(), 0
    for l in body.split("\n"):
        if l.startswith("## "):
            mod = l[3:].strip()
        elif l.startswith("- ") and (not a.module or mod == a.module) and (not q or all(w in l.lower() for w in q.split())):
            print(f"[{mod}] {l[2:]}")
            n += 1
    if not n:
        print("ничего не найдено")
    return 0


# ---------- index ----------
def row(r, fm):
    return f"| [{r}](/{r}) | {fm.get('type')} | {fm.get('status')} | {fm.get('module', '')} | {str(fm.get('summary', '')).replace('|', '/')} |"


GEN_HEAD = "Файл собран `docs index` — руками не править.\n\n"


def write_gen(x, path, title, summary, body, head=GEN_HEAD):
    fm = {"type": "registry", "status": "active", "module": "", "updated": datetime.date.today().isoformat(),
          "summary": summary, "related": [], "generated": True}
    (x.root / path).parent.mkdir(parents=True, exist_ok=True)
    (x.root / path).write_text(dump_fm(fm) + f"\n# {title}\n\n" + head + body, encoding="utf-8")


def cmd_index(x, a):
    x.need_docs()
    dd, c = x.c["docs_dir"], x.c
    fp = x.root / x.reg / "findings.md"
    if not fp.exists():  # INDEX.md ссылается на реестр выводов — заготовка (дальше пишется вручную)
        fm = {"type": "registry", "status": "active", "module": "", "updated": datetime.date.today().isoformat(),
              "summary": "Реестр выводов: что мы знаем, по модулям (пишется вручную).", "related": []}
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(dump_fm(fm) + "\n# Реестр выводов\n\nПо модулю — раздел `## <модуль>`, вывод — пункт `- …` "
                      "(со ссылкой на источник). Поиск — `docs findings`.\n", encoding="utf-8")
    items = [(r, fm, body) for r, fm, body in docs_all(x) if fm is not None]
    sections = [
        ("Описания систем (guide)", lambda r: _under(r, f"{dd}/guide")),
        ("Контракты стыков", lambda r: _under(r, c["contracts_dir"])),
        ("Исследования", lambda r: _under(r, f"{dd}/research")),
        ("Планы (живые и отложенные)", lambda r: _under(r, c["plan_dir"])),
        ("Реестры", lambda r: _under(r, x.reg)),
    ]
    used, out = {x.index_path}, []
    cols = "| путь | тип | статус | модуль | summary |\n|---|---|---|---|---|"
    for title, pred in sections:
        rows = [(r, fm) for r, fm, _ in items if pred(r) and r not in used]
        used.update(r for r, _ in rows)
        if rows:
            out.append(f"## {title}\n\n{cols}")
            out += [row(r, fm) for r, fm in rows]
            out.append("")
    rest = [(r, fm) for r, fm, _ in items if r not in used]
    if rest:
        out.append(f"## Прочее\n\n{cols}")
        out += [row(r, fm) for r, fm in rest]
        out.append("")
    arch = x.docs / "archive"
    if arch.is_dir():
        n = len(list(arch.rglob("*.md")))
        out.append(f"## Архив\n\n`{dd}/archive/` — закрытые работы ({n} md, из поиска по умолчанию исключены). "
                   f"Выводы из них — в [реестре выводов](/{x.reg}/findings.md).\n")
    head = (f"Точка входа в документацию. Что мы знаем про X — [выводы](/{x.reg}/findings.md), `docs find`, `docs findings`, "
            "`search`. Файл собран `docs index` — руками не править.\n\n")
    write_gen(x, x.index_path, "Индекс документации", f"Все документы {dd}/: путь, тип, статус, summary; точка входа.", "\n".join(out), head)

    rrows = ["| тема | вывод | данные | применено | путь |", "|---|---|---|---|---|"]
    for r, fm, body in items:
        if fm.get("type") != "research":
            continue
        rrows.append("| {} | {} | {} | {} | [{}](/{}) |".format(
            title_of(body, Path(r).stem).replace("|", "/")[:90], str(fm.get("conclusion") or fm.get("summary", "")).replace("|", "/")[:300],
            str(fm.get("data", "")).replace("|", "/"), str(fm.get("applied_in", "")).replace("|", "/"), r, r))
    write_gen(x, f"{x.reg}/research.md", "Реестр исследований", "Все исследования: тема, вывод, данные, где применено.", "\n".join(rrows) + "\n")

    crows = ["| модуль | контракты (id vN) | файл |", "|---|---|---|"]
    for r, fm, body in items:
        if fm.get("type") == "contract":
            cs = ", ".join(f"{k['id']} v{k['version']}" for k in fm.get("contracts", []) if isinstance(k, dict))
            crows.append(f"| {fm.get('module', '')} | {cs} | [{r}](/{r}) |")
    write_gen(x, f"{x.reg}/contracts.md", "Реестр контрактов", "Контракты стыков по модулям: идентификаторы и версии из заголовков.", "\n".join(crows) + "\n")

    drows, total = [], 0
    for d in sorted((x.root / c["plan_dir"]).glob("*/decisions.jsonl")):
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
            drows.append(f"- {str(k.get('t', ''))[:10]} {k.get('kind', 'decision')}: {txt[:400]}" + (f" — почему: {why[:240]}" if why else ""))
            total += 1
        drows.append("")
    write_gen(x, f"{x.reg}/decisions.md", "Реестр решений", f"Решения всех модулей из decisions.jsonl ({total} записей), по модулям.", "\n".join(drows))
    print(f"docs index: INDEX.md, registry/research|contracts|decisions.md (решений {total})")
    return 0


# ---------- регистрация ----------
def _run(fn):
    def run(a):
        return fn(Ctx(), a) or 0
    return run


def register(sp):
    p = sp.add_parser("docs", help="реестр и проверка документации: check|index|find|show|findings|init")
    ds = p.add_subparsers(dest="docs_cmd", required=True)
    ds.add_parser("check", help="frontmatter, ссылки, размер").set_defaults(func=_run(cmd_check))
    ds.add_parser("index", help="собрать INDEX.md и реестры").set_defaults(func=_run(cmd_index))
    q = ds.add_parser("find", help="найти документы")
    q.add_argument("text", nargs="?")
    q.add_argument("--type")
    q.add_argument("--status")
    q.add_argument("--module")
    q.set_defaults(func=_run(cmd_find))
    q = ds.add_parser("show", help="frontmatter и оглавление")
    q.add_argument("path")
    q.set_defaults(func=_run(cmd_show))
    q = ds.add_parser("findings", help="выводы из registry/findings.md")
    q.add_argument("text", nargs="?")
    q.add_argument("--module")
    q.set_defaults(func=_run(cmd_findings))
    q = ds.add_parser("init", help="дописать frontmatter файлам без него")
    q.add_argument("--dry", action="store_true")
    q.add_argument("--refresh-contracts", action="store_true")
    q.set_defaults(func=_run(cmd_init))
    return p
