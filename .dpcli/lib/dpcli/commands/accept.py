"""accept: прогон проверок карточки (в т.ч. в фоне через job)."""
import concurrent.futures as cf
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .. import agents, config, gitx, reexec
from ..journal import add_event, by_default, expect_arg, find_task
from ..util import CLI, DpError, die, now, read_json, rel, short, write_json
from .jobs import job_start, tmux_args, tmux_opts


def parse_expect(exp):
    if exp is None:
        return {"exit": 0}
    if isinstance(exp, dict):
        return exp
    s = str(exp).strip()
    if s.startswith("{"):
        return expect_arg(s)
    if s.startswith("exit="):
        return {"exit": int(s[5:])}
    if s.startswith("!re:"):
        return {"not_re": s[4:]}
    if s.startswith("re:"):
        return {"re": s[3:]}
    if s == "tests":
        return {"tests": True}
    if s.startswith("num:"):
        body, _, cond = s[4:].rpartition(" ")
        m = re.fullmatch(r"(>=|<=|==|<|>)(-?[\d.eE+-]+)", cond)
        if not m:
            raise DpError(f"expect «{s}»: ожидалось 'num:<regex> <op><число>'")
        key = {">=": "min", "<=": "max", "==": "eq", ">": "gt", "<": "lt"}[m[1]]
        return {"num": body, key: float(m[2])}
    raise DpError(f"expect «{s}»: не понял (exit=N | re:… | !re:… | num:<regex> <op>N | tests)")


TESTS_SUMMARY = r"(?P<total>\d+) тестов, (?P<failed>\d+) упало(?:, (?P<skipped>\d+) пропущено)?"


def tests_summary_rx():
    """Регэксп итога прогона тестов: checks.tests_summary (группы total, failed; skipped — по желанию)."""
    src = config.get("checks.tests_summary") or TESTS_SUMMARY
    try:
        rx = re.compile(src, re.M)
    except re.error as e:
        raise DpError(f"checks.tests_summary «{src}»: неверный регэксп ({e})")
    if not {"total", "failed"} <= set(rx.groupindex):
        raise DpError(f"checks.tests_summary «{src}»: нужны группы (?P<total>…) и (?P<failed>…)")
    return rx


def judge(exp, code, out):
    """(pass, value)."""
    ok, vals = True, []
    if "exit" in exp:
        ok &= code == exp["exit"]
        vals.append(f"exit {code}")
    if exp.get("tests"):
        m = list(tests_summary_rx().finditer(out))
        if m:
            g = m[-1].groupdict()
            tot, fail, skip = (int(g.get(k) or 0) for k in ("total", "failed", "skipped"))
            ok &= fail == 0 and tot > 0
            vals.append(f"{tot - fail}/{tot}" + (f" (пропуск {skip})" if skip else ""))
            if fail:
                names = re.findall(r"^\s*FAIL (\S+)", out, re.M)
                vals.append("FAIL " + ",".join(n.split("::")[-1] for n in names[:3]))
        else:  # итог (checks.tests_summary) не напечатан — судим по коду выхода раннера
            ok &= code == 0
            if "exit" not in exp:
                vals.append(f"exit {code}")
    if exp.get("re"):
        m = re.search(exp["re"], out, re.M)
        ok &= bool(m)
        vals.append(short(m[0], 40) if m else "нет совпадения")
    if exp.get("not_re"):
        m = re.search(exp["not_re"], out, re.M)
        ok &= not m
        if m:
            vals.append("есть: " + short(m[0], 40))
    if exp.get("num"):
        m = list(re.finditer(exp["num"], out, re.M))
        if not m:
            return False, "число не найдено"
        g = m[-1]
        try:
            v = float((g.group(1) if g.groups() else g.group(0)).replace(",", "."))
        except ValueError:
            return False, f"не число: {short(g[0], 30)}"
        for k, f in (("min", lambda x, y: x >= y), ("max", lambda x, y: x <= y), ("eq", lambda x, y: abs(x - y) < 1e-12),
                     ("gt", lambda x, y: x > y), ("lt", lambda x, y: x < y)):
            if k in exp:
                ok &= f(v, float(exp[k]))
        vals.append(f"{v:g}")
    return bool(ok), "; ".join(vals) or f"exit {code}"


def check_env(tid):
    """Окружение проверки: DPCLI_TASK + checks.env ({tmpdir} — свежий временный каталог на проверку)."""
    env = dict(os.environ, DPCLI_TASK=tid)
    tmp = None
    for k, v in (config.get("checks.env") or {}).items():
        v = str(v)
        if "{tmpdir}" in v and tmp is None:
            tmp = tempfile.mkdtemp(prefix="dpcli-")
        env[str(k)] = os.path.expanduser(config.subst(v.replace("{tmpdir}", tmp or ""), task=tid))
    return env


def run_check(c, cwd, logdir, idx, tid):
    name = c.get("name", f"check{idx}")
    cmd = c.get("cmd")
    if not cmd and c.get("tests"):
        tpl = config.get("checks.tests")
        if not tpl:
            return name, False, "проверка tests недоступна: нет шаблона checks.tests в конфиге", "", 0
        cmd = str(tpl).replace("{filter}", str(c["tests"]))
    if not cmd:
        return name, False, "нет cmd", "", 0
    exp = parse_expect({"tests": True} if c.get("tests") and "expect" not in c else c.get("expect"))
    wd = Path(os.path.expanduser(c.get("cwd") or cwd))
    if not wd.is_absolute():
        wd = Path(cwd) / wd
    env = check_env(tid)
    safe = re.sub(r"[^\w.-]+", "_", name)
    log = logdir / f"{idx:02d}-{safe}.log"
    t0 = time.time()
    try:
        r = subprocess.run(["bash", "-c", cmd], cwd=wd, env=env, capture_output=True, text=True,
                           timeout=c.get("timeout", 900))
        code, out = r.returncode, r.stdout + ("\n" + r.stderr if r.stderr else "")
    except subprocess.TimeoutExpired as e:
        code, out = 124, (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        out += f"\n[dpcli] таймаут {c.get('timeout', 900)} с"
    dur = time.time() - t0
    log.write_text(f"$ cd {wd}\n$ {cmd}\n[exit {code}, {dur:.0f} с]\n\n{out}")
    ok, val = judge(exp, code, out) if code != 124 else (False, "таймаут")
    if not ok and "exit" in val and len(val) < 12:
        tail = [x for x in out.strip().splitlines() if x.strip()][-1:] or [""]
        val += " · " + short(tail[0], 60)
    return name, ok, val, str(log), dur


def accept_bg(a, cwd, logdir):
    """Фоновый прогон (долгие проверки) через job; результат — accept тем же процессом, событие пишет он."""
    skip = {"--bg"}
    argv, it = [], iter(sys.argv[1:])
    for x in it:
        if x in skip:
            continue
        if x in ("--timeout", "--tmux-session"):
            next(it, None)
            continue
        if x in ("--tmux", "--no-tmux") or x.startswith("--tmux-session="):
            continue
        if x.startswith("--timeout="):
            continue
        argv.append(x)
    name = f"dp-accept-{a.id}"
    try:
        job_start(name, a.timeout, [*reexec.self_cmd(), *argv, "--cwd", str(cwd)], tmux_opts(a))
    except DpError as e:
        die(str(e))
    print(f"ждать: {CLI} job wait {name} {a.timeout}; итог — в событиях ({CLI} log {a.id}), логи — {rel(logdir)}")
    sys.exit(0)


def cmd_accept(a):
    mod, home = find_task(a.id)
    card = read_json(home / "tasks" / f"{a.id}.json")
    checks = [c for c in card.get("accept", []) if not a.only or c.get("name") in a.only]
    if not checks:
        raise DpError(f"{a.id}: нет проверок в карточке" + (f" с именами {a.only}" if a.only else ""))
    cwd = a.cwd
    if not cwd:
        cp = Path(os.path.expanduser(card.get("copy", ""))) if card.get("copy") else None
        cwd = str(cp) if cp and cp.is_dir() and not a.here else str(gitx.toplevel())
    logdir = config.repo_path(config.get("checks.log_dir", "build/dpcli")) / a.id
    logdir.mkdir(parents=True, exist_ok=True)
    if a.bg:
        return accept_bg(a, cwd, logdir)
    with cf.ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
        def one(ic):
            nm = ic[1].get("name", f"check{ic[0]}")
            print(f"… {nm}", file=sys.stderr, flush=True)  # прогресс — в stderr, итоговая таблица — в stdout
            r = run_check(ic[1], cwd, logdir, ic[0], a.id)
            print(f"{'PASS' if r[1] else 'FAIL'} {nm} {r[4]:.0f} с", file=sys.stderr, flush=True)
            return r
        res = list(ex.map(one, enumerate(checks, 1)))
    w = max(len(r[0]) for r in res)
    for name, ok, val, log, dur in res:
        print(f"{'PASS' if ok else 'FAIL'} {name:<{w}} {val}" + (f"  [{rel(log)}]" if log and (not ok or a.full) else ""))
    npass = sum(r[1] for r in res)
    allok = npass == len(res)
    print(f"{a.id}: {npass}/{len(res)} в {rel(cwd)}" + ("" if allok else "; логи " + rel(logdir)))
    # сводка по всем проверкам карточки: последний результат каждой (для текущего HEAD копии)
    head = gitx.gitr("rev-parse", "--short", "HEAD", cwd=cwd).stdout.strip()
    resf = logdir / "results.json"
    store = read_json(resf) or {}
    for name, ok, val, log, dur in res:
        store[name] = {"ok": ok, "val": val, "t": now(), "head": head}
    write_json(resf, store)
    allnames = [c.get("name") for c in card.get("accept", [])]
    cur = {n: store[n] for n in allnames if n in store and store[n].get("head") == head}
    n_ok = sum(1 for v in cur.values() if v["ok"])
    if a.only or len(cur) < len(allnames):
        gaps = [f"{n}={'FAIL' if n in cur else ('устарело' if n in store else 'не запускалась')}"
                for n in allnames if n not in cur or not cur[n]["ok"]]
        print(f"Сводно по карточке ({head}): {n_ok}/{len(allnames)} PASS" + (f"; нет: {', '.join(gaps)}" if gaps else ""))
    if not a.dry:
        summ = "; ".join(f"{n}={'ok' if cur[n]['ok'] else 'FAIL'}:{short(cur[n]['val'], 30)}" for n in cur)
        full_set = n_ok == len(allnames)
        need_rev = agents.needs_review(card.get("type")) and not a.here and not a.no_review
        kind = "accepted" if allok and full_set and not a.no_accept and not need_rev else "checked"
        add_event(home, a.id, kind, by_default(a), note=f"{n_ok}/{len(allnames)} {summ}", commits=a.commit)
        if allok and full_set and need_rev:
            print(f"{a.id}: PASS → ревью: {agents.reviewer_name()} (задание: «Ревью задачи {a.id}»), вердикт — {CLI} review {a.id}")
    sys.exit(0 if allok else 1)


def register(sp):
    q = sp.add_parser("accept", help="прогнать проверки карточки → PASS/FAIL, итог в события")
    q.add_argument("id"); q.add_argument("--only", action="append", metavar="ИМЯ")
    q.add_argument("--cwd", help="где запускать (по умолчанию копия задачи, если есть, иначе текущая)")
    q.add_argument("--here", action="store_true", help="в текущей копии (после слияния в ветку модуля)")
    q.add_argument("-j", "--jobs", type=int, default=1); q.add_argument("--commit", action="append")
    q.add_argument("--dry", action="store_true", help="не писать событие")
    q.add_argument("--no-accept", dest="no_accept", action="store_true", help="записать checked, даже если всё PASS")
    q.add_argument("--no-review", dest="no_review", action="store_true",
                   help="типы с dpcli_review: accepted без ревью (по умолчанию PASS → checked, ждёт ревьюера)")
    q.add_argument("--full", action="store_true", help="пути логов и для PASS"); q.add_argument("--by")
    q.add_argument("--bg", action="store_true", help=f"в фоне через job (долгие проверки); ждать — {CLI} job wait dp-accept-<ID>")
    q.add_argument("--timeout", type=int, default=3600, metavar="СЕК", help="с --bg: общий таймаут фонового прогона (3600)")
    tmux_args(q)
    q.set_defaults(func=cmd_accept)
