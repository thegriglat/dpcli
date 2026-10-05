"""Определения агентов: frontmatter `<agents_dir>/*.md` (name, dpcli_role, dpcli_review, model, …).

dpcli_role: coordinator | executor | reviewer | status; dpcli_review: нужен ли ревьюер после PASS в accept.
Нет файлов — встроенные умолчания (DEFAULT_AGENTS).
"""
import sys

from . import config, yamlmini
from .util import DpError

ROLES = ("coordinator", "executor", "reviewer", "status")

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
        return v.strip().lower() in ("true", "yes", "1", "да")
    return bool(v)


def load_agents():
    """{имя: {role, review, model, description, file, …}}; кэш на процесс."""
    global _AGENTS
    if _AGENTS is not None:
        return _AGENTS
    out = {}
    d = agents_dir()
    files = sorted(d.glob("*.md")) if d and d.is_dir() else []
    for f in files:
        try:
            meta, _ = yamlmini.frontmatter(f.read_text(encoding="utf-8"))
        except (OSError, yamlmini.YamlError) as e:
            print(f"dpcli: {f}: frontmatter не разобран ({e}) — пропущен", file=sys.stderr)
            continue
        name = meta.get("name") or f.stem
        role = meta.get("dpcli_role")
        if role is not None and role not in ROLES:
            print(f"dpcli: {f}: dpcli_role «{role}» не из {', '.join(ROLES)}", file=sys.stderr)
        info = {k: v for k, v in meta.items() if k not in ("name", "dpcli_role", "dpcli_review")}
        info.update({"role": role, "review": _bool(meta.get("dpcli_review", False)), "file": str(f)})
        out[str(name)] = info
    if not out:
        out = {k: dict(v) for k, v in DEFAULT_AGENTS.items()}
    _AGENTS = out
    return out


def executor_types():
    return [n for n, a in load_agents().items() if a.get("role") == "executor"]


def needs_review(typ):
    a = load_agents().get(typ or "")
    return bool(a and a.get("review"))


def reviewer_name():
    return next((n for n, a in load_agents().items() if a.get("role") == "reviewer"), "ревьюер")
