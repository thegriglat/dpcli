"""Module journal: module home, module list, cards, events, task states, module codes."""
import json
import os
import re
from pathlib import Path

from . import config, gitx
from .util import DpError, append_jsonl, lang_commit, now, pretty, read_json, read_jsonl, write_json

LIFECYCLE = ["created", "started", "reported", "checked", "reviewed", "accepted", "merged", "blocked", "cancelled"]
EVENT_KINDS = ["started", "reported", "accepted", "merged", "blocked", "cancelled", "note"]
FINAL = {"accepted", "merged", "cancelled"}
SEVERITY = {"blocker": "B", "major": "M", "minor": "m"}
CODE_RE = re.compile(r"^[A-Z]{2,4}$")
ID_RE = re.compile(r"^([A-Z]{2,4})-([A-Z]?)(\d+)[a-z]?$")  # NN-7, NN-7a, stage IDs NN-P8


def infer_role():
    """Author without --by and $DPCLI_ROLE — by the copy's branch: module branch → coordinator, task branch → executor,
    any other (main_branch or a feature branch modules are created from) → main; outside a repo → «-»."""
    br = gitx.git("branch", "--show-current")
    if not br:
        return "-"
    if config.module_of_branch(br):
        return "coordinator"
    return "executor" if config.task_branch_fields(br) else "main"


def by_default(args):
    return getattr(args, "by", None) or os.environ.get("DPCLI_ROLE") or infer_role()


def local_only():
    return bool(os.environ.get("DPCLI_LOCAL"))


def module_home(mod):
    """Module journal dir: the module branch's copy if present, else the current one."""
    pd = config.plan_dir()
    if not local_only():
        mb = config.module_branch(mod)
        for path, br in gitx.worktrees():
            if br == mb and is_module_dir(Path(path) / pd / mod):
                return Path(path) / pd / mod
    return gitx.toplevel() / pd / mod


def home_root(home):
    """Copy root from the module home (<root>/<plan_dir>/<module>)."""
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
    """(module, module dir) by task ID."""
    mods = all_modules()
    hits = [(m, h) for m, h in mods.items() if (h / "tasks" / f"{tid}.json").exists()]
    if not hits:
        raise DpError(f"task {tid} not found (modules: {', '.join(mods) or 'none'})")
    if len(hits) > 1:
        raise DpError(f"{tid} is in several modules: {', '.join(m for m, _ in hits)}")
    return hits[0]


def resolve_target(x):
    """Task ID or module name → (module, home, task|None)."""
    mods = all_modules()
    if x in mods:
        return x, mods[x], None
    mod, home = find_task(x)
    return mod, home, x


def is_work_branch(br):
    """A dpcli module or task branch — no module is created from it and nothing is delivered to it. By the journal:
    any feature branch may match the name templates (`feature/x`, `a/b`)."""
    return any(br == module_meta(m, h)["branch"] or any((c or {}).get("branch") == br for c in task_cards(h).values())
               for m, h in all_modules().items())


def module_base(meta):
    """Module base — the branch it was created from (module new --from, default the main session's current branch);
    sync and deliver go to it. Old modules without base — main_branch."""
    return meta.get("base") or config.main_branch()


def guard_main(into, explicit, base=None):
    """protect_main: dpcli merges into main_branch only with an explicit --into and only a module created from it:
    the usual way into main is a feature-branch MR merged by a human."""
    main = config.main_branch()
    if into != main or not config.get("protect_main"):
        return
    if not explicit:
        raise DpError(f"not merging into {main} without explicit --into {main}: usual path is feature branch → MR, merged by a human")
    if base and base != main:
        raise DpError(f"module was created from {base}: delivered to {base}; into {main} only via a feature-branch MR")


def module_meta(mod, home):
    m = read_json(home / "module.json") or {}
    m.setdefault("module", mod)
    m.setdefault("plan", f"{config.plan_dir()}/{mod}.md")
    m.setdefault("contracts", f"{config.contracts_dir()}/{mod}.md")
    m.setdefault("branch", config.module_branch(mod))
    return m


def module_codes():
    """{code: module} from all modules' module.json."""
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
        raise DpError(f"module code «{code}»: 2–4 capital Latin letters"
                      + (f" (reserved: {', '.join(sorted(res))})" if res else "") + ", e.g. NN, UC")
    other = module_codes().get(code)
    if other and other != mod:
        raise DpError(f"code {code} already belongs to module {other}")


def check_area(area, required=True):
    """Module area — from config.areas; if the list is set, a module cannot be created without area."""
    allowed = config.areas()
    if not allowed:
        return
    if not area:
        if required:
            raise DpError(f"--area required: one of {', '.join(allowed)} (config key areas). "
                          f"Don't pick it yourself — ask the developer which area the module belongs to")
        return
    if area not in allowed:
        raise DpError(f"area «{area}» is not one of {', '.join(allowed)} (config key areas)")


def ensure_module(mod, home, **kw):
    if kw.get("code"):
        check_code(kw["code"], mod)
    if kw.get("area"):
        check_area(kw["area"])
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
    """rev:rework 2B1M — verdict and finding counts by severity."""
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
    """{ID: {status, t, last_t, commits[], note}} from events."""
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
    """Coordinator addenda to an already issued task: note events with addendum."""
    return [e for e in read_jsonl(home / "events.jsonl") if e.get("task") == tid and e.get("addendum")]


def open_questions(home):
    decs = read_jsonl(home / "decisions.jsonl")
    answered = {x.get("answers") for x in decs if x.get("answers")}
    return [q for q in decs if q.get("kind") == "question" and q.get("id") not in answered]


def question_answers(home):
    """{Qn: latest answer (decisions entry)}."""
    return {d["answers"]: d for d in read_jsonl(home / "decisions.jsonl") if d.get("answers")}


def expect_arg(exp):
    """EXPECT from the command line: «{…}» — JSON object (compound condition), else a string."""
    if isinstance(exp, str) and exp.lstrip().startswith("{"):
        try:
            return json.loads(exp)
        except json.JSONDecodeError as e:
            raise DpError(f"expect: invalid JSON object ({e})")
    return exp


def journal_commit(path):
    """The dpcli journal (<plan_dir>/<module>/) doesn't count as «dirt»: we commit it by its own paths, «<module>: dpcli journal».
    → list of modules. Other changes stay and still cause a refusal."""
    pd = config.plan_dir()
    pparts = list(Path(pd).parts)
    n = len(pparts)
    mods = []
    for _xy, f in gitx.status_entries(path, "--untracked-files=all", pathspec=[pd]):
        parts = f.split("/")
        if len(parts) >= n + 2 and parts[:n] == pparts and parts[n] not in mods:
            mods.append(parts[n])
    for m in mods:
        gitx.commit_paths(path, [Path(path) / pd / m], lang_commit(f"{m}: dpcli journal", f"{m}: журнал dpcli"))
    return mods
