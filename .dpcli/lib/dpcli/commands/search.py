"""search (по журналам), search --sem и index (смысловой индекс через Ollama)."""
import json
import os
import re
import subprocess
import sys
import time

from .. import config, gitx, reexec
from ..journal import all_modules, task_cards
from ..util import CLI, DpError, read_json, read_jsonl


def cmd_search(a):
    """Поиск по карточкам, отчётам, событиям и решениям всех модулей: строка на находку."""
    if a.sem:
        a.max = a.max or 10
        return sem_search(a)
    a.max = a.max or 30
    try:
        rx = re.compile(a.pattern, re.I)
    except re.error:
        rx = re.compile(re.escape(a.pattern), re.I)
    hits = []

    def scan(mod, tid, typ, t, text, src=None, unparsed=None):
        text = " ".join(str(text).split())
        m = rx.search(text)
        if m:
            lo, hi = max(0, m.start() - 70), min(len(text), m.end() + 90)
            frag = ("…" if lo else "") + text[lo:hi] + ("…" if hi < len(text) else "")
            hits.append((str(t or "")[:10], mod, tid or "-", typ + (" unparsed" if unparsed else ""), frag + (f" [{src}]" if src else "")))

    for mod, home in all_modules().items():
        if a.module and mod != a.module:
            continue
        for tid, c in task_cards(home).items():
            scan(mod, tid, "card", c.get("created"), " | ".join(
                str(c.get(k, "")) for k in ("title", "goal", "notes", "plan_ref")) + " | " + " ".join(c.get("scope") or [])
                + " | " + " ".join(f"{x.get('name')}@{x.get('version')}" if isinstance(x, dict) else str(x)
                                   for x in c.get("contracts") or []), src=c.get("src"))
            r = read_json(home / "tasks" / f"{tid}.report.json")
            if r:
                scan(mod, tid, "report", r.get("t"), " | ".join(
                    [str(r.get("summary", "")), str(r.get("how_to_check", "")), str(r.get("dp_feedback", ""))]
                    + [str(x) for x in r.get("not_done") or []]
                    + [f"{k.get('name')}={k.get('value')}" for k in r.get("checks") or []]))
        for e in read_jsonl(home / "events.jsonl"):
            if e.get("note"):
                scan(mod, e.get("task"), "event:" + str(e.get("ev")), e.get("t"), e["note"], e.get("src"), e.get("unparsed"))
        for d in read_jsonl(home / "decisions.jsonl"):
            scan(mod, d.get("task"), d.get("kind", "decision"), d.get("t"), f"{d.get('text', '')} {d.get('why', '')}",
                 d.get("src"), d.get("unparsed"))
    hits.sort(key=lambda h: (h[0], h[1], h[2]), reverse=True)
    for d, mod, tid, typ, frag in hits[: a.max]:
        print(f"{mod} {tid} {typ} {d} — {frag}")
    if len(hits) > a.max:
        print(f"… ещё {len(hits) - a.max} (--max N, --module М)")
    if not hits:
        print("ничего не найдено")


# ---------------------------------------------------------------- sem (index / search --sem)

SEM_CHUNK = 1500
SEM_BATCH = 32


def sem_chunks(path, rel, text):
    """Нарезка markdown по заголовкам, кусок ≤ ~SEM_CHUNK символов с перекрытием."""
    lines = text.splitlines()
    secs, cur, title, start = [], [], rel, 1
    for i, ln in enumerate(lines, 1):
        if re.match(r"#{1,4}\s", ln) and cur:
            secs.append((start, title, "\n".join(cur)))
            cur, start = [], i
        if re.match(r"#{1,4}\s", ln):
            title = ln.lstrip("# ").strip()
        cur.append(ln)
    if cur:
        secs.append((start, title, "\n".join(cur)))
    out = []
    for st, ti, body in secs:
        if not body.strip():
            continue
        pos = 0
        while pos < len(body):
            end = min(len(body), pos + SEM_CHUNK)
            if end < len(body):
                nl = body.rfind("\n", pos + SEM_CHUNK // 2, end)
                end = nl if nl > 0 else end
            part = body[pos:end]
            if part.strip():
                out.append((st + body.count("\n", 0, pos), ti, part))
            if end >= len(body):
                break
            pos = max(end - 200, pos + 1)
    return out


def archive_prefix():
    return f"{config.docs_dir()}/archive/"


def sem_corpus():
    top = gitx.common_root()
    pd = config.plan_dir()
    files = set()
    for pat in config.get("sem.globs") or []:
        files.update(f for f in top.glob(pat) if f.is_file())
    items = []
    for f in sorted(files):
        rel = str(f.relative_to(top))
        m = re.match(re.escape(pd) + r"/([^/]+)/", rel)
        txt = f.read_text(encoding="utf-8", errors="replace")
        sm = re.match(r"---\n(?:.*\n)*?status:\s*\"?(\w+)", txt) if txt.startswith("---\n") else None
        status = sm.group(1) if sm else ("archive" if rel.startswith(archive_prefix()) else "")
        for st, ti, body in sem_chunks(f, rel, txt):
            items.append({"id": f"{rel}#{st}", "path": rel, "line": st, "title": ti, "module": m.group(1) if m else "",
                          "text": body, "status": status})

    def rec(mod, rel, line, kind, title, text):
        if text.strip():
            items.append({"id": f"{rel}#{line}", "path": rel, "line": line, "title": f"{kind} {title}".strip(), "module": mod, "text": text})

    for mod, home in all_modules().items():
        rel0 = f"{pd}/{mod}"
        for tid, c in task_cards(home).items():
            rec(mod, f"{rel0}/tasks/{tid}.json", 1, "card", f"{tid} {c.get('title', '')}", " | ".join(
                str(c.get(k, "")) for k in ("title", "goal", "notes")) + " | " + " ".join(c.get("scope") or []))
            r = read_json(home / "tasks" / f"{tid}.report.json")
            if r:
                rec(mod, f"{rel0}/tasks/{tid}.report.json", 1, "report", tid, " | ".join(
                    [str(r.get("summary", "")), str(r.get("how_to_check", "")), str(r.get("dp_feedback", ""))]
                    + [str(x) for x in r.get("not_done") or []]))
        for n, e in enumerate(read_jsonl(home / "events.jsonl"), 1):
            if e.get("note"):
                rec(mod, f"{rel0}/events.jsonl", n, "event", f"{e.get('ev')} {e.get('task') or ''} {str(e.get('t', ''))[:10]}", e["note"])
        for n, d in enumerate(read_jsonl(home / "decisions.jsonl"), 1):
            rec(mod, f"{rel0}/decisions.jsonl", n, d.get("kind", "decision"), f"{d.get('task') or ''} {str(d.get('t', ''))[:10]}",
                f"{d.get('text', '')} {d.get('why', '')}")
    return items


def sem_url(path):
    return str(config.get("sem.url", "http://localhost:11434")).rstrip("/") + path


def sem_model():
    return str(config.get("sem.model", "bge-m3"))


def sem_dir():
    return config.expand(config.get("sem.cache_dir", "~/.cache/dpcli/{project}")) / "sem"


def sem_enabled():
    return bool(config.get("sem.enabled", False))


def require_sem():
    if not sem_enabled():
        raise DpError("смысловой поиск выключен: sem.enabled: true в конфиге и Ollama с моделью "
                      f"(ollama pull {sem_model()}); обычный поиск — {CLI} search без --sem")


def ollama_embed(texts):
    import urllib.request
    body = json.dumps({"model": sem_model(), "input": texts, "truncate": True, "keep_alive": "2m"}
                      | ({"options": {"num_gpu": 0}} if os.environ.get("DPCLI_SEM_CPU") else {})).encode()  # DPCLI_SEM_CPU=1 — только CPU
    try:
        req = urllib.request.Request(sem_url("/api/embed"), body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.loads(r.read())["embeddings"]
    except Exception as e:
        raise DpError(f"Ollama не запущен / нет модели: ollama pull {sem_model()} ({sem_url('')})") from e


def sem_norm(v):
    n = sum(x * x for x in v) ** 0.5 or 1.0
    return [x / n for x in v]


def sem_sync(quiet=False):
    """Привести общий индекс к корпусу (по хешу текста куска). -> (meta, rows, embedded, removed, dir, dim)."""
    import fcntl
    import hashlib
    import struct
    idx = sem_dir()
    idx.mkdir(parents=True, exist_ok=True)
    corpus = list({c["id"]: c for c in sem_corpus()}.values())  # id уникален
    lock = open(idx / ".lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX)  # вторая индексация ждёт первую
    try:
        old = {}
        info = read_json(idx / "info.json") or {}
        dim = info.get("dim") if info.get("model") == sem_model() else None
        try:
            meta = [json.loads(l) for l in (idx / "meta.jsonl").read_text(encoding="utf-8").splitlines()]
            raw = (idx / "emb.f16").read_bytes()
            if dim and len(raw) == 2 * dim * len(meta):
                for i, m in enumerate(meta):
                    old[m["id"]] = (m["h"], raw[i * 2 * dim:(i + 1) * 2 * dim])
        except (OSError, ValueError):
            pass
        new_meta, rows, todo = [], [], []
        for c in corpus:
            h = hashlib.sha1(c["text"].encode()).hexdigest()[:16]
            if c["id"] in old and old[c["id"]][0] == h:
                rows.append(old[c["id"]][1])
            else:
                rows.append(None)
                todo.append(len(new_meta))
            new_meta.append({"id": c["id"], "path": c["path"], "line": c["line"], "title": c["title"], "module": c["module"],
                             "h": h, "snip": " ".join(c["text"].split())[:400], "status": c.get("status", ""),
                             "_t": c["title"] + "\n" + c["text"]})
        removed = len(old) - sum(1 for m in new_meta if m["id"] in old)
        t0 = time.time()
        for s0 in range(0, len(todo), SEM_BATCH):
            idxs = todo[s0:s0 + SEM_BATCH]
            embs = ollama_embed([new_meta[i]["_t"][:3000] for i in idxs])
            for i, v in zip(idxs, embs):
                if dim is None:
                    dim = len(v)
                rows[i] = struct.pack(f"{dim}e", *sem_norm(v))
            if not quiet:
                print(f"\rиндекс: {min(s0 + SEM_BATCH, len(todo))}/{len(todo)} кусков, {time.time() - t0:.0f} с",
                      end="", file=sys.stderr, flush=True)
        if todo and not quiet:
            print(file=sys.stderr)
        for m in new_meta:
            m.pop("_t")
        if todo or removed or not old:
            # атомарная замена: читающий поиск видит либо старую, либо новую версию
            for name, data in (("emb.f16", b"".join(rows)),
                               ("meta.jsonl", "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in new_meta).encode()),
                               ("info.json", json.dumps({"model": sem_model(), "dim": dim}).encode())):
                tmp = idx / (name + ".tmp")
                tmp.write_bytes(data)
                os.replace(tmp, idx / name)
        return new_meta, rows, len(todo), removed, idx, dim
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def sem_index_bg():
    """После слияния в главную ветку: index отвязанным процессом (лог index.log); без Ollama — предупреждение."""
    import urllib.request
    if not sem_enabled():
        return ""
    try:
        urllib.request.urlopen(sem_url("/api/tags"), timeout=2).read()
    except Exception:
        return "индекс не обновлён: Ollama не запущен"
    idx = sem_dir()
    idx.mkdir(parents=True, exist_ok=True)
    log = open(idx / "index.log", "w")
    subprocess.Popen([*reexec.self_cmd(), "index"], cwd=gitx.common_root(), stdout=log, stderr=log,
                     stdin=subprocess.DEVNULL, start_new_session=True)
    return "индекс обновляется в фоне"


def cmd_index(a):
    require_sem()
    t0 = time.time()
    if a.full:
        for n in ("emb.f16", "meta.jsonl", "info.json"):
            (sem_dir() / n).unlink(missing_ok=True)
    meta, rows, n, rm, idx, _ = sem_sync()
    size = sum(p.stat().st_size for p in idx.glob("*") if p.is_file()) / 1e6
    print(f"индекс {idx}: кусков {len(meta)}, пересчитано {n}, убрано {rm}, {size:.1f} МБ, {time.time() - t0:.0f} с")


def sem_search(a):
    import operator
    import struct
    require_sem()
    t0 = time.time()
    meta, rows, n, _, _, dim = sem_sync(quiet=True)
    q = sem_norm(ollama_embed([a.pattern])[0])
    res = []
    for m, r in zip(meta, rows):
        if a.module and m["module"] != a.module:
            continue
        if a.path and not m["path"].startswith(a.path):
            continue
        if not a.all and (m["path"].startswith(archive_prefix()) or m.get("status") in ("superseded", "closed", "archive")):
            continue
        res.append((sum(map(operator.mul, q, struct.unpack(f"{dim}e", r))), m))
    res.sort(key=lambda x: -x[0])
    for sc, h in res[: a.max]:
        sn = h["snip"][:150] + ("…" if len(h["snip"]) > 150 else "")
        st = f" [{h['status']}]" if h.get("status") else ""
        print(f"{sc:.2f} {h['path']}:{h['line']}{st} — {h['title']} — {sn}")
    if not res:
        print("ничего не найдено")
    print(f"({time.time() - t0:.0f} с, обновлено кусков: {n})")


def register(sp):
    q = sp.add_parser("search", help="поиск по карточкам, отчётам, событиям, решениям всех модулей (прошлые работы)")
    q.add_argument("pattern", metavar="текст|regex"); q.add_argument("--module"); q.add_argument("--max", type=int, default=None)
    q.add_argument("--sem", action="store_true", help=f"по смыслу (опционально: sem.enabled, Ollama; нужен {CLI} index); --max по умолчанию 10")
    q.add_argument("--path", help="с --sem: префикс пути")
    q.add_argument("--all", action="store_true", help="с --sem: и <docs_dir>/archive/**, и документы status: superseded|closed")
    q.set_defaults(func=cmd_search)

    q = sp.add_parser("index", help="смысловой индекс проекта для search --sem (вне git, sem.cache_dir)")
    q.add_argument("--full", action="store_true", help="пересчитать всё")
    q.set_defaults(func=cmd_index)
