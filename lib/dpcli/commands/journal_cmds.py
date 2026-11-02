"""event, decide, log, inbox, questions, answer."""
import argparse
import os

from ..journal import (EVENT_KINDS, ID_RE, add_event, all_modules, by_default, ensure_module, find_task, module_home,
                       open_questions, question_answers, resolve_target)
from ..util import CLI, DpError, age, append_jsonl, hm, now, read_jsonl, short
from .plan import DEFAULT_SECTION, plan_edit


def cmd_event(a):
    mod, home, task = resolve_target(a.target)
    if task is None and a.kind != "note":
        raise DpError("for a module only note; for a task use ID")
    add_event(home, task, a.kind, by_default(a), note=a.note or "", commits=a.commit)
    print(f"{task or mod}: {a.kind}")


def cmd_decide(a):
    mods = all_modules()
    home = mods.get(a.module) or module_home(a.module)
    ensure_module(a.module, home)
    decs = read_jsonl(home / "decisions.jsonl")
    d = {"t": a.date or now(), "by": a.by or by_default(a), "text": a.text}
    plan_note = ""
    if a.plan is not None:
        if a.ask:
            raise DpError("--plan is for decisions, not --ask")
        line = f"- **{a.text}** ({d['t'][:10]})" + (f" — {a.why}" if a.why else "")
        _, title, _ = plan_edit(a.module, a.plan, append=line, create=a.plan == DEFAULT_SECTION)
        plan_note = f"; to plan: {short(title, 40)}"
    if a.why:
        d["why"] = a.why
    if a.task:
        d["task"] = a.task
    if a.ask:
        n = 1 + sum(1 for x in decs if x.get("kind") == "question")
        d.update({"kind": "question", "id": f"Q{n}"})
    else:
        d["kind"] = "decision"
        if a.answers:
            d["answers"] = a.answers
    append_jsonl(home / "decisions.jsonl", d)
    print(f"{a.module}: {d.get('id', 'decision')} recorded ({d['by']}){plan_note}")


def mark(e):
    """Journal line tail: unparsed marker and source (entries migrated from old journals)."""
    return (" [unparsed]" if e.get("unparsed") else "") + (f" [{e['src']}]" if e.get("src") else "")


def cmd_log(a):
    mod, home, task = resolve_target(a.target)
    rows = [(e.get("t", ""), "ev", e) for e in read_jsonl(home / "events.jsonl") if task is None or e.get("task") == task]
    if not a.no_decisions:
        rows += [(d.get("t", ""), "dec", d) for d in read_jsonl(home / "decisions.jsonl") if task is None or d.get("task") == task]
    rows.sort(key=lambda r: r[0])
    for t, kind, e in rows[-a.n:]:
        if kind == "ev":
            c = (" " + ",".join(e["commits"])) if e.get("commits") else ""
            n = (" — " + short(e["note"], 100 if not a.full else 10000)) if e.get("note") else ""
            print(f"{t[5:16].replace('T', ' ')} {e.get('task') or '·'} {e['ev']} ({e.get('by', '-')}){c}{n}{mark(e)}")
        else:
            tag = ("question " + str(e.get("id", ""))) if e.get("kind") == "question" else (
                "decision" + (f" (answer to {e['answers']})" if e.get("answers") else ""))
            why = f" — why: {short(e['why'], 100 if not a.full else 10000)}" if e.get("why") else ""
            print(f"{t[5:16].replace('T', ' ')} {e.get('task') or '·'} {tag} ({e.get('by', '-')}): "
                  f"{short(e.get('text', ''), 100 if not a.full else 10000)}{why}{mark(e)}")


def inbox_task(a):
    """inbox <ID>: card addenda and edits since last read (marker per reader and task)."""
    mod, home = find_task(a.module)
    reader = a.by or os.environ.get("DPCLI_ROLE") or "executor"
    stamp_p = home / f".read_{reader}.{a.module}"
    since = stamp_p.read_text().strip() if stamp_p.exists() else ""
    items = []
    for e in read_jsonl(home / "events.jsonl"):
        if e.get("task") != a.module or e.get("t", "") <= since or e.get("by") == reader:
            continue
        if e.get("addendum"):
            items.append((e["t"], f"addendum ({e.get('by', '-')}): {e['note']}"))
        elif e.get("ev") == "edited":
            items.append((e["t"], f"card edited ({e.get('by', '-')}): {e.get('note', '')} — {CLI} task show {a.module} --diff"))
    if not items:
        print(f"{a.module}: nothing new")
    for t, what in items[-a.max:]:
        print(f"{hm(t)} {short(what, 400 if not a.full else 10000)}")
    if not a.peek:
        stamp_p.write_text(now() + "\n")


def cmd_inbox(a):
    mods = all_modules()
    if a.module not in mods and ID_RE.match(a.module):
        return inbox_task(a)
    if a.module not in mods:
        raise DpError(f"module {a.module} not found (have: {', '.join(mods) or 'none'})")
    home = mods[a.module]
    reader = a.by or os.environ.get("DPCLI_ROLE") or "coordinator"
    stamp_p = home / f".read_{reader}"
    since = stamp_p.read_text().strip() if stamp_p.exists() else ""
    decs = read_jsonl(home / "decisions.jsonl")
    qtext = {d.get("id"): d.get("text", "") for d in decs if d.get("kind") == "question"}
    items = []
    for d in decs:
        if d.get("t", "") < since or d.get("by") == reader:
            continue
        if d.get("kind") == "question":
            what = f"question {d['id']}: {d['text']}"
        elif d.get("answers"):
            what = f"answer to {d['answers']} «{short(qtext.get(d['answers'], ''), 60)}»: {d['text']}"
        else:
            what = f"decision: {d['text']}"
        items.append((d["t"], f"{what}" + (f" — {d['why']}" if d.get("why") else "") + f" ({d.get('by', '-')})"))
    for e in read_jsonl(home / "events.jsonl"):
        if e.get("t", "") >= since and e.get("ev") in ("plan", "note") and e.get("by") != reader:
            items.append((e["t"], f"{'plan edit' if e['ev'] == 'plan' else 'note'} ({e.get('by', '-')}): {e.get('note', '')}"))
    items.sort()
    if not items:
        print(f"{a.module}: nothing new")
    else:
        skipped = max(0, len(items) - a.max)
        if skipped:
            print(f"… {skipped} more older")
        for t, what in items[-a.max:]:
            print(f"{hm(t)} {short(what, 400 if not a.full else 10000)}")
    if not a.peek:
        stamp_p.write_text(now() + "\n")


def find_open_question(qid, module=None):
    """(module, home, question) by Qn or module/Qn."""
    if "/" in qid:
        module, _, qid = qid.partition("/")
    mods = all_modules()
    hits = []
    for m, h in mods.items():
        if module and m != module:
            continue
        hits += [(m, h, q) for q in open_questions(h) if q.get("id") == qid]
    if not hits:
        raise DpError(f"no open question {qid}" + (f" in module {module}" if module else "") + f" ({CLI} questions)")
    if len(hits) > 1:
        raise DpError(f"{qid} is open in several modules ({', '.join(m for m, _, _ in hits)}): --module")
    return hits[0]


def cmd_questions(a):
    n, lim = 0, 200 if not a.full else 10000
    mods = all_modules()
    if a.module:
        if a.module not in mods:
            raise DpError(f"module {a.module} not found (have: {', '.join(mods) or 'none'})")
        mods = {a.module: mods[a.module]}
    for m, h in mods.items():
        if not (a.all or a.module):
            for q in open_questions(h):
                n += 1
                print(f"{q['id']} [{m}] ({age(q['t'])}): {short(q['text'], lim)}")
            continue
        ans = question_answers(h)
        for q in read_jsonl(h / "decisions.jsonl"):
            if q.get("kind") != "question":
                continue
            n += 1
            d = ans.get(q.get("id"))
            print(f"{q['id']} [{m}] ({age(q['t'])}) {'✓' if d else '?'} {short(q['text'], lim)}"
                  + (f"\n    → {short(d['text'], lim)} ({d.get('by', '-')}, {hm(d['t'])})" if d else ""))
    if not n:
        print("no open questions" if not (a.all or a.module) else "no questions")


def cmd_answer(a):
    mod, home, q = find_open_question(a.qid, a.module)
    d = {"t": now(), "by": a.by or "user", "kind": "decision", "text": a.text, "answers": q["id"]}
    append_jsonl(home / "decisions.jsonl", d)
    print(f"{mod}: answer to {q['id']} recorded ({d['by']}) → {CLI} inbox {mod}")


def register(sp):
    q = sp.add_parser("event", help="task event (or module note) in events.jsonl")
    q.add_argument("target", metavar="ID|module"); q.add_argument("kind", choices=EVENT_KINDS)
    q.add_argument("--commit", action="append"); q.add_argument("--note"); q.add_argument("--by")
    q.set_defaults(func=cmd_event)

    q = sp.add_parser("decide", help="decision (or --ask: question to the user) in decisions.jsonl")
    q.add_argument("module"); q.add_argument("text")
    q.add_argument("--by", help="user|coordinator|main"); q.add_argument("--why"); q.add_argument("--task")
    q.add_argument("--ask", action="store_true", help="open a question (gate) → Qn")
    q.add_argument("--answers", metavar="Qn", help="closes the question")
    q.add_argument("--plan", nargs="?", const=DEFAULT_SECTION, metavar="SECTION",
                   help=f"append «- **decision** (date) — why» to a plan section (no value — «{DEFAULT_SECTION}»)")
    q.add_argument("--date", help=argparse.SUPPRESS)
    q.set_defaults(func=cmd_decide)

    q = sp.add_parser("log", help="latest events of a module or task")
    q.add_argument("target", metavar="ID|module"); q.add_argument("-n", type=int, default=10)
    q.add_argument("--full", action="store_true")
    q.add_argument("--no-decisions", dest="no_decisions", action="store_true", help="hide decisions/questions")
    q.set_defaults(func=cmd_log)

    q = sp.add_parser("inbox", help="what's new for the reader in a module: decisions, answers, plan edits, notes")
    q.add_argument("module", metavar="module|ID")
    q.add_argument("--by", help="reader (default $DPCLI_ROLE or coordinator; for an ID — executor)")
    q.add_argument("--peek", action="store_true", help="don't mark as read"); q.add_argument("--max", type=int, default=20)
    q.add_argument("--full", action="store_true")
    q.set_defaults(func=cmd_inbox)

    q = sp.add_parser("questions", help="open questions to the user across all modules (--all/--module — incl. answered, with answers)")
    q.add_argument("--full", action="store_true")
    q.add_argument("--all", action="store_true", help="also answered, with answer text")
    q.add_argument("--module", help="only this module (all its questions with answers)")
    q.set_defaults(func=cmd_questions)

    q = sp.add_parser("answer", help="user's answer to question Qn (lands in the module inbox)")
    q.add_argument("qid", metavar="Qn|module/Qn"); q.add_argument("text"); q.add_argument("--module"); q.add_argument("--by")
    q.set_defaults(func=cmd_answer)
