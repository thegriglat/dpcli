"""Перезапуск из главной копии: если в главном worktree `.dpcli` новее (VERSION) — exec его с теми же аргументами."""
import os
import re
import sys
from pathlib import Path

from . import VERSION

PKG_DIR = Path(__file__).resolve().parent          # .dpcli/lib/dpcli
DIST_DIR = PKG_DIR.parent.parent                   # .dpcli


def entry():
    """Точка входа этой копии (.dpcli/dpcli) — для запуска себя в фоне."""
    return DIST_DIR / "dpcli"


def self_cmd():
    return [sys.executable, str(entry())]


def maybe_reexec():
    if os.environ.get("DPCLI_NO_REEXEC") or os.environ.get("DPCLI_REEXECED"):
        return
    try:
        from . import gitx
        mw = gitx.main_worktree()
        if not mw:
            return
        main = mw / ".dpcli" / "dpcli"
        init = mw / ".dpcli" / "lib" / "dpcli" / "__init__.py"
        if not main.is_file() or main.resolve() == entry().resolve() or not init.is_file():
            return
        m = re.search(r"^VERSION\s*=\s*(\d+)", init.read_text()[:6000], re.M)
        if not m or int(m[1]) <= VERSION:
            return
        print(f"dpcli: версия {VERSION} старее главной ({m[1]}) — запуск из {main} (DPCLI_NO_REEXEC=1 — отключить)",
              file=sys.stderr)
        os.environ["DPCLI_REEXECED"] = "1"
        os.execv(sys.executable, [sys.executable, str(main)] + sys.argv[1:])
    except OSError:
        return
