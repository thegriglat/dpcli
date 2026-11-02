"""Re-exec from the main copy: if `.dpcli` in the main worktree is newer (VERSION), exec it with the same arguments."""
import os
import re
import sys
from pathlib import Path

from . import VERSION

PKG_DIR = Path(__file__).resolve().parent          # .dpcli/lib/dpcli
DIST_DIR = PKG_DIR.parent.parent                   # .dpcli


def entry():
    """Entry point of this copy (.dpcli/dpcli), for relaunching itself in the background."""
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
        print(f"dpcli: version {VERSION} is older than main's ({m[1]}); running from {main} (DPCLI_NO_REEXEC=1 disables)",
              file=sys.stderr)
        os.environ["DPCLI_REEXECED"] = "1"
        os.execv(sys.executable, [sys.executable, str(main)] + sys.argv[1:])
    except OSError:
        return
