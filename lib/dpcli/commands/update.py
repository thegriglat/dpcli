"""update: move the .dpcli submodule to the latest release tag, re-render with the project layer, commit the pointer;
report what happened to this project's PRs/issues at the dpcli hub."""
import datetime as dt
import json
import re
import shutil
import subprocess
import sys

from .. import VERSION, config, gitx, reexec
from ..util import CLI, append_jsonl, lang_commit, now, read_json, short, write_json
from .contribute import outbox
from .feedback import ledger, ledger_path

GENERATED = [".dpcli", ".claude/agents", ".claude/skills", ".claude/.dpcli-manifest.json", ".claude/settings.json", "CLAUDE.md"]


def run(*cmd, cwd=None, timeout=60):
    try:
        return subprocess.run(list(cmd), cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", "timeout")


def pin_file():
    return config.repo_path(config.get("local_dir", ".dpcli-local")) / "update.json"


def stamp_file():
    return config.expand("~/.cache/dpcli/{project}/update.stamp")


def tag_num(t):
    m = re.fullmatch(r"v(\d+)", t)
    return int(m[1]) if m else None


def changelog(dist, ref, lo, hi):
    """First line of each CHANGELOG section lo < N ≤ hi at ref."""
    text = run("git", "show", f"{ref}:CHANGELOG.md", cwd=dist).stdout
    out = []
    for m in re.finditer(r"^## (\d+)[^\n]*\n+- ([^\n]+)", text, re.M):
        if lo < int(m[1]) <= hi:
            out.append(f"v{m[1]}: {short(m[2], 100)}")
    return out


def cmd_update(a):
    if a.pin or a.unpin:
        write_json(pin_file(), {"pin": a.pin} if a.pin else {})
        print(f"dpcli pinned to {a.pin}" if a.pin else "dpcli unpinned")
        return
    if a.auto:
        st = stamp_file()
        today = dt.date.today().isoformat()
        if st.is_file() and st.read_text().strip() == today:
            return
        st.parent.mkdir(parents=True, exist_ok=True)
        st.write_text(today + "\n")
    lines = check_prs()  # first: a merged PR frees .dpcli from its improve/* branch before the update
    if not a.prs_only:
        lines += update_dist(a)
    lines += unsent()
    if lines:
        print("\n".join(lines))


def update_dist(a):
    root, mw = gitx.toplevel(), gitx.main_worktree()
    if mw and root.resolve() != mw.resolve():
        return [] if a.auto else ["update: only in the main copy (task copies re-exec it)"]
    dist = reexec.DIST_DIR
    if run("git", "rev-parse", "--show-toplevel", cwd=dist).stdout.strip() != str(dist):
        return ["update: .dpcli is not a git submodule — reinstall with install.sh"]
    if run("git", "status", "--porcelain", cwd=dist).stdout.strip():
        return ["update: skipped — uncommitted changes in .dpcli (commit them on improve/* or revert)"]
    br = run("git", "branch", "--show-current", cwd=dist).stdout.strip()
    if br and br != "main":
        return [f"update: skipped — .dpcli is on {br} (finish it: {CLI} contribute)"]
    if run("git", "fetch", "-q", "--prune", "--tags", "origin", cwd=dist, timeout=15).returncode:
        return ["update: offline, skipped"]
    if run("git", "log", "--oneline", "origin/main..main", cwd=dist).stdout.strip():  # -B main below would drop them
        return ["update: skipped — local commits on .dpcli main: move them to improve/* and contribute"]
    tags = sorted(n for n in map(tag_num, run("git", "tag", "-l", "v*", cwd=dist).stdout.split()) if n)
    pin = tag_num((read_json(pin_file()) or {}).get("pin") or "")
    cand = [n for n in tags if pin is None or n <= pin]
    # same VERSION off the tag: an own PR squash-merged, .dpcli still on its branch commit — move to the release
    on_tag = cand and run("git", "rev-parse", "HEAD", cwd=dist).stdout == \
        run("git", "rev-parse", f"v{cand[-1]}^{{commit}}", cwd=dist).stdout
    if not cand or cand[-1] < VERSION or (cand[-1] == VERSION and on_tag):
        if not a.check and not br and on_tag:
            run("git", "checkout", "-q", "-B", "main", cwd=dist)  # the release as branch main, not a detached tag
        if not a.check and run(sys.executable, str(reexec.entry()), "init", "--check", cwd=root).returncode:
            # the version is current but .claude/ is not (dpcli changed in place, or init never ran): re-render
            h, err = render_and_commit(root, f"dpcli v{VERSION}")
            if err:
                return [f"dpcli v{VERSION}: .claude is stale and init failed — fix and run {CLI} init: {err}"]
            if run(sys.executable, str(reexec.entry()), "init", "--check", cwd=root).returncode:
                return [f"dpcli v{VERSION}: .claude stays stale after init (edited by hand?) — see {CLI} init --check"]
            return [f"dpcli v{VERSION}: .claude re-rendered" + (f", committed {h}" if h else "")]
        return [f"dpcli v{VERSION} is up to date" + (f" (pinned v{pin})" if pin else "")] if not a.auto else []
    target = cand[-1]
    if a.check:
        return [f"dpcli v{VERSION} → v{target} available: {CLI} update"]
    r = run("git", "checkout", "-q", "-B", "main", f"v{target}", cwd=dist)
    if r.returncode:
        return [f"update: checkout v{target} failed: {r.stderr.strip()}"]
    h, err = render_and_commit(root, f"dpcli v{target}")
    if err:
        return [f"update: v{target} checked out, but init failed — fix and run {CLI} init: {err}"]
    notes = changelog(dist, f"v{target}", VERSION, target)
    return [f"dpcli v{VERSION} → v{target}" + (f", committed {h}" if h else "")] + [f"  {x}" for x in notes]


def render_and_commit(root, msg):
    """init + commit of the generated files. -> (commit hash or "" when nothing changed, None | init's error)."""
    r = run(sys.executable, str(reexec.entry()), "init", cwd=root)
    if r.returncode:
        return "", short((r.stderr or r.stdout).strip(), 200) or f"exit {r.returncode}"
    wf = config.repo_path(config.get("workflow"), root=root).resolve()
    extra = [str(wf.relative_to(root.resolve()))] if root.resolve() in wf.parents else []  # outside the repo: not ours to commit
    paths = [p for p in GENERATED + extra if (root / p).exists()]
    if run("git", "status", "--porcelain", "--", *paths, cwd=root).stdout.strip():
        return gitx.commit_paths(root, paths, lang_commit(msg, msg)), None
    return "", None


def check_prs():
    """Fate of open PRs/issues sent by `contribute`: merged → fixed; rework/rejected → arguments into the ledger."""
    led = ledger()
    todo = {fid: c for fid, c in led.items() if c.get("pr") and c["status"] in ("open", "rework")}
    if not todo or not shutil.which("gh") or run("gh", "auth", "status").returncode:
        return []
    out = []
    for fid, c in todo.items():
        url = c["pr"]
        kind = "pr" if "/pull/" in url else "issue"
        r = run("gh", kind, "view", url, "--json", "state,labels,comments", timeout=20)
        try:
            info = json.loads(r.stdout)
        except (json.JSONDecodeError, TypeError):
            continue
        state = str(info.get("state", "")).upper()
        labels = {x.get("name") for x in info.get("labels") or []}
        verdict = next((x.get("body", "") for x in reversed(info.get("comments") or []) if "VERDICT:" in x.get("body", "")), "")
        why = short(" ".join(l.strip("- ") for l in verdict.splitlines()[1:] if l.strip()), 200)
        tag = url.rstrip("/").rsplit("/", 2)[-2] + "/" + url.rstrip("/").rsplit("/", 1)[-1]
        if state == "MERGED":  # rejected/closed: the branch may be the only copy, harness-retro may rework it
            drop_branches(fid)
        if state == "MERGED" or (kind == "issue" and state == "CLOSED" and "rejected" not in labels):
            append_jsonl(ledger_path(), {"t": now(), "id": fid, "kind": "fix", "where": f"dpcli (merged {url})", "pr": url})
            out.append(f"{tag} merged → {fid} fixed (remove temporary workarounds marked until: {url})")
        elif state == "CLOSED" or "rejected" in labels:
            append_jsonl(ledger_path(), {"t": now(), "id": fid, "kind": "rejected", "why": why})
            out.append(f"{tag} rejected → {fid}: {why or 'see the PR'} — drop it or solve in .dpcli-local/ (harness-retro)")
        elif "rework" in labels and c["status"] != "rework":
            append_jsonl(ledger_path(), {"t": now(), "id": fid, "kind": "rework", "why": why})
            out.append(f"{tag} rework → {fid}: {why or 'see the review'} — rework on its improve/* branch or drop (harness-retro)")
    return out


def drop_branches(fid):
    """The PR is merged: its local improve/<fid>-* branch is done (-D: a squash merge is not an ancestor)."""
    dist = reexec.DIST_DIR
    for b in run("git", "for-each-ref", "--format=%(refname:short)", f"refs/heads/improve/{fid}-*", cwd=dist).stdout.split():
        if b == run("git", "branch", "--show-current", cwd=dist).stdout.strip():
            if run("git", "status", "--porcelain", cwd=dist).stdout.strip():
                continue
            run("git", "checkout", "-q", "--detach", cwd=dist)
        run("git", "branch", "-q", "-D", b, cwd=dist)


def unsent():
    """Contributions written to disk because gh was not logged in: the user sees them until they are sent."""
    return [f"{x.name[11:]} not sent to the dpcli hub (gh not logged in; dpcli updates wait while .dpcli is on its branch): "
            f"gh auth login, then {CLI} contribute {x.name[11:]}"
            for x in sorted(outbox("").parent.glob("contribute-F-*")) if x.is_dir()]


def register(sp):
    q = sp.add_parser("update", help="update the .dpcli submodule to the latest release, re-render, commit; check own PRs")
    q.add_argument("--auto", action="store_true", help="at most once a day, silent when nothing happened (SessionStart hook)")
    q.add_argument("--check", action="store_true", help="only tell whether a new version is available")
    q.add_argument("--prs-only", dest="prs_only", action="store_true", help="only check own PRs/issues at the hub")
    g = q.add_mutually_exclusive_group()
    g.add_argument("--pin", metavar="vN", help="never update above vN (stored in .dpcli-local/update.json)")
    g.add_argument("--unpin", action="store_true")
    q.set_defaults(func=cmd_update)

