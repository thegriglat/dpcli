"""task new|show|brief|set|note|sync, module init."""
import json
import re
import sys
from pathlib import Path

from .. import agents, config, copies, gitx
from ..journal import (ID_RE, add_event, addenda, all_modules, by_default, check_area, check_code, ensure_module, expect_arg, home_root,
                       find_task, module_home, module_meta, reserved_codes, task_cards)
from .accept import check_bounds
from ..util import CLI, DpError, Parser, hm, lang_commit, now, pretty, read_json, read_jsonl, rel, short, subgroup, write_json

CARD_TEMPLATE = {
    "id": "", "module": "", "type": "", "title": "", "goal": "",
    "plan_ref": "", "contracts": [], "copy": "", "branch": "", "base": "",
    "scope": [], "dont_touch": [], "accept": [], "report_extra": [], "notes": "",
}


def cmd_task_new(a):
    home = module_home(a.module)
    if not a.id:
        code = (read_json(home / "module.json") or {}).get("code")
        if not code:
            raise DpError(f"module {a.module} has no code: {CLI} module init {a.module} --code XX (2–4 capital letters), "
                          "or give the ID explicitly")
        stage = (a.stage or "").upper()
        if stage and not re.fullmatch(r"[A-Z]", stage):
            raise DpError(f"--stage «{a.stage}»: one capital Latin letter")
        nums = [int(m[3]) for t in task_cards(home) if (m := ID_RE.match(t)) and m[1] == code and m[2] == stage]
        a.id = f"{code}-{stage}{max(nums, default=0) + 1}"
    else:
        m = ID_RE.match(a.id)
        if not m or m[1] in reserved_codes():
            raise DpError(f"ID «{a.id}»: format <CODE>-[stage]<n>[letter], e.g. NN-7, NN-7a, NN-P8 (code: 2–4 capital "
                          "Latin letters, not in reserved_codes); omit ID for the next number")
        for mod, h in all_modules().items():
            if mod != a.module and (h / "tasks" / f"{a.id}.json").exists():
                raise DpError(f"ID {a.id} already exists in module {mod}")
    p = home / "tasks" / f"{a.id}.json"
    if p.exists() and not a.force:
        raise DpError(f"card already exists: {rel(p)} (--force to overwrite)")
    card = json.loads(json.dumps(CARD_TEMPLATE))
    if a.from_:
        src = sys.stdin.read() if a.from_ == "-" else Path(a.from_).read_text()
        try:
            card.update(json.loads(src))
        except json.JSONDecodeError as e:
            raise DpError(f"--from: invalid JSON ({e})")
    meta = module_meta(a.module, home)
    card.update({"id": a.id, "module": a.module})
    for k in ("type", "title", "goal", "plan_ref", "copy", "branch"):
        v = getattr(a, k, None)
        if v:
            card[k] = v
    card["branch"] = card["branch"] or config.task_branch(a.module, a.id)
    card["copy"] = card["copy"] or pretty(config.task_copy(a.module, a.id))
    card["base"] = card["base"] or meta["branch"]
    for c in a.contract or []:
        name, _, ver = c.partition("@")
        card["contracts"].append({"name": name, "version": ver or "?", "ref": contract_ref(name, meta)})
    card["scope"] += a.scope or []
    card["dont_touch"] += a.dont_touch or []
    for f in a.test or []:
        card["accept"].append({"name": f, "tests": f})
    for name, cmd, exp in a.check or []:
        card["accept"].append({"name": name, "cmd": cmd, "expect": expect_arg(exp)})
    set_timeouts(card, a.check_timeout)
    types = agents.executor_types()
    if not card["type"]:
        raise DpError(f"--type required ({'|'.join(types) or 'no agents with dpcli_role: executor'})")
    if card["type"] not in types:
        raise DpError(f"--type «{card['type']}»: not an executor (available: {', '.join(types) or 'none'}; "
                      f"agents in {config.get('agents_dir')}/*.md, dpcli_role: executor)")
    validate_checks(card.get("accept"))
    check_plan_ref(a.module, card.get("plan_ref"))
    check_bounds(card)
    ensure_module(a.module, home)
    card["created"] = card.get("created") or now()
    write_json(p, card)
    add_event(home, a.id, "created", by_default(a), note=card.get("title", ""))
    empty = missing_for_brief(card)
    print(f"{a.id}: {rel(p)}" + (f"; empty: {', '.join(empty)} — brief will refuse (fill in: {CLI} task set {a.id} …)"
                                  if empty else ""))
    hint = related_tests(card, home_root(home))
    if hint:
        print(f"tests referencing scope files — add those the change will touch ({CLI} task set {a.id} scope+=PATH): "
              + ", ".join(hint))
    if not a.no_copy:
        print(make_copy(card))


def _report_path(tid):
    from .report import report_file  # lazy: task does not depend on report at import time
    return rel(report_file(tid))


def general_rules():
    """The "General rules" section of the process description, inline: executors need it, not the whole file
    (~460 of ~3300 tokens)."""
    from ..mdsec import find_section, headings, section_body
    wf = config.get("workflow")
    try:
        path = config.repo_path(wf)
        lines, heads = headings(path.read_text())
    except (OSError, DpError):
        return [f"Rules: {wf}, \"General rules\" (mandatory reading)."]
    sel = find_section(heads, "General rules")
    if sel is None:
        return [f"Rules: {wf}, \"General rules\" (mandatory reading)."]
    return [f"Rules ({wf}; other sections only when the card points to them):"] + section_body(lines, heads, sel)[1:]


def check_plan_ref(mod, ref):
    """A card's plan_ref must name an existing plan section (when the plan file exists)."""
    if not ref:
        return
    from ..mdsec import find_section, headings
    from .plan import plan_path
    try:
        path = plan_path(mod)
    except DpError:
        return
    if path.is_file() and find_section(headings(path.read_text())[1], ref) is None:
        raise DpError(f"plan_ref \"{ref}\" is not a section of {rel(path)} (sections: {CLI} plan {mod})")


def related_tests(card, cwd, limit=6):
    """Test files that mention a scope file's name: the change will likely touch them, so they belong in the scope.
    A heuristic (name match, paths containing test/spec), printed as a hint only."""
    from .accept import _pat, path_in
    pats = [p for e in card.get("scope") or [] for p in _pat(e)]
    stems = {Path(p).stem for p in pats if p and not p.startswith("!") and not any(c in p for c in "*?[")
             and len(Path(p).stem) >= 4 and Path(p).suffix}
    if not stems:
        return []
    args = ["grep", "-l", "-w", "-F"] + [x for s in sorted(stems) for x in ("-e", s)] + ["--", "*test*", "*spec*"]
    found = [f for f in gitx.git(*args, cwd=cwd).splitlines() if f and not path_in(f, pats)]
    return found[:limit] + ([f"… (+{len(found) - limit})"] if len(found) > limit else [])


def set_timeouts(card, pairs):
    """--check-timeout NAME SEC: per-check timeout in the card (default 900 s). -> names changed."""
    out = []
    for name, sec in pairs or []:
        c = next((c for c in card.get("accept") or [] if c.get("name") == name), None)
        if c is None or not str(sec).isdigit():
            raise DpError(f"--check-timeout {name} {sec}: no such check, or seconds not a number")
        c["timeout"] = int(sec)
        out.append(name)
    return out


def validate_checks(checks):
    """Card checks are parsed right away (task new/set), not only in accept."""
    from .accept import parse_expect
    names = [c.get("name") for c in checks or [] if isinstance(c, dict)]
    dup = sorted({n for n in names if n and names.count(n) > 1})
    if dup:  # results and logs are kept by check name
        raise DpError(f"duplicate check names: {', '.join(dup)} (task set … --drop-check NAME replaces one)")
    for c in checks or []:
        if not isinstance(c, dict) or not c.get("name"):
            raise DpError(f"check {json.dumps(c, ensure_ascii=False)}: object with name required")
        if c.get("tests") and "expect" not in c:
            continue
        exp = parse_expect(c.get("expect"))
        for k in ("re", "not_re", "num"):
            if exp.get(k):
                try:
                    re.compile(exp[k])
                except re.error as e:
                    raise DpError(f"check «{c['name']}»: invalid regex «{exp[k]}» ({e})")


def make_copy(card):
    """Task copy and branch (copies.create + setup); reuse if present."""
    br, base = card["branch"], card["base"]
    cp = Path(card["copy"]).expanduser()
    have = gitx.copy_of(br)
    if have:
        return f"copy: {pretty(have)} (already exists, branch {br})"
    if cp.exists() and any(cp.iterdir()):
        return f"copy not created: {pretty(cp)} is occupied by something other than a copy of {br} — create it yourself or use --copy"
    if gitx.branch_exists(br):
        copies.create(cp, br)
    elif gitx.branch_exists(base):
        copies.create(cp, br, base)
    else:
        return f"copy not created: no branch {base} ({CLI} module new {card['module']})"
    return "\n  ".join([f"copy: {pretty(cp)}, branch {br} from {base}"] + copies.setup(cp))


def missing_for_brief(card):
    return [k for k in ("goal", "scope", "accept") if not card.get(k)]


BRIEF_W = 120


def _fit(items, room):
    """Items joined by ", " within room characters; if they don't fit, "… (+N: task show)"."""
    items = [str(x) for x in items]
    out = []
    for x in items:
        if out and len(", ".join(out + [x])) > room:
            return ", ".join(out) + f" … (+{len(items) - len(out)}: task show)"
        out.append(x)
    return ", ".join(out)


def cmd_task_brief(a):
    """Ready-made job message for the executor (or reviewer): the coordinator sends it as is."""
    mod, home = find_task(a.id)
    card = read_json(home / "tasks" / f"{a.id}.json")
    miss = missing_for_brief(card)
    if miss:
        raise DpError(f"{a.id}: card not ready to hand out — missing: {', '.join(miss)} "
                      f"({CLI} task set {a.id} goal=… scope+=… | --check …)")
    tid, cp, br, base = card["id"], card.get("copy"), card.get("branch"), card.get("base")
    where = f"copy {cp}, branch {br}"
    if not (cp and Path(cp).expanduser().is_dir()):  # --no-copy: the work is wherever the card was made
        cp, br = pretty(gitx.toplevel()), gitx.git("branch", "--show-current") or "HEAD"
        where = f"no task copy — the work is in {cp} ({br})"
    if a.review:
        L = [f"Review {tid}: {where}.",
             f"Data: {CLI} task show {tid} --full; {CLI} report {tid} --show."]
        prev = read_json(home / "tasks" / f"{tid}.review.json") or {}
        if prev.get("verdict") == "rework" and prev.get("head"):
            L.append(f"Re-review: check that the previous issues are fixed ({CLI} review {tid} --show) and only what changed "
                     f"since (git -C {cp} diff --stat {prev['head']}..HEAD); the rest was reviewed.")
        L += [f"Verdict: {CLI} review {tid} --verdict accept|rework --from r.json (schema: --template).",
             f"Reply: «{tid} review accept|rework <n>»"]
    else:
        sect = card.get("plan_ref") or "<section>"
        bound = "Scope: only " + _fit(card["scope"], BRIEF_W - 40)
        if card.get("dont_touch"):
            bound += "; don't touch " + _fit(card["dont_touch"], max(30, BRIEF_W - len(bound) - 14))
        L = [f"{tid} {card.get('type', '')}: {card.get('title', '')}",
             (f"Copy: {cp}  branch: {br} (from {base})" if where.startswith("copy") else f"Work: {where}"),
             f"Do: {CLI} task show {tid}  · plan: {CLI} plan {mod} {sect}",
             bound,
             f"Done when: {CLI} accept {tid} --dry → PASS; report: {_report_path(tid)} → {CLI} report {tid}",
             f"Reply: one line «{tid} reported» | «{tid} blocked: <reason ≤15 words>» | «{tid} contract: <what to change>»"]
    print("\n".join(L))


def fmt_check(c):
    if c.get("tests"):
        return f"{c['name']}: tests «{c['tests']}» (checks.tests) → 0 failed"
    exp = c.get("expect", "exit=0")
    return f"{c['name']}: `{c.get('cmd', '')}` → {json.dumps(exp, ensure_ascii=False) if isinstance(exp, dict) else exp}"


def _set_value(raw):
    """Field value: JSON if it parses (numbers, lists, objects, true/false), else a string."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def cmd_task_set(a):
    """Edit a card without rewriting JSON: field=value, field+=item, field-=item, acceptance checks."""
    mod, home = find_task(a.id)
    p = home / "tasks" / f"{a.id}.json"
    card = read_json(p)
    before = json.loads(json.dumps(card))
    changed = []
    for op in a.ops or []:
        m = re.match(r"^([A-Za-z_][\w]*)(\+=|-=|=)(.*)$", op, re.S)
        if not m:
            raise DpError(f"«{op}»: expected field=value | field+=item | field-=item")
        key, kind, raw = m.groups()
        if key == "id":
            raise DpError("id cannot be changed")
        val = _set_value(raw)
        if kind == "=":
            if isinstance(val, str) and (isinstance(card.get(key), list) or isinstance(CARD_TEMPLATE.get(key), list)):
                val = [x.strip() for x in val.split(",") if x.strip()]  # report_extra=a,b -> ["a", "b"], not per character
            if key == "type" and val not in agents.executor_types():
                raise DpError(f"type «{val}»: not an executor (available: {', '.join(agents.executor_types()) or 'none'})")
            card[key] = val
        else:
            lst = card.get(key)
            if lst is None:
                lst = []
            if not isinstance(lst, list):
                raise DpError(f"{key} is not a list, «{kind}» does not apply")
            if kind == "+=":
                lst.append(val)
            else:
                keep = [x for x in lst if not (x == val or (isinstance(x, dict) and x.get("name") == val))]
                if len(keep) == len(lst):
                    raise DpError(f"{key}: «{raw}» not found")
                lst = keep
            card[key] = lst
        changed.append(key)
    for c in a.contract or []:
        name, _, ver = c.partition("@")
        cs = card.setdefault("contracts", [])
        old = next((x for x in cs if x.get("name") == name), None)
        if old:
            old["version"] = ver or old.get("version", "?")
        else:
            cs.append({"name": name, "version": ver or "?", "ref": contract_ref(name, module_meta(mod, home))})
        changed.append(f"contract:{name}")
    acc = card.setdefault("accept", [])
    # drop first, then add: --drop-check X --check X … replaces a check
    for name in a.drop_check or []:
        n0 = len(acc)
        acc[:] = [c for c in acc if c.get("name") != name]
        if len(acc) == n0:
            raise DpError(f"no check «{name}» in card")
        changed.append(f"accept:-{name}")
    for name, cmd, exp in a.check or []:
        acc[:] = [c for c in acc if c.get("name") != name] + [{"name": name, "cmd": cmd, "expect": expect_arg(exp)}]
        changed.append(f"accept:{name}")
    for f in a.test or []:
        acc[:] = [c for c in acc if c.get("name") != f] + [{"name": f, "tests": f}]
        changed.append(f"accept:{f}")
    changed += [f"timeout:{n}" for n in set_timeouts(card, a.check_timeout)]
    validate_checks(card.get("accept"))
    if {"scope", "dont_touch"} & set(changed):
        check_bounds(card)
    if "plan_ref" in changed:
        check_plan_ref(mod, card.get("plan_ref"))
    if not changed:
        raise DpError("nothing to change: field=value, --check, --test, --drop-check, --contract")
    card["edited"] = now()
    write_json(p, card)
    diff = {k: [short(json.dumps(before.get(k), ensure_ascii=False), 300), short(json.dumps(card.get(k), ensure_ascii=False), 300)]
            for k in dict.fromkeys(c.split(":")[0] for c in changed)}
    add_event(home, a.id, "edited", by_default(a), note=", ".join(changed), diff=diff)
    print(f"{a.id}: changed — {', '.join(changed)}")


def cmd_task_note(a):
    """Append a rule/note to a task already handed to the executor: shown in task show and inbox <ID>."""
    mod, home = find_task(a.id)
    if not a.text.strip():
        raise DpError("empty text")
    add_event(home, a.id, "note", by_default(a), note=a.text, addendum=True)
    print(f"{a.id}: addendum recorded -> executor sees it: {CLI} inbox {a.id} (and {CLI} task show {a.id})")


def contract_ref(name, meta, stored=""):
    """Contract file: "<name>.Cx" is a contract of another module <name> (docs/contracts/<name>.md), else the current module's contracts."""
    head = name.split(".", 1)[0] if "." in name else ""
    if head and head != meta.get("module"):
        return f"{config.contracts_dir()}/{head}.md"
    return stored or meta["contracts"]


def cmd_task_show(a):
    mod, home = find_task(a.id)
    card = read_json(home / "tasks" / f"{a.id}.json")
    if a.json:
        print(json.dumps(card, ensure_ascii=False, indent=2))
        return
    if a.diff:
        evs = [e for e in read_jsonl(home / "events.jsonl") if e.get("task") == a.id and e.get("ev") == "edited"]
        if not evs:
            print(f"{a.id}: card unchanged since creation")
        for e in evs:
            print(f"{hm(e['t'])} ({e.get('by', '-')}) {e.get('note', '')}")
            for k, (old, new) in (e.get("diff") or {}).items():
                print(f"    {k}: {old} → {new}")
        return
    meta = module_meta(mod, home)
    full = a.full
    L = [f"{card['id']} [{mod}] {card.get('title', '')} — {card.get('type', '')}"]
    if card.get("goal"):
        L.append(f"Goal: {card['goal']}")
    plan = meta["plan"] + (f" {card['plan_ref']}" if card.get("plan_ref") else "")
    L.append(f"Plan: {plan} ({CLI} plan {mod} <section>)")
    L.append(f"Copy: {card.get('copy')}  branch: {card.get('branch')} from {card.get('base')}")
    if card.get("contracts"):
        L.append("Contracts: " + "; ".join(f"{c['name']} v{c.get('version', '?')} ({contract_ref(c['name'], meta, c.get('ref', ''))})" for c in card["contracts"]))
    for key, title in (("scope", "Scope"), ("dont_touch", "Don't touch")):
        items = card.get(key) or []
        if items and (full or len(items) > 3):
            L += [f"{title}:"] + [f"  - {x}" for x in items]
        elif items:
            L.append(f"{title}: " + "; ".join(items))
    if card.get("accept"):
        L.append(f"Acceptance ({CLI} accept {card['id']}; trial run before report: {CLI} accept {card['id']} --dry):")
        L += [f"  - {fmt_check(c)}" for c in card["accept"]]
    if card.get("notes"):
        L.append(f"Notes: {card['notes']}")
    adds = addenda(home, a.id)
    if adds:
        shown = adds if full else adds[-5:]
        L.append(f"Addenda since handout ({len(adds)}" + (f", older {len(adds) - len(shown)}: --full" if len(shown) < len(adds) else "") + "):")
        L += [f"  ! {hm(e['t'])} ({e.get('by', '-')}): {e['note']}" for e in shown]
    nedit = sum(1 for e in read_jsonl(home / "events.jsonl") if e.get("task") == a.id and e.get("ev") == "edited")
    if nedit:
        L.append(f"Card edited {nedit} time(s) ({CLI} task show {a.id} --diff)")
    L += general_rules()
    L.append(f"Neighbours' fresh work (branch {card.get('base') or 'module'} -> yours): {CLI} task sync {card['id']}.")
    L.append(f"Long runs: `{CLI} job start <name> <timeout_s> <command…>`, wait with `{CLI} job wait <name> <timeout_s>` "
             "in the background (run_in_background), not `until grep` loops.")
    rx = ", ".join(f"«{k}»" for k in card.get("report_extra") or [])
    L.append(f"Report: write {_report_path(card['id'])}, then {CLI} report {card['id']} (schema with the card's fields: {CLI} report --template {card['id']})"
             f"{'; required top-level report fields: ' + rx if rx else ''}; finish with dpcli feedback "
             "(field dp_feedback).")
    if full:
        L.append("The task copy is yours; don't touch others; change contracts only via the coordinator; commit only your own files "
                 "(git commit -- <paths>), with a Claude-Session line. Neighbours' fresh work: git merge the module branch "
                 f"into yours ({CLI} task sync {card['id']}).")
        L.append(f"Journal and card: {config.plan_dir()}/{mod}/ ({CLI} log {card['id']}, {CLI} task show {card['id']} --diff).")
    print("\n".join(L))


def cmd_task_sync(a):
    mod, home = find_task(a.id)
    card = read_json(home / "tasks" / f"{a.id}.json")
    br, base = card.get("branch"), card.get("base") or config.module_branch(mod)
    path = gitx.copy_of(br) if br else None
    if not path:
        raise DpError(f"task branch {br} has no copy")
    h, n, kind = gitx.do_merge(path, base, a.message or lang_commit(f"Merge {base} into {br}", f"Слияние {base} в {br}"), trailers=a.trailer)
    print(f"{br}: {base} already merged" if kind == "up-to-date" else f"{br}: merged {base}, {h}, {n} file(s)")


def cmd_module_init(a):
    home = module_home(a.module)
    ensure_module(a.module, home, plan=a.plan, contracts=a.contracts, branch=a.branch, copy=a.copy, code=a.code, area=a.area)
    mp = home / "module.json"
    m = read_json(mp) or {}
    check_area(a.area or m.get("area"))
    if a.legacy or a.code or a.area:
        if a.legacy:
            m["legacy_journal"] = a.legacy
        if a.code:
            check_code(a.code, a.module)
            m["code"] = a.code
        if a.area:
            m["area"] = a.area
        write_json(mp, m)
    print(f"{a.module}: {rel(home)}")


def register(sp):
    t = sp.add_parser("task", help="task card: new | show | brief | set | note | sync (sync merges the module branch into the task branch)")
    tsp = t.add_subparsers(dest="sub", required=True, parser_class=Parser, metavar="new|show|brief|set|note|sync")
    q = tsp.add_parser("new", help="create a card")
    q.add_argument("module"); q.add_argument("id", nargs="?", help="<CODE>-[stage]<n>[letter]; omit for the module's next number")
    q.add_argument("--stage", metavar="LETTER", help="stage for auto-numbering: --stage P -> next <CODE>-P<n>")
    q.add_argument("--type", help="executor type: an agent with dpcli_role: executor (e.g. dp-engineer)")
    q.add_argument("--title"); q.add_argument("--goal"); q.add_argument("--plan-ref", dest="plan_ref", help="plan section, e.g. §UC-3")
    q.add_argument("--copy"); q.add_argument("--branch")
    q.add_argument("--from", dest="from_", metavar="FILE", help="JSON card (fields over the template), - = stdin")
    q.add_argument("--contract", action="append", metavar="NAME@VERSION")
    q.add_argument("--scope", action="append", metavar="PATH"); q.add_argument("--dont-touch", dest="dont_touch", action="append", metavar="PATH")
    q.add_argument("--test", action="append", metavar="FILTER", help="check: project tests (checks.tests, {filter}=FILTER), 0 failed")
    q.add_argument("--check", action="append", nargs=3, metavar=("NAME", "CMD", "EXPECT"),
                   help="EXPECT: exit=N | re:<regex> | !re:<regex> | num:<regex with group> <op>N | tests")
    q.add_argument("--check-timeout", dest="check_timeout", action="append", nargs=2, metavar=("NAME", "SEC"),
                   help="timeout of a check, s (default 900)")
    q.add_argument("--no-copy", dest="no_copy", action="store_true",
                   help="do not create the task copy and branch (default: git worktree add -b <branch> <copy> <base>)")
    q.add_argument("--force", action="store_true"); q.add_argument("--by")
    q.set_defaults(func=cmd_task_new)
    q = tsp.add_parser("brief", help="ready-made job message for the executor (--review: for the reviewer); send as is")
    q.add_argument("id"); q.add_argument("--review", action="store_true")
    q.set_defaults(func=cmd_task_brief)
    q = tsp.add_parser("show", help="card for the executor (short)")
    q.add_argument("id"); q.add_argument("--json", action="store_true")
    q.add_argument("--full", action="store_true", help="full job for the executor: card + rules + notes, one item per line")
    q.add_argument("--diff", action="store_true", help="how the card changed (edited events)")
    q.set_defaults(func=cmd_task_show)
    q = tsp.add_parser("sync", help="merge the module branch (card base) into the task branch in its copy")
    q.add_argument("id"); q.add_argument("--message"); q.add_argument("--trailer", action="append")
    q.set_defaults(func=cmd_task_sync)
    q = tsp.add_parser("set", help="edit a card: field=value | field+=item | field-=item (JSON or string)")
    q.add_argument("id"); q.add_argument("ops", nargs="*", metavar="FIELD=VALUE")
    q.add_argument("--check", action="append", nargs=3, metavar=("NAME", "CMD", "EXPECT"), help="add/replace a check")
    q.add_argument("--check-timeout", dest="check_timeout", action="append", nargs=2, metavar=("NAME", "SEC"),
                   help="timeout of a check, s")
    q.add_argument("--test", action="append", metavar="FILTER", help="add/replace a tests check (checks.tests)")
    q.add_argument("--drop-check", dest="drop_check", action="append", metavar="NAME", help="remove a check")
    q.add_argument("--contract", action="append", metavar="NAME@VERSION", help="bump a contract version (or add it)")
    q.add_argument("--by")
    q.set_defaults(func=cmd_task_set)
    q = tsp.add_parser("note", help="append a rule/note to an already handed-out task (executor sees it in task show and inbox)")
    q.add_argument("id"); q.add_argument("text"); q.add_argument("--by")
    q.set_defaults(func=cmd_task_note)

    msp = subgroup(sp, "module", "module: new (branch + copy + journal) | init (journal only)")
    q = msp.add_parser("init", help="create the module journal (module.json) in the current copy; task new does this itself")
    q.add_argument("module")
    q.add_argument("--plan"); q.add_argument("--contracts"); q.add_argument("--branch"); q.add_argument("--copy")
    q.add_argument("--code", help="module code for task IDs: 2–4 capital Latin letters (NN, UC), unique")
    q.add_argument("--legacy", metavar="PATH", help="link to the module's old journal (legacy_journal field in module.json)")
    q.add_argument("--area", help="module area (key of areas in config); for an existing module: set or change")
    q.set_defaults(func=cmd_module_init)
