"""Project config: dpcli.json | dpcli.yml | dpcli.yaml (searched upward from cwd to the git toplevel; json takes priority).

Defaults are in DEFAULTS; the file is deep-merged over them (null in the file = default value).
Path and branch templates: {module}, {task}, {project}, {copies}; `~` is expanded.
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
    "project": None,  # default — name of the main copy's directory
    "main_branch": "main",
    # true — dpcli merges into main_branch only with explicit --into and only a module created from it (usual path — MR)
    "protect_main": False,
    "module_branch": "feature/{module}",
    "task_branch": "{module}/{task}",
    "copies_dir": "~/worktrees",
    "module_copy": "{copies}/{project}/{module}",
    "task_copy": "{copies}/{project}/{module}-{task}",
    "plan_dir": "docs/plan",
    "contracts_dir": "docs/contracts",
    # monorepo areas a module belongs to (module new --area); empty — area unused
    "areas": [],
    "docs_dir": "docs",
    "checks": {
        "env": {},  # extra env vars for checks; {tmpdir} — a fresh temp dir
        "tests": None,  # command template for checks {tests: FILTER}; {filter} — the filter
        "log_dir": "build/dpcli",
        # test-run summary regexp: groups (?P<total>) and (?P<failed>), optionally (?P<skipped>);
        # None — built-in «N tests, M failed[, K skipped]» (Russian form also accepted); no match — judge by exit code
        "tests_summary": None,
        # accept runs in the background (job) when its checks took longer than this last time, s; 0 — never
        "bg_after": 100,
    },
    "artifacts_dir": "build/artifacts",
    "reserved_codes": [],
    "gc": {"ignore_dirs": ["build", "__pycache__"], "ignore_globs": []},
    "sem": {
        "enabled": False,  # semantic search (search --sem, index) — optional, needs Ollama
        "model": "bge-m3",
        "url": "http://localhost:11434",
        "cache_dir": "~/.cache/dpcli/{project}",
        "globs": ["docs/**/*.md", "CHANGELOG.md"],
    },
    "jobs": {"dir": "~/.cache/dpcli/{project}/jobs", "tmux_session": "dp", "cpu_slots": None},
    "locks": None,  # lock dir for lock cpu|gpu; default <jobs.dir>/locks
    # module delivery (deliver): what from <plan_dir>/<module>/ goes into the target branch; the journal goes under an archive tag
    "deliver": {"keep": ["decisions.md", "summary.md"], "archive_tag": "archive/{module}"},
    "agents_dir": ".dpcli/agents",
    # project's own agents (.claude/agents) in the dpcli process without editing their files: {name: {role, review}}
    "roles": {},
    "workflow": ".claude/dpcli-workflow.md",
    # language of text agents write for people (replies, reports, journal, plans, docs) and of commit messages
    "language": {"text": "en", "commits": "en"},
    # project layer: project rules, agent additions, own skills, friction ledger — committed with the project
    "local_dir": ".dpcli-local",
    # preparing new copies (module new, task new, copy setup) — see copies.py
    "worktree": {
        "hooks": True,  # also copy a relative core.hooksPath (e.g. .husky/_) from the main copy
        # git-ignored paths of the main copy: pattern without «/» — by name at any depth, with «/» — from the root
        "link": ["node_modules"],  # hard links (cp -al); on another FS — a copy
        "copy": [".env", ".env.*"],  # plain copy
        "setup": None,  # bash command in the new copy; env DPCLI_COPY, DPCLI_MAIN_COPY, DPCLI_BRANCH
        "setup_timeout": 1800,
    },
}

_CFG = None
_PATH = None


def merge(base, over):
    """Deep dict merge: over on top of base; None in over doesn't overwrite base's value."""
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
    """Config file path or None: from cwd upward to the git toplevel (outside git — cwd only)."""
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
        raise DpError(f"{p}: unparsed ({e})")
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise DpError(f"{p}: expected a key mapping")
    return data


def load():
    """Config (cached per process)."""
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
    """Value by dotted key: get('checks.tests')."""
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
    return Path(os.path.expanduser(subst(os.environ.get("DPCLI_COPIES") or get("copies_dir", "~/worktrees"), copies=None)))


def subst(tpl, **kw):
    """Substitute {module} {task} {project} {copies} (and passed kw); unknown {…} are left as is."""
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
    """Path template → Path with ~ expanded."""
    return Path(os.path.expanduser(subst(tpl, **kw)))


def repo_path(tpl, root=None, **kw):
    """Path from config: absolute (or ~) — as is, relative — from the copy root."""
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


def areas():
    """Allowed module areas from config (order = INDEX.md section order); [] — area unused."""
    v = get("areas") or []
    return [v] if isinstance(v, str) else [str(x) for x in v]


def branch_fields(tpl, br):
    """Branch template fields ({module}, {task}) by branch name, or None if it doesn't match."""
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
    """Module by module branch (module_branch template) or None."""
    f = branch_fields(get("module_branch"), br)
    return f.get("module") if f else None


def task_branch_fields(br):
    return branch_fields(get("task_branch"), br)
