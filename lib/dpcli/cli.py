"""Argument parsing and command dispatch. build() assembles the parser from register(sp) of commands/* modules."""
import argparse
import importlib
import sys

from . import VERSION
from .reexec import maybe_reexec
from .util import CLI, DpError, Parser, die

COMMANDS = ["task", "roles", "journal_cmds", "accept", "report", "status", "plan", "branches", "deliver", "search", "jobs", "feedback", "contribute", "update"]
OPTIONAL = ["init", "docs"]  # optional; no module, no command


def build():
    p = Parser(prog="dpcli", description="Journal, task cards and module acceptance. To merge the module branch into a task branch: "
                                         f"{CLI} task sync <ID>.",
               formatter_class=argparse.RawDescriptionHelpFormatter,
               epilog="Event author: --by or $DPCLI_ROLE. Config: dpcli.json | dpcli.yml in the project root. "
                      "Exit codes: 0 ok, 1 error/FAIL, 2 arguments.")
    p.add_argument("--version", action="version", version=f"dpcli {VERSION}")
    sp = p.add_subparsers(dest="cmd", required=True, parser_class=Parser, metavar="command")
    for name in COMMANDS + OPTIONAL:
        try:
            mod = importlib.import_module(f".commands.{name}", __package__)
        except ModuleNotFoundError as e:
            if name in OPTIONAL and e.name == f"{__package__}.commands.{name}":
                continue
            raise
        mod.register(sp)
    return p


def hoist_job_opts(argv):
    """job start --tmux … <name> <timeout> <command…>: options between the action and the command (REMAINDER does not parse them) are moved to the front."""
    if argv[:1] != ["job"]:
        return argv
    rest, hoisted, pos, i = argv[1:], [], 0, 0
    keep = []
    while i < len(rest) and pos < 3:
        t = rest[i]
        if t in ("--tmux", "--no-tmux", "--all"):
            hoisted.append(t)
        elif t in ("--tmux-session", "--lock") and i + 1 < len(rest):
            hoisted += [t, rest[i + 1]]
            i += 1
        else:
            keep.append(t)
            pos += not t.startswith("--")
        i += 1
    while i < len(rest) and rest[i] in ("--tmux", "--no-tmux", "--all", "--tmux-session", "--lock"):  # options after <timeout>
        n = 2 if rest[i] in ("--tmux-session", "--lock") and i + 1 < len(rest) else 1
        hoisted += rest[i:i + n]
        i += n
    return ["job", *hoisted, *keep, *rest[i:]]


def main(argv=None):
    maybe_reexec()
    argv = sys.argv[1:] if argv is None else argv
    try:
        a = build().parse_args(hoist_job_opts(argv))
        fn = getattr(a, "func", None) or getattr(a, "fn", None)
        rc = fn(a)
    except DpError as e:
        die(str(e))
    except BrokenPipeError:
        rc = 0
    if isinstance(rc, int) and rc:
        sys.exit(rc)
