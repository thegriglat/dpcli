"""task new|show|set|note|sync, module init."""
import json
import re
import sys
from pathlib import Path

from .. import agents, config, gitx
from ..journal import (ID_RE, add_event, addenda, all_modules, by_default, check_code, ensure_module, expect_arg,
                       find_task, module_home, module_meta, reserved_codes, task_cards)
from ..util import CLI, DpError, Parser, hm, now, pretty, read_json, read_jsonl, rel, short, subgroup, write_json

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
            raise DpError(f"у модуля {a.module} нет кода: {CLI} module init {a.module} --code XX (2–4 заглавные буквы), "
                          "либо задайте ID явно")
        stage = (a.stage or "").upper()
        if stage and not re.fullmatch(r"[A-Z]", stage):
            raise DpError(f"--stage «{a.stage}»: одна заглавная латинская буква")
        nums = [int(m[3]) for t in task_cards(home) if (m := ID_RE.match(t)) and m[1] == code and m[2] == stage]
        a.id = f"{code}-{stage}{max(nums, default=0) + 1}"
    else:
        m = ID_RE.match(a.id)
        if not m or m[1] in reserved_codes():
            raise DpError(f"ID «{a.id}»: формат <КОД>-[этап]<n>[буква], напр. NN-7, NN-7a, NN-P8 (код — 2–4 заглавные "
                          "латинские, не из reserved_codes); без ID — следующий номер")
        for mod, h in all_modules().items():
            if mod != a.module and (h / "tasks" / f"{a.id}.json").exists():
                raise DpError(f"ID {a.id} уже есть в модуле {mod}")
    p = home / "tasks" / f"{a.id}.json"
    if p.exists() and not a.force:
        raise DpError(f"карточка уже есть: {rel(p)} (--force — перезаписать)")
    card = json.loads(json.dumps(CARD_TEMPLATE))
    if a.from_:
        src = sys.stdin.read() if a.from_ == "-" else Path(a.from_).read_text()
        try:
            card.update(json.loads(src))
        except json.JSONDecodeError as e:
            raise DpError(f"--from: неверный JSON ({e})")
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
        card["contracts"].append({"name": name, "version": ver or "?", "ref": meta["contracts"]})
    card["scope"] += a.scope or []
    card["dont_touch"] += a.dont_touch or []
    for f in a.test or []:
        card["accept"].append({"name": f, "tests": f})
    for name, cmd, exp in a.check or []:
        card["accept"].append({"name": name, "cmd": cmd, "expect": expect_arg(exp)})
    types = agents.executor_types()
    if not card["type"]:
        raise DpError(f"нужен --type ({'|'.join(types) or 'нет агентов с dpcli_role: executor'})")
    if card["type"] not in types:
        raise DpError(f"--type «{card['type']}»: не исполнитель (есть: {', '.join(types) or 'нет'}; "
                      f"агенты — {config.get('agents_dir')}/*.md, dpcli_role: executor)")
    ensure_module(a.module, home)
    card["created"] = card.get("created") or now()
    write_json(p, card)
    add_event(home, a.id, "created", by_default(a), note=card.get("title", ""))
    empty = [k for k in ("goal", "scope", "accept") if not card.get(k)]
    print(f"{a.id}: {rel(p)}" + (f"; пусто: {', '.join(empty)}" if empty else ""))


def fmt_check(c):
    if c.get("tests"):
        return f"{c['name']}: тесты «{c['tests']}» (checks.tests) → 0 упало"
    exp = c.get("expect", "exit=0")
    return f"{c['name']}: `{c.get('cmd', '')}` → {json.dumps(exp, ensure_ascii=False) if isinstance(exp, dict) else exp}"


def _set_value(raw):
    """Значение поля: JSON, если разбирается (числа, списки, объекты, true/false), иначе строка."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def cmd_task_set(a):
    """Правка карточки без переписывания JSON: поле=значение, поле+=элемент, поле-=элемент, проверки приёмки."""
    mod, home = find_task(a.id)
    p = home / "tasks" / f"{a.id}.json"
    card = read_json(p)
    before = json.loads(json.dumps(card))
    changed = []
    for op in a.ops or []:
        m = re.match(r"^([A-Za-z_][\w]*)(\+=|-=|=)(.*)$", op, re.S)
        if not m:
            raise DpError(f"«{op}»: ожидалось поле=значение | поле+=элемент | поле-=элемент")
        key, kind, raw = m.groups()
        if key == "id":
            raise DpError("id не меняется")
        val = _set_value(raw)
        if kind == "=":
            if isinstance(val, str) and (isinstance(card.get(key), list) or isinstance(CARD_TEMPLATE.get(key), list)):
                val = [x.strip() for x in val.split(",") if x.strip()]  # report_extra=a,b → ["a", "b"], а не по символам
            if key == "type" and val not in agents.executor_types():
                raise DpError(f"type «{val}»: не исполнитель (есть: {', '.join(agents.executor_types()) or 'нет'})")
            card[key] = val
        else:
            lst = card.get(key)
            if lst is None:
                lst = []
            if not isinstance(lst, list):
                raise DpError(f"{key} — не список, «{kind}» неприменимо")
            if kind == "+=":
                lst.append(val)
            else:
                keep = [x for x in lst if not (x == val or (isinstance(x, dict) and x.get("name") == val))]
                if len(keep) == len(lst):
                    raise DpError(f"{key}: «{raw}» не найдено")
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
            cs.append({"name": name, "version": ver or "?", "ref": module_meta(mod, home)["contracts"]})
        changed.append(f"contract:{name}")
    acc = card.setdefault("accept", [])
    # сначала снять, потом добавить: --drop-check X --check X … заменяет проверку
    for name in a.drop_check or []:
        n0 = len(acc)
        acc[:] = [c for c in acc if c.get("name") != name]
        if len(acc) == n0:
            raise DpError(f"проверки «{name}» нет в карточке")
        changed.append(f"accept:-{name}")
    for name, cmd, exp in a.check or []:
        acc[:] = [c for c in acc if c.get("name") != name] + [{"name": name, "cmd": cmd, "expect": expect_arg(exp)}]
        changed.append(f"accept:{name}")
    for f in a.test or []:
        acc[:] = [c for c in acc if c.get("name") != f] + [{"name": f, "tests": f}]
        changed.append(f"accept:{f}")
    if not changed:
        raise DpError("нечего менять: поле=значение, --check, --test, --drop-check, --contract")
    card["edited"] = now()
    write_json(p, card)
    diff = {k: [short(json.dumps(before.get(k), ensure_ascii=False), 300), short(json.dumps(card.get(k), ensure_ascii=False), 300)]
            for k in dict.fromkeys(c.split(":")[0] for c in changed)}
    add_event(home, a.id, "edited", by_default(a), note=", ".join(changed), diff=diff)
    print(f"{a.id}: изменено — {', '.join(changed)}")


def cmd_task_note(a):
    """Дописать правило/заметку в задачу, уже выданную исполнителю: видно в task show и inbox <ID>."""
    mod, home = find_task(a.id)
    if not a.text.strip():
        raise DpError("пустой текст")
    add_event(home, a.id, "note", by_default(a), note=a.text, addendum=True)
    print(f"{a.id}: дополнение записано → исполнителю: {CLI} inbox {a.id} (и {CLI} task show {a.id})")


def cmd_task_show(a):
    mod, home = find_task(a.id)
    card = read_json(home / "tasks" / f"{a.id}.json")
    if a.json:
        print(json.dumps(card, ensure_ascii=False, indent=2))
        return
    if a.diff:
        evs = [e for e in read_jsonl(home / "events.jsonl") if e.get("task") == a.id and e.get("ev") == "edited"]
        if not evs:
            print(f"{a.id}: карточка не менялась после создания")
        for e in evs:
            print(f"{hm(e['t'])} ({e.get('by', '-')}) {e.get('note', '')}")
            for k, (old, new) in (e.get("diff") or {}).items():
                print(f"    {k}: {old} → {new}")
        return
    meta = module_meta(mod, home)
    full = a.full
    L = [f"{card['id']} [{mod}] {card.get('title', '')} — {card.get('type', '')}"]
    if card.get("goal"):
        L.append(f"Цель: {card['goal']}")
    plan = meta["plan"] + (f" {card['plan_ref']}" if card.get("plan_ref") else "")
    L.append(f"План: {plan} ({CLI} plan {mod} <раздел>)")
    L.append(f"Копия: {card.get('copy')}  ветка: {card.get('branch')} от {card.get('base')}")
    if card.get("contracts"):
        L.append("Контракты: " + "; ".join(f"{c['name']} v{c.get('version', '?')} ({c.get('ref', '')})" for c in card["contracts"]))
    for key, title in (("scope", "Скоуп"), ("dont_touch", "Не трогать")):
        items = card.get(key) or []
        if items and (full or len(items) > 3):
            L += [f"{title}:"] + [f"  - {x}" for x in items]
        elif items:
            L.append(f"{title}: " + "; ".join(items))
    if card.get("accept"):
        L.append(f"Приёмка ({CLI} accept {card['id']}; пробный прогон до отчёта — {CLI} accept {card['id']} --dry):")
        L += [f"  - {fmt_check(c)}" for c in card["accept"]]
    if card.get("notes"):
        L.append(f"Заметки: {card['notes']}")
    adds = addenda(home, a.id)
    if adds:
        L.append(f"Дополнения после выдачи ({len(adds)}):")
        L += [f"  ! {hm(e['t'])} ({e.get('by', '-')}): {e['note'] if full else short(e['note'], 300)}"
              for e in adds[-(len(adds) if full else 5):]]
    nedit = sum(1 for e in read_jsonl(home / "events.jsonl") if e.get("task") == a.id and e.get("ev") == "edited")
    if nedit:
        L.append(f"Карточка правилась {nedit} раз ({CLI} task show {a.id} --diff)")
    L.append(f"Правила: {config.get('workflow')}, «Общие правила» (читать обязательно).")
    L.append(f"Свежая работа соседей (ветка {card.get('base') or 'модуля'} → ваша): {CLI} task sync {card['id']}.")
    L.append(f"Долгие запуски — `{CLI} job start <имя> <таймаут_с> <команда…>`, ожидание — `{CLI} job wait <имя> <таймаут_с>` "
             "в фоне (run_in_background), не циклы `until grep`.")
    rx = ", ".join(f"«{k}»" for k in card.get("report_extra") or [])
    L.append(f"Отчёт: {CLI} report {card['id']} < отчёт.json (схема с полями карточки — {CLI} report --template {card['id']})"
             f"{'; обязательные поля верхнего уровня отчёта: ' + rx if rx else ''}; в конце — обратная связь по dpcli "
             "(поле dp_feedback).")
    if full:
        L.append("Копия задачи — своя; чужие не трогать; контракты менять только через координатора; коммиты — только свои файлы "
                 "(git commit -- <пути>), по-русски, со строкой Claude-Session. Свежая работа соседей — git merge ветки модуля "
                 f"в свою ({CLI} task sync {card['id']}).")
        L.append(f"Журнал и карточка: {config.plan_dir()}/{mod}/ ({CLI} log {card['id']}, {CLI} task show {card['id']} --diff).")
    print("\n".join(L))


def cmd_task_sync(a):
    mod, home = find_task(a.id)
    card = read_json(home / "tasks" / f"{a.id}.json")
    br, base = card.get("branch"), card.get("base") or config.module_branch(mod)
    path = gitx.copy_of(br) if br else None
    if not path:
        raise DpError(f"у ветки задачи {br} нет рабочей копии")
    h, n, kind = gitx.do_merge(path, base, a.message or f"Слияние {base} в {br}", trailers=a.trailer)
    print(f"{br}: {base} уже влит" if kind == "up-to-date" else f"{br}: влит {base}, {h}, файлов {n}")


def cmd_module_init(a):
    home = module_home(a.module)
    ensure_module(a.module, home, plan=a.plan, contracts=a.contracts, branch=a.branch, copy=a.copy, code=a.code)
    if a.legacy or a.code:
        mp = home / "module.json"
        m = read_json(mp) or {}
        if a.legacy:
            m["legacy_journal"] = a.legacy
        if a.code:
            check_code(a.code, a.module)
            m["code"] = a.code
        write_json(mp, m)
    print(f"{a.module}: {rel(home)}")


def register(sp):
    t = sp.add_parser("task", help="карточка задачи: new | show | set | note | sync (sync — влить ветку модуля в ветку задачи)")
    tsp = t.add_subparsers(dest="sub", required=True, parser_class=Parser, metavar="new|show|set|note|sync")
    q = tsp.add_parser("new", help="создать карточку")
    q.add_argument("module"); q.add_argument("id", nargs="?", help="<КОД>-[этап]<n>[буква]; без ID — следующий номер модуля")
    q.add_argument("--stage", metavar="БУКВА", help="этап для авто-номера: --stage P → следующий <КОД>-P<n>")
    q.add_argument("--type", help="тип исполнителя: агент с dpcli_role: executor (напр. dp-engineer)")
    q.add_argument("--title"); q.add_argument("--goal"); q.add_argument("--plan-ref", dest="plan_ref", help="раздел плана, напр. §UC-3")
    q.add_argument("--copy"); q.add_argument("--branch")
    q.add_argument("--from", dest="from_", metavar="FILE", help="JSON-карточка (поля поверх шаблона), - = stdin")
    q.add_argument("--contract", action="append", metavar="ИМЯ@ВЕРСИЯ")
    q.add_argument("--scope", action="append", metavar="ПУТЬ"); q.add_argument("--dont-touch", dest="dont_touch", action="append", metavar="ПУТЬ")
    q.add_argument("--test", action="append", metavar="ФИЛЬТР", help="проверка: тесты проекта (checks.tests, {filter}=ФИЛЬТР), 0 упало")
    q.add_argument("--check", action="append", nargs=3, metavar=("ИМЯ", "CMD", "EXPECT"),
                   help="EXPECT: exit=N | re:<regex> | !re:<regex> | num:<regex с группой> <op>N | tests")
    q.add_argument("--force", action="store_true"); q.add_argument("--by")
    q.set_defaults(func=cmd_task_new)
    q = tsp.add_parser("show", help="карточка для исполнителя (коротко)")
    q.add_argument("id"); q.add_argument("--json", action="store_true")
    q.add_argument("--full", action="store_true", help="полное задание исполнителю: карточка + правила + заметки, пункты по строке")
    q.add_argument("--diff", action="store_true", help="как менялась карточка (события edited)")
    q.set_defaults(func=cmd_task_show)
    q = tsp.add_parser("sync", help="влить ветку модуля (base из карточки) в ветку задачи в её копии")
    q.add_argument("id"); q.add_argument("--message"); q.add_argument("--trailer", action="append")
    q.set_defaults(func=cmd_task_sync)
    q = tsp.add_parser("set", help="правка карточки: поле=значение | поле+=элемент | поле-=элемент (JSON или строка)")
    q.add_argument("id"); q.add_argument("ops", nargs="*", metavar="ПОЛЕ=ЗНАЧ")
    q.add_argument("--check", action="append", nargs=3, metavar=("ИМЯ", "CMD", "EXPECT"), help="добавить/заменить проверку")
    q.add_argument("--test", action="append", metavar="ФИЛЬТР", help="добавить/заменить проверку тестами (checks.tests)")
    q.add_argument("--drop-check", dest="drop_check", action="append", metavar="ИМЯ", help="убрать проверку")
    q.add_argument("--contract", action="append", metavar="ИМЯ@ВЕРСИЯ", help="поднять версию контракта (или добавить)")
    q.add_argument("--by")
    q.set_defaults(func=cmd_task_set)
    q = tsp.add_parser("note", help="дописать правило/заметку в уже выданную задачу (исполнитель увидит в task show и inbox)")
    q.add_argument("id"); q.add_argument("text"); q.add_argument("--by")
    q.set_defaults(func=cmd_task_note)

    msp = subgroup(sp, "module", "модуль: new (ветка + копия + журнал) | init (только журнал)")
    q = msp.add_parser("init", help="завести журнал модуля (module.json) в текущей копии; task new делает это сам")
    q.add_argument("module")
    q.add_argument("--plan"); q.add_argument("--contracts"); q.add_argument("--branch"); q.add_argument("--copy")
    q.add_argument("--code", help="код модуля для ID задач: 2–4 заглавные латинские (NN, UC), уникален")
    q.add_argument("--legacy", metavar="ПУТЬ", help="ссылка на старый журнал модуля (поле legacy_journal в module.json)")
    q.set_defaults(func=cmd_module_init)
