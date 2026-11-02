"""report (executor report) and review (reviewer verdict)."""
import difflib
import json
import sys
from pathlib import Path

from .. import config, gitx
from ..journal import SEVERITY, add_event, by_default, count_sev, find_task, rev_tag
from ..util import CLI, DpError, now, read_json, rel, short, write_json

REPORT_STATUS = {"done", "partial", "blocked", "failed"}
VERDICTS = ("accept", "rework")
MAX_ISSUES = 7


def stdin_redirected():
    """`< file` only; pipes need an explicit `-` (an idle open pipe in agent shells must not block)."""
    import os
    import stat
    try:
        return stat.S_ISREG(os.fstat(0).st_mode)
    except OSError:
        return False


def report_file(tid):
    """Per-task report file in the copy: a shared path (/tmp/r.json) let parallel agents overwrite each other."""
    return config.repo_path(config.get("checks.log_dir", "build/dpcli")) / tid / "report.json"


def report_template():
    return {
        "id": "<task ID>",
        "status": "done | partial | blocked | failed",
        "summary": "1-3 sentences: what was done",
        "commits": ["abc1234 short description"],
        "checks": [{"name": "check name from the card or your own", "value": "number/result", "pass": True}],
        "not_done": ["what failed and why"],
        "questions": ["open question for the coordinator"],
        "images": [f"{config.get('artifacts_dir', 'build/artifacts')}/<task>/01_….png"],
        "how_to_check": f"command or {CLI} accept <ID>",
        "uncertain": [{"where": "file:line", "why": "what you are unsure about", "checked": "what you already checked"}],
        "dp_feedback": "process friction: what dpcli lacked, which rule/card/permission got in the way, where extra rounds went (may be empty)",
        "extra": {"your_number": "free-form object for your own numbers/tables (may be omitted)"},
    }


def validate_report(r, card):
    errs = []
    if not isinstance(r, dict):
        return ["report must be a JSON object"]
    if r.get("status") not in REPORT_STATUS:
        errs.append(f"status ∈ {sorted(REPORT_STATUS)}")
    if not isinstance(r.get("summary"), str) or not r.get("summary"):
        errs.append("summary must be a non-empty string")
    for k in ("commits", "not_done", "questions", "images"):
        if k in r and not isinstance(r[k], list):
            errs.append(f"{k} must be a list")
    if r.get("status") == "done" and not r.get("commits"):
        errs.append("status=done without commits")
    for i, c in enumerate(r.get("checks", []) or []):
        if not isinstance(c, dict) or "name" not in c or "pass" not in c:
            errs.append(f"checks[{i}]: name, value, pass required")
    names = {c.get("name") for c in r.get("checks", []) or [] if isinstance(c, dict)}
    miss = [c["name"] for c in (card or {}).get("accept", []) if c.get("name") not in names]
    if miss and r.get("status") == "done":
        errs.append("missing check results: " + ", ".join(miss))
    if "extra" in r and not isinstance(r["extra"], dict):
        errs.append("extra must be an object")
    want = [k for k in (card or {}).get("report_extra", []) or [] if isinstance(k, str)]
    for k in want:
        if k in r:
            continue
        alt = match_extra_key(k, [x for x in r if x not in want])
        if alt:  # case/unique prefix: rename to the card key
            r[k] = r.pop(alt)
            continue
        near = difflib.get_close_matches(k, [x for x in r if x not in want], n=1, cutoff=0.5)
        errs.append(f"missing field \"{k}\" (report_extra)" + (f"; similar \"{near[0]}\" exists: rename it" if near else "")
                    + ("" if len(want) < 2 else f"; expected: {', '.join(want)}"))
    return errs


def match_extra_key(k, keys):
    """Report key matching a card key: case-insensitive or unique prefix (either direction, 3+ chars)."""
    kl = k.lower()
    ci = [x for x in keys if isinstance(x, str) and x.lower() == kl]
    if len(ci) == 1:
        return ci[0]
    pre = [x for x in keys if isinstance(x, str) and len(x) >= 3 and len(kl) >= 3
           and (kl.startswith(x.lower()) or x.lower().startswith(kl))]
    return pre[0] if len(pre) == 1 else None


def cmd_report(a):
    if a.template:
        t = report_template()
        if a.id:  # card report_extra keys become top-level fields
            _, home = find_task(a.id)
            card = read_json(home / "tasks" / f"{a.id}.json") or {}
            t["id"] = a.id
            for k in card.get("report_extra") or []:
                t[k] = "… (required card field)"
        print(json.dumps(t, ensure_ascii=False, indent=2))
        return
    if not a.id:
        raise DpError("task ID required")
    mod, home = find_task(a.id)
    card = read_json(home / "tasks" / f"{a.id}.json")
    p = home / "tasks" / f"{a.id}.report.json"
    if a.show:
        r = read_json(p)
        if not r:
            raise DpError(f"{a.id}: no report")
        if a.full:
            print(json.dumps(r, ensure_ascii=False, indent=2))
            return
        L = [f"{a.id} {r.get('status')}: {short(r.get('summary', ''), 300)}"]
        if r.get("commits"):
            L.append("commits: " + "; ".join(short(c, 60) for c in r["commits"]))
        for c in r.get("checks", []) or []:
            L.append(f"  {'PASS' if c.get('pass') else 'FAIL'} {c.get('name')} {short(c.get('value', ''), 80)}")
        for k, t in (("not_done", "not done"), ("questions", "question")):
            L += [f"{t}: {short(x, 200)}" for x in r.get(k, []) or []]
        if r.get("images"):
            L.append(f"images: {len(r['images'])} ({rel(Path(r['images'][0]).parent)})")
        for u in r.get("uncertain", []) or []:
            if isinstance(u, dict):
                L.append(f"uncertain: {u.get('where', '')} — {short(u.get('why', ''), 120)}"
                         + (f" (checked: {short(u.get('checked', ''), 80)})" if u.get("checked") else ""))
            else:
                L.append("uncertain: " + short(str(u), 200))
        if isinstance(r.get("extra"), dict) and r["extra"]:
            L.append("extra: " + short("; ".join(f"{k}={json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v}"
                                                 for k, v in r["extra"].items()), 300) + "  (--full: whole)")
        if r.get("dp_feedback"):
            L.append("dpcli: " + short(r["dp_feedback"], 200))
        print("\n".join(L))
        return
    from_file = not (a.file == "-" or (a.file is None and stdin_redirected()))  # explicit input beats a stale file
    if not from_file:
        src = sys.stdin.read()
    else:
        f = Path(a.file) if a.file else report_file(a.id)
        if not f.is_file():
            raise DpError(f"no report file {rel(f)}: write it there ({CLI} report --template {a.id}), or pass FILE, "
                          f"`< FILE` or `- ` for a pipe")
        src = f.read_text()
    try:
        r = json.loads(src)
    except json.JSONDecodeError as e:
        raise DpError(f"report: invalid JSON ({e}); schema: {CLI} report --template")
    if isinstance(r, dict) and r.get("id") not in (None, "", a.id, "<task ID>"):
        raise DpError(f"this report is for {r['id']}, not {a.id} — a file shared with another agent? use {rel(report_file(a.id))}")
    if from_file and isinstance(r, dict) and not r.get("id"):
        print(f"dpcli: warning: the report has no \"id\" — make sure it is {a.id}'s", file=sys.stderr)
    errs = validate_report(r, card)
    if errs:
        raise DpError(f"{a.id}: report rejected: " + "; ".join(errs))
    r["t"] = now()
    r["by"] = by_default(a)
    write_json(p, r)
    commits = [c.split()[0] for c in r.get("commits", []) if c]
    add_event(home, a.id, "reported", r["by"], note=f"{r['status']}: {short(r['summary'], 120)}", commits=commits,
              dp_feedback=r.get("dp_feedback", ""))
    print(f"{a.id}: report {r['status']} → {rel(p)}")


REVIEW_TEMPLATE = {
    "verdict": "accept | rework",
    "summary": "1-3 lines: review outcome",
    "issues": [{"file": "src/module/file.py", "line": 42, "severity": "blocker | major | minor",
                "what": "what is wrong (contract, scope, test-fitting, bug, report != fact)",
                "fix": "what to do"}],
    "rerun": [{"name": "check rerun by the reviewer", "value": "number/result", "pass": True}],
    "harness": "process frictions you noticed: vague card, weak checks, missing command (optional)",
}


def validate_review(r):
    errs = []
    if not isinstance(r, dict):
        return ["review must be a JSON object"]
    if r.get("verdict") not in VERDICTS:
        errs.append(f"verdict ∈ {list(VERDICTS)}")
    sm = r.get("summary")
    if not isinstance(sm, str) or not sm.strip():
        errs.append("summary must be a non-empty string")
    elif len(sm.strip().splitlines()) > 3:
        errs.append("summary must be at most 3 lines")
    iss = r.get("issues", [])
    if not isinstance(iss, list):
        errs.append("issues must be a list")
        iss = []
    if len(iss) > MAX_ISSUES:
        errs.append(f"issues: at most {MAX_ISSUES} (nitpicks and style are not issues)")
    for n, i in enumerate(iss):
        if not isinstance(i, dict):
            errs.append(f"issues[{n}] must be an object")
            continue
        miss = [k for k in ("file", "severity", "what", "fix") if not i.get(k)]
        if miss:
            errs.append(f"issues[{n}]: missing {', '.join(miss)}")
        if i.get("severity") and i["severity"] not in SEVERITY:
            errs.append(f"issues[{n}].severity ∈ {list(SEVERITY)}")
        if "line" in i and i["line"] not in (None, "") and not isinstance(i["line"], (int, str)):
            errs.append(f"issues[{n}].line must be a number or a string like \"12-30\"")
    if r.get("verdict") == "accept" and any(isinstance(i, dict) and i.get("severity") == "blocker" for i in iss):
        errs.append("verdict=accept with a blocker is contradictory")
    if "rerun" in r and not isinstance(r["rerun"], list):
        errs.append("rerun must be a list")
    return errs


def cmd_review(a):
    if a.template:
        print(json.dumps(REVIEW_TEMPLATE, ensure_ascii=False, indent=2))
        return
    if not a.id:
        raise DpError("task ID required")
    mod, home = find_task(a.id)
    p = home / "tasks" / f"{a.id}.review.json"
    if a.show:
        r = read_json(p)
        if not r:
            raise DpError(f"{a.id}: no review")
        if a.full:
            print(json.dumps(r, ensure_ascii=False, indent=2))
            return
        L = [f"{a.id} {rev_tag({'verdict': r.get('verdict'), 'issues': count_sev(r)})} ({r.get('by', '-')}): "
             f"{short(r.get('summary', ''), 300)}"]
        for i in r.get("issues", []):
            ln = f":{i['line']}" if i.get("line") not in (None, "") else ""
            L.append(f"  [{i.get('severity')}] {i.get('file')}{ln} — {short(i.get('what', ''), 160)} → {short(i.get('fix', ''), 120)}")
        for c in r.get("rerun", []) or []:
            L.append(f"  rerun: {'PASS' if c.get('pass') else 'FAIL'} {c.get('name')} {short(c.get('value', ''), 60)}")
        print("\n".join(L))
        return
    if not a.verdict:
        raise DpError("--verdict accept|rework required (or --show / --template)")
    if a.from_:
        src = sys.stdin.read() if a.from_ == "-" else Path(a.from_).read_text()
        try:
            r = json.loads(src)
        except json.JSONDecodeError as e:
            raise DpError(f"review: invalid JSON ({e}); schema: {CLI} review --template")
        if not isinstance(r, dict):
            raise DpError("review must be a JSON object")
        if r.get("verdict") and r["verdict"] != a.verdict:
            raise DpError(f"verdict in file ({r['verdict']}) != --verdict {a.verdict}")
        r["verdict"] = a.verdict
        if a.note and not r.get("summary"):
            r["summary"] = a.note
    else:
        if not a.note:
            raise DpError("--from review.json or --note \"summary\" required")
        r = {"verdict": a.verdict, "summary": a.note, "issues": []}
    r.setdefault("issues", [])
    errs = validate_review(r)
    if errs:
        raise DpError(f"{a.id}: review rejected: " + "; ".join(errs))
    r["t"] = now()
    r["by"] = by_default(a)
    card = read_json(home / "tasks" / f"{a.id}.json") or {}
    cp = Path(card.get("copy") or "").expanduser()
    if cp.is_dir():  # the next review of a rework looks only at what changed since this commit
        r["head"] = gitx.git("rev-parse", "--short", "HEAD", cwd=cp)
    write_json(p, r)
    cnt = count_sev(r)
    ev = add_event(home, a.id, "reviewed", r["by"], note=short(r["summary"], 160), verdict=a.verdict,
                   issues={k: v for k, v in cnt.items() if v}, review=f"{config.plan_dir()}/{mod}/tasks/{a.id}.review.json")
    print(f"{a.id}: {rev_tag(ev)} → {rel(p)}")


def register(sp):
    q = sp.add_parser("report", help=f"executor report: {CLI} report ID [FILE|-] (default <log_dir>/ID/report.json) | --show | --template")
    q.add_argument("id", nargs="?"); q.add_argument("file", nargs="?")
    q.add_argument("--show", action="store_true"); q.add_argument("--template", action="store_true")
    q.add_argument("--full", action="store_true"); q.add_argument("--by")
    q.set_defaults(func=cmd_report)

    q = sp.add_parser("review", help="reviewer verdict: review ID --verdict accept|rework --from r.json | --note … | --show | --template")
    q.add_argument("id", nargs="?"); q.add_argument("--verdict", choices=VERDICTS)
    q.add_argument("--from", dest="from_", metavar="FILE", help="review JSON (review --template), - = stdin")
    q.add_argument("--note", help="short review without a file (no issues) or summary for --from")
    q.add_argument("--show", action="store_true"); q.add_argument("--template", action="store_true")
    q.add_argument("--full", action="store_true"); q.add_argument("--by")
    q.set_defaults(func=cmd_review)
