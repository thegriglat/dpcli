"""feedback (friction ledger: collect, dedup, clusters, triage, fix) and stats (durations, rework, frictions)."""
import re
import statistics

from .. import config
from ..journal import all_modules, task_cards
from ..util import CLI, DpError, append_jsonl, now, read_json, read_jsonl, short

# dpcli commands and frequent topics: unclustered frictions are grouped by the first one mentioned
TOPICS = ["task show", "task brief", "task new", "task set", "task note", "task sync", "accept", "report", "review",
          "plan", "job", "lock", "merge", "sync", "gc", "deliver", "docs", "search", "status", "inbox", "init",
          "module new", "scope", "stash", "worktree"]
EMPTY = {"", "-", "—", "none", "no", "ok", "нет", "ок", "всё ок", "замечаний нет", "n/a"}


def ledger_path():
    return config.repo_path(config.get("local_dir", ".dpcli-local")) / "feedback.jsonl"


def norm(s):
    return re.sub(r"[\s.,;:!]+$", "", " ".join(str(s).split()).lower())


def items(since="", module=None):
    """[{t, module, task, text, src}] from the journals of all modules and, for delivered modules (journal gone),
    the ledger's `item` records written by deliver."""
    out = [{k: r.get(k) for k in ("t", "module", "task", "text", "src")} for r in read_jsonl(ledger_path())
           if r.get("kind") == "item" and r.get("t", "") >= since and (not module or r.get("module") == module)]
    for mod, home in all_modules().items():
        if module and mod != module:
            continue
        for e in read_jsonl(home / "events.jsonl"):
            t = e.get("t", "")
            if t < since:
                continue
            if e.get("ev") == "reported" and e.get("dp_feedback"):
                fb = e["dp_feedback"]  # reports may carry a list of frictions: one item each
                out += [{"t": t, "module": mod, "task": e.get("task"), "text": str(x), "src": "report"}
                        for x in (fb if isinstance(fb, list) else [fb])]
            elif e.get("ev") == "note" and re.match(r"\s*harness:", e.get("note") or "", re.I):
                out.append({"t": t, "module": mod, "task": e.get("task"), "src": "note",
                            "text": re.sub(r"^\s*harness:\s*", "", e["note"], flags=re.I)})
        for f in sorted((home / "tasks").glob("*.review.json")):
            r = read_json(f) or {}
            if r.get("harness") and r.get("t", "") >= since:
                out.append({"t": r.get("t", ""), "module": mod, "task": f.name[:-12], "text": r["harness"], "src": "review"})
    uniq = {(i["module"], i["t"], i["text"]): i for i in out}  # a delivered item whose journal is still around
    return [i for i in uniq.values() if norm(i["text"]) not in EMPTY]


def keep_items(mod):
    """Before deliver drops the journal: the module's frictions go to the ledger as `item` records."""
    have = {(r.get("t"), r.get("text")) for r in read_jsonl(ledger_path())
            if r.get("kind") == "item" and r.get("module") == mod}
    for i in items(module=mod):
        if (i["t"], i["text"]) not in have:
            append_jsonl(ledger_path(), {**i, "kind": "item"})


def ledger():
    """{F-n: {title, match, scope, why, status, t_fix, where, pr, t}} folded from feedback.jsonl."""
    out = {}
    for r in read_jsonl(ledger_path()):
        fid, kind = r.get("id"), r.get("kind")
        if kind == "cluster":
            out[fid] = {**r, "status": "open"}
        elif fid in out:
            c = out[fid]
            if kind == "fix":
                c.update(status="fixed", t_fix=r["t"], where=r.get("where", ""), pr=r.get("pr", c.get("pr", "")))
            elif kind == "wontfix":
                c.update(status="wontfix", why=r.get("why", c.get("why", "")))
            elif kind in ("rework", "rejected"):
                c.update(status=kind, why=r.get("why", c.get("why", "")))
            elif kind == "reopen":
                c.update(status="open", t_fix="")
            elif kind in ("pr", "issue"):
                c["pr"] = r.get("url", "")
    return out


def topic(text):
    low = text.lower()
    hits = [(low.find(t), t) for t in TOPICS if re.search(rf"(?<![\w-]){re.escape(t)}(?![\w-])", low)]
    return min(hits)[1] if hits else "other"


def assign(its, clusters):
    """(by cluster id, by topic) — an item goes to the first cluster whose regex matches, else to its topic."""
    rx = [(fid, re.compile(c["match"], re.I)) for fid, c in clusters.items()]
    by_c, by_t = {}, {}
    for i in its:
        fid = next((f for f, r in rx if r.search(i["text"])), None)
        (by_c.setdefault(fid, []) if fid else by_t.setdefault(topic(i["text"]), [])).append(i)
    return by_c, by_t


def uniq(its):
    """[(text, count, tasks)] by normalized text, most frequent first."""
    g = {}
    for i in its:
        k = norm(i["text"])
        x = g.setdefault(k, [i["text"], 0, []])
        x[1] += 1
        if i["task"] and i["task"] not in x[2]:
            x[2].append(i["task"])
    return sorted(g.values(), key=lambda x: -x[1])


def cmd_feedback(a):
    sub = a.sub or "list"
    if sub == "new":
        try:
            re.compile(a.match)
        except re.error as e:
            raise DpError(f"--match: invalid regex ({e})")
        n = 1 + max((int(f[2:]) for f in ledger() if f[2:].isdigit()), default=0)
        fid = f"F-{n}"
        append_jsonl(ledger_path(), {"t": now(), "id": fid, "kind": "cluster", "title": a.title, "match": a.match,
                                     "scope": a.scope, "why": a.why or ""})
        print(f"{fid}: {a.title} [{a.scope}] → {CLI} feedback show {fid}")
        return
    led = ledger()
    if sub in ("fix", "wontfix", "reopen"):
        if a.id not in led:
            raise DpError(f"{a.id}: no such cluster ({CLI} feedback)")
        rec = {"t": now(), "id": a.id, "kind": sub}
        rec.update({k: v for k, v in (("where", getattr(a, "where", None)), ("pr", getattr(a, "pr", None)),
                                       ("why", getattr(a, "why", None))) if v})
        append_jsonl(ledger_path(), rec)
        print(f"{a.id}: {sub}")
        return
    its = items(a.since or "", a.module)
    by_c, by_t = assign(its, led)
    if sub == "show":
        group = by_c.get(a.id) if a.id in led else by_t.get(a.id)
        if group is None:
            raise DpError(f"{a.id}: nothing (clusters F-n or topics: {', '.join(sorted(by_t)) or '-'})")
        if a.id in led:
            c = led[a.id]
            print(f"{a.id} {c['title']} [{c['scope']}] {c['status']} · match /{c['match']}/" + (f" · {c['pr']}" if c.get("pr") else ""))
        for text, cnt, tasks in uniq(group):
            print(f"×{cnt} {short(text, 160 if not a.full else 10000)}" + (f" | {', '.join(tasks[:6])}" if tasks else ""))
        return
    print(f"frictions {len(its)}, unique {len(uniq(its))}" + (f" since {a.since}" if a.since else ""))
    for fid, c in sorted(led.items(), key=lambda kv: int(kv[0][2:]) if kv[0][2:].isdigit() else 0):
        if c["status"] == "wontfix" and not a.all:
            continue
        g = by_c.get(fid, [])
        if not g and (a.module or a.since):
            continue  # filtered view: only clusters this module/period has
        after = [i for i in g if c.get("t_fix") and i["t"] > c["t_fix"]]
        print(f"{fid} ×{len(g)} [{c['scope']}] {c['status']}" + (f" ⚠{len(after)} after fix" if after else "")
              + f" — {short(c['title'], 80)}" + (f" · {c['pr']}" if c.get("pr") else ""))
    if by_t:
        print(f"unclustered ({CLI} feedback show <topic>; cluster: {CLI} feedback new \"title\" --match REGEX --scope project|dpcli):")
        for t, g in sorted(by_t.items(), key=lambda kv: -len(kv[1])):
            u = uniq(g)
            print(f"  {t} ×{len(g)} ({len(u)} unique): {short(u[0][0], 90)}")


def cmd_stats(a):
    mods = all_modules()
    if a.module and a.module not in mods:
        raise DpError(f"module {a.module} not found (have: {', '.join(mods) or 'none'})")
    durs = {}
    usage, main = agent_usage({t: m for m, h in mods.items() for t in task_cards(h)}, a.since or "") \
        if a.tokens else ({}, None)
    for mod, home in mods.items():
        if a.module and mod != a.module:
            continue
        evs = [e for e in read_jsonl(home / "events.jsonl") if e.get("t", "") >= (a.since or "")]
        created, accepted, rework, tasks = {}, {}, 0, set()
        for e in evs:
            tid = e.get("task")
            if not tid:
                continue
            tasks.add(tid)
            k = e.get("ev")
            if k == "created":
                created.setdefault(tid, e["t"])
            elif k == "accepted":
                accepted.setdefault(tid, e["t"])
                for n, s in (e.get("durs") or {}).items():
                    durs.setdefault(n, []).append(float(s))
            elif k == "reviewed" and e.get("verdict") == "rework":
                rework += 1
        lead = [_hours(created[t], accepted[t]) for t in accepted if t in created]
        nfr = len(items(a.since or "", mod))
        print(f"{mod}: tasks {len(tasks)} accepted {len(accepted)} | created→accepted "
              + (f"median {statistics.median(lead):.1f}h max {max(lead):.1f}h" if lead else "-")
              + f" | rework {rework} | frictions {nfr}")
        u = usage.get(mod) if a.tokens else None
        if u:
            roles = " · ".join(f"{r} {_m(u[r][0])} ({u[r][1]})" for r in ("executors", "reviewers", "coordinators") if r in u)
            per = list(u["tasks"].values())
            print(f"  tokens (context): {roles}" + (f" | per task median {_m(statistics.median(per))}" if per else ""))
    if main:  # every turn re-reads the whole context: a long main session costs more than the agents it runs
        print(f"main sessions (all modules): {_m(main[0])} in {main[1]}, largest turn {main[2] // 1000}k")
    if durs:
        print("checks, s (median/max): " + " · ".join(f"{n} {statistics.median(v):.0f}/{max(v):.0f}"
                                                      for n, v in sorted(durs.items(), key=lambda kv: -max(kv[1]))))


def agent_usage(task_module, since=""):
    """({module: {role: [context tokens, agents], "tasks": {ID: tokens}}}, (main sessions' tokens, sessions, largest
    turn) | None) from Claude Code's logs of this project. An agent is dpcli's when its first message is a brief:
    "<ID> <type>: …", "Review <ID>: …", "Module <m>: …"."""
    import re
    from pathlib import Path
    from .. import gitx
    root = gitx.main_worktree()
    base = Path.home() / ".claude" / "projects" / re.sub(r"[/_.]", "-", str(root)) if root else None
    out = {}
    have = base and base.is_dir()
    main = [_log_ctx(f, since) for f in sorted(base.glob("*.jsonl"))] if have else []  # main sessions: not per module
    main = [(ctx, peak) for _, ctx, peak in main if ctx]
    main = (sum(c for c, _ in main), len(main), max(p for _, p in main)) if main else None
    for f in sorted(base.glob("*/subagents/*.jsonl")) if have else []:
        first, ctx, _ = _log_ctx(f, "")
        # English protocol, and the Russian one of older journals ("Ревью <ID>", "Модуль <m>:")
        m = re.match(r"\s*(?:(Review|Ревью) )?([A-Z]{2,4}-[A-Z]?\d+[a-z]?)\b|\s*(?:Module|Модуль) (\S+?):", first or "")
        if not m:
            continue
        mod = m[3] or task_module.get(m[2])
        if not mod:
            continue
        role = "coordinators" if m[3] else "reviewers" if m[1] else "executors"
        d = out.setdefault(mod, {"tasks": {}})
        d.setdefault(role, [0, 0])
        d[role][0] += ctx
        d[role][1] += 1
        if m[2]:
            d["tasks"][m[2]] = d["tasks"].get(m[2], 0) + ctx
    return out, main


def _log_ctx(f, since):
    """(first user message, context tokens of turns since `since`, largest one turn's context) of a Claude Code log."""
    import json
    first, ctx, peak = None, 0, 0
    for line in f.open(errors="replace"):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if first is None and r.get("type") == "user":
            c = (r.get("message") or {}).get("content")
            first = c if isinstance(c, str) else " ".join(x.get("text", "") for x in c or [] if isinstance(x, dict))
        u = (r.get("message") or {}).get("usage") if r.get("type") == "assistant" else None
        if u and str(r.get("timestamp", "")) >= since:
            n = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
            ctx, peak = ctx + n, max(peak, n)
    return first, ctx, peak


def _m(n):
    v = n / 1e6
    return f"{v:.0f}M" if v >= 10 else f"{v:.2g}M"


def _hours(t0, t1):
    import datetime as dt
    try:
        return (dt.datetime.fromisoformat(t1) - dt.datetime.fromisoformat(t0)).total_seconds() / 3600
    except ValueError:
        return 0.0


def register(sp):
    q = sp.add_parser("feedback", help="friction ledger: list | show | new | fix | wontfix | reopen")
    q.add_argument("sub", nargs="?", choices=["list", "show", "new", "fix", "wontfix", "reopen"])
    q.add_argument("id", nargs="?", metavar="F-n|TOPIC|TITLE")
    q.add_argument("--since", metavar="DATE"); q.add_argument("--module")
    q.add_argument("--all", action="store_true", help="also wontfix clusters")
    q.add_argument("--full", action="store_true")
    q.add_argument("--match", metavar="REGEX", help="new: frictions of the cluster")
    q.add_argument("--scope", choices=["project", "dpcli"], help="new: fixed in .dpcli-local/ or in dpcli itself")
    q.add_argument("--why"); q.add_argument("--where", help="fix: where it was fixed (.dpcli-local/…, dpcli vN)")
    q.add_argument("--pr", metavar="URL")
    q.set_defaults(func=_dispatch)

    q = sp.add_parser("stats", help="per module: tasks, created→accepted, rework rounds, frictions; check durations")
    q.add_argument("module", nargs="?"); q.add_argument("--since", metavar="DATE")
    q.add_argument("--tokens", action="store_true", help="context tokens of executors/reviewers/coordinators, per task "
                                                         "(Claude Code subagent logs)")
    q.set_defaults(func=cmd_stats)


def _dispatch(a):
    if a.sub == "new":
        if not (a.id and a.match and a.scope):
            raise DpError(f'{CLI} feedback new "title" --match REGEX --scope project|dpcli')
        a.title = a.id
    elif a.sub in ("show", "fix", "wontfix", "reopen") and not a.id:
        raise DpError(f"{CLI} feedback {a.sub} <F-n{'|TOPIC' if a.sub == 'show' else ''}>")
    return cmd_feedback(a)
