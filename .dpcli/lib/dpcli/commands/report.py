"""report (отчёт исполнителя) и review (вердикт ревьюера)."""
import difflib
import json
import sys
from pathlib import Path

from .. import config
from ..journal import SEVERITY, add_event, by_default, count_sev, find_task, rev_tag
from ..util import CLI, DpError, now, read_json, rel, short, write_json

REPORT_STATUS = {"done", "partial", "blocked", "failed"}
VERDICTS = ("accept", "rework")
MAX_ISSUES = 7


def report_template():
    return {
        "status": "done | partial | blocked | failed",
        "summary": "1–3 фразы: что сделано",
        "commits": ["abc1234 короткое описание"],
        "checks": [{"name": "имя проверки из карточки или своё", "value": "число/итог", "pass": True}],
        "not_done": ["что не вышло и почему"],
        "questions": ["открытый вопрос координатору"],
        "images": [f"{config.get('artifacts_dir', 'build/artifacts')}/<задача>/01_….png"],
        "how_to_check": f"команда или {CLI} accept <ID>",
        "uncertain": [{"where": "файл:строка", "why": "в чём не уверен", "checked": "что уже проверил"}],
        "dp_feedback": "чего не хватило в dpcli, что неудобно (можно пусто)",
        "extra": {"своё_число": "свободный объект для своих чисел/таблиц (можно опустить)"},
    }


def validate_report(r, card):
    errs = []
    if not isinstance(r, dict):
        return ["отчёт должен быть объектом JSON"]
    if r.get("status") not in REPORT_STATUS:
        errs.append(f"status ∈ {sorted(REPORT_STATUS)}")
    if not isinstance(r.get("summary"), str) or not r.get("summary"):
        errs.append("summary — непустая строка")
    for k in ("commits", "not_done", "questions", "images"):
        if k in r and not isinstance(r[k], list):
            errs.append(f"{k} — список")
    if r.get("status") == "done" and not r.get("commits"):
        errs.append("status=done без commits")
    for i, c in enumerate(r.get("checks", []) or []):
        if not isinstance(c, dict) or "name" not in c or "pass" not in c:
            errs.append(f"checks[{i}]: нужны name, value, pass")
    names = {c.get("name") for c in r.get("checks", []) or [] if isinstance(c, dict)}
    miss = [c["name"] for c in (card or {}).get("accept", []) if c.get("name") not in names]
    if miss and r.get("status") == "done":
        errs.append("нет результатов проверок: " + ", ".join(miss))
    if "extra" in r and not isinstance(r["extra"], dict):
        errs.append("extra — объект")
    want = [k for k in (card or {}).get("report_extra", []) or [] if isinstance(k, str)]
    for k in want:
        if k in r:
            continue
        alt = match_extra_key(k, [x for x in r if x not in want])
        if alt:  # регистр/единственный префикс — переименовать в ключ карточки
            r[k] = r.pop(alt)
            continue
        near = difflib.get_close_matches(k, [x for x in r if x not in want], n=1, cutoff=0.5)
        errs.append(f"нет поля «{k}» (report_extra)" + (f"; есть похожее «{near[0]}» — переименуйте" if near else "")
                    + ("" if len(want) < 2 else f"; ожидаются: {', '.join(want)}"))
    return errs


def match_extra_key(k, keys):
    """Ключ отчёта, подходящий под ключ карточки: без учёта регистра или единственный префикс (в любую сторону, от 3 знаков)."""
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
        if a.id:  # ключи report_extra карточки — полями верхнего уровня
            _, home = find_task(a.id)
            card = read_json(home / "tasks" / f"{a.id}.json") or {}
            for k in card.get("report_extra") or []:
                t[k] = "… (обязательное поле карточки)"
        print(json.dumps(t, ensure_ascii=False, indent=2))
        return
    if not a.id:
        raise DpError("нужен ID задачи")
    mod, home = find_task(a.id)
    card = read_json(home / "tasks" / f"{a.id}.json")
    p = home / "tasks" / f"{a.id}.report.json"
    if a.show:
        r = read_json(p)
        if not r:
            raise DpError(f"{a.id}: отчёта нет")
        if a.full:
            print(json.dumps(r, ensure_ascii=False, indent=2))
            return
        L = [f"{a.id} {r.get('status')}: {short(r.get('summary', ''), 300)}"]
        if r.get("commits"):
            L.append("коммиты: " + "; ".join(short(c, 60) for c in r["commits"]))
        for c in r.get("checks", []) or []:
            L.append(f"  {'PASS' if c.get('pass') else 'FAIL'} {c.get('name')} {short(c.get('value', ''), 80)}")
        for k, t in (("not_done", "не вышло"), ("questions", "вопрос")):
            L += [f"{t}: {short(x, 200)}" for x in r.get(k, []) or []]
        if r.get("images"):
            L.append(f"картинки: {len(r['images'])} ({rel(Path(r['images'][0]).parent)})")
        for u in r.get("uncertain", []) or []:
            if isinstance(u, dict):
                L.append(f"не уверен: {u.get('where', '')} — {short(u.get('why', ''), 120)}"
                         + (f" (проверил: {short(u.get('checked', ''), 80)})" if u.get("checked") else ""))
            else:
                L.append("не уверен: " + short(str(u), 200))
        if isinstance(r.get("extra"), dict) and r["extra"]:
            L.append("extra: " + short("; ".join(f"{k}={json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v}"
                                                 for k, v in r["extra"].items()), 300) + "  (--full — целиком)")
        if r.get("dp_feedback"):
            L.append("dpcli: " + short(r["dp_feedback"], 200))
        print("\n".join(L))
        return
    src = sys.stdin.read() if a.file in (None, "-") else Path(a.file).read_text()
    try:
        r = json.loads(src)
    except json.JSONDecodeError as e:
        raise DpError(f"отчёт: неверный JSON ({e}); схема — {CLI} report --template")
    errs = validate_report(r, card)
    if errs:
        raise DpError(f"{a.id}: отчёт не принят: " + "; ".join(errs))
    r["t"] = now()
    r["by"] = by_default(a)
    write_json(p, r)
    commits = [c.split()[0] for c in r.get("commits", []) if c]
    add_event(home, a.id, "reported", r["by"], note=f"{r['status']}: {short(r['summary'], 120)}", commits=commits,
              dp_feedback=r.get("dp_feedback", ""))
    print(f"{a.id}: отчёт {r['status']} → {rel(p)}")


REVIEW_TEMPLATE = {
    "verdict": "accept | rework",
    "summary": "1–3 строки: итог ревью",
    "issues": [{"file": "src/module/file.py", "line": 42, "severity": "blocker | major | minor",
                "what": "что не так (контракт, скоуп, подгонка под тест, баг, отчёт ≠ факт)",
                "fix": "что сделать"}],
    "rerun": [{"name": "проверка, перезапущенная ревьюером", "value": "число/итог", "pass": True}],
}


def validate_review(r):
    errs = []
    if not isinstance(r, dict):
        return ["ревью должно быть объектом JSON"]
    if r.get("verdict") not in VERDICTS:
        errs.append(f"verdict ∈ {list(VERDICTS)}")
    sm = r.get("summary")
    if not isinstance(sm, str) or not sm.strip():
        errs.append("summary — непустая строка")
    elif len(sm.strip().splitlines()) > 3:
        errs.append("summary — не больше 3 строк")
    iss = r.get("issues", [])
    if not isinstance(iss, list):
        errs.append("issues — список")
        iss = []
    if len(iss) > MAX_ISSUES:
        errs.append(f"issues — не больше {MAX_ISSUES} (мелочи и стиль — не замечания)")
    for n, i in enumerate(iss):
        if not isinstance(i, dict):
            errs.append(f"issues[{n}] — объект")
            continue
        miss = [k for k in ("file", "severity", "what", "fix") if not i.get(k)]
        if miss:
            errs.append(f"issues[{n}]: нет {', '.join(miss)}")
        if i.get("severity") and i["severity"] not in SEVERITY:
            errs.append(f"issues[{n}].severity ∈ {list(SEVERITY)}")
        if "line" in i and i["line"] not in (None, "") and not isinstance(i["line"], (int, str)):
            errs.append(f"issues[{n}].line — число или строка «12-30»")
    if r.get("verdict") == "accept" and any(isinstance(i, dict) and i.get("severity") == "blocker" for i in iss):
        errs.append("verdict=accept при blocker — противоречие")
    if "rerun" in r and not isinstance(r["rerun"], list):
        errs.append("rerun — список")
    return errs


def cmd_review(a):
    if a.template:
        print(json.dumps(REVIEW_TEMPLATE, ensure_ascii=False, indent=2))
        return
    if not a.id:
        raise DpError("нужен ID задачи")
    mod, home = find_task(a.id)
    p = home / "tasks" / f"{a.id}.review.json"
    if a.show:
        r = read_json(p)
        if not r:
            raise DpError(f"{a.id}: ревью нет")
        if a.full:
            print(json.dumps(r, ensure_ascii=False, indent=2))
            return
        L = [f"{a.id} {rev_tag({'verdict': r.get('verdict'), 'issues': count_sev(r)})} ({r.get('by', '-')}): "
             f"{short(r.get('summary', ''), 300)}"]
        for i in r.get("issues", []):
            ln = f":{i['line']}" if i.get("line") not in (None, "") else ""
            L.append(f"  [{i.get('severity')}] {i.get('file')}{ln} — {short(i.get('what', ''), 160)} → {short(i.get('fix', ''), 120)}")
        for c in r.get("rerun", []) or []:
            L.append(f"  перезапуск: {'PASS' if c.get('pass') else 'FAIL'} {c.get('name')} {short(c.get('value', ''), 60)}")
        print("\n".join(L))
        return
    if not a.verdict:
        raise DpError("нужен --verdict accept|rework (или --show / --template)")
    if a.from_:
        src = sys.stdin.read() if a.from_ == "-" else Path(a.from_).read_text()
        try:
            r = json.loads(src)
        except json.JSONDecodeError as e:
            raise DpError(f"ревью: неверный JSON ({e}); схема — {CLI} review --template")
        if not isinstance(r, dict):
            raise DpError("ревью должно быть объектом JSON")
        if r.get("verdict") and r["verdict"] != a.verdict:
            raise DpError(f"verdict в файле ({r['verdict']}) ≠ --verdict {a.verdict}")
        r["verdict"] = a.verdict
        if a.note and not r.get("summary"):
            r["summary"] = a.note
    else:
        if not a.note:
            raise DpError("нужен --from review.json или --note «итог»")
        r = {"verdict": a.verdict, "summary": a.note, "issues": []}
    r.setdefault("issues", [])
    errs = validate_review(r)
    if errs:
        raise DpError(f"{a.id}: ревью не принято: " + "; ".join(errs))
    r["t"] = now()
    r["by"] = by_default(a)
    write_json(p, r)
    cnt = count_sev(r)
    ev = add_event(home, a.id, "reviewed", r["by"], note=short(r["summary"], 160), verdict=a.verdict,
                   issues={k: v for k, v in cnt.items() if v}, review=f"{config.plan_dir()}/{mod}/tasks/{a.id}.review.json")
    print(f"{a.id}: {rev_tag(ev)} → {rel(p)}")


def register(sp):
    q = sp.add_parser("report", help=f"отчёт исполнителя: {CLI} report ID < r.json | --show | --template")
    q.add_argument("id", nargs="?"); q.add_argument("file", nargs="?")
    q.add_argument("--show", action="store_true"); q.add_argument("--template", action="store_true")
    q.add_argument("--full", action="store_true"); q.add_argument("--by")
    q.set_defaults(func=cmd_report)

    q = sp.add_parser("review", help="вердикт ревьюера: review ID --verdict accept|rework --from r.json | --note … | --show | --template")
    q.add_argument("id", nargs="?"); q.add_argument("--verdict", choices=VERDICTS)
    q.add_argument("--from", dest="from_", metavar="FILE", help="JSON ревью (review --template), - = stdin")
    q.add_argument("--note", help="короткое ревью без файла (замечаний нет) или summary к --from")
    q.add_argument("--show", action="store_true"); q.add_argument("--template", action="store_true")
    q.add_argument("--full", action="store_true"); q.add_argument("--by")
    q.set_defaults(func=cmd_review)
