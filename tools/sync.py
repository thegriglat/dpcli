#!/usr/bin/env python3
"""Before the AI review: merge current main into the PR, so tests and review see what would land.
Parallel PRs always collide on VERSION and the top of CHANGELOG.md: only those hunks are resolved here (the PR's
VERSION and its own CHANGELOG section become main's VERSION + 1); everything else in the merged files is kept.
Any other conflict, a fork branch or a merge the token cannot push → comment + `rework`, exit 1 (review skipped).
Runs from the base branch only: the merge happens in a separate worktree, nothing from the PR is executed.
shortcut: main moving during the review is not re-synced (decide.py's merge fails → `rework`, the next push
re-syncs); upgrade to a resync on push to main if that happens often."""
import json
import os
import re
import subprocess
import sys

from decide import gh, label

INIT, LOG = "lib/dpcli/__init__.py", "CHANGELOG.md"
HUNK = re.compile(r"^<<<<<<< [^\n]*\n(.*?)^=======\n(.*?)^>>>>>>> [^\n]*\n", re.M | re.S)


class Unresolved(Exception):
    pass


def git(*a, cwd=None, check=True):
    r = subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode:
        sys.exit(f"git {' '.join(a[:3])}: {r.stderr.strip()}")
    return r


def version(text):
    m = re.search(r"^VERSION = (\d+)", text, re.M)
    if not m:
        raise Unresolved(f"{INIT} (no VERSION line)")
    return int(m[1])


def bumped(text, n):
    return re.sub(r"^VERSION = \d+", f"VERSION = {n}", text, count=1, flags=re.M)


def resolve(path, text, own, n):
    """The merged file with the VERSION / CHANGELOG-top hunks resolved (ours = the PR, theirs = main).
    own — the PR's VERSION; raises Unresolved for any other conflict."""
    def hunk(m):
        ours, theirs = m[1], m[2]
        if path == INIT and {l.split("=")[0].strip() for l in (ours + theirs).splitlines() if l.strip()} == {"VERSION"}:
            return bumped(theirs, n)
        if path == LOG and re.fullmatch(rf"## {own}\b[^\n]*\n(?:(?!## )[^\n]*\n)*", ours) and theirs.startswith("## "):
            return re.sub(r"^## \d+", f"## {n}", ours, count=1) + ("" if ours.endswith("\n\n") else "\n") + theirs
        raise Unresolved(path)
    text = HUNK.sub(hunk, text)
    if path == INIT:
        return bumped(text, n)
    if not re.search(rf"^## {n}\b", text, re.M):  # merged cleanly: the PR's section still has its old number
        if len(re.findall(rf"^## {own}\b", text, re.M)) != 1:
            raise Unresolved(path)
        text = re.sub(rf"^## {own}\b", f"## {n}", text, count=1, flags=re.M)
    return text


def block(pr, why):
    gh("pr", "comment", pr, "--body", f"VERDICT: rework\n- Not reviewed: {why}.")  # update shows projects this line
    label(pr, "rework", ["rejected"])
    sys.exit(f"#{pr}: {why}")


def main(pr):
    info = json.loads(gh("pr", "view", pr, "--json", "headRefName,isCrossRepository"))
    head = f"refs/remotes/pr/{pr}"
    git("fetch", "-q", "origin", "main", f"+refs/pull/{pr}/head:{head}")
    if git("merge-base", "--is-ancestor", "origin/main", head, check=False).returncode == 0:
        return print(f"#{pr}: up to date with main")
    sha = git("rev-parse", head).stdout.strip()
    wt = os.path.join(os.environ.get("RUNNER_TEMP") or "/tmp", f"pr-{pr}")
    git("worktree", "add", "-q", "--detach", wt, head)
    git("-c", "merge.conflictStyle=merge", "merge", "-q", "--no-commit", "--no-ff", "origin/main", cwd=wt, check=False)
    conflicts = set(git("diff", "--name-only", "--diff-filter=U", cwd=wt).stdout.split())
    if info["isCrossRepository"]:  # the workflow token cannot push to a fork; a clean one is tested on its merge ref
        if conflicts:
            block(pr, f"conflicts with main in {', '.join(sorted(conflicts))}; merge main into the fork branch and push")
        return print(f"#{pr}: fork, merges cleanly with main; reviewed as is")
    if git("diff", "--name-only", f"{head}...origin/main", "--", ".github/workflows").stdout.strip():
        block(pr, "main changed .github/workflows since this branch, and the CI token may not push workflow files; "
                  "merge main into the branch and push (not a conflict)")
    show = lambda ref, f: git("show", f"{ref}:{f}", check=False).stdout
    try:
        own, n = version(show(head, INIT)), version(show("origin/main", INIT)) + 1
        bumps = own > version(show(git("merge-base", "origin/main", head).stdout.strip(), INIT))  # else: pr_checks
        if conflicts - ({INIT, LOG} if bumps else set()):
            raise Unresolved(", ".join(sorted(conflicts - {INIT, LOG}) or sorted(conflicts)))
        if bumps:
            for f in (INIT, LOG):
                p = os.path.join(wt, f)
                if os.path.islink(p):  # the PR's tree is untrusted: never write through its symlinks
                    raise Unresolved(f"{f} (a symlink)")
                with open(p, encoding="utf-8") as fh:
                    text = resolve(f, fh.read(), own, n)
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(text)
    except Unresolved as e:
        block(pr, f"conflicts with main in {e}; merge main and push")
    git("add", "-A", cwd=wt)
    git("commit", "-q", "--no-edit", cwd=wt)
    b = info["headRefName"]
    r = git("push", "-q", f"--force-with-lease=refs/heads/{b}:{sha}", "origin", f"HEAD:refs/heads/{b}", cwd=wt, check=False)
    if r.returncode:  # the author pushed meanwhile: that push starts a new review, which cancels this one
        sys.exit(f"#{pr}: push rejected ({r.stderr.strip()[-200:]}); the branch moved, its new review takes over")
    # a push with the workflow token starts no workflows: run the tests on the new head for decide.py
    gh("workflow", "run", "test.yml", "--ref", b, "-f", f"ref={b}")
    print(f"#{pr}: merged main" + (f", VERSION {n}" if bumps else ""))


if __name__ == "__main__":
    main(sys.argv[1])
