#!/usr/bin/env python3
"""How heavy dpcli is: code lines, prompt tokens agents pay on every run, duplication, risky spots.

  python3 tools/metrics.py                  # JSON to stdout
  python3 tools/metrics.py --check          # exit 1 if over tools/budgets.json (+ tolerance)
  python3 tools/metrics.py --write-budgets  # lower budgets to the current values, never raise (nightly shrink)
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUDGETS = ROOT / "tools" / "budgets.json"
TOLERANCE = 0.02  # small growth passes; more needs a budget change justified in the PR
RISKY = {
    "rm -rf": r"rm -rf",
    "force": r"--force\b|\"-f\"",
    "reset --hard": r"reset --hard",
    "shell=True": r"shell=True",
    "push": r"[\"' ]push[\"' ]",
}


def tokens(text):
    return round(len(text) / 4)  # rough: ~4 chars per token


def prompt_files():
    return sorted([*ROOT.glob("agents/*.md"), *ROOT.glob("skills/*/SKILL.md"), *ROOT.glob("templates/*.md")])


def code_files():
    return sorted(ROOT.glob("lib/dpcli/**/*.py"))


def duplicates(files, window=6):
    """Number of repeated windows of `window` non-blank, stripped lines across files."""
    seen, dup = {}, 0
    for f in files:
        lines = [l.strip() for l in f.read_text().splitlines() if l.strip() and not l.strip().startswith("#")]
        for i in range(len(lines) - window + 1):
            key = "\n".join(lines[i:i + window])
            if len(key) < 120:
                continue
            if key in seen and seen[key] != (f, i):
                dup += 1
            seen.setdefault(key, (f, i))
    return dup


def measure():
    code = {str(f.relative_to(ROOT)): sum(1 for l in f.read_text().splitlines() if l.strip()) for f in code_files()}
    prompts = {str(f.relative_to(ROOT)): tokens(f.read_text()) for f in prompt_files()}
    src = "\n".join(f.read_text() for f in [*code_files(), ROOT / "install.sh"] if f.is_file())
    return {
        "code_lines": sum(code.values()),
        "prompt_tokens": sum(prompts.values()),
        "prompt_max": max(prompts.values(), default=0),
        "duplicate_windows": duplicates(code_files()),
        "risky": {k: len(re.findall(rx, src)) for k, rx in RISKY.items()},
        "files": {"code": code, "prompts": prompts},
    }


def over(m, b):
    out = []
    for k in ("code_lines", "prompt_tokens", "prompt_max", "duplicate_windows"):
        if k in b and m[k] > b[k] * (1 + TOLERANCE):
            out.append(f"{k} {m[k]} > budget {b[k]}")
    for k, v in m["risky"].items():
        if v > (b.get("risky") or {}).get(k, v):
            out.append(f"risky '{k}' {v} > budget {b['risky'][k]}")
    return out


def lowered(m, b):
    """Budgets from measurement m, none above the old budgets b: a raise needs a justified PR, not a rewrite."""
    out = {k: min(m[k], b.get(k, m[k])) for k in ("code_lines", "prompt_tokens", "prompt_max", "duplicate_windows")}
    out["risky"] = {k: min(v, (b.get("risky") or {}).get(k, v)) for k, v in m["risky"].items()}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write-budgets", action="store_true")
    a = ap.parse_args()
    m = measure()
    if a.write_budgets:
        BUDGETS.write_text(json.dumps(lowered(m, json.loads(BUDGETS.read_text())), indent=2) + "\n")
    if a.check:
        bad = over(m, json.loads(BUDGETS.read_text()))
        for b in bad:
            print(f"over budget: {b}", file=sys.stderr)
        if bad:
            print("shrink it, or raise tools/budgets.json with a justification in the PR", file=sys.stderr)
        sys.exit(1 if bad else 0)
    print(json.dumps(m, indent=2))


if __name__ == "__main__":
    main()
