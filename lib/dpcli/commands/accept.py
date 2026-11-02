"""accept: run the card checks (optionally in the background via job)."""
import concurrent.futures as cf
import fnmatch
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .. import agents, config, copies, gitx, reexec
from ..journal import add_event, by_default, expect_arg, find_task
from ..util import CLI, DpError, die, now, read_json, read_jsonl, rel, short, write_json
from .jobs import job_start, qualify, tmux_args, tmux_opts


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
            raise DpError(f"expect «{s}»: expected 'num:<regex> <op><number>'")
        key = {">=": "min", "<=": "max", "==": "eq", ">": "gt", "<": "lt"}[m[1]]
        return {"num": body, key: float(m[2])}
    raise DpError(f"expect «{s}»: not understood (exit=N | re:… | !re:… | num:<regex> <op>N | tests)")


TESTS_SUMMARY = r"(?P<total>\d+) (?:тестов|tests?), (?P<failed>\d+) (?:упало|failed)(?:, (?P<skipped>\d+) (?:пропущено|skipped))?"


def tests_summary_rx():
    """Regex for the test-run summary: checks.tests_summary (groups total, failed; skipped optional)."""
    src = config.get("checks.tests_summary") or TESTS_SUMMARY
    try:
        rx = re.compile(src, re.M)
    except re.error as e:
        raise DpError(f"checks.tests_summary «{src}»: invalid regex ({e})")
    if not {"total", "failed"} <= set(rx.groupindex):
        raise DpError(f"checks.tests_summary «{src}»: groups (?P<total>…) and (?P<failed>…) required")
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
            vals.append(f"{tot - fail}/{tot}" + (f" (skipped {skip})" if skip else ""))
            if fail:
                names = re.findall(r"^\s*FAIL (\S+)", out, re.M)
                vals.append("FAIL " + ",".join(n.split("::")[-1] for n in names[:3]))
        else:  # summary (checks.tests_summary) not printed: judge by the runner's exit code
            ok &= code == 0
            if "exit" not in exp:
                vals.append(f"exit {code}")
    if exp.get("re"):
        m = re.search(exp["re"], out, re.M)
        ok &= bool(m)
        vals.append(short(m[0], 40) if m else "no match")
    if exp.get("not_re"):
        m = re.search(exp["not_re"], out, re.M)
        ok &= not m
        if m:
            vals.append("found: " + short(m[0], 40))
    if exp.get("num"):
        m = list(re.finditer(exp["num"], out, re.M))
        if not m:
            return False, "number not found"
        g = m[-1]
        try:
            v = float((g.group(1) if g.groups() else g.group(0)).replace(",", "."))
        except ValueError:
            return False, f"not a number: {short(g[0], 30)}"
        for k, f in (("min", lambda x, y: x >= y), ("max", lambda x, y: x <= y), ("eq", lambda x, y: abs(x - y) < 1e-12),
                     ("gt", lambda x, y: x > y), ("lt", lambda x, y: x < y)):
            if k in exp:
                ok &= f(v, float(exp[k]))
        vals.append(f"{v:g}")
    return bool(ok), "; ".join(vals) or f"exit {code}"


def check_env(tid):
    """Check environment: DPCLI_TASK + checks.env ({tmpdir} is a fresh temp dir per check)."""
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
            return name, False, "tests check unavailable: no checks.tests template in config", "", 0
        cmd = str(tpl).replace("{filter}", str(c["tests"]))
    if not cmd:
        return name, False, "no cmd", "", 0
    exp = parse_expect({"tests": True} if c.get("tests") and "expect" not in c else c.get("expect"))
    wd = Path(os.path.expanduser(c.get("cwd") or cwd))
    if not wd.is_absolute():
        wd = Path(cwd) / wd
    env = check_env(tid)
    safe = re.sub(r"[^\w.-]+", "_", name)
    log = logdir / f"{safe}.log"  # by name: --only or a re-created check must not leave stale logs under other numbers
    t0 = time.time()
    try:
        r = subprocess.run(["bash", "-c", cmd], cwd=wd, env=env, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=c.get("timeout", 900))  # `prettier --check` without files reads stdin
        code, out = r.returncode, r.stdout + ("\n" + r.stderr if r.stderr else "")
    except subprocess.TimeoutExpired as e:
        code, out = 124, (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        out += f"\n[dpcli] timeout {c.get('timeout', 900)} s"
    dur = time.time() - t0
    log.write_text(f"$ cd {wd}\n$ {cmd}\n[exit {code}, {dur:.0f} s]\n\n{out}")
    ok, val = judge(exp, code, out) if code != 124 else (False, "timeout")
    if not ok and "exit" in val and len(val) < 12:
        tail = [x for x in out.strip().splitlines() if x.strip()][-1:] or [""]
        val += " · " + short(tail[0], 60)
    return name, ok, val, str(log), dur


_NOTE = re.compile(r"\s+(?:—|–|-|\(|:)(?:\s|$)")


def _pat(entry):
    """Patterns from a scope entry: path/glob. The path may contain spaces ("docs/My notes/Contract.md") and be followed by
    a note ("src/x.py — function f"): take the backtick-quoted text, else everything before " — "/" - "/" ("/": ";
    with no note, both the whole line and its first word qualify (legacy behaviour). -> list of patterns."""
    e = str(entry).strip()
    q = re.match(r"^`([^`]+)`", e)
    if q:
        return [q.group(1).strip()]
    m = _NOTE.search(e)
    head = (e[:m.start()] if m else e).strip().strip("'\"")
    first = e.split()[0].strip("`'\"") if e.split() else ""
    return [x for x in dict.fromkeys([head, first]) if x]


def _hit(path, pat):
    if any(ch in pat for ch in "*?["):
        return fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(path, pat.replace("**/", ""))
    p = pat.rstrip("/").removeprefix("./")
    return path == p or path.startswith(p + "/")


def path_in(path, pats):
    """Path matches a pattern (glob: * ? [, ** = any directories; or a file/directory prefix) and no `!pattern`."""
    pats = [p for p in pats if p]
    return (any(_hit(path, p) for p in pats if not p.startswith("!"))
            and not any(_hit(path, p[1:]) for p in pats if p.startswith("!")))


EXCLUDE_WORDS = {"кроме", "except", "excluding"}  # unambiguous only: notes like "(but only f())" are fine


def check_bounds(card):
    """scope/dont_touch are paths or globs; exclusions are `!pattern` entries, not prose; scope must not lie inside
    dont_touch — both made accept fail on files the card itself requires. Prose is detected by an exclusion word
    after the first word of the path part or at the start of a note (so `docs/My notes except.md` needs backticks)."""
    for key in ("scope", "dont_touch"):
        for e in card.get(key) or []:
            if str(e).lstrip().startswith("`"):
                continue  # `a path with spaces` — the path is explicit
            m = _NOTE.search(str(e))  # the path part, and a note that *starts* with an exception ("(except a.py)")
            words = (str(e)[:m.start()] if m else str(e)).lower().split()[1:]
            note = str(e)[m.end():].strip(" (").lower().split()[:1] if m else []
            if EXCLUDE_WORDS & {w.strip("()[],;:") for w in words + note}:
                raise DpError(f"{key} \"{e}\": write exclusions as separate entries `!<path>`, not as text "
                              f"(e.g. --dont-touch src/api/ --dont-touch '!src/api/a.py'); an old entry: remove it with "
                              f"task set <ID> '{key}-={e}'")
    dont = [p for x in card.get("dont_touch") or [] for p in _pat(x)]
    for e in card.get("scope") or []:
        for s in _pat(e):
            fixed = re.split(r"[*?\[]", s)[0].rsplit("/", 1)[0] if any(ch in s for ch in "*?[") else s  # glob's fixed dir
            if s and not s.startswith("!") and fixed and f"!{s}" not in dont and path_in(fixed.rstrip("/"), dont):
                raise DpError(f"scope \"{s}\" lies inside dont_touch: add --dont-touch '!{s}' or narrow dont_touch")


def changed_files(cwd, base):
    """Net changes of the branch (base...HEAD) made by its own commits, plus uncommitted (incl. untracked).
    Files only brought in by merges are not the task's work; a file added and reverted is no change. Accepted
    limitation: edits made while resolving a merge, or work merged from a sub-branch, are not checked."""
    q = ("-c", "core.quotepath=off")
    net = gitx.gitr(*q, "diff", "--name-only", "-z", f"{base}...HEAD", cwd=cwd)
    own = gitx.gitr(*q, "log", "--first-parent", "--no-merges", "--format=", "--name-only", "-z", f"{base}..HEAD", cwd=cwd)
    if net.returncode or own.returncode:
        raise DpError(f"git diff/log {base}...HEAD: {gitx.gerr(net if net.returncode else own)}")
    files = set(net.stdout.split("\0")) & {f.strip("\n") for f in own.stdout.split("\0")}
    files.update(f for _xy, f in gitx.status_entries(cwd, "--untracked-files=all"))
    return sorted(f for f in files if f)


def scope_check(card, cwd, mod):
    """(ok | None = skipped, value): task-branch changed files are within scope and disjoint from dont_touch."""
    scope = [p for x in card.get("scope") or [] for p in _pat(x)]
    if not any(scope):
        return None, "skipped: empty scope"
    br, base = card.get("branch"), card.get("base") or config.module_branch(mod)
    cur = gitx.git("branch", "--show-current", cwd=cwd)
    no_copy = not (card.get("copy") and Path(card["copy"]).expanduser().is_dir())
    if br and cur != br and not no_copy:
        return None, f"skipped: {rel(cwd)} is not on task branch {br}"
    try:  # a --no-copy card's work is the uncommitted changes of the copy it runs in
        files = sorted({f for _xy, f in gitx.status_entries(cwd, "--untracked-files=all")}) if br and cur != br \
            else changed_files(cwd, base)
    except DpError as e:
        return False, str(e)
    skip = [f"{config.plan_dir()}/{mod}/", str(config.get("checks.log_dir") or "build/dpcli")]
    skip += [str(d) for d in config.get("gc.ignore_dirs") or []]
    hp = copies.hooks_dir(cwd)
    skip += [hp] if hp else []  # hooks dir (.husky/_) is copy setup, not task work
    globs = [str(g) for g in config.get("gc.ignore_globs") or []]
    # a submodule pointer drifts with the copy's checkout; a deliberate pointer move also skips dont_touch
    subs = {e.split("\t", 1)[1] for e in gitx.git("ls-files", "--stage", "-z", "--", *files, cwd=cwd).split("\0")
            if e.startswith("160000")} if files else set()
    files = [f for f in files if f not in subs and not path_in(f, skip) and not any(fnmatch.fnmatch(f.rsplit("/", 1)[-1], g) for g in globs)
             and not any(f"/{d}/" in f"/{f}" for d in config.get("gc.ignore_dirs") or [])]
    dont = [p for x in card.get("dont_touch") or [] for p in _pat(x)]
    out = [f for f in files if not path_in(f, scope)]
    bad = [f for f in files if path_in(f, dont)]
    merges = gitx.git("rev-list", "--count", "--merges", "--first-parent", f"{base}..HEAD", cwd=cwd)
    note = f" ({merges} merge commit(s): conflict resolutions not checked)" if merges not in ("", "0") else ""
    if not out and not bad:
        return True, f"{len(files)} file(s) within bounds{note}"
    parts = []
    if out:
        parts.append("outside scope: " + ", ".join(out[:10]) + (f" … (+{len(out) - 10})" if len(out) > 10 else ""))
    if bad:
        parts.append("in dont_touch: " + ", ".join(bad[:10]) + (f" … (+{len(bad) - 10})" if len(bad) > 10 else ""))
    return False, "; ".join(parts) + note


def accept_bg(a, cwd, logdir):
    """Background run (long checks) via job; the job re-runs accept itself and writes the event."""
    skip = {"--bg", "--fg"}
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
    short_name = f"dp-accept-{a.id}"  # job names are per copy; `job wait` from this copy finds it by the short name
    name = qualify(short_name)
    try:
        job_start(name, a.timeout, [*reexec.self_cmd(), *argv, "--fg", "--cwd", str(cwd)], tmux_opts(a))
    except DpError as e:
        die(str(e))
    print(f"wait: {CLI} job wait {short_name} {a.timeout}; result in events ({CLI} log {a.id}), logs in {rel(logdir)}")
    sys.exit(0)


def expected_seconds(logdir, home, tid, checks, jobs):
    """Duration of the same checks last time (results.json of this copy, else the journal's `durs`): sum, or the
    longest one when run in parallel."""
    store = read_json(logdir / "results.json") or {}
    last = {}
    for e in read_jsonl(home / "events.jsonl"):
        if e.get("task") == tid and isinstance(e.get("durs"), dict):
            last.update(e["durs"])
    durs = [float((store.get(c.get("name")) or {}).get("dur") or last.get(c.get("name")) or 0) for c in checks]
    return (max(durs, default=0) if jobs > 1 else sum(durs))


def cmd_accept(a):
    mod, home = find_task(a.id)
    card = read_json(home / "tasks" / f"{a.id}.json")
    checks = [c for c in card.get("accept", []) if not a.only or c.get("name") in a.only]
    if not checks:
        raise DpError(f"{a.id}: no checks in card" + (f" named {a.only}" if a.only else ""))
    cwd = a.cwd
    if not cwd:
        cp = Path(os.path.expanduser(card.get("copy", ""))) if card.get("copy") else None
        cwd = str(cp) if cp and cp.is_dir() and not a.here else str(gitx.toplevel())
    logdir = config.repo_path(config.get("checks.log_dir", "build/dpcli")) / a.id
    logdir.mkdir(parents=True, exist_ok=True)
    if a.bg:
        return accept_bg(a, cwd, logdir)
    est = expected_seconds(logdir, home, a.id, checks, a.jobs)
    limit = int(config.get("checks.bg_after", 100) or 0)
    if not a.fg and limit and est > limit:  # a foreground run this long hits the agent's tool timeout
        print(f"{a.id}: last run took ~{est:.0f} s > {limit} s — running in the background ({CLI} accept … --fg to wait here)")
        return accept_bg(a, cwd, logdir)
    with cf.ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
        def one(ic):
            nm = ic[1].get("name", f"check{ic[0]}")
            print(f"… {nm}", file=sys.stderr, flush=True)  # progress to stderr, result table to stdout
            r = run_check(ic[1], cwd, logdir, ic[0], a.id)
            print(f"{'PASS' if r[1] else 'FAIL'} {nm} {r[4]:.0f} s", file=sys.stderr, flush=True)
            return r
        res = list(ex.map(one, enumerate(checks, 1)))
    sc_ok, sc_val = scope_check(card, cwd, mod)
    w = max(len(r[0]) for r in res + [("scope",)])
    for name, ok, val, log, dur in res:
        print(f"{'PASS' if ok else 'FAIL'} {name:<{w}} {val}" + (f"  [{rel(log)}]" if log and (not ok or a.full) else ""))
    print(f"{'SKIP' if sc_ok is None else 'PASS' if sc_ok else 'FAIL'} {'scope':<{w}} {sc_val}")
    npass = sum(r[1] for r in res)
    allok = npass == len(res) and sc_ok is not False
    stash = gitx.git("stash", "list", cwd=cwd).splitlines()
    if stash:  # refs/stash is shared by all worktrees: a pop in one copy takes another task's changes
        print(f"warning: git stash has {len(stash)} entr{'y' if len(stash) == 1 else 'ies'} shared by all copies — "
              f"commit instead of stashing; check `git stash list` before any pop", file=sys.stderr)
    print(f"{a.id}: {npass}/{len(res)}{'' if sc_ok is not False else ' + FAIL scope'} in {rel(cwd)}"
          + ("" if allok else "; logs " + rel(logdir)))
    # summary over all card checks: latest result of each (for the copy's current HEAD)
    head = gitx.gitr("rev-parse", "--short", "HEAD", cwd=cwd).stdout.strip()
    resf = logdir / "results.json"
    store = read_json(resf) or {}
    for name, ok, val, log, dur in res:
        store[name] = {"ok": ok, "val": val, "t": now(), "head": head, "dur": round(dur)}
    write_json(resf, store)
    allnames = [c.get("name") for c in card.get("accept", [])]
    cur = {n: store[n] for n in allnames if n in store and store[n].get("head") == head}
    n_ok = sum(1 for v in cur.values() if v["ok"])
    if a.only or len(cur) < len(allnames):
        gaps = [f"{n}={'FAIL' if n in cur else ('stale' if n in store else 'not run')}"
                for n in allnames if n not in cur or not cur[n]["ok"]]
        print(f"Card total ({head}): {n_ok}/{len(allnames)} PASS" + (f"; missing: {', '.join(gaps)}" if gaps else ""))
    if not a.dry:
        summ = "; ".join(f"{n}={'ok' if cur[n]['ok'] else 'FAIL'}:{short(cur[n]['val'], 30)}" for n in cur)
        if sc_ok is False:
            summ += f"; scope=FAIL:{short(sc_val, 60)}"
        full_set = n_ok == len(allnames)
        need_rev = agents.needs_review(card.get("type")) and not a.here and not a.no_review
        kind = "accepted" if allok and full_set and not a.no_accept and not need_rev else "checked"
        add_event(home, a.id, kind, by_default(a), note=f"{n_ok}/{len(allnames)} {summ}", commits=a.commit,
                  durs={name: round(dur) for name, ok, val, log, dur in res})
        if allok and full_set and need_rev:
            print(f"{a.id}: PASS -> review: {agents.reviewer_name()} (job: {CLI} task brief {a.id} --review), verdict: {CLI} review {a.id}")
    sys.exit(0 if allok else 1)


def register(sp):
    q = sp.add_parser("accept", help="run the card checks -> PASS/FAIL, result goes to events")
    q.add_argument("id"); q.add_argument("--only", action="append", metavar="NAME")
    q.add_argument("--cwd", help="where to run (default: the task copy if any, else the current one)")
    q.add_argument("--here", action="store_true", help="in the current copy (after merging into the module branch)")
    q.add_argument("-j", "--jobs", type=int, default=1); q.add_argument("--commit", action="append")
    q.add_argument("--dry", action="store_true", help="do not write the event")
    q.add_argument("--no-accept", dest="no_accept", action="store_true", help="record checked even if all PASS")
    q.add_argument("--no-review", dest="no_review", action="store_true",
                   help="types with dpcli_review: accepted without review (default: PASS -> checked, awaits reviewer)")
    q.add_argument("--full", action="store_true", help="log paths for PASS too"); q.add_argument("--by")
    q.add_argument("--fg", action="store_true", help="stay in the foreground even if the checks are known to be long")
    q.add_argument("--bg", action="store_true", help=f"in the background via job (long checks); wait with {CLI} job wait dp-accept-<ID>")
    q.add_argument("--timeout", type=int, default=3600, metavar="SEC", help="with --bg: overall background timeout (3600)")
    tmux_args(q)
    q.set_defaults(func=cmd_accept)
