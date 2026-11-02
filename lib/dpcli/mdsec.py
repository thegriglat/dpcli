"""Markdown sections: headings (outside ``` blocks), section lookup by number or text, bounds, table of contents.

Shared by `plan` and `docs section`.
"""
import re

HEAD_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def headings(text):
    """-> (lines, [(line index, level, heading text)])."""
    out, fence = [], False
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("```"):
            fence = not fence
        if not fence:
            m = HEAD_RE.match(line)
            if m:
                out.append((i, len(m[1]), m[2].strip()))
    return lines, out


def _norm(t):
    return t.lower().replace("§", "").strip()


def match_sections(heads, q):
    """Candidates (heading indexes): a table-of-contents number wins; else exact match, then prefix, then substring."""
    q = q.strip()
    if q.isdigit() and 1 <= int(q) <= len(heads):
        return [int(q) - 1]
    ql = _norm(q.lstrip("§"))
    for test in (lambda t: t == ql, lambda t: t.startswith(ql), lambda t: ql in t):
        found = [n for n, (_, _, t) in enumerate(heads) if test(_norm(t))]
        if found:
            return found
    parts = [p.strip() for p in re.split(r"\s+/\s+|[()]", q) if p.strip() and p.strip() != q]
    for p in reversed(parts):  # "5. Tasks / DS-0", "4. Tasks (PF-5)": the most specific part first
        pl = _norm(p.lstrip("§"))
        if not re.search(r"[^\W\d_]", pl):  # "1", "2.": a bare number would match any numbered heading
            continue
        for test in (lambda t: t == pl, lambda t: t.startswith(pl)):  # no numbers, no substrings: a bad ref must fail
            found = [n for n, (_, _, t) in enumerate(heads) if test(_norm(t))]
            if found:
                return found
    return []


def find_section(heads, q):
    """Index of the first matching heading; None if none."""
    c = match_sections(heads, q)
    return c[0] if c else None


def section_end(lines, heads, sel):
    """Index of the line after the section end (subsections included)."""
    _, lvl, _ = heads[sel]
    for j, l2, _ in heads[sel + 1:]:
        if l2 <= lvl:
            return j
    return len(lines)


def section_len(lines, heads, n):
    return section_end(lines, heads, n) - heads[n][0]


def toc(lines, heads, depth=3, width=90):
    """Numbered table-of-contents lines: "  N  indent heading  (lines)"."""
    from .util import short
    return [f"{n:>3} {'  ' * (lvl - 1)}{short(t, width)}  ({section_len(lines, heads, n - 1)})"
            for n, (_, lvl, t) in enumerate(heads, 1) if lvl <= depth]


def section_body(lines, heads, sel, max_lines=0):
    """Section lines (heading + body + subsections) without trailing blanks; max_lines>0 truncates with a note."""
    body = lines[heads[sel][0]:section_end(lines, heads, sel)]
    while body and not body[-1].strip():
        body.pop()
    if max_lines and len(body) > max_lines:
        body = body[:max_lines] + [f"… {len(body) - max_lines} more lines (--max 0 for all)"]
    return body
