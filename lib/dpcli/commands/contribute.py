"""contribute: send a dpcli-scope friction to the hub — PR from origin or a fork, +1 on a similar open one, or an issue."""
import difflib
import json
import re
import shutil
import subprocess

from .. import config, reexec
from ..util import CLI, DpError, append_jsonl, now
from .feedback import assign, items, ledger, ledger_path

FOOTER = "_Sent by `dpcli contribute`. Anonymized: no project names, paths or quotes._"


def run(*cmd, cwd=None):
    return subprocess.run(list(cmd), cwd=cwd, capture_output=True, text=True)


def hub(dist):
    h = config.get("hub")
    if h:
        return str(h)
    url = run("git", "remote", "get-url", "origin", cwd=dist).stdout.strip()
    m = re.search(r"github\.com[:/](.+?)(?:\.git)?$", url)
    if not m:
        raise DpError(f"hub repository unknown: origin of .dpcli is «{url}»; set `hub: owner/repo` in the config")
    return m[1]


def gh_ok():
    return shutil.which("gh") and run("gh", "auth", "status").returncode == 0


def cmd_contribute(a):
    c = ledger().get(a.id)
    if not c:
        raise DpError(f"{a.id}: no such cluster ({CLI} feedback)")
    if c["scope"] != "dpcli":
        raise DpError(f"{a.id} is project scope: fix it in .dpcli-local/, not in dpcli")
    dist = reexec.DIST_DIR
    if run("git", "rev-parse", "--show-toplevel", cwd=dist).stdout.strip() != str(dist):
        raise DpError(f"{dist} is not a git repository (install dpcli as a submodule)")
    run("git", "fetch", "-q", "origin", cwd=dist)
    branch = run("git", "branch", "--show-current", cwd=dist).stdout.strip()
    title = a.title or c["title"]
    log = lambda: [x for x in run("git", "log", "--format=%s", "origin/main..HEAD", cwd=dist).stdout.split("\n") if x.strip()]
    if log() and not branch.startswith(f"improve/{a.id}-"):  # the current branch is pushed: another cluster's otherwise
        raise DpError(f"commits on {branch or 'a detached HEAD'} are not {a.id}'s: move them to a branch improve/{a.id}-<slug> "
                      f"(or leave {a.id}'s edits uncommitted on main: {CLI} contribute {a.id} makes the branch)")
    if run("git", "status", "--porcelain", cwd=dist).stdout.strip():  # edits left uncommitted: branch and commit here
        if not branch.startswith(f"improve/{a.id}-"):
            branch = f"improve/{a.id}-" + (re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "fix")
            r = run("git", "switch", "-q", "-c", branch, cwd=dist)
            if r.returncode:
                raise DpError(f"git switch -c {branch}: {r.stderr.strip()}")
        run("git", "add", "-A", cwd=dist)
        r = run("git", "commit", "-q", "-m", title, cwd=dist)
        if r.returncode:
            raise DpError(f"git commit in .dpcli: {(r.stderr or r.stdout).strip()}")
        files = run("git", "show", "--name-only", "--format=", "HEAD", cwd=dist).stdout.split()
        print(f"{a.id}: committed on {branch}: {' '.join(files)}")
    commits = log()
    by_c, _ = assign(items(), {a.id: c})
    group = by_c.get(a.id, [])
    ntasks = len({i["task"] for i in group if i["task"]})
    body = (f"**Friction** — {title}\n\nSeen ×{len(group)} in {ntasks} task(s) of one project."
            + (f"\n\n{c['why']}" if c.get("why") else "")
            + ("\n\n**Change**\n" + "\n".join(f"- {x}" for x in commits) if commits else "")
            + f"\n\n{FOOTER}\n")
    if not gh_ok():
        return offline(a.id, title, body, commits, dist)
    repo = hub(dist)
    if not a.new:
        dup = similar(repo, title)
        if dup:
            r = run("gh", "issue", "comment", str(dup["number"]), "--repo", repo, "--body",
                    f"+1 from another project: ×{len(group)} in {ntasks} task(s).\n\n{FOOTER}")
            if r.returncode:
                raise DpError(f"gh issue comment: {r.stderr.strip()}")
            record(a.id, "pr" if "/pull/" in dup["url"] else "issue", dup["url"])
            print(f"{a.id}: +1 on {dup['url']} (similar: «{dup['title']}»; new one anyway — --new)")
            return
    if commits:
        url = open_pr(repo, dist, branch, title, body)
        record(a.id, "pr", url)
        print(f"{a.id}: PR {url}")
    else:
        r = run("gh", "issue", "create", "--repo", repo, "--title", title, "--body", body, "--label", "feedback")
        if r.returncode:
            raise DpError(f"gh issue create: {r.stderr.strip()}")
        url = r.stdout.strip().splitlines()[-1]
        record(a.id, "issue", url)
        print(f"{a.id}: issue {url}")


def similar(repo, title):
    r = run("gh", "search", "issues", title, "--repo", repo, "--state", "open", "--label", "feedback", "--include-prs",
            "--json", "number,title,url", "--limit", "20")
    try:
        found = json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        return None
    best = max(found, key=lambda x: difflib.SequenceMatcher(None, title.lower(), x["title"].lower()).ratio(), default=None)
    if best and difflib.SequenceMatcher(None, title.lower(), best["title"].lower()).ratio() >= 0.6:
        return best
    return None


def open_pr(repo, dist, branch, title, body):
    can_push = run("gh", "api", f"repos/{repo}", "--jq", ".permissions.push").stdout.strip() == "true"
    remote, head = "origin", branch
    if not can_push:
        if "fork" not in run("git", "remote", cwd=dist).stdout.split():
            r = run("gh", "repo", "fork", repo, "--remote", "--remote-name", "fork", "--clone=false", cwd=dist)
            if r.returncode:
                raise DpError(f"gh repo fork: {r.stderr.strip()}")
        remote, head = "fork", f"{run('gh', 'api', 'user', '--jq', '.login').stdout.strip()}:{branch}"
    r = run("git", "push", "-q", "-u", remote, "HEAD", cwd=dist)
    if r.returncode:
        raise DpError(f"git push {remote}: {r.stderr.strip()}")
    args = ["gh", "pr", "create", "--repo", repo, "--base", "main", "--head", head, "--title", title, "--body", body]
    r = run(*args, "--label", "feedback", cwd=dist)
    if r.returncode and not can_push:  # fork authors may not be allowed to label
        r = run(*args, cwd=dist)
    if r.returncode:
        raise DpError(f"gh pr create: {r.stderr.strip()}")
    return r.stdout.strip().splitlines()[-1]


def outbox(fid):
    return config.repo_path(config.get("checks.log_dir", "build/dpcli")) / f"contribute-{fid}"


def offline(fid, title, body, commits, dist):
    out = outbox(fid)
    out.mkdir(parents=True, exist_ok=True)
    (out / "issue.md").write_text(f"# {title}\n\n{body}", encoding="utf-8")
    if commits:
        run("git", "format-patch", "-q", "origin/main..HEAD", "-o", str(out), cwd=dist)
    print(f"{fid}: gh is not available or not logged in — wrote {out}/ (issue.md"
          + (", *.patch" if commits else "") + "); open an issue or PR at the dpcli repository by hand, "
          f"then: {CLI} feedback fix {fid} --pr <url> once merged")


def record(fid, kind, url):
    append_jsonl(ledger_path(), {"t": now(), "id": fid, "kind": kind, "url": url})
    shutil.rmtree(outbox(fid), ignore_errors=True)  # sent: no longer reported by update as waiting


def register(sp):
    q = sp.add_parser("contribute", help="send a dpcli-scope friction F-n to the dpcli hub: PR (origin or fork), +1, or issue")
    q.add_argument("id", metavar="F-n")
    q.add_argument("--title", help="PR/issue title (default: the cluster title; keep it anonymized)")
    q.add_argument("--new", action="store_true", help="don't +1 a similar open PR/issue, open a new one")
    q.set_defaults(func=cmd_contribute)
