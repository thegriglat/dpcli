"""module new, sync, merge, gc — ветки и рабочие копии."""
import fnmatch
import subprocess
from pathlib import Path

from .. import config, gitx
from ..journal import FINAL, add_event, all_modules, by_default, check_code, ensure_module, task_cards, task_states
from ..util import DpError, pretty, subgroup


def resolve_branch(x):
    """модуль или имя ветки → ветка."""
    if gitx.branch_exists(x):
        return x
    mb = config.module_branch(x)
    if gitx.branch_exists(mb):
        return mb
    raise DpError(f"ветки {x} (или {mb}) нет")


def cmd_module_new(a):
    mod = a.module
    br = config.module_branch(mod)
    copy = config.module_copy(mod)
    if gitx.branch_exists(br):
        raise DpError(f"ветка {br} уже есть")
    if copy.exists():
        raise DpError(f"{copy} уже существует")
    base = a.from_ or config.main_branch()
    if not gitx.branch_exists(base):
        raise DpError(f"базовой ветки {base} нет")
    if a.code:
        check_code(a.code, mod)  # до git worktree add: неверный код не оставляет ветку и копию
    r = gitx.gitr("worktree", "add", "-b", br, str(copy), base)
    if r.returncode:
        raise DpError(f"git worktree add: {gitx.gerr(r)}")
    gitx.reset_worktrees()
    home = copy / config.plan_dir() / mod
    ensure_module(mod, home, copy=pretty(copy), code=a.code)
    add_event(home, None, "note", by_default(a), note=f"модуль заведён от {base}")
    h = gitx.commit_paths(copy, [home], f"{mod}: заведён модуль dpcli (module.json, events.jsonl)")
    print(f"{mod}: {br} от {base} @ {pretty(copy)}, коммит {h}")


def cmd_sync(a):
    br = resolve_branch(a.target)
    path = gitx.copy_of(br)
    if not path:
        raise DpError(f"у ветки {br} нет рабочей копии")
    main = config.main_branch()
    h, n, kind = gitx.do_merge(path, main, a.message or f"Слияние {main} в {br}", trailers=a.trailer)
    print(f"{br}: {main} уже влит" if kind == "up-to-date" else f"{br}: влит {main}, {h}, файлов {n}")


def cmd_merge(a):
    from .search import sem_index_bg
    into = a.into or config.main_branch()
    br = resolve_branch(a.branch)
    path = gitx.copy_of(into)
    if not path:
        raise DpError(f"ветка {into} нигде не выписана — нужна копия, где она открыта")
    subj = gitx.gitr("log", "-1", "--format=%s", br, "--").stdout.strip()
    h, n, kind = gitx.do_merge(path, br, a.message or f"Слияние {br}: {subj}", ff=False, trailers=a.trailer)
    out = f"{into}: {br} уже влита" if kind == "up-to-date" else f"{into} {h}: слияние {br}, файлов {n}"
    if a.push:
        r = gitx.gitr("push", "origin", into, cwd=path)
        if r.returncode:
            raise DpError(f"{out}; push не удался: {gitx.gerr(r)}")
        out += "; pushed"
    if into == config.main_branch() and kind != "up-to-date" and not a.no_index:
        out += "; " + sem_index_bg()
    print(out)


def gc_live_reason(b, merged, mods):
    """Почему влитую ветку нельзя убирать: у модуля/задачи идёт работа. None — можно."""
    mod = config.module_of_branch(b)
    is_mod = mod is not None
    if not is_mod:
        tf = config.task_branch_fields(b)
        mod = tf.get("module") if tf else None
    if not mod or mod not in mods:
        return None
    home = mods[mod]
    st = task_states(home)
    cards = task_cards(home)
    if is_mod:
        live = sorted(t for t in cards if st.get(t, {}).get("status", "created") not in FINAL)
        if live:
            return f"у модуля незакрытые задачи ({', '.join(live[:4])}{'…' if len(live) > 4 else ''})"
        subs = [x for x in gitx.local_branches()
                if x not in merged and (config.task_branch_fields(x) or {}).get("module") == mod]
        if subs:
            return f"живые ветки задач ({', '.join(subs[:3])})"
        return None
    for t, c in cards.items():
        if c and c.get("branch") == b and st.get(t, {}).get("status", "created") not in FINAL:
            return f"задача {t} не закрыта ({st.get(t, {}).get('status', 'created')})"
    return None


def gc_symlink_reason(path, wt_paths):
    """Симлинки из других копий внутрь path (например на .venv) — их сломает удаление копии."""
    root = Path(path).resolve()
    hits = []
    for other in wt_paths:
        if Path(other).resolve() == root:
            continue
        out = subprocess.run(["git", "-C", str(other), "status", "--porcelain", "--ignored"], capture_output=True, text=True).stdout
        for l in out.splitlines():
            if l[:3] not in ("?? ", "!! "):
                continue
            f = Path(other) / l[3:].rstrip("/")
            if f.is_symlink():
                try:
                    tgt = f.resolve()
                except OSError:
                    continue
                if tgt == root or root in tgt.parents:
                    hits.append(f"{pretty(f)} → {pretty(tgt)}")
    return f"на неё ссылаются симлинки других копий ({'; '.join(hits[:2])})" if hits else None


def ignored_dirs(path):
    """Игнорируемые git каталоги копии, кроме кешей сборки gc.ignore_dirs (их тоже снимет удаление копии)."""
    skip = set(config.get("gc.ignore_dirs") or [])
    out = subprocess.run(["git", "-C", str(path), "status", "--porcelain", "--ignored"], capture_output=True, text=True).stdout
    return [l[3:] for l in out.splitlines() if l.startswith("!! ") and l.endswith("/")
            and l[3:].rstrip("/").split("/")[0] not in skip and not any(f"{d}/" in l for d in skip)]


def junk_ok(f):
    """Неотслеживаемый файл — сгенерированный (gc.ignore_globs), не работа."""
    name = f.rstrip("/").rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(name, g) or fnmatch.fnmatch(f, g) for g in config.get("gc.ignore_globs") or [])


def cmd_gc(a):
    main = config.main_branch()
    main_tip = gitx.gitr("rev-parse", main).stdout.strip()
    merged = [b for b in gitx.gitr("branch", "--merged", main, "--format=%(refname:short)").stdout.split() if b != main]
    here = str(gitx.toplevel())
    wt = {b: p for p, b in gitx.worktrees()}
    n = 0
    if a.branches:
        want = {x if "/" in x else config.module_branch(x) for x in a.branches} | set(a.branches)
        miss = [x for x in a.branches if x not in merged and config.module_branch(x) not in merged]
        if miss:
            raise DpError(f"не влиты в {main} или нет такой ветки: {', '.join(miss)}")
        merged = [b for b in merged if b in want]
    mods = all_modules()
    for b in merged:
        if gitx.gitr("rev-parse", b).stdout.strip() == main_tip:
            continue  # ветка = главной (только что заведена или влита fast-forward) — не трогаем
        path = wt.get(b)
        label = f"{b}" + (f" @ {pretty(path)}" if path else " (без копии)")
        why = gc_live_reason(b, merged, mods) or (path and gc_symlink_reason(path, wt.values()))
        if why:
            print(f"пропуск {label}: {why}")
            continue
        if not a.remove:
            ign = ignored_dirs(path) if path else []
            print(label + (f" (снимет и игнорируемые: {', '.join(ign[:4])})" if ign else ""))
            n += 1
            continue
        if path and path == here:
            print(f"пропуск {label}: это текущая копия")
            continue
        ign = []
        if path:
            d = gitx.dirty(path)
            if d:
                print(f"пропуск {label}: грязная копия ({len(d)} файлов)")
                continue
            junk = [l[3:] for l in subprocess.run(["git", "-C", str(path), "status", "--porcelain"], capture_output=True,
                                                     text=True).stdout.splitlines() if l.startswith("?? ")]
            other = [f for f in junk if not junk_ok(f)]
            if other:
                print(f"пропуск {label}: неотслеживаемые файлы ({len(other)}: {', '.join(other[:3])})")
                continue
            # только сгенерированные файлы (gc.ignore_globs) — не работа, снимаем копию с --force
            ign = ignored_dirs(path)
            r = gitx.gitr("worktree", "remove", *(["--force"] if junk else []), path)
            if r.returncode:
                print(f"пропуск {label}: {gitx.gerr(r)}")
                continue
        r = gitx.gitr("branch", "-d", b)
        print((f"удалено {label}" + (f" (с игнорируемыми: {', '.join(ign[:4])})" if path and ign else ""))
              if r.returncode == 0 else f"копия снята, ветка {b} осталась: {gitx.gerr(r)}")
        n += 1
    if not n:
        print("влитых веток нет")


def register(sp):
    msp = subgroup(sp, "module", "модуль: new (ветка + копия + журнал) | init (только журнал)")
    q = msp.add_parser("new", help="ветка модуля (module_branch) + git worktree (module_copy) + module.json/events.jsonl")
    q.add_argument("module"); q.add_argument("--from", dest="from_", default=None, help="базовая ветка (по умолчанию main_branch)")
    q.add_argument("--by")
    q.add_argument("--code", help="код модуля для ID задач: 2–4 заглавные латинские (NN, UC), уникален")
    q.set_defaults(func=cmd_module_new)

    q = sp.add_parser("sync", help="влить главную ветку в ветку модуля (в её копии)")
    q.add_argument("target", metavar="модуль|ветка")
    q.add_argument("--message", "-m", help="сообщение слияния вместо стандартного")
    q.add_argument("--trailer", action="append", help="доп. строка в конец сообщения (можно несколько)")
    q.set_defaults(func=cmd_sync)

    q = sp.add_parser("merge", help="слияние --no-ff ветки в целевую (в копии, где она выписана)")
    q.add_argument("branch", metavar="ветка|модуль"); q.add_argument("--into", default=None, help="целевая ветка (main_branch)")
    q.add_argument("--push", action="store_true")
    q.add_argument("--no-index", action="store_true", help="не обновлять смысловой индекс в фоне (при слиянии в главную ветку)")
    q.add_argument("--message", "-m", help="сообщение слияния вместо стандартного")
    q.add_argument("--trailer", action="append", help="доп. строка в конец сообщения (можно несколько)")
    q.set_defaults(func=cmd_merge)

    q = sp.add_parser("gc", help="копии и ветки, уже влитые в главную ветку (список; --remove — удалить)")
    q.add_argument("branches", nargs="*", metavar="ВЕТКА|МОДУЛЬ", help="только эти (модуль → ветка модуля)")
    q.add_argument("--remove", action="store_true")
    q.set_defaults(func=cmd_gc)
