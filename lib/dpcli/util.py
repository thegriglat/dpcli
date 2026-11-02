"""Shared helpers: errors, argument parser, time, JSON/JSONL, short formatting."""
import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

CLI = ".dpcli/dpcli"  # how to invoke the tool from the copy root (in agent hints)


class DpError(Exception):
    pass


def die(msg, code=1):
    print(f"dpcli: {msg}", file=sys.stderr)
    sys.exit(code)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        die(f"{message} ({self.prog} -h)", 2)


def subgroup(sp, name, help):
    """Shared subcommand group (`module new` and `module init` register from different modules)."""
    p = sp.choices.get(name)
    if p is None:
        p = sp.add_parser(name, help=help)
        p._dpcli_sub = p.add_subparsers(dest="sub", required=True, parser_class=Parser)
    return p._dpcli_sub


def now():
    return dt.datetime.now().replace(microsecond=0).isoformat()


def read_json(p):
    try:
        return json.loads(Path(p).read_text())
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as e:
        raise DpError(f"{p}: invalid JSON ({e})")


def write_json(p, obj):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def append_jsonl(p, obj):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, ensure_ascii=False) + "\n"
    fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line.encode())
    finally:
        os.close(fd)


def read_jsonl(p):
    out = []
    try:
        for i, line in enumerate(Path(p).read_text().splitlines(), 1):
            if line.strip():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    print(f"dpcli: {p}:{i}: skipped invalid line", file=sys.stderr)
    except FileNotFoundError:
        pass
    return out


def pretty(p):
    return str(p).replace(str(Path.home()), "~")


def rel(p):
    from . import gitx
    try:
        return str(Path(p).relative_to(gitx.toplevel()))
    except (ValueError, DpError):
        return pretty(p)


def age(ts):
    try:
        s = (dt.datetime.now() - dt.datetime.fromisoformat(ts)).total_seconds()
    except (TypeError, ValueError):
        return "?"
    if s < 3600:
        return f"{int(s // 60)}m"
    if s < 86400:
        return f"{int(s // 3600)}h"
    return f"{int(s // 86400)}d"


def short(s, n):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def hm(t):
    return str(t)[5:16].replace("T", " ")


def session_line():
    v = os.environ.get("DPCLI_SESSION", "").strip()
    if not v:
        return ""
    return f"Claude-Session: {v if '://' in v else 'https://claude.ai/code/' + v}"


def _lang(kind):
    from . import config
    return str(config.get(f"language.{kind}", "en") or "en").lower()


def lang_text(en, ru):
    """Text dpcli writes into project files (plans, docs, journal summaries): language.text."""
    return ru if _lang("text") == "ru" else en


def lang_commit(en, ru):
    """Commit/merge message dpcli writes: language.commits."""
    return ru if _lang("commits") == "ru" else en
