"""dpcli agent registry: roles (coordinator | executor | reviewer | status) and whether a reviewer is needed after PASS.

Sources (each next one overrides the previous):
  1. dpcli   — `<agents_dir>/*.md` (frontmatter: name, dpcli_role, dpcli_review, model, …);
  2. project — `.claude/agents/*.md` not created by `dpcli init` (not in the manifest): with dpcli_role — that role;
               without dpcli_role — no role (a project agent with the same name as a dpcli agent overrides it);
  3. config  — key `roles: {name: {role, review}}` (plug in your own agents without editing their files).
No agent with a role at all: built-in defaults (DEFAULT_AGENTS).
"""
import json
import sys

from . import config, yamlmini
from .util import DpError

ROLES = ("coordinator", "executor", "reviewer", "status")
MANIFEST = ".claude/.dpcli-manifest.json"

DEFAULT_AGENTS = {
    "dp-coordinator": {"role": "coordinator", "review": False},
    "dp-engineer": {"role": "executor", "review": True},
    "dp-researcher": {"role": "executor", "review": True},
    "dp-writer": {"role": "executor", "review": False},
    "dp-mechanic": {"role": "executor", "review": False},
    "dp-reviewer": {"role": "reviewer", "review": False},
    "dp-status": {"role": "status", "review": False},
}

_AGENTS = None


def agents_dir():
    try:
        return config.repo_path(config.get("agents_dir", ".dpcli/agents"))
    except DpError:
        return None


def _bool(v):
    if isinstance(v, str):
        return v.strip().lower() in ("true", "yes", "1", "да")  # "да" = Russian "yes" (user-written frontmatter)
    return bool(v)


def _warn(msg):
    print(f"dpcli: {msg}", file=sys.stderr)


def _read(f):
    try:
        meta, _ = yamlmini.frontmatter(f.read_text(encoding="utf-8"))
    except (OSError, yamlmini.YamlError) as e:
        _warn(f"{f}: frontmatter parse error ({e}); skipped")
        return None
    return meta or {}


def _entry(meta, f, source):
    role = meta.get("dpcli_role")
    if role is not None and role not in ROLES:
        _warn(f"{f}: dpcli_role \"{role}\" not in {', '.join(ROLES)}")
    info = {k: v for k, v in meta.items() if k not in ("name", "dpcli_role", "dpcli_review")}
    info.update({"role": role, "review": _bool(meta.get("dpcli_review", False)), "file": str(f), "source": source})
    return info


def _project_files():
    """.claude/agents/*.md not in the init manifest (i.e. project files)."""
    try:
        root = config.repo_path(".")
    except DpError:
        return []
    d = root / ".claude" / "agents"
    if not d.is_dir():
        return []
    try:
        man = json.loads((root / MANIFEST).read_text()).get("files", {})
    except (OSError, ValueError, AttributeError):
        man = {}
    return [f for f in sorted(d.glob("*.md")) if f".claude/agents/{f.name}" not in man]


def load_agents():
    """{name: {role, review, model, description, file, source, …}}; cached per process."""
    global _AGENTS
    if _AGENTS is not None:
        return _AGENTS
    out = {}
    d = agents_dir()
    for f in sorted(d.glob("*.md")) if d and d.is_dir() else []:
        meta = _read(f)
        if meta is not None:
            out[str(meta.get("name") or f.stem)] = _entry(meta, f, "dpcli")
    for f in _project_files():
        meta = _read(f)
        if meta is None:
            continue
        out[str(meta.get("name") or f.stem)] = _entry(meta, f, "project")
    roles = config.get("roles") or {}
    if not isinstance(roles, dict):
        _warn("roles in config: expected a mapping agent_name → {role, review}")
        roles = {}
    for name, v in roles.items():
        if isinstance(v, str):
            v = {"role": v}
        if not isinstance(v, dict):
            _warn(f"roles.{name}: expected {{role, review}}")
            continue
        role = v.get("role")
        if role not in ROLES:
            _warn(f"roles.{name}: role \"{role}\" not in {', '.join(ROLES)}")
        e = out.setdefault(str(name), {"file": ""})
        e.update({"role": role, "source": "config"})
        if "review" in v:
            e["review"] = _bool(v["review"])
        e.setdefault("review", False)
    if not any(a.get("role") for a in out.values()):
        out.update({k: dict(v, source="default") for k, v in DEFAULT_AGENTS.items()})
    _AGENTS = out
    return out


def executor_types():
    return [n for n, a in load_agents().items() if a.get("role") == "executor"]


def needs_review(typ):
    a = load_agents().get(typ or "")
    return bool(a and a.get("review"))


def reviewer_name():
    return next((n for n, a in load_agents().items() if a.get("role") == "reviewer"), "reviewer")
