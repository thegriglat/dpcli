"""Подмножество YAML для конфига и frontmatter агентов. Если установлен PyYAML — используется он.

Поддержано: словари по отступам, списки `- x` (в т.ч. на том же отступе, что ключ), списки словарей `- key: v`,
inline `[a, b]` и `{k: v}`, скаляры (строки в кавычках и без, целые и дробные числа, true/false, null/~),
блочные строки `|` и `>` (с `-`/`+`), комментарии `#`. Якоря, теги, многодокументность — нет.
"""
import json
import re

try:  # pragma: no cover — зависит от окружения
    import yaml as _yaml
except ImportError:
    _yaml = None


class YamlError(ValueError):
    pass


def loads(text, use_pyyaml=True):
    if use_pyyaml and _yaml is not None:
        try:
            return _yaml.safe_load(text)
        except _yaml.YAMLError as e:
            raise YamlError(str(e))
    return _Parser(text).parse()


def frontmatter(text):
    """(словарь frontmatter, тело) для markdown с `---` в первой строке; без frontmatter — ({}, text)."""
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines(keepends=True)
    if lines[0].strip() != "---":
        return {}, text
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            meta = loads("".join(lines[1:i])) or {}
            if not isinstance(meta, dict):
                raise YamlError("frontmatter — не словарь")
            return meta, "".join(lines[i + 1:])
    raise YamlError("frontmatter не закрыт строкой ---")


_INT = re.compile(r"^[-+]?\d+$")
_FLOAT = re.compile(r"^[-+]?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?$")


def _scalar(s):
    s = s.strip()
    if not s:
        return None
    if s[0] == "'":
        if len(s) < 2 or s[-1] != "'":
            raise YamlError(f"незакрытая кавычка: {s}")
        return s[1:-1].replace("''", "'")
    if s[0] == '"':
        if len(s) < 2 or s[-1] != '"':
            raise YamlError(f"незакрытая кавычка: {s}")
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return s[1:-1]
    low = s.lower()
    if low in ("null", "~"):
        return None
    if low == "true":
        return True
    if low == "false":
        return False
    if _INT.match(s):
        return int(s)
    if _FLOAT.match(s):
        return float(s)
    return s


def _strip_comment(s):
    q = None
    depth = 0
    for i, ch in enumerate(s):
        if q:
            if ch == q:
                q = None
            elif ch == "\\" and q == '"':
                continue
        elif ch in "'\"" and (i == 0 or s[i - 1] in " \t[{,:-"):
            q = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        elif ch == "#" and (i == 0 or s[i - 1] in " \t"):
            return s[:i].rstrip()
    return s.rstrip()


def _split_key(text):
    """'key: value' → (key, value) или None, если строка — не пара ключ: значение."""
    if not text or text[0] in "[{":
        return None
    if text[0] in "'\"":
        q = text[0]
        j = text.find(q, 1)
        while q == "'" and j != -1 and text[j + 1:j + 2] == "'":
            j = text.find(q, j + 2)
        if j == -1:
            return None
        rest = text[j + 1:]
        if rest == ":" or rest.startswith(": "):
            return _scalar(text[:j + 1]), rest[1:].strip()
        return None
    m = re.search(r":(\s|$)", text)
    if not m:
        return None
    return text[:m.start()].strip(), text[m.end():].strip()


class _Flow:
    def __init__(self, s):
        self.s, self.i = s, 0

    def ws(self):
        while self.i < len(self.s) and self.s[self.i] in " \t":
            self.i += 1

    def value(self):
        self.ws()
        if self.i >= len(self.s):
            raise YamlError(f"обрыв inline-значения: {self.s}")
        ch = self.s[self.i]
        if ch == "[":
            self.i += 1
            out = []
            self.ws()
            if self.s[self.i:self.i + 1] == "]":
                self.i += 1
                return out
            while True:
                out.append(self.value())
                self.ws()
                c = self.s[self.i:self.i + 1]
                self.i += 1
                if c == "]":
                    return out
                if c != ",":
                    raise YamlError(f"ожидалось , или ]: {self.s}")
                self.ws()
                if self.s[self.i:self.i + 1] == "]":
                    self.i += 1
                    return out
        if ch == "{":
            self.i += 1
            out = {}
            self.ws()
            if self.s[self.i:self.i + 1] == "}":
                self.i += 1
                return out
            while True:
                k = self.atom(stop=":,}")
                self.ws()
                if self.s[self.i:self.i + 1] != ":":
                    raise YamlError(f"ожидалось «:» в {self.s}")
                self.i += 1
                self.ws()
                c = self.s[self.i:self.i + 1]
                out[k] = None if c in (",", "}") else self.value()
                self.ws()
                c = self.s[self.i:self.i + 1]
                self.i += 1
                if c == "}":
                    return out
                if c != ",":
                    raise YamlError(f"ожидалось , или }}: {self.s}")
                self.ws()
                if self.s[self.i:self.i + 1] == "}":
                    self.i += 1
                    return out
        return self.atom(stop=",]}")

    def atom(self, stop):
        self.ws()
        ch = self.s[self.i:self.i + 1]
        if ch in ("'", '"'):
            j = self.i + 1
            while j < len(self.s):
                if self.s[j] == "\\" and ch == '"':
                    j += 2
                    continue
                if self.s[j] == ch:
                    if ch == "'" and self.s[j + 1:j + 2] == "'":
                        j += 2
                        continue
                    break
                j += 1
            tok = self.s[self.i:j + 1]
            self.i = j + 1
            return _scalar(tok)
        j = self.i
        while j < len(self.s):
            c = self.s[j]
            if c in ",]}" and c in stop:
                break
            if c == ":" and ":" in stop and (j + 1 >= len(self.s) or self.s[j + 1] in " \t,]}"):
                break
            j += 1
        tok = self.s[self.i:j]
        self.i = j
        return _scalar(tok)


def _flow(s):
    f = _Flow(s)
    v = f.value()
    f.ws()
    if f.i != len(s):
        raise YamlError(f"лишнее после inline-значения: {s}")
    return v


def _value(s):
    s = s.strip()
    if s[:1] in ("[", "{"):
        return _flow(s)
    return _scalar(s)


class _Parser:
    def __init__(self, text):
        self.raw = text.splitlines()
        if any("\t" in l[:len(l) - len(l.lstrip(" \t"))] for l in self.raw):
            raise YamlError("табуляция в отступе")
        self.i = 0

    def peek(self):
        while self.i < len(self.raw):
            s = self.raw[self.i]
            st = s.strip()
            if not st or st.startswith("#") or (s.startswith("---") and st == "---") or st == "...":
                self.i += 1
                continue
            return len(s) - len(s.lstrip(" ")), _strip_comment(st)
        return None

    def err(self, msg):
        raise YamlError(f"строка {self.i + 1}: {msg}")

    def parse(self):
        p = self.peek()
        if p is None:
            return None
        if _split_key(p[1]) is None and not _is_dash(p[1]):
            self.i += 1
            v = _value(p[1])
            if self.peek() is not None:
                self.err("лишнее после значения")
            return v
        v = self.block(p[0])
        if self.peek() is not None:
            self.err(f"не разобрано: «{self.raw[self.i].strip()}» (отступ?)")
        return v

    def block(self, ind):
        p = self.peek()
        return self.seq(ind) if _is_dash(p[1]) else self.mapping(ind)

    def mapping(self, ind):
        d = {}
        while True:
            p = self.peek()
            if p is None or p[0] < ind:
                return d
            if p[0] > ind:
                self.err("лишний отступ")
            if _is_dash(p[1]):
                return d
            kv = _split_key(p[1])
            if kv is None:
                self.err(f"ожидалось «ключ: значение»: {p[1]}")
            key, rest = kv
            self.i += 1
            d[key] = self.after_key(rest, ind)

    def after_key(self, rest, ind):
        if rest == "":
            p = self.peek()
            if p and (p[0] > ind or (p[0] == ind and _is_dash(p[1]))):
                return self.block(p[0])
            return None
        if re.fullmatch(r"[|>][-+]?", rest):
            return self.block_scalar(rest, ind)
        return _value(rest)

    def seq(self, ind):
        lst = []
        while True:
            p = self.peek()
            if p is None or p[0] != ind or not _is_dash(p[1]):
                if p is not None and p[0] > ind:
                    self.err("лишний отступ")
                return lst
            body = p[1][1:].lstrip()
            if not body:
                self.i += 1
                q = self.peek()
                lst.append(self.block(q[0]) if q and q[0] > ind else None)
            elif _is_dash(body) or (_split_key(body) is not None):
                line = self.raw[self.i]
                pos = len(line) - len(line.lstrip(" ")) + (len(p[1]) - len(body))
                self.raw[self.i] = " " * pos + body
                lst.append(self.block(pos))
            elif re.fullmatch(r"[|>][-+]?", body):
                self.i += 1
                lst.append(self.block_scalar(body, ind))
            else:
                self.i += 1
                lst.append(_value(body))

    def block_scalar(self, ind_s, ind):
        style, chomp = ind_s[0], ind_s[1:]
        lines = []
        bi = None
        while self.i < len(self.raw):
            s = self.raw[self.i]
            if s.strip():
                cur = len(s) - len(s.lstrip(" "))
                if cur <= ind:
                    break
                if bi is None:
                    bi = cur
                if cur < bi:
                    break
                lines.append(s[bi:])
            else:
                lines.append("")
            self.i += 1
        while lines and lines[-1] == "" and chomp != "+":
            lines.pop()
        if style == "|":
            text = "\n".join(lines)
        else:
            parts, buf = [], []
            for l in lines:
                if l == "":
                    parts.append(" ".join(buf))
                    buf = []
                else:
                    buf.append(l)
            parts.append(" ".join(buf))
            text = "\n".join(parts)
        if chomp == "-" or not lines:
            return text
        return text + "\n"


def _is_dash(t):
    return t == "-" or t.startswith("- ")
