"""Self-built code extractor (dec-016 P1/P2). Stdlib only.

Tier A — Python via `ast`: full-fidelity symbols, imports, inheritance, and call edges
with light local type inference (var = Class(...) / super()) so method calls resolve.
Tier B — JS/TS and Go via a comment/string-aware tokenizer + brace/scope tracking:
declarations, imports, and best-effort call edges with the same var:Type inference.
Tier C — other languages via a generic declaration table: symbols + imports only,
never fabricated call edges (honest degradation, dec-016).

Every extractor returns the same shape:
    {"symbols": [{name, qualname, kind, line_start, line_end, sig, visibility}],
     "refs":    [{src, dst_name, kind, line, confidence}],   # src = qualname or <module>
     "resources": [{src, kind, name, access, line}]}
`<module>` refs (imports) attach to the implicit module symbol sync creates per file.
"""
import ast
import bisect
import json
import os
import re

EXTRACTOR_VERSION = 2  # v2: decl-tier _extract_generic lineof fix — force re-extraction of files stuck at status=error

MODULE_QUAL = "<module>"


def module_name(rel_path):
    return os.path.splitext(os.path.basename(rel_path))[0]


def extract(rel_path, text, lang):
    if lang == "python":
        return _extract_python(text)
    if lang in ("javascript", "typescript"):
        return _extract_js(text)
    if lang == "go":
        return _extract_go(text)
    if lang in ("vue", "svelte"):
        return _extract_container(text)
    if lang == "notebook":
        return _extract_notebook(text)
    if lang in _GENERIC_DECLS:
        return _extract_generic(text, lang)
    return {"symbols": [], "refs": [], "resources": []}


def _extract_container(text):
    """Vue/Svelte SFC: extract the <script> region and delegate to the JS extractor
    with real line offsets (dec-016 gap 13)."""
    m = re.search(r"<script[^>]*>(.*?)</script>", text, re.S | re.I)
    if not m:
        return {"symbols": [], "refs": [], "resources": []}
    offset = text.count("\n", 0, m.start(1))
    data = _extract_js(m.group(1))
    for s2 in data["symbols"]:
        s2["line_start"] += offset
        s2["line_end"] += offset
    for coll in ("refs", "resources"):
        for r in data[coll]:
            r["line"] += offset
    return data


def _extract_notebook(text):
    """.ipynb: concatenate python code cells and extract. Line numbers refer to the
    concatenation, not the raw JSON — spans are pinned to 1:1 so explore never serves
    a misleading slice of the raw notebook."""
    try:
        nb = json.loads(text)
        cells = [c for c in nb.get("cells", []) if c.get("cell_type") == "code"]
        src = "\n".join("".join(c.get("source", [])) for c in cells)
    except (ValueError, AttributeError):
        return {"symbols": [], "refs": [], "resources": []}
    try:
        data = _extract_python(src)
    except ValueError:
        return {"symbols": [], "refs": [], "resources": []}
    for s2 in data["symbols"]:
        s2["line_start"] = s2["line_end"] = 1
    return data


# ------------------------------------------------------------------ resources

# env/url/route are single-line literals — scan line-by-line.
_RES_PATTERNS_LINE = [
    ("env", re.compile(r"""(?:os\.environ(?:\.get)?[([]|getenv\(|process\.env\.|os\.Getenv\()\s*['"]?([A-Z][A-Z0-9_]{2,})""")),
    ("url", re.compile(r"""['"](https?://[^'"\s]{4,})['"]""")),
    ("route", re.compile(r"""['"](/(?:api|v\d+)/[A-Za-z0-9_/{}:.-]+)['"]""")),
]

# sql_table is extracted ONLY from a string literal that is actually a SQL statement. Matching a
# bare FROM/JOIN/INTO/UPDATE word anywhere fabricated tables out of ordinary prose
# (e.g. "update stats from cache") and, being line-by-line, missed real multi-line queries — both
# poison the resource-coupling edges `graph impact` builds. Requiring a statement shape fixes both.
_STRING_LITERAL = re.compile(
    r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|`[^`]*`|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'')
_SQL_STMT = re.compile(
    r"(?is)\b(?:select\b.+?\bfrom|insert\s+into|update\s+[a-z_][\w.]*\s+set|delete\s+from"
    r"|create\s+(?:table|view)|alter\s+table)\b")
_SQL_TABLE = re.compile(r"(?i)\b(?:FROM|INTO|JOIN|UPDATE)\s+([a-z_][a-z0-9_.]{2,})\b")


def _scan_resources(text, owner_of_line):
    out = []
    for i, line in enumerate(text.split("\n"), 1):
        for kind, pat in _RES_PATTERNS_LINE:
            for m in pat.finditer(line):
                out.append({"src": owner_of_line(i), "kind": kind, "name": m.group(1),
                            "access": "unknown", "line": i})
    for sm in _STRING_LITERAL.finditer(text):
        s = sm.group(0)
        if not _SQL_STMT.search(s):
            continue  # a string that isn't a SQL statement can't name a table (kills prose FPs)
        line = text.count("\n", 0, sm.start()) + 1
        seen = set()
        for tm in _SQL_TABLE.finditer(s):
            name = tm.group(1)
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            out.append({"src": owner_of_line(line), "kind": "sql_table", "name": name,
                        "access": "unknown", "line": line})
    return out


def _owner_fn(symbols):
    """line -> qualname of the innermost symbol containing it (else <module>).
    Bisect + bounded backward walk: the linear scan was O(spans) per lookup, which made
    big generated JS files quadratic (review M4)."""
    spans = sorted(((s["line_start"], s["line_end"], s["qualname"]) for s in symbols
                    if s["line_start"] and s["line_end"]),
                   key=lambda t: (t[0], -(t[1] or 0)))
    starts = [a for a, _, _ in spans]

    def owner(line):
        i = bisect.bisect_right(starts, line) - 1
        checked = 0
        while i >= 0 and checked < 64:  # nesting depth bound; >64 flat siblings -> module
            a, b, q = spans[i]
            if b >= line:
                return q  # largest start containing the line = innermost
            i -= 1
            checked += 1
        return MODULE_QUAL
    return owner


# -------------------------------------------------------------------- python

_PY_BUILTIN_SKIP = {"print", "len", "range", "str", "int", "float", "list", "dict", "set",
                    "tuple", "isinstance", "getattr", "setattr", "hasattr", "super", "type",
                    "enumerate", "zip", "map", "filter", "sorted", "min", "max", "sum", "abs",
                    "repr", "id", "iter", "next", "vars", "issubclass", "callable", "format", "open"}


def _extract_python(text):
    try:
        tree = ast.parse(text)
    except SyntaxError:
        raise ValueError("syntax error")
    symbols, refs = [], []

    def dotted(node):
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = dotted(node.value)
            return (base + "." + node.attr) if base else node.attr
        if isinstance(node, ast.Call):
            return dotted(node.func)
        return None

    def sig_of(fn):
        return "(" + ", ".join(a.arg for a in fn.args.args) + ")"

    def walk(node, stack, class_bases, local_types):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                src = stack[-1] if stack else MODULE_QUAL
                if isinstance(child, ast.Import):
                    names = [a.name for a in child.names]
                else:
                    mod = child.module or ""
                    names = [mod] if mod else [a.name for a in child.names]
                for n in names:
                    refs.append({"src": src, "dst_name": n, "kind": "imports",
                                 "line": child.lineno, "confidence": 1.0})
                continue
            if isinstance(child, ast.ClassDef):
                qual = ".".join(stack + [child.name]) if stack else child.name
                symbols.append({"name": child.name, "qualname": qual, "kind": "class",
                                "line_start": child.lineno, "line_end": child.end_lineno,
                                "sig": "", "visibility": "private" if child.name.startswith("_") else "public"})
                if stack:
                    refs.append({"src": stack[-1] if stack else MODULE_QUAL, "dst_name": qual,
                                 "kind": "contains", "line": child.lineno, "confidence": 1.0})
                bases = [dotted(b) for b in child.bases if dotted(b)]
                for b in bases:
                    refs.append({"src": qual, "dst_name": b, "kind": "inherits",
                                 "line": child.lineno, "confidence": 1.0})
                walk(child, stack + [child.name], {**class_bases, qual: bases}, {})
                continue
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = ".".join(stack + [child.name]) if stack else child.name
                symbols.append({"name": child.name, "qualname": qual, "kind": "function",
                                "line_start": child.lineno, "line_end": child.end_lineno,
                                "sig": sig_of(child),
                                "visibility": "private" if child.name.startswith("_") else "public"})
                _walk_body(child, qual, stack + [child.name], class_bases)
                continue
            walk(child, stack, class_bases, local_types)

    def _walk_body(fn, qual, stack, class_bases):
        local_types = {}
        class_qual = ".".join(stack[:-1]) if len(stack) > 1 else None
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                callee = dotted(node.value.func)
                if callee and callee[:1].isupper():
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            local_types[t.id] = callee
            if isinstance(node, ast.Call):
                name = dotted(node.func)
                if not name:
                    continue
                conf = 1.0
                head, _, rest = name.partition(".")
                if head == "super" or name.startswith("super()."):
                    attr = name.rsplit(".", 1)[-1]
                    bases = class_bases.get(class_qual or "", [])
                    name = (bases[0] + "." + attr) if bases else attr
                    conf = 0.9
                elif rest and head in local_types:
                    name = local_types[head] + "." + rest
                    conf = 0.9
                if name in _PY_BUILTIN_SKIP:
                    continue
                refs.append({"src": qual, "dst_name": name, "kind": "calls",
                             "line": node.lineno, "confidence": conf})

    walk(tree, [], {}, {})
    _module_level_calls(tree, refs, dotted)
    out = {"symbols": symbols, "refs": _dedupe(refs), "resources": []}
    out["resources"] = _scan_resources(strip_comments(text, "python", keep_strings=True),
                                       _owner_fn(symbols))
    return out


def _module_level_calls(tree, refs, dotted):
    """Top-level wiring (`app = create_app()`, `if __name__: main()`) is real coupling —
    record it against the module symbol."""
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                             ast.Import, ast.ImportFrom)):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                name = dotted(sub.func)
                if name and name not in _PY_BUILTIN_SKIP:
                    refs.append({"src": MODULE_QUAL, "dst_name": name, "kind": "calls",
                                 "line": sub.lineno, "confidence": 1.0})


# ------------------------------------------------------------- tokenizer (B)

def _linecalc(text):
    """O(log n) position->line lookup (the per-match count() was O(n^2) on big files)."""
    nl = [i for i, c in enumerate(text) if c == "\n"]
    return lambda pos: bisect.bisect_left(nl, pos) + 1


def strip_comments(text, lang, keep_strings=False):
    """Blank out comments — and, unless keep_strings, string contents too — so regex
    passes can't be fooled by braces/keywords inside them. Newlines preserved."""
    out, i, n = [], 0, len(text)
    line_c = ("//",) if lang in ("javascript", "typescript", "go") else ("#",)
    js = lang in ("javascript", "typescript")
    prev = ""  # last significant char emitted (regex-vs-division disambiguation)
    while i < n:
        ch = text[i]
        two = text[i:i + 2]
        if js and ch == "/" and two not in ("//", "/*"):
            tail = "".join(out)[-12:].rstrip()
            after_kw = bool(re.search(r"\b(return|typeof|case|in|of|delete|void|do|else|instanceof|new)$", tail))
            if prev == "" or prev in "=([{,;:!&|?+-*%~^<>" or after_kw:
                j, incls = i + 1, False
                while j < n:
                    c = text[j]
                    if c == "\\":
                        j += 2
                        continue
                    if c == "\n":
                        break  # not a regex literal after all
                    if c == "[":
                        incls = True
                    elif c == "]":
                        incls = False
                    elif c == "/" and not incls:
                        break
                    j += 1
                if j < n and text[j] == "/":
                    j += 1
                    while j < n and text[j].isalpha():
                        j += 1
                    out.append(" " * (j - i))  # blank the literal (no newlines inside)
                    prev = "/"
                    i = j
                    continue
        if two == "/*" and lang in ("javascript", "typescript", "go"):
            j = text.find("*/", i + 2)
            j = n if j == -1 else j + 2
            out.append(re.sub(r"[^\n]", " ", text[i:j]))
            i = j
            continue
        if any(text.startswith(c, i) for c in line_c):
            j = text.find("\n", i)
            j = n if j == -1 else j
            out.append(" " * (j - i))
            i = j
            continue
        if ch in "'\"`":
            q, j = ch, i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == q:
                    break
                j += 1
            j = min(j + 1, n)
            if keep_strings:
                out.append(text[i:j])
            else:
                out.append(q + re.sub(r"[^\n]", " ", text[i + 1:j - 1]) + (q if j <= n else ""))
            prev = q
            i = j
            continue
        out.append(ch)
        if not ch.isspace():
            prev = ch
        i += 1
    return "".join(out)


def _brace_spans(clean):
    """For each opening-brace position: (open_line, close_line). Used to bound class
    bodies and function bodies in brace languages."""
    stack, spans, line = [], {}, 1
    for i, ch in enumerate(clean):
        if ch == "\n":
            line += 1
        elif ch == "{":
            stack.append((i, line))
        elif ch == "}" and stack:
            pos, oline = stack.pop()
            spans[pos] = (oline, line)
    return spans


def _find_span(clean, spans, match_end, fallback_line):
    brace = clean.find("{", match_end)
    if brace != -1 and brace in spans:
        return spans[brace]
    return (fallback_line, fallback_line)


_JS_DECL = re.compile(r"^[ \t]*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?"
                      r"(class)\s+([A-Za-z_$][\w$]*)", re.M)
_JS_FUNC = re.compile(r"^[ \t]*(?:export\s+)?(?:default\s+)?(?:async\s+)?"
                      r"function\s+([A-Za-z_$][\w$]*)\s*\(", re.M)
_JS_CONST_FN = re.compile(r"^[ \t]*(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=\s*"
                          r"(?:async\s*)?(?:\([^)\n]*\)|[A-Za-z_$][\w$]*)\s*=>", re.M)
_JS_METHOD = re.compile(r"^[ \t]+(?:static\s+)?(?:async\s+)?(?:get\s+|set\s+)?"
                        r"([A-Za-z_$][\w$]*)\s*\([^)\n]*\)\s*\{", re.M)
_JS_IMPORT = re.compile(r"""(?:^[ \t]*import\b[^\n]*?from\s*['"]([^'"]+)['"]"""
                        r"""|require\(\s*['"]([^'"]+)['"])""", re.M)
_JS_NEW = re.compile(r"\bnew\s+([A-Za-z_$][\w$]*)")
_JS_CALL = re.compile(r"(?<![\w$.])([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\(")
_JS_KW = {"if", "for", "while", "switch", "catch", "return", "function", "typeof", "await",
          "async", "new", "super", "import", "require", "console.log", "console.error"}
_JS_EXTENDS = re.compile(r"class\s+([A-Za-z_$][\w$]*)\s+extends\s+([A-Za-z_$][\w$.]*)")


def _extract_js(text):
    clean = strip_comments(text, "javascript")
    nocmt = strip_comments(text, "javascript", keep_strings=True)
    lineof = _linecalc(clean)
    spans = _brace_spans(clean)
    symbols, refs = [], []
    classes = []
    for m in _JS_DECL.finditer(clean):
        line = lineof(m.start())
        a, b = _find_span(clean, spans, m.end(), line)
        classes.append((m.group(2), a, b))
        symbols.append({"name": m.group(2), "qualname": m.group(2), "kind": "class",
                        "line_start": a, "line_end": b, "sig": "",
                        "visibility": "public" if "export" in m.group(0) else "private"})
    for m in _JS_EXTENDS.finditer(clean):
        line = lineof(m.start())
        refs.append({"src": m.group(1), "dst_name": m.group(2), "kind": "inherits",
                     "line": line, "confidence": 0.9})

    def enclosing_class(line):
        for name, a, b in classes:
            if a <= line <= b:
                return name
        return None

    for pat, kind in ((_JS_FUNC, "function"), (_JS_CONST_FN, "function")):
        for m in pat.finditer(clean):
            line = lineof(m.start())
            if enclosing_class(line):
                continue
            a, b = _find_span(clean, spans, m.end(), line)
            symbols.append({"name": m.group(1), "qualname": m.group(1), "kind": kind,
                            "line_start": line, "line_end": max(b, line), "sig": "",
                            "visibility": "public" if "export" in m.group(0) else "private"})
    for m in _JS_METHOD.finditer(clean):
        line = lineof(m.start())
        cls = enclosing_class(line)
        name = m.group(1)
        if not cls or name in _JS_KW:
            continue
        a, b = _find_span(clean, spans, m.end() - 1, line)
        symbols.append({"name": name, "qualname": cls + "." + name, "kind": "function",
                        "line_start": line, "line_end": max(b, line), "sig": "",
                        "visibility": "public"})
    for m in _JS_IMPORT.finditer(nocmt):
        line = lineof(m.start())
        refs.append({"src": MODULE_QUAL, "dst_name": m.group(1) or m.group(2),
                     "kind": "imports", "line": line, "confidence": 1.0})

    owner = _owner_fn([s for s in symbols if s["kind"] == "function"])
    var_types = {}
    for m in re.finditer(r"([A-Za-z_$][\w$]*)\s*=\s*new\s+([A-Za-z_$][\w$]*)", clean):
        var_types[m.group(1)] = m.group(2)
    for m in _JS_NEW.finditer(clean):
        line = lineof(m.start())
        refs.append({"src": owner(line), "dst_name": m.group(1), "kind": "calls",
                     "line": line, "confidence": 0.9})
    for m in _JS_CALL.finditer(clean):
        name = m.group(1)
        line = lineof(m.start())
        if name in _JS_KW or name.split(".")[0] in _JS_KW:
            continue
        head, _, rest = name.partition(".")
        conf = 0.7
        if rest and head in var_types:
            name, conf = var_types[head] + "." + rest, 0.8
        src = owner(line)
        if name == src:
            continue
        # a method/function's own declaration line matches the call regex — skip it
        if any(s2["name"] == name and s2["line_start"] == line for s2 in symbols):
            continue
        refs.append({"src": src, "dst_name": name, "kind": "calls",
                     "line": line, "confidence": conf})
    out = {"symbols": symbols, "refs": _dedupe(refs), "resources": []}
    out["resources"] = _scan_resources(nocmt, _owner_fn(symbols))
    return out


_GO_FUNC = re.compile(r"^func\s+(?:\(\s*\w+\s+\*?([A-Za-z_]\w*)\s*\)\s*)?([A-Za-z_]\w*)\s*\(", re.M)
_GO_TYPE = re.compile(r"^type\s+([A-Za-z_]\w*)\s+(struct|interface)\b", re.M)
_GO_IMPORT_BLOCK = re.compile(r"^import\s*\(([^)]*)\)", re.M | re.S)
_GO_IMPORT_ONE = re.compile(r'^import\s+"([^"]+)"', re.M)
_GO_CALL = re.compile(r"(?<![\w.])([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*\(")
_GO_KW = {"if", "for", "switch", "func", "return", "go", "defer", "make", "new", "len",
          "cap", "append", "copy", "delete", "panic", "recover", "print", "println", "range",
          "string", "int", "int8", "int16", "int32", "int64", "uint", "uint8", "uint16",
          "uint32", "uint64", "float32", "float64", "byte", "rune", "bool", "error"}


def _extract_go(text):
    clean = strip_comments(text, "go")
    nocmt = strip_comments(text, "go", keep_strings=True)
    lineof = _linecalc(clean)
    spans = _brace_spans(clean)
    symbols, refs = [], []
    for m in _GO_TYPE.finditer(clean):
        line = lineof(m.start())
        a, b = _find_span(clean, spans, m.end(), line)
        symbols.append({"name": m.group(1), "qualname": m.group(1), "kind": m.group(2),
                        "line_start": line, "line_end": max(b, line), "sig": "",
                        "visibility": "public" if m.group(1)[0].isupper() else "private"})
    for m in _GO_FUNC.finditer(clean):
        recv, name = m.group(1), m.group(2)
        qual = (recv + "." + name) if recv else name
        line = lineof(m.start())
        a, b = _find_span(clean, spans, m.end(), line)
        symbols.append({"name": name, "qualname": qual, "kind": "function",
                        "line_start": line, "line_end": max(b, line), "sig": "",
                        "visibility": "public" if name[0].isupper() else "private"})
    for m in _GO_IMPORT_BLOCK.finditer(nocmt):
        base = lineof(m.start())
        for j, ln in enumerate(m.group(1).split("\n")):
            im = re.search(r'"([^"]+)"', ln)
            if im:
                refs.append({"src": MODULE_QUAL, "dst_name": im.group(1),
                             "kind": "imports", "line": base + j, "confidence": 1.0})
    for m in _GO_IMPORT_ONE.finditer(nocmt):
        line = lineof(m.start())
        refs.append({"src": MODULE_QUAL, "dst_name": m.group(1), "kind": "imports",
                     "line": line, "confidence": 1.0})

    fn_syms = [s for s in symbols if s["kind"] == "function"]
    owner = _owner_fn(fn_syms)
    var_types = {}
    for m in re.finditer(r"([A-Za-z_]\w*)\s*:?=\s*&?([A-Z]\w*)\{", clean):
        var_types[m.group(1)] = m.group(2)
    for m in _GO_CALL.finditer(clean):
        name = m.group(1)
        line = lineof(m.start())
        if name in _GO_KW or name.split(".")[0] in _GO_KW:
            continue
        head, _, rest = name.partition(".")
        conf = 0.7
        if rest and head in var_types:
            name, conf = var_types[head] + "." + rest, 0.8
        src = owner(line)
        if name == src or src == MODULE_QUAL and name in ("import",):
            continue
        # a func's own declaration line matches the call regex — skip self-decl hits
        if any((s["qualname"] == name or s["name"] == name) and s["line_start"] == line
               for s in fn_syms):
            continue
        refs.append({"src": src, "dst_name": name, "kind": "calls",
                     "line": line, "confidence": conf})
    out = {"symbols": symbols, "refs": _dedupe(refs), "resources": []}
    out["resources"] = _scan_resources(nocmt, _owner_fn(symbols))
    return out


# --------------------------------------------------------- generic decls (C)

# Tier C: declarations + imports only — call edges are never fabricated here (a regex
# call graph would make impact confidently wrong; text-reference search covers the gap).
_GENERIC_DECLS = {
    "java": [(re.compile(r"^\s*(?:public|protected|private)?\s*(?:abstract\s+|final\s+|static\s+)*(class|interface|enum)\s+(\w+)", re.M), None),
             (re.compile(r"^\s*import\s+([\w.]+);", re.M), "imports")],
    "kotlin": [(re.compile(r"^\s*(?:open\s+|data\s+|sealed\s+)*(class|interface|object)\s+(\w+)", re.M), None),
               (re.compile(r"^\s*(?:suspend\s+)?fun\s+(\w+)", re.M), "function"),
               (re.compile(r"^\s*import\s+([\w.]+)", re.M), "imports")],
    "csharp": [(re.compile(r"^\s*(?:public|internal|private)?\s*(?:abstract\s+|sealed\s+|static\s+|partial\s+)*(class|interface|struct|enum)\s+(\w+)", re.M), None),
               (re.compile(r"^\s*using\s+([\w.]+);", re.M), "imports")],
    "ruby": [(re.compile(r"^\s*(class|module)\s+([A-Z]\w*)", re.M), None),
             (re.compile(r"^\s*def\s+(?:self\.)?([\w?!]+)", re.M), "function"),
             (re.compile(r"^\s*require(?:_relative)?\s+['\"]([^'\"]+)['\"]", re.M), "imports")],
    "rust": [(re.compile(r"^\s*(?:pub\s+)?(struct|enum|trait)\s+(\w+)", re.M), None),
             (re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)", re.M), "function"),
             (re.compile(r"^\s*use\s+([\w:]+)", re.M), "imports")],
    "php": [(re.compile(r"^\s*(?:abstract\s+|final\s+)?(class|interface|trait)\s+(\w+)", re.M), None),
            (re.compile(r"^\s*(?:public|protected|private)?\s*(?:static\s+)?function\s+(\w+)", re.M), "function"),
            (re.compile(r"^\s*use\s+([\w\\]+);", re.M), "imports")],
    "c": [(re.compile(r"^\s*(?:static\s+)?(?:[\w*]+\s+)+\**(\w+)\s*\([^;]*\)\s*\{", re.M), "function"),
          (re.compile(r'^\s*#include\s+[<"]([^>"]+)[>"]', re.M), "imports")],
    "cpp": [(re.compile(r"^\s*(class|struct)\s+(\w+)", re.M), None),
            (re.compile(r'^\s*#include\s+[<"]([^>"]+)[>"]', re.M), "imports")],
    "swift": [(re.compile(r"^\s*(?:public\s+|open\s+|final\s+)*(class|struct|protocol|enum)\s+(\w+)", re.M), None),
              (re.compile(r"^\s*(?:public\s+|private\s+)?func\s+(\w+)", re.M), "function"),
              (re.compile(r"^\s*import\s+(\w+)", re.M), "imports")],
    "shell": [(re.compile(r"^\s*(?:function\s+)?([A-Za-z_][\w]*)\s*\(\)\s*\{", re.M), "function"),
              (re.compile(r"^\s*(?:\.|source)\s+([^\s;]+)", re.M), "imports")],
}


def _extract_generic(text, lang):
    lc = "//" if lang in ("java", "kotlin", "csharp", "rust", "php", "c", "cpp", "swift") else "#"
    clean = strip_comments(text, "go" if lc == "//" else "python", keep_strings=True)
    lineof = _linecalc(clean)
    symbols, refs = [], []
    for pat, kind in _GENERIC_DECLS[lang]:
        for m in pat.finditer(clean):
            line = lineof(m.start())
            if kind == "imports":
                refs.append({"src": MODULE_QUAL, "dst_name": m.group(1), "kind": "imports",
                             "line": line, "confidence": 1.0})
            elif kind == "function":
                symbols.append({"name": m.group(1), "qualname": m.group(1), "kind": "function",
                                "line_start": line, "line_end": line, "sig": "",
                                "visibility": "public"})
            else:  # (decl_kind, name) pair
                symbols.append({"name": m.group(2), "qualname": m.group(2), "kind": m.group(1),
                                "line_start": line, "line_end": line, "sig": "",
                                "visibility": "public"})
    out = {"symbols": _dedupe_syms(symbols), "refs": _dedupe(refs), "resources": []}
    out["resources"] = _scan_resources(clean, _owner_fn(symbols))
    return out


def _dedupe(refs):
    seen, out = set(), []
    for r in refs:
        k = (r["src"], r["dst_name"], r["kind"])
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def _dedupe_syms(symbols):
    seen, out = set(), []
    for s in symbols:
        k = (s["qualname"], s["kind"])
        if k not in seen:
            seen.add(k)
            out.append(s)
    return out
