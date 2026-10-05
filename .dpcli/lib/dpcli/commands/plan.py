"""plan (оглавление/раздел), plan edit, render (md-журнал модуля)."""
import sys
from pathlib import Path

from .. import config, gitx
from ..journal import (add_event, all_modules, by_default, home_root, module_home, module_meta, task_cards,
                       task_states)
from ..mdsec import find_section, section_body, section_end, toc
from ..mdsec import headings as plan_headings
from ..util import CLI, DpError, read_json, read_jsonl, rel, short

DEFAULT_SECTION = "Решения пользователя"


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
    if a.target == "edit":
        if not a.section or not a.extra:
            raise DpError(f"{CLI} plan edit <модуль|файл.md> <раздел> --append|--replace СТАРОЕ НОВОЕ|--set [ФАЙЛ|-]")
        a.target, a.section = a.section, a.extra
        return cmd_plan_edit(a)
    path = plan_path(a.target, a.contracts)
    if not path.exists():
        raise DpError(f"нет файла {rel(path)}")
    lines, heads = plan_headings(path.read_text())
    if not a.section:
        print(f"{rel(path)} — {len(lines)} строк; {CLI} plan {a.target} <номер|текст>")
        for t in toc(lines, heads, a.depth):
            print(t)
        return
    sel = find_section(heads, a.section)
    if sel is None:
        raise DpError(f"раздел «{a.section.strip()}» не найден; оглавление — {CLI} plan {a.target}")
    print("\n".join(section_body(lines, heads, sel, a.max)))


def plan_edit(target, section, contracts=False, append=None, replace=None, set_=None, create=False, all_=False):
    """Правка тела раздела (раздел «*» — весь файл, только --replace). → (путь, заголовок, что сделано)."""
    path = plan_path(target, contracts)
    if not path.exists():
        raise DpError(f"нет файла {rel(path)}")
    if section.strip() == "*":
        if not replace:
            raise DpError("раздел «*» (весь файл) — только с --replace СТАРОЕ НОВОЕ")
        old, new = replace
        text = path.read_text()
        n = text.count(old)
        if n == 0 or (n > 1 and not all_):
            raise DpError(f"«{short(old, 40)}» в файле: вхождений {n}" + ("" if n == 0 else ", нужно ровно одно (--all — все)"))
        path.write_text(text.replace(old, new))
        return path, "весь файл", f"замена «{short(old, 25)}» ×{n}"
    lines, heads = plan_headings(path.read_text())
    sel = find_section(heads, section)
    if sel is None:
        if not create:
            raise DpError(f"раздел «{section.strip()}» не найден; оглавление — {CLI} plan {target}")
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
        what = f"дописано {len(new)} стр."
    elif replace:
        old, new = replace
        body = "\n".join(lines[i + 1:end])
        n = body.count(old)
        if n == 0 or (n > 1 and not all_):
            raise DpError(f"«{short(old, 40)}» в разделе «{short(title, 40)}»: вхождений {n}"
                          + ("" if n == 0 else ", нужно ровно одно (--all — все; раздел «*» — весь файл)"))
        lines[i + 1:end] = body.replace(old, new).split("\n")
        what = f"замена «{short(old, 25)}»" + (f" ×{n}" if n > 1 else "")
    elif set_ is not None:
        new = set_.rstrip("\n").splitlines()
        lines[i + 1:be] = ([""] + new) if new else []
        what = f"тело заменено ({len(new)} стр.)"
    else:
        raise DpError("нужно --append, --replace СТАРОЕ НОВОЕ или --set [ФАЙЛ|-]")
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
        add_event(home, None, "plan", by_default(a), note=f"{'контракты' if a.contracts else 'план'} {short(title, 50)}: {what}")
    if a.commit:
        h = gitx.commit_paths(path.parent, [path], f"{a.target if is_mod else path.name}: {'контракты' if a.contracts else 'план'} — "
                                                   f"{short(title.lstrip('§ '), 50)}: {what}")
        out += f"; коммит {h}"
    print(out)


MARK = "<!-- generated by dpcli render; не править руками -->"


def cmd_render(a):
    mods = all_modules()
    if a.module not in mods:
        raise DpError(f"модуль {a.module} не найден")
    home = mods[a.module]
    meta = module_meta(a.module, home)
    st = task_states(home)
    cards = task_cards(home)
    reps = {p.name[:-12]: read_json(p) for p in (home / "tasks").glob("*.report.json")}
    revs = {p.name[:-12]: read_json(p) for p in sorted((home / "tasks").glob("*.review.json"))}
    evs = read_jsonl(home / "events.jsonl")
    decs = read_jsonl(home / "decisions.jsonl")
    L = [MARK, f"# Журнал модуля «{a.module}»", "",
         f"План — `{meta['plan']}`, контракты — `{meta['contracts']}`. Ветка `{meta['branch']}`, копия `{meta.get('copy', '')}`.",
         f"Источник — `{config.plan_dir()}/{a.module}/` (события, решения, карточки, отчёты); файл собран `{CLI} render`.", ""]
    L += ["## Решения", ""]
    answered = {x.get("answers") for x in decs if x.get("answers")}
    for d in decs:
        tag = {"user": "решение пользователя", "coordinator": "решение координатора", "main": "главная сессия"}.get(d.get("by"), d.get("by", ""))
        if d.get("kind") == "question":
            tag = f"вопрос {d['id']}" + (" (закрыт)" if d["id"] in answered else " — **ждёт решения**")
        why = f" Почему: {d['why']}" if d.get("why") else ""
        ans = f" (ответ на {d['answers']})" if d.get("answers") else ""
        L.append(f"- {d['t'][8:10]}.{d['t'][5:7]} — {tag}{ans}: {d['text']}{why}")
    L += ["", "## Задачи", "", "| Задача | Статус | Исполнитель | Копия / ветка | Коммиты | Итог |", "|---|---|---|---|---|---|"]
    order = list(cards) + [t for t in st if t not in cards]
    for tid in order:
        c = cards.get(tid) or {}
        s = st.get(tid, {"status": "created", "t": "", "commits": []})
        r = reps.get(tid) or {}
        res = r.get("summary", "") or s.get("note", "")
        if r.get("checks"):
            res += " Проверки: " + "; ".join(f"{x['name']} {x.get('value', '')}" for x in r["checks"])
        date = f" ({s['t'][8:10]}.{s['t'][5:7]})" if s.get("t") else ""
        cell = lambda x: str(x).replace("|", "\\|").replace("\n", " ")  # noqa: E731
        L.append(f"| {tid} {cell(c.get('title', ''))} | **{s['status']}**{date} | {c.get('type', '')} | "
                 f"`{c.get('branch', '')}` | {', '.join(s.get('commits', []))} | {cell(res)} |")
    L += ["", "## Ревью", ""]
    for tid, rv in revs.items():
        if not rv:
            continue
        L.append(f"- {tid} — **{rv.get('verdict')}** ({rv.get('by', '-')}, {str(rv.get('t', ''))[:16].replace('T', ' ')}): "
                 + str(rv.get("summary", "")).replace("\n", " "))
        for i in rv.get("issues", []):
            ln = f":{i['line']}" if i.get("line") not in (None, "") else ""
            L.append(f"  - [{i.get('severity')}] `{i.get('file')}{ln}` {i.get('what')} → {i.get('fix')}")
    if not revs:
        L.append("- нет")
    L += ["", "## Хронология", ""]
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
        raise DpError(f"{rel(op)} написан руками — не перезаписываю (--out другой путь или --force)")
    op.parent.mkdir(parents=True, exist_ok=True)
    op.write_text(text)
    print(f"{rel(op)}: {len(L)} строк, задач {len(order)}, событий {len(evs)}, решений {len(decs)}")


def register(sp):
    q = sp.add_parser("plan", help="оглавление плана или раздел (номер из оглавления или начало заголовка); plan edit — правка")
    q.add_argument("target", metavar="модуль|файл.md|edit"); q.add_argument("section", nargs="?"); q.add_argument("extra", nargs="?")
    q.add_argument("--contracts", action="store_true", help="файл контрактов модуля вместо плана")
    q.add_argument("--append", metavar="ТЕКСТ", help="edit: дописать в конец раздела")
    q.add_argument("--replace", nargs=2, metavar=("СТАРОЕ", "НОВОЕ"),
                   help="edit: точная замена в разделе (ровно одно вхождение; --all — все; раздел «*» — весь файл)")
    q.add_argument("--all", action="store_true", help="edit --replace: заменить все вхождения")
    q.add_argument("--set", nargs="?", const="-", metavar="ФАЙЛ", help="edit: заменить тело раздела (ФАЙЛ или stdin)")
    q.add_argument("--commit", action="store_true", help="edit: закоммитить файл (только его)"); q.add_argument("--by")
    q.add_argument("--depth", type=int, default=3, help="уровни заголовков в оглавлении (3)")
    q.add_argument("--max", type=int, default=150, help="строк раздела (150; 0 — всё)")
    q.set_defaults(func=cmd_plan)

    q = sp.add_parser("render", help="собрать md-журнал <plan_dir>/<модуль>/journal.md")
    q.add_argument("module"); q.add_argument("--out", help="путь или - (stdout)"); q.add_argument("--force", action="store_true")
    q.set_defaults(func=cmd_render)
