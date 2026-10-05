"""status (сводка, --since) и digest (основа записи дневника)."""
import datetime as dt
import re
from pathlib import Path

from .. import config, gitx
from ..journal import FINAL, all_modules, module_meta, question_answers, state_label, task_cards, task_states
from ..util import CLI, DpError, age, pretty, read_jsonl, rel, short


def module_status(mod, home, a, lines):
    st = task_states(home)
    cards = task_cards(home)
    for tid in cards:
        st.setdefault(tid, {"status": "created", "t": None, "last_t": None, "commits": [], "note": "", "rev": "", "seen": set()})
    wt = {b: p for p, b in gitx.worktrees()}
    meta = module_meta(mod, home)
    cnt = {}
    for s in st.values():
        cnt[state_label(s)] = cnt.get(state_label(s), 0) + 1
    mwt, mlast = gitx.branch_info(meta["branch"], wt)
    evs = read_jsonl(home / "events.jsonl")
    last_ev = f" | событие {age(evs[-1]['t'])} назад" if evs else ""
    lines.append(f"{mod}: " + " ".join(f"{k} {v}" for k, v in sorted(cnt.items())) + last_ev +
                 (f" | {meta['branch']} {mlast}" if mlast else "") + (f" @ {rel(mwt)}" if mwt else ""))
    stale_min = a.stale
    main = config.main_branch()
    for tid, s in st.items():
        if s["status"] in FINAL and not a.full:
            continue
        card = cards.get(tid) or {}
        br = card.get("branch", "")
        bwt, blast = gitx.branch_info(br, wt) if br else ("", "")
        old = ""
        if s["status"] not in FINAL and s["last_t"]:
            last = dt.datetime.fromisoformat(s["last_t"])
            cts = gitx.branch_last_ts(br, main) if br and gitx.branch_exists(br) else None
            if cts and cts > last:
                last = cts  # тихо = ни событий, ни коммитов ветки задачи
            mins = (dt.datetime.now() - last).total_seconds() / 60
            if mins > stale_min:
                old = f" ⚠тихо {age(last.isoformat())}"
        extra = f" {br} {blast}" if blast else ""
        note = f" — {short(s['note'], 60)}" if s["note"] and s["status"] in ("blocked", "checked") else ""
        rv = f" {s['rev']}" if s.get("rev") else ""
        lines.append(f"  {tid} {state_label(s)} {age(s['t'])} {card.get('type', '').removeprefix('dp-')}{rv}{extra}{old}{note}")
    decs = read_jsonl(home / "decisions.jsonl")
    answered = {x.get("answers") for x in decs if x.get("answers")}
    for q in decs:
        if q.get("kind") == "question" and q.get("id") not in answered:
            lines.append(f"  ? {q['id']} ждёт решения ({age(q['t'])}): {short(q['text'], 90)}")


def cmd_status(a):
    if a.since:
        return status_since(a)
    mods = all_modules()
    lines = []
    if a.module:
        if a.module not in mods:
            raise DpError(f"модуль {a.module} не найден (есть: {', '.join(mods) or 'нет'})")
        module_status(a.module, mods[a.module], a, lines)
    else:
        for m, h in mods.items():
            module_status(m, h, a, lines)
        feats = [(p, config.module_of_branch(b)) for p, b in gitx.worktrees()]
        feats = [(p, m) for p, m in feats if m and m not in mods and Path(p) != gitx.toplevel()
                 and (Path(p) / config.plan_dir()).is_dir()]
        if feats:
            lines.append("копии без журнала dpcli: " + ", ".join(m for p, m in feats))
        if not lines:
            lines.append("модулей dpcli нет")
    print("\n".join(lines))


def parse_since(s):
    s = s.strip().lower()
    t0 = dt.datetime.now()
    if s == "today":
        return t0.replace(hour=0, minute=0, second=0, microsecond=0)
    m = re.fullmatch(r"(\d+)([mhd])", s)
    if m:
        return t0 - dt.timedelta(**{{"m": "minutes", "h": "hours", "d": "days"}[m[2]]: int(m[1])})
    try:
        return dt.datetime.fromisoformat(s)
    except ValueError:
        raise DpError(f"--since «{s}»: ожидалось 30m | 2h | 1d | today | ГГГГ-ММ-ДД")


def status_since(a):
    cut = parse_since(a.since)
    iso = cut.isoformat()
    main = config.main_branch()
    mods = all_modules()
    if a.module:
        if a.module not in mods:
            raise DpError(f"модуль {a.module} не найден (есть: {', '.join(mods) or 'нет'})")
        mods = {a.module: mods[a.module]}
    wt = {b: p for p, b in gitx.worktrees()}
    feats = [b for b in gitx.local_branches() if config.module_of_branch(b)]
    seen, L = set(), []
    for mod, home in mods.items():
        cards = task_cards(home)
        brs = [config.module_branch(mod)] + [c["branch"] for c in cards.values() if c and c.get("branch")]
        evs = [e for e in read_jsonl(home / "events.jsonl") if e.get("t", "") >= iso]
        qs = [q for q in read_jsonl(home / "decisions.jsonl") if q.get("kind") == "question" and q.get("t", "") >= iso]
        blines, ncom = [], 0
        for b in dict.fromkeys(brs):
            seen.add(b)
            if gitx.branch_exists(b):
                cs = gitx.log_since(cut, b, "--no-merges", "--not", main)
                if cs:
                    ncom += len(cs)
                    blines.append(f"  {b} {len(cs)}к: {short(cs[0], 70)}" + (f" @ {pretty(wt[b])}" if b in wt else ""))
        if not (evs or qs or blines):
            continue
        ans = question_answers(home)
        nopen = sum(1 for q in qs if q.get("id") not in ans)
        L.append(f"{mod}: событий {len(evs)}, коммитов {ncom}, новых вопросов {len(qs)}" + (f" (открыто {nopen})" if qs else ""))
        L += blines
        L += [f"  {'✓' if q.get('id') in ans else '?'} {q['id']}: {short(q['text'], 80)}"
              + (f" → {short(ans[q['id']]['text'], 50)}" if q.get("id") in ans else "") for q in qs]
        for e in evs[-5:]:
            L.append(f"  {str(e['t'])[11:16]} {e.get('task') or '·'} {e['ev']} ({e.get('by', '-')})"
                     + (f" — {short(e['note'], 80)}" if e.get("note") else ""))
        if len(evs) > 5:
            L.append(f"  … ещё {len(evs) - 5} событий ({CLI} log {mod})")
    if not a.module:
        for b in feats:
            if b not in seen:
                cs = gitx.log_since(cut, b, "--no-merges", "--not", main)
                if cs:
                    L.append(f"{b} (без журнала): {len(cs)}к: {short(cs[0], 70)}" + (f" @ {pretty(wt[b])}" if b in wt else ""))
        mc = gitx.log_since(cut, main, "--first-parent")
        if mc:
            L.append(f"{main}: {len(mc)} коммитов, последний {short(mc[0], 80)}")
    print("\n".join(L) if L else f"с {iso[:16].replace('T', ' ')} тихо")


def cmd_digest(a):
    cut = parse_since(a.since)
    iso = cut.isoformat()
    main = config.main_branch()
    L = [f"# с {iso[:16].replace('T', ' ')}"]
    dec, acc, plans = [], [], []
    for mod, home in all_modules().items():
        for d in read_jsonl(home / "decisions.jsonl"):
            if d.get("t", "") >= iso and d.get("kind") != "question" and d.get("by") == "user":
                dec.append(f"- [{mod}] {d['text']}" + (f" — {d['why']}" if d.get("why") else "")
                           + (f" (ответ на {d['answers']})" if d.get("answers") else ""))
        cards = task_cards(home)
        for e in read_jsonl(home / "events.jsonl"):
            if e.get("t", "") < iso:
                continue
            if e.get("ev") == "accepted" and e.get("task"):
                acc.append(f"- [{mod}] {e['task']} {short((cards.get(e['task']) or {}).get('title', ''), 80)}")
            elif e.get("ev") == "plan":
                plans.append(f"- [{mod}] {e.get('note', '')}")
    for title, items in (("Решения пользователя", dec), ("Принятые задачи", acc), ("Правки плана", plans)):
        if items:
            L += ["", f"## {title}"] + list(dict.fromkeys(items))
    mc = gitx.log_since(cut, main, "--first-parent")
    if mc:
        L += ["", f"## Коммиты {main} ({len(mc)})"] + [f"- {short(c, 120)}" for c in mc[:30]]
        if len(mc) > 30:
            L.append(f"- … ещё {len(mc) - 30}")
    if len(L) == 1:
        L.append("ничего нового")
    print("\n".join(L))


def register(sp):
    q = sp.add_parser("status", help="сводка: задачи, ветки, тишина, вопросы пользователю")
    q.add_argument("module", nargs="?"); q.add_argument("--full", action="store_true", help="и закрытые задачи")
    q.add_argument("--stale", type=int, default=40, metavar="МИН", help="порог «тихо» (40)")
    q.add_argument("--since", metavar="30m|2h|today", help="за период: коммиты веток, события, новые вопросы (все модули и копии)")
    q.set_defaults(func=cmd_status)

    q = sp.add_parser("digest", help="основа записи дневника: решения, принятые задачи, правки плана, коммиты главной ветки")
    q.add_argument("--since", default="today", metavar="today|ДАТА|2h")
    q.set_defaults(func=cmd_digest)
