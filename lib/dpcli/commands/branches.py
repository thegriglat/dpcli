"""module new, sync, merge, gc: branches and copies."""
import fnmatch
import functools
import subprocess
from pathlib import Path

from .. import config, copies, gitx
from ..journal import (FINAL, add_event, all_modules, by_default, check_area, check_code, ensure_module, guard_main,
                       is_work_branch, module_base, module_meta, task_cards, task_states)
from ..util import DpError, lang_commit, pretty, subgroup


def resolve_branch(x):
    """module or branch name -> branch."""
    if gitx.branch_exists(x):
        return x
    mb = config.module_branch(x)
    if gitx.branch_exists(mb):
        return mb
    raise DpError(f"no branch {x} (or {mb})")


def cmd_module_new(a):
    mod = a.module
    br = config.module_branch(mod)
    copy = config.module_copy(mod)
    if gitx.branch_exists(br):
        raise DpError(f"branch {br} already exists")
    if copy.exists():
        raise DpError(f"{copy} already exists")
    base = a.from_ or gitx.git("branch", "--show-current", cwd=gitx.toplevel())
    if not base:
        raise DpError("current copy is not on a branch: give the module base with --from <branch>")
    if is_work_branch(base):
        raise DpError(f"{base} is a dpcli module or task branch; a module starts from a task feature branch: --from <branch>")
    if not gitx.branch_exists(base):
        raise DpError(f"base branch {base} does not exist")
    if a.code:
        check_code(a.code, mod)  # before git worktree add: a bad code leaves no branch or copy
    check_area(a.area)
    copies.create(copy, br, base)
    try:
        home = copy / config.plan_dir() / mod
        ensure_module(mod, home, copy=pretty(copy), code=a.code, area=a.area, base=base)
        add_event(home, None, "note", by_default(a), note=f"module created from {base}")
        h = gitx.commit_paths(copy, [home], lang_commit(f"{mod}: dpcli module created (module.json, events.jsonl)", f"{mod}: заведён модуль dpcli (module.json, events.jsonl)"))
    except BaseException:
        copies.rollback(copy, br)  # no module branch without a copy and journal
        raise
    print(f"{mod}: {br} from {base} @ {pretty(copy)}, commit {h}")
    for ln in copies.setup(copy):
        print(f"  {ln}")


def cmd_copy_setup(a):
    path = Path(a.path).expanduser() if a.path else gitx.toplevel()
    if not (path / ".git").exists():
        raise DpError(f"{pretty(path)} is not a git working copy")
    for ln in copies.setup(path):
        print(ln)


def cmd_sync(a):
    br = resolve_branch(a.target)
    path = gitx.copy_of(br)
    if not path:
        raise DpError(f"branch {br} has no working copy")
    main = base_of(br)
    h, n, kind = gitx.do_merge(path, main, a.message or lang_commit(f"Merge {main} into {br}", f"Слияние {main} в {br}"), trailers=a.trailer)
    print(f"{br}: {main} already merged" if kind == "up-to-date" else f"{br}: merged {main}, {h}, files {n}")


def base_of(br):
    """Default merge target and sync source: task branch -> its card base (module branch),
    module branch -> module base (feature branch), else None."""
    mod = config.module_of_branch(br)
    mods = all_modules()
    if mod and mod in mods:
        return module_base(module_meta(mod, mods[mod]))
    f = config.task_branch_fields(br)
    if f and f.get("module") in mods:
        card = task_cards(mods[f["module"]]).get(f.get("task")) or {}
        return card.get("base") or config.module_branch(f["module"])
    return None


def cmd_merge(a):
    from .search import sem_index_bg
    br = resolve_branch(a.branch)
    into = a.into or base_of(br)
    if not into:
        raise DpError(f"{br} is not a dpcli module or task branch: give --into <branch>")
    guard_main(into, bool(a.into))
    path = gitx.copy_of(into)
    if not path:  # no copy can open it (e.g. a vendored .dpcli on main vs the submodule): a fast-forward needs none
        old = gitx.gitr("rev-parse", f"refs/heads/{into}").stdout.strip()
        if not old or gitx.gitr("merge-base", "--is-ancestor", old, br).returncode:
            raise DpError(f"branch {into} is open in no copy and {br} is not a fast-forward of it: "
                          f"merge {into} into {br} first, or open {into} in a copy")
        r = gitx.gitr("update-ref", f"refs/heads/{into}", br, old)  # with the old value: no lost concurrent update
        if r.returncode:
            raise DpError(f"{into}: update-ref failed: {gitx.gerr(r)}")
        kind = "up-to-date" if gitx.git("rev-parse", br) == old else "ff"
        out = f"{into}: fast-forward to {br} ({gitx.git('rev-parse', '--short', br)}), no copy needed"
    else:
        subj = gitx.gitr("log", "-1", "--format=%s", br, "--").stdout.strip()
        h, n, kind = gitx.do_merge(path, br, a.message or lang_commit(f"Merge {br}: {subj}", f"Слияние {br}: {subj}"), ff=False, trailers=a.trailer)
        out = f"{into}: {br} already merged" if kind == "up-to-date" else f"{into} {h}: merged {br}, files {n}"
    if a.push:
        r = gitx.gitr("push", "origin", into, cwd=path)
        if r.returncode:
            raise DpError(f"{out}; push failed: {gitx.gerr(r)}")
        out += "; pushed"
    if into == config.main_branch() and kind != "up-to-date" and not a.no_index:
        msg = sem_index_bg()
        out += f"; {msg}" if msg else ""
    print(out)


def gc_live_reason(b, merged, mods):
    """Why a merged branch must not be removed: its module/task still has work. None: removable."""
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
            return f"module has open tasks ({', '.join(live[:4])}{'…' if len(live) > 4 else ''})"
        subs = [x for x in gitx.local_branches()
                if x not in merged and (config.task_branch_fields(x) or {}).get("module") == mod]
        if subs:
            return f"live task branches ({', '.join(subs[:3])})"
        return None
    for t, c in cards.items():
        if c and c.get("branch") == b and st.get(t, {}).get("status", "created") not in FINAL:
            return f"task {t} not closed ({st.get(t, {}).get('status', 'created')})"
    return None


def gc_symlink_reason(path, wt_paths):
    """Symlinks from other copies into path (e.g. .venv): removing the copy would break them."""
    root = Path(path).resolve()
    hits = [f"{pretty(f)} → {pretty(tgt)}" for other in wt_paths if Path(other).resolve() != root and Path(other).is_dir()  # removed earlier in this run
            for f, tgt in _symlinks(str(other)) if tgt == root or root in tgt.parents]
    return f"symlinks from other copies point into it ({'; '.join(hits[:2])})" if hits else None


@functools.lru_cache(maxsize=None)
def _symlinks(copy):
    """Untracked/ignored symlinks of a copy → [(link, target)]; one git status per copy per run (gc was O(n²))."""
    out = []
    for xy, name in gitx.status_entries(copy, "--ignored"):
        f = Path(copy) / name.rstrip("/")
        if xy in ("??", "!!") and f.is_symlink():
            try:
                out.append((f, f.resolve()))
            except OSError:
                continue
    return out


def ignored_dirs(path):
    """Git-ignored dirs of the copy, except build caches in gc.ignore_dirs (removed with the copy anyway)."""
    skip = set(config.get("gc.ignore_dirs") or [])
    return [f for xy, f in gitx.status_entries(path, "--ignored") if xy == "!!" and f.endswith("/")
            and f.rstrip("/").split("/")[0] not in skip and not any(f"{d}/" in f for d in skip)]


def junk_ok(f):
    """Untracked file is generated (gc.ignore_globs, or inside a gc.ignore_dirs dir), not work."""
    name = f.rstrip("/").rsplit("/", 1)[-1]
    if set(f.rstrip("/").split("/")) & {str(d) for d in config.get("gc.ignore_dirs") or []}:
        return True
    return any(fnmatch.fnmatch(name, g) or fnmatch.fnmatch(f, g) for g in config.get("gc.ignore_globs") or [])


def remove_copy(path):
    """Remove a copy: refuse (-> reason) on changes in tracked files or untracked work files;
    git-ignored and generated files (gc.ignore_dirs, gc.ignore_globs) do not block it. -> (reason|None, ignored dirs)."""
    # status noise with content equal to HEAD (a hook restored the files) is not work; any change inside a submodule is,
    # and so is a submodule commit on no remote: its repository is removed with the copy
    d = gitx.dirty(path)
    if d and gitx.gitr("diff", "--quiet", "HEAD", cwd=path).returncode:
        return f"dirty copy ({len(d)} files)", []
    r = gitx.gitr("submodule", "foreach", "--quiet", "--recursive",
                  "git status --porcelain && git stash list && git rev-list --branches HEAD --not --remotes", cwd=path)
    if r.returncode:
        return f"cannot check submodules: {gitx.gerr(r)}", []
    if r.stdout.split():
        return "changes or unpushed commits in submodules", []
    junk = [f for xy, f in gitx.status_entries(path) if xy == "??"]
    other = [f for f in junk if not junk_ok(f)]
    if other:
        return f"untracked files ({len(other)}: {', '.join(other[:3])})", []
    ign = ignored_dirs(path)
    # checked above; --force: git refuses on untracked generated files and on any copy with a submodule
    r = gitx.gitr("worktree", "remove", "--force", str(path))
    if r.returncode:
        return gitx.gerr(r), []
    return None, ign


def squash_merged(main, merged):
    """Local branches squash-merged into main (their whole diff is one commit there, by patch-id), plus branches
    merged into those. A branch with an empty net diff is never matched. Costs a few git calls per unmerged
    branch and leaves one dangling commit object each (collected by git gc)."""
    rest = [b for b in gitx.local_branches() if b != main and b not in merged]
    out = set()
    for b in rest:
        base = gitx.gitr("merge-base", main, b).stdout.strip()
        if not base or gitx.gitr("rev-parse", f"{b}^{{tree}}").stdout == gitx.gitr("rev-parse", f"{base}^{{tree}}").stdout:
            continue
        tmp = gitx.gitr("commit-tree", f"{b}^{{tree}}", "-p", base, "-m", "gc").stdout.strip()
        if tmp and gitx.gitr("cherry", main, tmp).stdout.startswith("-"):
            out.add(b)
    out |= {b for b in rest if b not in out and any(
        gitx.gitr("merge-base", "--is-ancestor", b, s).returncode == 0 for s in out)}
    return [b for b in rest if b in out]


def cmd_gc(a):
    main = config.main_branch()
    main_tip = gitx.gitr("rev-parse", main).stdout.strip()
    merged = [b for b in gitx.gitr("branch", "--merged", main, "--format=%(refname:short)").stdout.split() if b != main]
    squashed = squash_merged(main, merged)
    merged += squashed
    here = str(gitx.toplevel())
    wt = {b: p for p, b in gitx.worktrees()}
    n = 0
    if a.branches:
        want = {x if "/" in x else config.module_branch(x) for x in a.branches} | set(a.branches)
        miss = [x for x in a.branches if x not in merged and config.module_branch(x) not in merged]
        if miss:
            raise DpError(f"not merged into {main} or no such branch: {', '.join(miss)}")
        merged = [b for b in merged if b in want]
    mods = all_modules()
    for b in merged:
        if gitx.gitr("rev-parse", b).stdout.strip() == main_tip:
            continue  # branch == main (just created or fast-forward merged): leave it
        path = wt.get(b)
        label = f"{b}" + (f" @ {pretty(path)}" if path else " (no copy)")
        why = gc_live_reason(b, merged, mods) or (path and gc_symlink_reason(path, wt.values()))
        if why:
            print(f"skip {label}: {why}")
            continue
        if not a.remove:
            ign = ignored_dirs(path) if path else []
            print(label + (f" (will also remove ignored: {', '.join(ign[:4])})" if ign else ""))
            n += 1
            continue
        if path and path == here:
            print(f"skip {label}: this is the current copy")
            continue
        ign = []
        if path:
            why_not, ign = remove_copy(path)
            if why_not:
                print(f"skip {label}: {why_not}")
                continue
        r = gitx.gitr("branch", "-D" if b in squashed else "-d", b)
        print((f"removed {label}" + (f" (with ignored: {', '.join(ign[:4])})" if path and ign else ""))
              if r.returncode == 0 else f"copy removed, branch {b} kept: {gitx.gerr(r)}")
        n += 1
    if not n:
        print("no merged branches")


def register(sp):
    msp = subgroup(sp, "module", "module: new (branch + copy + journal) | init (journal only)")
    q = msp.add_parser("new", help="module branch (module_branch) + git worktree (module_copy) + module.json/events.jsonl")
    q.add_argument("module"); q.add_argument("--from", dest="from_", default=None,
                                             help="module base: task feature branch (default: current branch of the main copy)")
    q.add_argument("--by")
    q.add_argument("--code", help="module code for task IDs: 2-4 uppercase Latin letters (NN, UC), unique")
    q.add_argument("--area", help="module area (areas key in config): whose product goal the module serves")
    q.set_defaults(func=cmd_module_new)

    csp = subgroup(sp, "copy", "copies: setup (prepare a copy: hooks, env, node_modules, worktree.setup)")
    q = csp.add_parser("setup", help="carry into the copy what git lacks (config worktree.*); idempotent")
    q.add_argument("path", nargs="?", help="path to the copy (default: current)")
    q.set_defaults(func=cmd_copy_setup)

    q = sp.add_parser("sync", help="merge the module base (branch it started from) into the module branch (in its copy)")
    q.add_argument("target", metavar="module|branch")
    q.add_argument("--message", "-m", help="merge message instead of the default")
    q.add_argument("--trailer", action="append", help="extra line at the end of the message (repeatable)")
    q.set_defaults(func=cmd_sync)

    q = sp.add_parser("merge", help="--no-ff merge of a branch into the target (in the copy where it is checked out)")
    q.add_argument("branch", metavar="branch|module")
    q.add_argument("--into", default=None, help="target branch (default: task -> module branch, module -> its base; "
                                               "main_branch only explicitly)")
    q.add_argument("--push", action="store_true")
    q.add_argument("--no-index", action="store_true", help="skip background semantic index update (on merge into main branch)")
    q.add_argument("--message", "-m", help="merge message instead of the default")
    q.add_argument("--trailer", action="append", help="extra line at the end of the message (repeatable)")
    q.set_defaults(func=cmd_merge)

    q = sp.add_parser("gc", help="copies and branches already merged into main branch (list; --remove: delete)")
    q.add_argument("branches", nargs="*", metavar="BRANCH|MODULE", help="only these (module -> module branch)")
    q.add_argument("--remove", action="store_true")
    q.set_defaults(func=cmd_gc)
