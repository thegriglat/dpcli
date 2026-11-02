#!/usr/bin/env python3
"""PreToolUse hook (Bash): refuse editing project files through the shell (sed -i, perl -i, cat > file <<, python3 -
heredocs that write); Edit/Write pay only the change. Exit 2 = blocked. Temporary files pass; echo/tee > file are
not covered on purpose."""
import json
import re
import sys

TEMP = ("/tmp/", "$TMPDIR", "${TMPDIR", "/dev/")
SHELL = [  # on every command line outside heredoc bodies, quoted strings removed; -i anywhere in the arguments
    (r"\bsed\b[^|;&]*?\s(?:-[a-zA-Z]*i\b|--in-place)", "sed -i"),
    (r"\bperl\b[^|;&]*?\s-[lnpaws0]*i[.\w]*(?=\s|$)", "perl -i"),  # switch clusters only: not -Mstrict, -fail
    (r"\bcat\s*>>?\s*([^\s&|;<>]+)\s*<<", "cat > file <<"),
]
PY_HEREDOC = re.compile(r"\bpython3?\s+-\s*<<")
PY_WRITES = re.compile(r"\.write_(?:text|bytes)\(|\bopen\([^)]*['\"][wax]b?\+?['\"]")


def split(cmd):
    """(command lines with quoted strings removed, heredoc bodies)."""
    lines, bodies, end = [], [], None
    for raw in cmd.split("\n"):
        if end is not None:
            if raw.strip() == end:
                end = None
            else:
                bodies.append(raw)
            continue
        m = re.search(r"(?<!<)<<(?!<)-?\s*['\"]?([A-Za-z_]\w*)", re.sub(r"'(\w+)'|\"(\w+)\"", r"\1\2", raw))
        bare = re.sub(r"'[^']*'|\"[^\"]*\"", "''", raw)  # quoted text removed: `git commit -m 'sed -i …'`
        lines.append(re.sub(r"'[^']*\s[^']*'|\"[^\"]*\s[^\"]*\"", "''", raw).replace('"', "").replace("'", ""))
        if m and re.search(r"(?<!<)<<(?!<)", bare):  # a heredoc opened outside quotes (`'EOF'` delimiters are fine)
            end = m[1]
    return lines, "\n".join(bodies)


def edits(ln):
    for rx, what in SHELL:
        m = re.search(rx, ln)
        if not m:
            continue
        seg = re.split(r"[|;&]", ln[m.end():], maxsplit=1)[0]  # this command only, not `; rm /tmp/x` after it
        target = m.group(1) if m.groups() else (seg.split() or [""])[-1]
        if not target.startswith(TEMP):  # temporary files are not project files
            return what
    return None


def main():
    try:
        cmd = (json.load(sys.stdin).get("tool_input") or {}).get("command") or ""
    except (ValueError, AttributeError):
        return 0
    lines, body = split(cmd)
    hits = [w for w in map(edits, lines) if w]
    writes = [ln for ln in body.split("\n") if PY_WRITES.search(ln) and not any(t.strip("/") in ln for t in TEMP)]
    if any(PY_HEREDOC.search(ln) for ln in lines) and writes:
        hits.append("python3 - writing files")
    if not hits:
        return 0
    print(f"dpcli: {hits[0]} edits project files through the shell — use the Edit tool (exact replacement) or Write "
          f"(new file); read with Read; bulk renames: ast-grep run -p OLD -r NEW -U. Temporary files (/tmp) are fine.",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
