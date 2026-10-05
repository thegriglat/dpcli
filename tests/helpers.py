"""Общая фикстура: временный git-проект с копией .dpcli и изолированным dpcli.json."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DIST = REPO / ".dpcli"
LIB = DIST / "lib"


def git(*args, cwd, check=True):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr}")
    return r.stdout.strip()


class Project:
    """Временный проект: <tmp>/proj (git, main), <tmp>/copies (worktree), <tmp>/cache."""

    def __init__(self, config=None, commit=True):
        self.tmp = Path(tempfile.mkdtemp(prefix="dpcli-test-")).resolve()
        self.root = self.tmp / "proj"
        self.root.mkdir()
        self.copies = self.tmp / "copies"
        self.copies.mkdir()
        self.cache = self.tmp / "cache"
        git("init", "-q", "-b", "main", cwd=self.root)
        git("config", "user.name", "Test", cwd=self.root)
        git("config", "user.email", "test@example.com", cwd=self.root)
        git("config", "commit.gpgsign", "false", cwd=self.root)
        shutil.copytree(DIST, self.root / ".dpcli", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        cfg = {
            "project": "proj",
            "copies_dir": str(self.copies),
            "jobs": {"dir": str(self.cache / "jobs"), "cpu_slots": 2},
            "locks": str(self.cache / "locks"),
            "sem": {"cache_dir": str(self.cache / "sem")},
        }
        if config:
            cfg = _deep(cfg, config)
        (self.root / "dpcli.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        (self.root / "README.md").write_text("# proj\n", encoding="utf-8")
        if commit:
            self.commit_all("init")

    def commit_all(self, msg, cwd=None):
        cwd = cwd or self.root
        git("add", "-A", cwd=cwd)
        git("commit", "-q", "-m", msg, cwd=cwd)

    @property
    def cli(self):
        return str(self.root / ".dpcli" / "dpcli")

    def env(self, extra=None):
        env = dict(os.environ)
        for k in list(env):
            if k.startswith("DPCLI_"):
                del env[k]
        env.update({"DPCLI_NO_REEXEC": "1", "DPCLI_NO_TMUX": "1", "HOME": str(self.tmp / "home"),
                    "TMPDIR": str(self.tmp), "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
                    "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com"})
        (self.tmp / "home").mkdir(exist_ok=True)
        env.update(extra or {})
        return env

    def run(self, *args, cwd=None, env=None, input=None, timeout=60):
        return run(self.cli, *args, cwd=cwd or self.root, env=self.env(env), input=input, timeout=timeout)

    def ok(self, *args, **kw):
        code, out, err = self.run(*args, **kw)
        if code:
            raise AssertionError(f"dpcli {' '.join(args)} -> {code}\n{out}\n{err}")
        return out

    def cleanup(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


def _deep(a, b):
    out = dict(a)
    for k, v in b.items():
        out[k] = _deep(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def run(cli, *args, cwd, env=None, input=None, timeout=60):
    """(code, stdout, stderr)."""
    env = dict(env if env is not None else os.environ)
    env.setdefault("DPCLI_NO_REEXEC", "1")
    r = subprocess.run([sys.executable, str(cli), *args], cwd=str(cwd), env=env, input=input,
                       capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr


class ProjectCase(unittest.TestCase):
    """Один проект на класс (setUpClass); для изоляции — свой Project в тесте."""
    CONFIG = None

    @classmethod
    def setUpClass(cls):
        cls.p = Project(cls.CONFIG)

    @classmethod
    def tearDownClass(cls):
        cls.p.cleanup()
