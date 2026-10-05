"""Журнал модуля: дом модуля, список модулей, карточки, события, состояния задач, коды модулей."""
import json
import os
import re
from pathlib import Path

from . import config, gitx
from .util import DpError, append_jsonl, now, pretty, read_json, read_jsonl, write_json

LIFECYCLE = ["created", "started", "reported", "checked", "reviewed", "accepted", "merged", "blocked", "cancelled"]
EVENT_KINDS = ["started", "reported", "accepted", "merged", "blocked", "cancelled", "note"]
FINAL = {"accepted", "merged", "cancelled"}
SEVERITY = {"blocker": "B", "major": "M", "minor": "m"}
CODE_RE = re.compile(r"^[A-Z]{2,4}$")
ID_RE = re.compile(r"^([A-Z]{2,4})-([A-Z]?)(\d+)[a-z]?$")  # NN-7, NN-7a, этапные NN-P8


def infer_role():
    """Автор без --by и $DPCLI_ROLE — по ветке копии: main_branch → main, ветка модуля → coordinator, иначе executor;
    вне репозитория → «-»."""
    br = gitx.git("branch", "--show-current")
    if not br:
        return "-"
    if br == config.main_branch():
        return "main"
    return "coordinator" if config.module_of_branch(br) else "executor"


def by_default(args):
    return getattr(args, "by", None) or os.environ.get("DPCLI_ROLE") or infer_role()


def local_only():
    return bool(os.environ.get("DPCLI_LOCAL"))


def module_home(mod):
    """Каталог журнала модуля: копия ветки модуля, если есть, иначе текущая."""
    pd = config.plan_dir()
    if not local_only():
        mb = config.module_branch(mod)
        for path, br in gitx.worktrees():
            if br == mb and is_module_dir(Path(path) / pd / mod):
                return Path(path) / pd / mod
    return gitx.toplevel() / pd / mod


def home_root(home):
    """Корень рабочей копии по дому модуля (<корень>/<plan_dir>/<модуль>)."""
    root = Path(home).parent
    for _ in Path(config.plan_dir()).parts:
        root = root.parent
    return root


def is_module_dir(d):
    return (d / "events.jsonl").exists() or (d / "module.json").exists()


def all_modules():
    found = {}
    roots = [gitx.toplevel()] + ([] if local_only() else
                                 [Path(p) for p, b in gitx.worktrees() if config.module_of_branch(b)])
    for root in roots:
        base = root / config.plan_dir()
        if base.is_dir():
            for d in sorted(base.iterdir()):
                if d.is_dir() and is_module_dir(d) and d.name not in found:
                    found[d.name] = module_home(d.name)
    return found


def find_task(tid):
    """(модуль, каталог модуля) по ID задачи."""
    mods = all_modules()
    hits = [(m, h) for m, h in mods.items() if (h / "tasks" / f"{tid}.json").exists()]
    if not hits:
        raise DpError(f"задача {tid} не найдена (модули: {', '.join(mods) or 'нет'})")
    if len(hits) > 1:
        raise DpError(f"{tid} есть в нескольких модулях: {', '.join(m for m, _ in hits)}")
    return hits[0]


def resolve_target(x):
    """ID задачи или имя модуля → (модуль, дом, task|None)."""
    mods = all_modules()
    if x in mods:
        return x, mods[x], None
    mod, home = find_task(x)
    return mod, home, x


def module_meta(mod, home):
    m = read_json(home / "module.json") or {}
    m.setdefault("module", mod)
    m.setdefault("plan", f"{config.plan_dir()}/{mod}.md")
    m.setdefault("contracts", f"{config.contracts_dir()}/{mod}.md")
    m.setdefault("branch", config.module_branch(mod))
    return m


def module_codes():
    """{код: модуль} по module.json всех модулей."""
    out = {}
    for m, h in all_modules().items():
        c = (read_json(h / "module.json") or {}).get("code")
        if c:
            out[c] = m
    return out


def reserved_codes():
    return {str(x) for x in config.get("reserved_codes") or []}


def check_code(code, mod):
    res = reserved_codes()
    if not CODE_RE.match(code) or code in res:
        raise DpError(f"код модуля «{code}»: 2–4 заглавные латинские буквы"
                      + (f" (зарезервированы: {', '.join(sorted(res))})" if res else "") + ", напр. NN, UC")
    other = module_codes().get(code)
    if other and other != mod:
        raise DpError(f"код {code} уже у модуля {other}")


def ensure_module(mod, home, **kw):
    if kw.get("code"):
        check_code(kw["code"], mod)
    p = home / "module.json"
    if not p.exists():
        meta = {"module": mod, "plan": f"{config.plan_dir()}/{mod}.md", "contracts": f"{config.contracts_dir()}/{mod}.md",
                "branch": config.module_branch(mod), "copy": pretty(config.module_copy(mod)), "created": now()}
        meta.update({k: v for k, v in kw.items() if v})
        write_json(p, meta)
    (home / "tasks").mkdir(parents=True, exist_ok=True)
    (home / "events.jsonl").touch()


def add_event(home, task, kind, by, note="", commits=None, **extra):
    ev = {"t": now(), "by": by, "task": task, "ev": kind}
    if commits:
        ev["commits"] = commits
    if note:
        ev["note"] = note
    ev.update({k: v for k, v in extra.items() if v not in (None, "", [], {})})
    append_jsonl(home / "events.jsonl", ev)
    return ev


def rev_tag(ev):
    """rev:rework 2B1M — вердикт и число замечаний по серьёзности."""
    cnt = ev.get("issues") or {}
    return f"rev:{ev.get('verdict', '?')}" + ("" if not any(cnt.values()) else " " + "".join(
        f"{cnt[k]}{SEVERITY[k]}" for k in SEVERITY if cnt.get(k)))


def count_sev(r):
    cnt = {k: 0 for k in SEVERITY}
    for i in r.get("issues", []) or []:
        if isinstance(i, dict) and i.get("severity") in cnt:
            cnt[i["severity"]] += 1
    return cnt


def task_cards(home):
    return {p.stem: read_json(p) for p in sorted((home / "tasks").glob("*.json"))
            if not p.name.endswith((".report.json", ".review.json"))}


def task_states(home):
    """{ID: {status, t, last_t, commits[], note}} по событиям."""
    st = {}
    for ev in read_jsonl(home / "events.jsonl"):
        tid = ev.get("task")
        if not tid:
            continue
        s = st.setdefault(tid, {"status": "created", "t": ev.get("t"), "last_t": ev.get("t"), "commits": [], "note": "",
                                "rev": "", "seen": set()})
        s["last_t"] = ev.get("t")
        k = ev.get("ev")
        s["seen"].add(k)
        if k in LIFECYCLE and not (k == "checked" and s["status"] in FINAL):
            s["status"] = k
            s["t"] = ev.get("t")
            if k in ("blocked", "checked", "accepted", "cancelled"):
                s["note"] = ev.get("note", "")
        if k == "reviewed":
            s["rev"] = rev_tag(ev)
        for c in ev.get("commits", []):
            if c not in s["commits"]:
                s["commits"].append(c)
    return st


def state_label(s):
    return "accepted+merged" if {"accepted", "merged"} <= s.get("seen", set()) else s["status"]


def addenda(home, tid):
    """Дополнения координатора к уже выданной задаче: события note с addendum."""
    return [e for e in read_jsonl(home / "events.jsonl") if e.get("task") == tid and e.get("addendum")]


def open_questions(home):
    decs = read_jsonl(home / "decisions.jsonl")
    answered = {x.get("answers") for x in decs if x.get("answers")}
    return [q for q in decs if q.get("kind") == "question" and q.get("id") not in answered]


def question_answers(home):
    """{Qn: последний ответ (запись decisions)}."""
    return {d["answers"]: d for d in read_jsonl(home / "decisions.jsonl") if d.get("answers")}


def expect_arg(exp):
    """EXPECT из командной строки: «{…}» — JSON-объект (составное условие), иначе строка."""
    if isinstance(exp, str) and exp.lstrip().startswith("{"):
        try:
            return json.loads(exp)
        except json.JSONDecodeError as e:
            raise DpError(f"expect: неверный JSON-объект ({e})")
    return exp


def journal_commit(path):
    """Журнал dpcli (<plan_dir>/<модуль>/) не считается «грязью»: коммитим его своими путями, «<модуль>: журнал dpcli».
    → список модулей. Остальные изменения остаются и по-прежнему дают отказ."""
    pd = config.plan_dir()
    pparts = list(Path(pd).parts)
    n = len(pparts)
    out = gitx.gitr("status", "--porcelain", "--untracked-files=all", "--", pd, cwd=path).stdout
    mods = []
    for l in out.splitlines():
        parts = l[3:].strip().strip('"').split("/")
        if len(parts) >= n + 2 and parts[:n] == pparts and parts[n] not in mods:
            mods.append(parts[n])
    for m in mods:
        gitx.commit_paths(path, [Path(path) / pd / m], f"{m}: журнал dpcli")
    return mods
