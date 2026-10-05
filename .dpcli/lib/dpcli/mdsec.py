"""Разделы markdown: заголовки (вне ```-блоков), поиск раздела по номеру или тексту, границы, оглавление.

Общее для `plan` и `docs section`.
"""
import re

HEAD_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def headings(text):
    """-> (строки, [(индекс строки, уровень, текст заголовка)])."""
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
    """Кандидаты (индексы заголовков): номер из оглавления → он; иначе точное совпадение, затем начало, затем вхождение."""
    q = q.strip()
    if q.isdigit() and 1 <= int(q) <= len(heads):
        return [int(q) - 1]
    ql = _norm(q.lstrip("§"))
    for test in (lambda t: t == ql, lambda t: t.startswith(ql), lambda t: ql in t):
        found = [n for n, (_, _, t) in enumerate(heads) if test(_norm(t))]
        if found:
            return found
    return []


def find_section(heads, q):
    """Индекс первого подходящего заголовка; None, если нет."""
    c = match_sections(heads, q)
    return c[0] if c else None


def section_end(lines, heads, sel):
    """Индекс строки после конца раздела (с подразделами)."""
    _, lvl, _ = heads[sel]
    for j, l2, _ in heads[sel + 1:]:
        if l2 <= lvl:
            return j
    return len(lines)


def section_len(lines, heads, n):
    return section_end(lines, heads, n) - heads[n][0]


def toc(lines, heads, depth=3, width=90):
    """Строки нумерованного оглавления: «  N  отступ заголовок  (строк)»."""
    from .util import short
    return [f"{n:>3} {'  ' * (lvl - 1)}{short(t, width)}  ({section_len(lines, heads, n - 1)})"
            for n, (_, lvl, t) in enumerate(heads, 1) if lvl <= depth]


def section_body(lines, heads, sel, max_lines=0):
    """Строки раздела (заголовок + тело + подразделы) без хвостовых пустых; max_lines>0 — обрезать с пометкой."""
    body = lines[heads[sel][0]:section_end(lines, heads, sel)]
    while body and not body[-1].strip():
        body.pop()
    if max_lines and len(body) > max_lines:
        body = body[:max_lines] + [f"… ещё {len(body) - max_lines} строк (--max 0 — всё)"]
    return body
