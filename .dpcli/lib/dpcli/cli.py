"""Разбор аргументов и запуск команд. build() собирает парсер из register(sp) модулей commands/*."""
import argparse
import importlib
import sys

from . import VERSION
from .reexec import maybe_reexec
from .util import CLI, DpError, Parser, die

COMMANDS = ["task", "journal_cmds", "accept", "report", "status", "plan", "branches", "search", "jobs"]
OPTIONAL = ["init", "docs"]  # появляются отдельно; нет модуля — команды нет


def build():
    p = Parser(prog="dpcli", description="Журнал, карточки задач и приёмка модулей. Влить ветку модуля в ветку задачи — "
                                         f"{CLI} task sync <ID>.",
               formatter_class=argparse.RawDescriptionHelpFormatter,
               epilog="Автор событий: --by или $DPCLI_ROLE. Конфиг: dpcli.json | dpcli.yml в корне проекта. "
                      "Коды: 0 ок, 1 ошибка/FAIL, 2 аргументы.")
    p.add_argument("--version", action="version", version=f"dpcli {VERSION}")
    sp = p.add_subparsers(dest="cmd", required=True, parser_class=Parser, metavar="команда")
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
    """job start --tmux … <имя> <таймаут> <команда…>: опции между действием и командой (REMAINDER их не разбирает) — в начало."""
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
