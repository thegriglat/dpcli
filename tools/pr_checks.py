#!/usr/bin/env python3
"""PR gate beyond tests: VERSION bump + CHANGELOG for distribution changes, anonymity of added lines, diff size.

  python3 tools/pr_checks.py <base-ref>      # e.g. origin/main
"""
import re
import subprocess
import sys

DIST = ("dpcli", "lib/", "agents/", "skills/", "templates/", "dpcli.example.yml", "install.sh")
MAX_DIFF = 1500
LEAKS = [(r"(?<![\w.])/(?:root|home/[\w.-]+|Users/[\w.-]+)/", "absolute home path"),
         (r"[\w.+-]+@(?!example\.com|anthropic\.com|users\.noreply\.github\.com)[\w-]+\.[\w.]+", "e-mail address")]


def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True, check=True).stdout


def version(ref):
    return int(re.search(r"^VERSION = (\d+)", git("show", f"{ref}:lib/dpcli/__init__.py"), re.M)[1])


def main(base):
    errs = []
    files = [f for f in git("diff", "--name-only", f"{base}...HEAD").splitlines() if f]
    if any(f.startswith(DIST) for f in files):
        old, new = version(base), version("HEAD")
        if new <= old:
            errs.append(f"distribution changed: bump VERSION in lib/dpcli/__init__.py (base {old})")
        elif not re.search(rf"^## {new}\b", git("show", "HEAD:CHANGELOG.md"), re.M):
            errs.append(f"CHANGELOG.md: add a section '## {new}'")
    added = [l[1:] for l in git("diff", "-U0", f"{base}...HEAD", "--", ".", ":(exclude)tests/").splitlines()
             if l.startswith("+") and not l.startswith("+++")]
    for rx, what in LEAKS:
        hits = [l.strip() for l in added if re.search(rx, l)]
        if hits:
            errs.append(f"{what} in added lines (keep the hub anonymized): {hits[0][:100]}")
    stat = git("diff", "--numstat", f"{base}...HEAD")
    size = sum(int(a) + int(d) for a, d, _ in (l.split("\t") for l in stat.splitlines()) if a.isdigit() and d.isdigit())
    if size > MAX_DIFF:
        errs.append(f"diff is {size} lines (> {MAX_DIFF}): split it")
    for e in errs:
        print(f"pr check: {e}", file=sys.stderr)
    print(f"pr checks: {len(files)} files, {size} lines, {'FAIL' if errs else 'ok'}")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "origin/main"))
