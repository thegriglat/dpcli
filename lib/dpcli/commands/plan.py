"""plan (table of contents/section), plan edit, render (module md journal)."""
import sys
from pathlib import Path

from .. import config, gitx
from ..journal import (add_event, all_modules, by_default, home_root, module_home, module_meta, task_cards,
                       task_states)
from ..mdsec import find_section, section_body, section_end, toc
from ..mdsec import headings as plan_headings
from ..util import CLI, DpError, lang_commit, lang_text, read_json, read_jsonl, rel, short

DEFAULT_SECTION = lang_text("User decisions", "Решения пользователя")
_DEFAULT_ALTS = ("User decisions", "Решения пользователя")


def plan_path(target, contracts=False):
    if target.endswith(".md") or "/" in target:
        path = Path(target)
        if path.is_absolute() or path.exists():
            return path
        return gitx.toplevel() / path
    home = all_modules().get(target) or module_home(target)
    meta = module_meta(target, home)
    f = meta["contracts"] if contracts else meta["plan"]
    root = home_root(home)
    return root / f if (root / f).exists() else gitx.toplevel() / f


def cmd_plan(a):
    words = a.section or []
    if a.target == "edit":
        if len(words) < 2:
            raise DpError(f"{CLI} plan edit <module|FILE.md> <section> --append|--replace OLD NEW|--set [FILE|-]")
        a.target, a.section = words[0], " ".join(words[1:])
        return cmd_plan_edit(a)
    a.section = " ".join(words)
    path = plan_path(a.target, a.contracts)
    if not path.exists():
        raise DpError(f"no file {rel(path)}")
    lines, heads = plan_headings(path.read_text())
    if not a.section:
        print(f"{rel(path)} — {len(lines)} lines; {CLI} plan {a.target} <number|text>")
        for t in toc(lines, heads, a.depth):
            print(t)
        return
    sel = find_section(heads, a.section)
    if sel is None:
        raise DpError(f"section \"{a.section.strip()}\" not found; table of contents: {CLI} plan {a.target}")
    print("\n".join(section_body(lines, heads, sel, a.max)))


def plan_edit(target, section, contracts=False, append=None, replace=None, set_=None, create=False, all_=False):
    """Edit a section body (section "*" = whole file, --replace only). -> (path, heading, what was done)."""
    path = plan_path(target, contracts)
    if not path.exists():
        raise DpError(f"no file {rel(path)}")
    if section.strip() == "*":
        if not replace:
            raise DpError("section \"*\" (whole file) works only with --replace OLD NEW")
        old, new = replace
        text = path.read_text()
        n = text.count(old)
        if n == 0 or (n > 1 and not all_):
            raise DpError(f"\"{short(old, 40)}\" in file: {n} occurrences" + ("" if n == 0 else ", exactly one needed (--all: all)"))
        path.write_text(text.replace(old, new))
        return path, "whole file", f"replaced \"{short(old, 25)}\" x{n}"
    lines, heads = plan_headings(path.read_text())
    sel = find_section(heads, section)
    if sel is None and section in _DEFAULT_ALTS:  # old plans keep the other-language section
        sel = next((x for x in map(lambda q: find_section(heads, q), _DEFAULT_ALTS) if x is not None), None)
    if sel is None:
        if not create:
            raise DpError(f"section \"{section.strip()}\" not found; table of contents: {CLI} plan {target}")
        lines += ["", f"## {section}", ""]
        lines, heads = plan_headings("\n".join(lines))
        sel = len(heads) - 1
    i, _, title = heads[sel]
    end = section_end(lines, heads, sel)
    be = end
    while be > i + 1 and not lines[be - 1].strip():
        be -= 1
    if append is not None:
        new = append.rstrip("\n").splitlines()
        lines[be:be] = ([""] if be == i + 1 else []) + new
        what = f"appended {len(new)} lines"
    elif replace:
        old, new = replace
        body = "\n".join(lines[i + 1:end])
        n = body.count(old)
        if n == 0 or (n > 1 and not all_):
            raise DpError(f"\"{short(old, 40)}\" in section \"{short(title, 40)}\": {n} occurrences"
                          + ("" if n == 0 else ", exactly one needed (--all: all; section \"*\": whole file)"))
        lines[i + 1:end] = body.replace(old, new).split("\n")
        what = f"replaced \"{short(old, 25)}\"" + (f" x{n}" if n > 1 else "")
    elif set_ is not None:
        new = set_.rstrip("\n").splitlines()
        lines[i + 1:be] = ([""] + new) if new else []
        what = f"body replaced ({len(new)} lines)"
    else:
        raise DpError("need --append, --replace OLD NEW or --set [FILE|-]")
    path.write_text("\n".join(lines) + "\n")
    return path, title, what


def cmd_plan_edit(a):
    set_ = None
    if a.set is not None:
        set_ = sys.stdin.read() if a.set == "-" else Path(a.set).read_text()
    path, title, what = plan_edit(a.target, a.section, a.contracts, a.append, a.replace, set_, all_=a.all)
    out = f"{a.target}: {short(title, 50)}: {what}"
    is_mod = not (a.target.endswith(".md") or "/" in a.target)
    if is_mod:
        home = all_modules().get(a.target) or module_home(a.target)
        add_event(home, None, "plan", by_default(a), note=f"{'contracts' if a.contracts else 'plan'} {short(title, 50)}: {what}")
    if a.commit:
        kind = lang_commit("contracts" if a.contracts else "plan", "контракты" if a.contracts else "план")
        h = gitx.commit_paths(path.parent, [path], f"{a.target if is_mod else path.name}: {kind} - "
                                                   f"{short(title.lstrip('§ '), 50)}: {what}")
        out += f"; commit {h}"
    print(out)


MARK = "<!-- generated by dpcli render; do not edit by hand -->"


def cmd_render(a):
    mods = all_modules()
    if a.module not in mods:
        raise DpError(f"module {a.module} not found")
    home = mods[a.module]
    meta = module_meta(a.module, home)
    st = task_states(home)
    cards = task_cards(home)
    reps = {p.name[:-12]: read_json(p) for p in (home / "tasks").glob("*.report.json")}
    revs = {p.name[:-12]: read_json(p) for p in sorted((home / "tasks").glob("*.review.json"))}
    evs = read_jsonl(home / "events.jsonl")
    decs = read_jsonl(home / "decisions.jsonl")
    T = lang_text
    L = [MARK, T(f"# Module journal \"{a.module}\"", f"# Журнал модуля «{a.module}»"), "",
         T(f"Plan: `{meta['plan']}`, contracts: `{meta['contracts']}`. Branch `{meta['branch']}`, copy `{meta.get('copy', '')}`.",
           f"План — `{meta['plan']}`, контракты — `{meta['contracts']}`. Ветка `{meta['branch']}`, копия `{meta.get('copy', '')}`."),
         T(f"Source: `{config.plan_dir()}/{a.module}/` (events, decisions, cards, reports); file built by `{CLI} render`.",
           f"Источник — `{config.plan_dir()}/{a.module}/` (события, решения, карточки, отчёты); файл собран `{CLI} render`."), ""]
    L += [T("## Decisions", "## Решения"), ""]
    answered = {x.get("answers") for x in decs if x.get("answers")}
    tags = {"user": T("user decision", "решение пользователя"), "coordinator": T("coordinator decision", "решение координатора"),
            "main": T("main session", "главная сессия")}
    for d in decs:
        tag = tags.get(d.get("by"), d.get("by", ""))
        if d.get("kind") == "question":
            tag = T("question", "вопрос") + f" {d['id']}" + (T(" (closed)", " (закрыт)") if d["id"] in answered else T(" - **awaiting decision**", " — **ждёт решения**"))
        why = f" {T('Why', 'Почему')}: {d['why']}" if d.get("why") else ""
        ans = f" ({T('answer to', 'ответ на')} {d['answers']})" if d.get("answers") else ""
        L.append(f"- {d['t'][8:10]}.{d['t'][5:7]} — {tag}{ans}: {d['text']}{why}")
    L += ["", T("## Tasks", "## Задачи"), "", T("| Task | Status | Executor | Copy / branch | Commits | Result |", "| Задача | Статус | Исполнитель | Копия / ветка | Коммиты | Итог |"), "|---|---|---|---|---|---|"]
    order = list(cards) + [t for t in st if t not in cards]
    for tid in order:
        c = cards.get(tid) or {}
        s = st.get(tid, {"status": "created", "t": "", "commits": []})
        r = reps.get(tid) or {}
        res = r.get("summary", "") or s.get("note", "")
        if r.get("checks"):
            res += T(" Checks: ", " Проверки: ") + "; ".join(f"{x['name']} {x.get('value', '')}" for x in r["checks"])
        date = f" ({s['t'][8:10]}.{s['t'][5:7]})" if s.get("t") else ""
        cell = lambda x: str(x).replace("|", "\\|").replace("\n", " ")  # noqa: E731
        L.append(f"| {tid} {cell(c.get('title', ''))} | **{s['status']}**{date} | {c.get('type', '')} | "
                 f"`{c.get('branch', '')}` | {', '.join(s.get('commits', []))} | {cell(res)} |")
    L += ["", T("## Review", "## Ревью"), ""]
    for tid, rv in revs.items():
        if not rv:
            continue
        L.append(f"- {tid} — **{rv.get('verdict')}** ({rv.get('by', '-')}, {str(rv.get('t', ''))[:16].replace('T', ' ')}): "
                 + str(rv.get("summary", "")).replace("\n", " "))
        for i in rv.get("issues", []):
            ln = f":{i['line']}" if i.get("line") not in (None, "") else ""
            L.append(f"  - [{i.get('severity')}] `{i.get('file')}{ln}` {i.get('what')} → {i.get('fix')}")
    if not revs:
        L.append(T("- none", "- нет"))
    L += ["", T("## Timeline", "## Хронология"), ""]
    for e in evs:
        cm = f" [{', '.join(e['commits'])}]" if e.get("commits") else ""
        L.append(f"- {e['t'][:16].replace('T', ' ')} {e.get('task') or '—'} **{e['ev']}** ({e.get('by', '-')}){cm}"
                 + (f": {e['note']}" if e.get("note") else ""))
    text = "\n".join(L) + "\n"
    out = a.out or str(gitx.toplevel() / config.plan_dir() / a.module / "journal.md")
    if out == "-":
        sys.stdout.write(text)
        return
    op = Path(out)
    if op.exists() and not op.read_text().startswith("<!-- generated by") and not a.force:
        raise DpError(f"{rel(op)} is hand-written, not overwriting (--out other path or --force)")
    op.parent.mkdir(parents=True, exist_ok=True)
    op.write_text(text)
    print(f"{rel(op)}: {len(L)} lines, tasks {len(order)}, events {len(evs)}, decisions {len(decs)}")


def register(sp):
    q = sp.add_parser("plan", help="plan table of contents or section (number from TOC or heading prefix); plan edit: edit")
    q.add_argument("target", metavar="module|FILE.md|edit"); q.add_argument("section", nargs="*", help="number or heading; several words need no quotes")
    q.add_argument("--contracts", action="store_true", help="module contracts file instead of plan")
    q.add_argument("--append", metavar="TEXT", help="edit: append to end of section")
    q.add_argument("--replace", nargs=2, metavar=("OLD", "NEW"),
                   help="edit: exact replace in section (exactly one match; --all: all; section \"*\": whole file)")
    q.add_argument("--all", action="store_true", help="edit --replace: replace all occurrences")
    q.add_argument("--set", nargs="?", const="-", metavar="FILE", help="edit: replace section body (FILE or stdin)")
    q.add_argument("--commit", action="store_true", help="edit: commit the file (only it)"); q.add_argument("--by")
    q.add_argument("--depth", type=int, default=3, help="heading levels in table of contents (3)")
    q.add_argument("--max", type=int, default=150, help="section lines (150; 0: all)")
    q.set_defaults(func=cmd_plan)

    q = sp.add_parser("render", help="build md journal <plan_dir>/<module>/journal.md")
    q.add_argument("module"); q.add_argument("--out", help="path or - (stdout)"); q.add_argument("--force", action="store_true")
    q.set_defaults(func=cmd_render)
