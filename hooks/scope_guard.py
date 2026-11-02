#!/usr/bin/env python3
"""PreToolUse hook (Edit/Write/MultiEdit/NotebookEdit): journal files (<plan_dir>/<m>/events.jsonl, decisions.jsonl,
module.json, tasks/*.json) are written only by dpcli — refused for everyone. In a task copy (branch by `task_branch`) an edit outside the
card's `scope` or inside `dont_touch` is refused at once — accept found it only after the work was done. The same
matching as accept's scope check. Exit 2 = blocked. Files outside the copy, the task's log dir and artifacts pass;
no card, empty scope or any error — pass (fails open)."""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))


def verdict(path):
    """None = allowed, else the refusal text."""
    from dpcli import config, gitx, journal
    from dpcli.commands.accept import _pat, path_in

    p = Path(path).expanduser()
    d = p.parent
    while not d.is_dir():
        d = d.parent
    os.chdir(d)
    top = gitx.toplevel()
    try:
        rel = p.resolve().relative_to(Path(top).resolve()).as_posix()
    except ValueError:
        return None  # outside the copy: temporary files, other repositories
    cli = os.environ.get("DPCLI_CLI") or ".dpcli/dpcli"
    pd = re.escape(config.plan_dir().strip("/"))
    if re.fullmatch(rf"{pd}/[^/]+/((events|decisions)\.jsonl|module\.json|tasks/[^/]+\.json)", rel):
        return (f"dpcli: {rel} is the module journal — written only by dpcli commands: cards `{cli} task new|set` "
                f"(--check NAME CMD EXPECT replaces a check, scope+=…), reports — edit your <log_dir>/<ID>/report.json and run "
                f"`{cli} report <ID>` again (it replaces the report), events `{cli} event`, decisions `{cli} decide`. A command is missing — say so in "
                f"`harness: …`, don't edit the journal.")
    br = gitx.git("branch", "--show-current")
    f = config.task_branch_fields(br) if br else None
    if not f or not f.get("task"):
        return None
    tid = f["task"]
    _mod, home = journal.find_task(tid)
    card = json.loads((home / "tasks" / f"{tid}.json").read_text(encoding="utf-8"))
    if card.get("branch") and card["branch"] != br:
        return None
    free = [str(config.get("checks.log_dir") or "build/dpcli"), str(config.get("artifacts_dir") or "")]
    free += [str(x) for x in config.get("gc.ignore_dirs") or []]
    if path_in(rel, [x for x in free if x and not os.path.isabs(x)]):
        return None
    scope = [x for e in card.get("scope") or [] for x in _pat(e)]
    if not any(scope):
        return None
    dont = [x for e in card.get("dont_touch") or [] for x in _pat(e)]
    if path_in(rel, dont):
        why = "is in dont_touch"
    elif not path_in(rel, scope):
        why = "is outside scope"
    else:
        return None
    return (f"dpcli: {rel} {why} of {tid} (scope: {', '.join(scope[:6])}). Not your task's file — don't edit it. "
            f"Really needed — reply to the coordinator «{tid} blocked: needs {rel}» (it can `{cli} task set {tid} "
            f"scope+={rel}`); a contract change — «{tid} contract: …».")


def main():
    try:
        data = json.load(sys.stdin)
        ti = data.get("tool_input") or {}
        path = ti.get("file_path") or ti.get("notebook_path")
        if not path:
            return 0
        if not os.path.isabs(path) and data.get("cwd"):
            path = os.path.join(data["cwd"], path)
        msg = verdict(path)
    except Exception:  # noqa: BLE001 — a guard must never break editing
        return 0
    if msg:
        print(msg, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
