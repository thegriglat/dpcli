"""Конфиг проекта: dpcli.json | dpcli.yml | dpcli.yaml (ищется вверх от cwd до toplevel git; json приоритетнее).

Значения по умолчанию — DEFAULTS; файл накладывается глубоким слиянием (null в файле = значение по умолчанию).
Шаблоны путей и веток: {module}, {task}, {project}, {copies}; `~` раскрывается.
"""
import copy
import json
import os
import re
from pathlib import Path

from . import yamlmini
from .util import DpError

NAMES = ("dpcli.json", "dpcli.yml", "dpcli.yaml")

DEFAULTS = {
    "project": None,  # по умолчанию — имя каталога главной рабочей копии
    "main_branch": "main",
    "module_branch": "feature/{module}",
    "task_branch": "{module}/{task}",
    "copies_dir": "~",
    "module_copy": "{copies}/{project}-{module}",
    "task_copy": "{copies}/{project}-{module}-{task}",
    "plan_dir": "docs/plan",
    "contracts_dir": "docs/contracts",
    "docs_dir": "docs",
    "checks": {
        "env": {},  # доп. переменные окружения проверок; {tmpdir} — свежий временный каталог
        "tests": None,  # шаблон команды для проверок {tests: ФИЛЬТР}; {filter} — фильтр
        "log_dir": "build/dpcli",
    },
    "artifacts_dir": "build/artifacts",
    "reserved_codes": [],
    "gc": {"ignore_dirs": ["build", "__pycache__"], "ignore_globs": []},
    "sem": {
        "model": "bge-m3",
        "url": "http://localhost:11434",
        "cache_dir": "~/.cache/dpcli/{project}",
        "globs": ["docs/**/*.md", "CHANGELOG.md"],
    },
    "jobs": {"dir": "~/.cache/dpcli/{project}/jobs", "tmux_session": "dp", "cpu_slots": None},
    "locks": None,  # каталог замков lock cpu|gpu; по умолчанию <jobs.dir>/locks
    "agents_dir": ".dpcli/agents",
    "workflow": ".claude/dpcli-workflow.md",
}

_CFG = None
_PATH = None


def merge(base, over):
    """Глубокое слияние словарей: over поверх base; None в over не затирает значение base."""
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if v is None and k in out:
            continue
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def find_file():
    """Путь к файлу конфига или None: от cwd вверх до toplevel git (вне git — только cwd)."""
    from . import gitx
    cwd = Path.cwd().resolve()
    top = gitx.git("rev-parse", "--show-toplevel")
    stop = Path(top).resolve() if top else cwd
    dirs, d = [], cwd
    while True:
        dirs.append(d)
        if d == stop or d.parent == d:
            break
        d = d.parent
    if stop not in dirs:
        dirs.append(stop)
    for d in dirs:
        for n in NAMES:
            if (d / n).is_file():
                return d / n
    return None


def parse_file(p):
    text = Path(p).read_text(encoding="utf-8")
    try:
        data = json.loads(text) if p.name.endswith(".json") else yamlmini.loads(text)
    except (json.JSONDecodeError, yamlmini.YamlError) as e:
        raise DpError(f"{p}: не разобран ({e})")
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise DpError(f"{p}: ожидался словарь ключей")
    return data


def load():
    """Конфиг (кэш на процесс)."""
    global _CFG, _PATH
    if _CFG is None:
        _PATH = find_file()
        _CFG = merge(DEFAULTS, parse_file(_PATH) if _PATH else {})
    return _CFG


def path_of_config():
    load()
    return _PATH


def reset():
    global _CFG, _PATH, _PROJECT
    _CFG = _PATH = _PROJECT = None


def get(key, default=None):
    """Значение по ключу с точками: get('checks.tests')."""
    v = load()
    for part in key.split("."):
        if not isinstance(v, dict) or part not in v:
            return default
        v = v[part]
    return default if v is None else v


_PROJECT = None


def project():
    global _PROJECT
    if _PROJECT is None:
        from . import gitx
        p = get("project")
        if not p:
            mw = gitx.main_worktree()
            p = mw.name if mw else Path.cwd().name
        _PROJECT = str(p)
    return _PROJECT


def copies_dir():
    return Path(os.path.expanduser(subst(os.environ.get("DPCLI_COPIES") or get("copies_dir", "~"), copies=None)))


def subst(tpl, **kw):
    """Подставить {module} {task} {project} {copies} (и переданные kw); неизвестные {…} остаются как есть."""
    tpl = str(tpl)
    vals = dict(kw)
    if "{project}" in tpl and "project" not in vals:
        vals["project"] = project()
    if "{copies}" in tpl and vals.get("copies", 0) is not None and "copies" not in vals:
        vals["copies"] = str(copies_dir())

    def rep(m):
        k = m[1]
        return str(vals[k]) if vals.get(k) is not None else m[0]
    return re.sub(r"\{(\w+)\}", rep, tpl)


def expand(tpl, **kw):
    """Шаблон пути → Path с раскрытым ~."""
    return Path(os.path.expanduser(subst(tpl, **kw)))


def repo_path(tpl, root=None, **kw):
    """Путь из конфига: абсолютный (или ~) — как есть, относительный — от корня рабочей копии."""
    from . import gitx
    p = expand(tpl, **kw)
    return p if p.is_absolute() else Path(root or gitx.toplevel()) / p


def main_branch():
    return get("main_branch", "main")


def module_branch(mod):
    return subst(get("module_branch"), module=mod)


def task_branch(mod, task):
    return subst(get("task_branch"), module=mod, task=task)


def module_copy(mod):
    return expand(get("module_copy"), module=mod)


def task_copy(mod, task):
    return expand(get("task_copy"), module=mod, task=task)


def plan_dir():
    return str(get("plan_dir")).rstrip("/")


def contracts_dir():
    return str(get("contracts_dir")).rstrip("/")


def docs_dir():
    return str(get("docs_dir")).rstrip("/")


def branch_fields(tpl, br):
    """Поля шаблона ветки ({module}, {task}) по имени ветки или None, если не подходит."""
    rx, pos = "", 0
    for m in re.finditer(r"\{(\w+)\}", tpl):
        rx += re.escape(tpl[pos:m.start()])
        k = m[1]
        if k == "project":
            rx += re.escape(project())
        elif k in ("module", "task"):
            rx += f"(?P<{k}>[^/]+)" if f"(?P<{k}>" not in rx else f"(?P={k})"
        else:
            rx += ".+?"
        pos = m.end()
    rx += re.escape(tpl[pos:])
    m = re.fullmatch(rx, br or "")
    return m.groupdict() if m else None


def module_of_branch(br):
    """Модуль по ветке модуля (шаблон module_branch) или None."""
    f = branch_fields(get("module_branch"), br)
    return f.get("module") if f else None


def task_branch_fields(br):
    return branch_fields(get("task_branch"), br)
