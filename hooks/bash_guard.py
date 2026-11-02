#!/usr/bin/env python3
"""PreToolUse hook (Bash): refuse editing project files through the shell (sed -i, perl -i, cat > file <<, python3 -
heredocs that write); Edit/Write pay only the change. Writing the module journal (events/decisions.jsonl, module.json,
task cards and reports) by any shell means — redirects, tee, cp/mv, git checkout/restore, python -c / heredoc / a
script file — is refused too: only dpcli writes it. Exit 2 = blocked. Temporary files pass; echo/tee > file of other
files are not covered on purpose."""
import json
import os
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


_J = r"(?:(?:events|decisions)\.jsonl|module\.json|tasks/[A-Z]{2,4}-[A-Z]?\d+[a-z]?(?:\.report|\.review)?\.json)\b"
JOURNAL_SHELL = [re.compile(rx) for rx in (
    r">>?\s*['\"]?[^\s|;&<>'\"]*" + _J,  # redirect into it
    r"\btee\b(?:\s+-\w+)*[^|;&\n]*?" + _J,
    r"\b(?:cp|mv|install|rsync)\b[^|;&\n]*\s['\"]?[^\s|;&'\"]*" + _J + r"['\"]?\s*(?:$|[|;&\n])",  # as the target
    r"\bgit\s+(?:checkout|restore)\b[^|;&\n]*" + _J,
    r"\b(?:sed|perl)\b[^|;&\n]*\s-[a-zA-Z]*i[^|;&\n]*" + _J)]
JOURNAL_CODE = re.compile(_J + r"|['\"]tasks['\"]")
CODE_WRITES = re.compile(PY_WRITES.pattern + r"|json\.dump\(")
PY_FILE = re.compile(r"\bpython3?\b(?:\s+-[A-Za-z]+)*\s+([^\s|;&<>-][^\s|;&<>]*\.py)\b")


def journal(cmd, cwd):
    """Refusal reason when the command writes the module journal, else None."""
    if any(rx.search(cmd) for rx in JOURNAL_SHELL):
        return "a shell write"
    codes = [cmd] if re.search(r"\bpython3?\b", cmd) else []
    for m in PY_FILE.finditer(cmd):  # a script file: look inside
        try:
            codes.append(open(os.path.join(cwd or ".", os.path.expanduser(m[1])), encoding="utf-8", errors="replace").read())
        except OSError:
            pass
    if any(JOURNAL_CODE.search(c) and CODE_WRITES.search(c) for c in codes):
        return "a script writing"
    return None


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
        data = json.load(sys.stdin)
        cmd = (data.get("tool_input") or {}).get("command") or ""
    except (ValueError, AttributeError):
        return 0
    why = journal(cmd, data.get("cwd"))
    if why:
        print(f"dpcli: {why} into the module journal — only dpcli writes it: cards `task new|set` (--check NAME CMD "
              f"EXPECT replaces a check, scope+=…), reports `report <ID> --set field=value`, a wrong event "
              f"`event <ID> revoke --note why`, a journal written in another copy `adopt <m>`, decisions `decide`. Reading is fine (`status`, `log`, `report --show`). A "
              f"command is missing — say so in `harness: …`, don't edit the journal.", file=sys.stderr)
        return 2
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
