#!/usr/bin/env python3
"""Token usage of this project's Claude Code sessions: turns, context, main vs subagents, models."""
import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--since", default="", help="YYYY-MM-DD — only turns from this date")
ap.add_argument("--dir", default=str(Path.cwd()), help="project root")
a = ap.parse_args()

# ~/.claude/projects/<path with / _ . replaced by ->
logs = Path.home() / ".claude" / "projects" / re.sub(r"[/_.]", "-", a.dir)
if not logs.is_dir():
    raise SystemExit(f"no logs: {logs}")


def turns(f):
    for line in f.open(errors="replace"):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("type") != "assistant" or r.get("timestamp", "") < a.since:
            continue
        u = r.get("message", {}).get("usage") or {}
        ctx = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
        yield r.get("message", {}).get("model", "?"), ctx, u.get("output_tokens", 0), r.get("timestamp", "")


sess, kinds = [], defaultdict(lambda: [0, 0, 0])
for f in sorted(logs.glob("*.jsonl")):
    t = list(turns(f))
    if t:
        c = [x[1] for x in t]
        sess.append((f.stem[:8], len(t), sum(c) / len(t), max(c), sum(c), t[0][3][:16], t[-1][3][:16]))
    for m, ctx, out, _ in t:
        k = kinds["main " + m]
        k[0] += 1; k[1] += ctx; k[2] += out
    for sf in (logs / f.stem / "subagents").glob("*.jsonl"):
        for m, ctx, out, _ in turns(sf):
            k = kinds["sub  " + m]
            k[0] += 1; k[1] += ctx; k[2] += out

total = sum(k[1] for k in kinds.values()) or 1
print("who/model                        turns  avg.context  context,M  output,M  share")
for name, (n, ctx, out) in sorted(kinds.items(), key=lambda kv: -kv[1][1]):
    print(f"{name:32} {n:6} {ctx / n / 1e3:10.0f}k {ctx / 1e6:11.0f} {out / 1e6:8.1f} {ctx / total:5.0%}")
print("\nmain sessions                    turns  avg.context   max  context,M  period")
for s, n, avg, mx, tot, t0, t1 in sorted(sess, key=lambda x: -x[4]):
    print(f"{s:32} {n:6} {avg / 1e3:10.0f}k {mx / 1e3:5.0f}k {tot / 1e6:11.0f}  {t0}..{t1}")
