"""job (долгие запуски без опроса по имени процесса, окно tmux) и lock (общие замки: gpu — один держатель, cpu — N слотов)."""
import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .. import config, reexec
from ..util import CLI, DpError, age, now


def job_dir():
    env = os.environ.get("DPCLI_JOB_DIR")
    d = Path(os.path.expanduser(env)) if env else config.expand(config.get("jobs.dir", "~/.cache/dpcli/{project}/jobs"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def job_files(name):
    d = job_dir()
    return d / f"{name}.pid", d / f"{name}.log", d / f"{name}.rc"


def job_start(name, limit, cmd, tm=None):
    """tm — сессия tmux (tmux_opts) или None; нет tmux/сессии → фон с предупреждением `dpcli: …`."""
    pidf, log, rcf = job_files(name)
    rcf.unlink(missing_ok=True)
    d = job_dir()
    if tm and tmux_job(name, limit, cmd, tm):
        return
    # setsid — своя группа: при таймауте гасится всё дерево; rc пишется всегда (124 — таймаут)
    pr = subprocess.Popen(["setsid", "bash", "-c", 'timeout -k 30 "$1" "${@:3}" >"$2.log" 2>&1; echo $? >"$2.rc"', "_", str(limit),
                           str(d / name), *cmd],
                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=False,
                          env={**os.environ, "DPCLI_NO_TMUX": "1"})
    pidf.write_text(str(pr.pid))
    print(f"{name}: PID {pr.pid}, лог {log}")


# окно tmux = outer (bash; по завершении окно закрывается) → runner (PID в .pid, код в .rc) → script (настоящий tty; лог без \r-перерисовок)
TMUX_RUNNER = r"""#!/bin/bash
# dpcli job: runner <таймаут> <база> <команда…>; PID — этого процесса, код — в <база>.rc
limit=$1; base=$2; shift 2
echo $$ >"$base.pid"
rm -f "$base.rc" "$base.cpid" "$base.fifo"
printf -v c '%q ' "$@"
c="echo \$\$ >$(printf %q "$base.cpid"); exec timeout -k 30 $limit $c"
mkfifo "$base.fifo"
awk '/^Script (started|done) on /{next} {n=split($0,a,"\r"); s=a[n]; if(s==""&&n>1)s=a[n-1]; print s; fflush()}' <"$base.fifo" >"$base.log" &
ap=$!
sig=0
script -qefc "$c" "$base.fifo" <&0 &
sp=$!
fw() { sig=$1; [ -s "$base.cpid" ] && kill -TERM "$(cat "$base.cpid")" 2>/dev/null; kill -TERM $sp 2>/dev/null; }
trap 'fw 143' TERM
trap 'fw 129' HUP
while :; do wait $sp; rc=$?; kill -0 $sp 2>/dev/null || break; done
wait $ap 2>/dev/null
rm -f "$base.fifo" "$base.cpid"
[ "$sig" != 0 ] && rc=$sig
echo $rc >"$base.rc"
exit $rc
"""
TMUX_OUTER = r"""runner=$1; shift; base=$2
trap : TERM
export DPCLI_NO_TMUX=1
bash "$runner" "$@"
"""
TMUX_ATTACH = r"""pid=$1; log=$2; rcf=$3
if [ "$pid" -gt 0 ] && kill -0 "$pid" 2>/dev/null; then tail -n 40 -F --pid="$pid" "$log"; exit; fi
tail -n 40 "$log"; echo; echo "Задача выполнена (код $(cat "$rcf" 2>/dev/null || echo ?))"
exec bash
"""


def default_session():
    return os.environ.get("DPCLI_TMUX_SESSION") or str(config.get("jobs.tmux_session", "dp"))


def tmux_opts(a):
    """Сессия tmux или None. Окно — по умолчанию (сессия $DPCLI_TMUX_SESSION, иначе jobs.tmux_session; нет — создаётся);
    --no-tmux и DPCLI_NO_TMUX (внутри задачи job) выключают."""
    if getattr(a, "no_tmux", False) or os.environ.get("DPCLI_NO_TMUX"):
        return None
    return getattr(a, "tmux_session", None) or default_session()


def tmux_args(q):
    q.add_argument("--tmux", action="store_true", help="окно tmux (это и так по умолчанию)")
    q.add_argument("--no-tmux", dest="no_tmux", action="store_true", help="без окна tmux, только фон")
    q.add_argument("--tmux-session", dest="tmux_session", metavar="S",
                   help="сессия tmux (по умолчанию $DPCLI_TMUX_SESSION, иначе jobs.tmux_session)")


def tmux_ok(sess):
    why = None
    if not shutil.which("tmux"):
        why = "нет tmux"
    elif subprocess.run(["tmux", "has-session", "-t", "=" + sess], capture_output=True).returncode and \
            subprocess.run(["tmux", "new-session", "-d", "-s", sess, "-n", "dpcli", "-c", str(Path.home())], capture_output=True).returncode:
        why = f"не удалось создать сессию {sess}"
    elif not shutil.which("script"):
        why = "нет script (util-linux)"
    if why:
        print(f"dpcli: tmux: {why} — запуск в фоне", file=sys.stderr)
    return why is None


def tmux_window(name, sess, argv, env=False):
    """Новое окно в сессии (имя занято — name-2, name-3…; старые окна не трогаем). → (window_id, имя) или None."""
    r = subprocess.run(["tmux", "list-windows", "-t", "=" + sess + ":", "-F", "#{window_name}"], capture_output=True, text=True)
    used = set(r.stdout.split())
    wn, i = name, 1
    while wn in used:
        i += 1
        wn = f"{name}-{i}"
    a = ["tmux", "new-window", "-d", "-P", "-F", "#{window_id}", "-t", "=" + sess + ":", "-n", wn, "-c", os.getcwd()]
    if env:
        for k, v in os.environ.items():
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k) and not k.startswith("TMUX") and k not in ("PWD", "OLDPWD", "SHLVL", "_"):
                a += ["-e", f"{k}={v}"]
    r = subprocess.run(a + argv, capture_output=True, text=True)
    if r.returncode:
        print(f"dpcli: tmux: окно не создано ({r.stderr.strip()[:100]}) — запуск в фоне", file=sys.stderr)
        return None
    return r.stdout.strip(), wn


def tmux_job(name, limit, cmd, sess):
    if not tmux_ok(sess):
        return False
    pidf, log, rcf = job_files(name)
    d = job_dir()
    runner = d / ".tmux_runner.sh"
    if not runner.exists() or runner.read_text() != TMUX_RUNNER:
        tmp = d / f".tmux_runner.{os.getpid()}"
        tmp.write_text(TMUX_RUNNER)
        tmp.rename(runner)
    pidf.unlink(missing_ok=True)
    w = tmux_window(name, sess, ["bash", "-c", TMUX_OUTER, "_", str(runner), str(limit), str(d / name), *cmd], env=True)
    if not w:
        return False
    for _ in range(100):
        if pidf.exists() and pidf.read_text().strip():
            print(f"{name}: PID {pidf.read_text().strip()}, лог {log}, окно tmux {sess}:{w[1]}")
            return True
        time.sleep(0.05)
    print(f"dpcli: tmux: окно {sess}:{w[1]} не запустило задачу", file=sys.stderr)
    return False


def job_attach(name, sess):
    pidf, log, rcf = job_files(name)
    if not log.exists():
        raise DpError(f"{name}: журнала нет ({log})")
    if not tmux_ok(sess):
        raise DpError("tmux недоступен — окно не открыто")
    try:
        pid = int(pidf.read_text())
    except (OSError, ValueError):
        pid = 0
    w = tmux_window(name, sess, ["bash", "-c", TMUX_ATTACH, "_", str(pid), str(log), str(rcf)])
    if not w:
        raise DpError("окно не открыто")
    print(f"{name}: окно tmux {sess}:{w[1]} (tail -F журнала)")


def job_alive(pid):
    try:
        os.kill(pid, 0)
        return Path(f"/proc/{pid}").exists() and Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
    except OSError:
        return False


def job_stop(name):
    pidf = job_files(name)[0]
    try:
        pid = int(pidf.read_text())
    except (OSError, ValueError):
        raise DpError(f"{name}: не запускался")
    if not job_alive(pid):
        return False
    if Path(f"/proc/{pid}").stat().st_uid != os.getuid() or \
            str(job_dir() / name) not in Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace"):
        raise DpError(f"PID {pid} — не наш запуск {name}, не трогаю")
    try:
        os.killpg(os.getpgid(pid), 15)
    except OSError:
        os.kill(pid, 15)
    return pid


def cmd_job(a):
    pidf, log, rcf = job_files(a.name) if a.name else (None, None, None)
    if a.action == "start":
        if not a.cmd or a.timeout is None:
            raise DpError(f"{CLI} job start <имя> <таймаут_с> <команда…>")
        cmd = a.cmd[1:] if a.cmd[:1] == ["--"] else a.cmd
        if a.lock:
            cmd = [*reexec.self_cmd(), "lock", a.lock, a.name, "--", *cmd]
        job_start(a.name, a.timeout, cmd, tmux_opts(a))
        return
    if a.action == "status" and not a.name:
        rows = []
        for f in job_dir().glob("*.pid"):
            n = f.stem
            rc = job_dir() / f"{n}.rc"
            try:
                pid = int(f.read_text() or 0)
            except ValueError:
                pid = 0
            st = f"код {rc.read_text().strip()}" if rc.exists() else "идёт" if job_alive(pid) else "нет данных"
            mt = max(x.stat().st_mtime for x in (f, rc, job_dir() / f"{n}.log") if x.exists())
            rows.append((st == "идёт", mt, n, st))
        rows.sort(key=lambda r: (not r[0], -r[1]))
        run = [r for r in rows if r[0]]
        done = [r for r in rows if not r[0]]
        show = run + (done if a.all or "--all" in (a.cmd or []) else done[:max(0, 10 - len(run))] if done else [])
        for _, mt, n, st in show:
            print(f"{n}: {st}" + ("" if st == "идёт" else f" ({age(dt.datetime.fromtimestamp(mt).isoformat(timespec='seconds'))})"))
        if not rows:
            print("запусков нет")
        elif len(show) < len(rows):
            print(f"… ещё {len(rows) - len(show)} завершённых (--all)")
        return
    if not a.name:
        raise DpError(f"{CLI} job {a.action} <имя>")
    if a.action == "wait":
        try:
            pid = int(pidf.read_text())
        except (OSError, ValueError):
            print(f"{a.name}: не запускался")
            sys.exit(2)
        limit = a.timeout
        if limit is None:
            raise DpError(f"{CLI} job wait <имя> <таймаут_с> — таймаут обязателен")
        r = subprocess.run(["timeout", str(limit), "tail", f"--pid={pid}", "-f", "/dev/null"])
        if rcf.exists():
            rc = int(rcf.read_text().strip() or 1)
            print(f"{a.name}: код {rc}")
            print("\n".join(log.read_text(errors="replace").splitlines()[-20:]))
            sys.exit(rc)
        if not job_alive(pid):
            print(f"{a.name}: прерван (нет кода выхода — остановлен job stop или убит)")
            sys.exit(143)
        print(f"{a.name}: ещё идёт (PID {pid}) — ожидание прервано по таймауту {limit} с")
        sys.exit(124 if r.returncode == 124 else 3)
    if a.action == "status":
        print(f"{a.name}: " + (f"код {rcf.read_text().strip()}" if rcf.exists()
                               else "идёт" if pidf.exists() and job_alive(int(pidf.read_text() or 0)) else "нет данных"))
        return
    if a.action == "stop":
        pid = job_stop(a.name)
        print(f"{a.name}: остановлен (PID {pid})" if pid else f"{a.name}: уже не идёт")
    if a.action in ("attach", "tmux"):
        job_attach(a.name, a.tmux_session or default_session())


# ---------------------------------------------------------------- lock

def locks_dir():
    v = config.get("locks")
    d = config.expand(v) if v else job_dir() / "locks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def lock_slots(res):
    d = locks_dir()
    if res == "gpu":
        return [d / "gpu.lock"]
    n = int(os.environ.get("DPCLI_CPU_SLOTS") or config.get("jobs.cpu_slots") or max(1, (os.cpu_count() or 8) // 2))
    return [d / f"cpu.{i}.lock" for i in range(n)]  # по умолчанию — слот на физическое ядро


def lock_status():
    import fcntl
    for res in ("gpu", "cpu"):
        slots = lock_slots(res)
        for i, lp in enumerate(slots):
            f = open(lp, "a")
            tag = res if res == "gpu" else f"cpu[{i + 1}/{len(slots)}]"
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                print(f"{tag}: свободен")
            except OSError:
                try:
                    x = json.loads(Path(str(lp) + ".info").read_text())
                    print(f"{tag}: занят — {x['holder']}, PID {x['pid']}, «{x['cmd']}», с {x['since']}, копия {x['cwd']}")
                except (OSError, ValueError):
                    print(f"{tag}: занят (держит процесс не через {CLI} lock)")
            finally:
                f.close()


def cmd_lock(a):
    import fcntl
    import signal
    args = list(a.args)
    if args[:1] == ["status"]:
        return lock_status()
    usage = f"{CLI} lock cpu|gpu <имя> [--timeout СЕК] [--no-tmux] [--tmux-session S] -- <команда…>  |  {CLI} lock status"
    if "--" not in args or len(args) < 4 or args[0] not in ("cpu", "gpu"):
        raise DpError(usage)
    k = args.index("--")
    head, cmd = args[:k], args[k + 1:]
    if not cmd or len(head) < 2:
        raise DpError(usage)
    res, holder, timeout = head[0], head[1], None
    if "--timeout" in head:
        timeout = int(head[head.index("--timeout") + 1])
    tm_args = argparse.Namespace(no_tmux="--no-tmux" in head,
                                 tmux_session=head[head.index("--tmux-session") + 1] if "--tmux-session" in head else None)
    tm = tmux_opts(tm_args)
    slots = lock_slots(res)
    deadline = time.time() + timeout if timeout else None
    got = None
    while got is None:
        for lp in slots:
            f = open(lp, "a")
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                got = (f, lp)
                break
            except OSError:
                f.close()
        if got is None:
            if deadline and time.time() > deadline:
                print(f"lock {res}: таймаут {timeout} с в ожидании", file=sys.stderr)
                sys.exit(124)
            time.sleep(0.2)
    f, lp = got
    ip = Path(str(lp) + ".info")
    ip.write_text(json.dumps({"holder": holder, "pid": os.getpid(), "cmd": " ".join(cmd)[:200], "since": now(), "cwd": os.getcwd()}))
    if tm and re.fullmatch(r"[\w.-]+", holder):  # команда — в окне tmux, замок держим здесь; ждём по PID, код — из .rc
        job_start(holder, 0, cmd, tm)
        pidf, _, rcf = job_files(holder)
        for sg in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sg, lambda sig, _: job_stop(holder))
        try:
            pid = int(pidf.read_text())
            while job_alive(pid):
                time.sleep(0.3)
            time.sleep(0.2)
            rc = int(rcf.read_text().strip()) if rcf.exists() else 143
        except (OSError, ValueError):
            rc = 1
        ip.unlink(missing_ok=True)
        f.close()
        sys.exit(rc)
    child = subprocess.Popen(cmd)
    for sg in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sg, lambda sig, _: child.send_signal(sig))
    try:
        rc = child.wait()
    finally:
        ip.unlink(missing_ok=True)
        f.close()
    sys.exit(rc)


def register(sp):
    q = sp.add_parser("job", help="долгий запуск в фоне: start <имя> <таймаут_с> <команда…> | wait <имя> <таймаут_с> | status [имя] | stop <имя>")
    q.add_argument("action", choices=["start", "wait", "status", "stop", "attach", "tmux"]); q.add_argument("name", nargs="?")
    q.add_argument("timeout", nargs="?", type=int); q.add_argument("cmd", nargs=argparse.REMAINDER)
    q.add_argument("--lock", metavar="cpu|gpu", help="start: выполнять под lock cpu|gpu (держатель — имя задачи)")
    q.add_argument("--all", action="store_true", help="status без имени: все запуски (по умолчанию идущие + последние 10)")
    tmux_args(q)
    q.set_defaults(func=cmd_job)

    q = sp.add_parser("lock", help="команда под общим замком: lock cpu|gpu <имя> [--timeout СЕК] -- <команда…> | lock status")
    q.add_argument("args", nargs=argparse.REMAINDER)
    q.set_defaults(func=cmd_lock)
