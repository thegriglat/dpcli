"""git: calls, toplevel, copies (worktree), branches, merge, commit of own paths."""
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
            raise DpError("not in a git working copy")
        _TOP = Path(t)
    return _TOP


_WT = None


def worktrees():
    """[(path, branch)] from git worktree list --porcelain."""
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
    """Main copy — the first in git worktree list --porcelain; None outside a repo."""
    for line in git("worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            return Path(line[9:])
    return None


def common_root():
    """Main copy by the shared .git dir (the shared semantic index is built from it, from any copy)."""
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


def status_entries(path, *flags, pathspec=()):
    """[(XY, path)] from `git status --porcelain -z`: paths without quotes or escapes (spaces, non-ASCII); for a rename — the new one."""
    if path and not Path(path).is_dir():
        return []  # the copy is already removed (gc --remove in the same pass)
    args = ["-c", "core.quotepath=off", "status", "--porcelain", "-z", *flags] + (["--", *pathspec] if pathspec else [])
    parts = gitr(*args, cwd=path).stdout.split("\0")
    res, i = [], 0
    while i < len(parts):
        ent = parts[i]
        i += 1
        if len(ent) < 4:
            continue
        res.append((ent[:2], ent[3:]))
        if ent[0] in "RC" or ent[1] in "RC":
            i += 1  # the old name follows
    return res


def dirty(path):
    return [f"{xy} {f}" for xy, f in status_entries(path, "--untracked-files=no")]


def commit_paths(cwd, paths, msg):
    """git add <paths> && git commit -- <paths>; the index of other paths is untouched. → short hash."""
    r = gitr("add", "--", *map(str, paths), cwd=cwd)
    if r.returncode:
        raise DpError(f"git add: {gerr(r)}")
    cm = ["commit", "-m", msg] + (["-m", session_line()] if session_line() else []) + ["--", *map(str, paths)]
    r = gitr(*cm, cwd=cwd)
    if r.returncode:
        raise DpError(f"git commit: {gerr(r)}")
    return gitr("rev-parse", "--short", "HEAD", cwd=cwd).stdout.strip()


def do_merge(path, src, msg, ff=True, trailers=None):
    """merge src into the branch of copy path. → (hash, files, 'up-to-date'|'merged'); conflict → abort + DpError."""
    from .journal import journal_commit
    jm = journal_commit(path)
    if jm:
        print(f"dpcli journal committed in {pretty(path)}: {', '.join(jm)}")
    if dirty(path):
        raise DpError(f"copy {pretty(path)} is dirty (changes in tracked files) — refusing")
    before = gitr("rev-parse", "HEAD", cwd=path).stdout.strip()
    args = (["merge", "--no-edit", "-m", msg] + (["-m", session_line()] if session_line() else [])
            + [x for t in trailers or [] for x in ("-m", t)] + ([] if ff else ["--no-ff"]) + [src])
    r = gitr(*args, cwd=path)
    if r.returncode:
        files = gitr("-c", "core.quotepath=off", "diff", "--name-only", "-z", "--diff-filter=U", cwd=path).stdout.split("\0")
        from .commands.docs import resolve_generated
        if resolve_generated(path, files) and not gitr("commit", "-q", "--no-edit", cwd=path).returncode:
            print(f"conflict only in generated indexes ({', '.join(f for f in files if f)}) — rebuilt (docs index)")
            r = None
    if r is not None and r.returncode:
        gitr("merge", "--abort", cwd=path)
        raise DpError(f"conflict merging {src} into {pretty(path)}, aborted (merge --abort); files: {', '.join(f for f in files if f) or gerr(r)}")
    after = gitr("rev-parse", "HEAD", cwd=path).stdout.strip()
    if after == before:
        return after[:7], 0, "up-to-date"
    nfiles = len([f for f in gitr("diff", "--name-only", "-z", before, after, cwd=path).stdout.split("\0") if f])
    return after[:7], nfiles, "merged"


def branch_info(br, wt_by_branch):
    """(copy, «hash age») of the branch's last commit."""
    last = git("log", "-1", "--format=%h %ct", br, "--")
    if not last:
        return wt_by_branch.get(br, ""), ""
    h, ts = last.split()
    return wt_by_branch.get(br, ""), f"{h} {age(dt.datetime.fromtimestamp(int(ts)).isoformat())}"


def branch_last_ts(br, main):
    """Time of the branch's last commit not in the main branch (datetime) or None."""
    out = git("log", "-1", "--format=%ct", br, "--not", main, "--")
    return dt.datetime.fromtimestamp(int(out)) if out.strip().isdigit() else None


def log_since(cut, ref, *extra):
    out = gitr("log", f"--since={cut.strftime('%Y-%m-%d %H:%M:%S')}", "--format=%h %s", ref, *extra, "--").stdout
    return [l for l in out.splitlines() if l.strip()]
