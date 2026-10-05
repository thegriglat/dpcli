"""git: вызовы, toplevel, рабочие копии (worktree), ветки, слияние, коммит своих путей."""
import datetime as dt
import subprocess
from pathlib import Path

from .util import DpError, age, pretty, session_line


def git(*args, cwd=None, check=False):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode:
        raise DpError(f"git {' '.join(args)}: {r.stderr.strip().splitlines()[-1:]}")
    return r.stdout.strip() if r.returncode == 0 else ""


def gitr(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def gerr(r):
    return " ".join((r.stderr.strip() or r.stdout.strip()).splitlines()[-2:])


_TOP = None


def toplevel():
    global _TOP
    if _TOP is None:
        t = git("rev-parse", "--show-toplevel")
        if not t:
            raise DpError("не в рабочей копии git")
        _TOP = Path(t)
    return _TOP


_WT = None


def worktrees():
    """[(path, branch)] из git worktree list --porcelain."""
    global _WT
    if _WT is None:
        _WT, path = [], None
        for line in git("worktree", "list", "--porcelain").splitlines():
            if line.startswith("worktree "):
                path = line[9:]
            elif line.startswith("branch "):
                _WT.append((path, line[7:].removeprefix("refs/heads/")))
            elif line == "detached" and path:
                _WT.append((path, "(detached)"))
    return _WT


def reset_worktrees():
    global _WT
    _WT = None


def main_worktree():
    """Главная рабочая копия — первая в git worktree list --porcelain; None вне репозитория."""
    for line in git("worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            return Path(line[9:])
    return None


def common_root():
    """Главная копия по общему каталогу .git (общий смысловой индекс считается по ней, из любой копии)."""
    cd = git("rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(cd).parent if cd else toplevel()


def branch_exists(br):
    return gitr("rev-parse", "--verify", "-q", f"refs/heads/{br}").returncode == 0


def local_branches(prefix=""):
    return gitr("for-each-ref", "--format=%(refname:short)", f"refs/heads/{prefix}").stdout.split()


def copy_of(branch):
    for p, b in worktrees():
        if b == branch:
            return Path(p)
    return None


def dirty(path):
    return [l for l in gitr("status", "--porcelain", "--untracked-files=no", cwd=path).stdout.splitlines() if l.strip()]


def commit_paths(cwd, paths, msg):
    """git add <пути> && git commit -- <пути>; индекс других путей не трогаем. → короткий хеш."""
    r = gitr("add", "--", *map(str, paths), cwd=cwd)
    if r.returncode:
        raise DpError(f"git add: {gerr(r)}")
    cm = ["commit", "-m", msg] + (["-m", session_line()] if session_line() else []) + ["--", *map(str, paths)]
    r = gitr(*cm, cwd=cwd)
    if r.returncode:
        raise DpError(f"git commit: {gerr(r)}")
    return gitr("rev-parse", "--short", "HEAD", cwd=cwd).stdout.strip()


def do_merge(path, src, msg, ff=True, trailers=None):
    """merge src в ветку копии path. → (хеш, файлов, 'up-to-date'|'merged'); конфликт → abort + DpError."""
    from .journal import journal_commit
    jm = journal_commit(path)
    if jm:
        print(f"журнал dpcli закоммичен в {pretty(path)}: {', '.join(jm)}")
    if dirty(path):
        raise DpError(f"копия {pretty(path)} грязная (изменения в отслеживаемых файлах) — отказ")
    before = gitr("rev-parse", "HEAD", cwd=path).stdout.strip()
    args = (["merge", "--no-edit", "-m", msg] + (["-m", session_line()] if session_line() else [])
            + [x for t in trailers or [] for x in ("-m", t)] + ([] if ff else ["--no-ff"]) + [src])
    r = gitr(*args, cwd=path)
    if r.returncode:
        files = gitr("diff", "--name-only", "--diff-filter=U", cwd=path).stdout.split()
        gitr("merge", "--abort", cwd=path)
        raise DpError(f"конфликт при слиянии {src} в {pretty(path)}, отменено (merge --abort); файлы: {', '.join(files) or gerr(r)}")
    after = gitr("rev-parse", "HEAD", cwd=path).stdout.strip()
    if after == before:
        return after[:7], 0, "up-to-date"
    nfiles = len(gitr("diff", "--name-only", before, after, cwd=path).stdout.split())
    return after[:7], nfiles, "merged"


def branch_info(br, wt_by_branch):
    """(копия, «хеш возраст») последнего коммита ветки."""
    last = git("log", "-1", "--format=%h %ct", br, "--")
    if not last:
        return wt_by_branch.get(br, ""), ""
    h, ts = last.split()
    return wt_by_branch.get(br, ""), f"{h} {age(dt.datetime.fromtimestamp(int(ts)).isoformat())}"


def branch_last_ts(br, main):
    """Время последнего коммита ветки, которого нет в главной ветке (datetime) или None."""
    out = git("log", "-1", "--format=%ct", br, "--not", main, "--")
    return dt.datetime.fromtimestamp(int(out)) if out.strip().isdigit() else None


def log_since(cut, ref, *extra):
    out = gitr("log", f"--since={cut.strftime('%Y-%m-%d %H:%M:%S')}", "--format=%h %s", ref, *extra, "--").stdout
    return [l for l in out.splitlines() if l.strip()]
