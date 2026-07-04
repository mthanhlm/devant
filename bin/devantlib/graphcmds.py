"""`devant graph …` — the fixed P0 query/sync surface over index.db (dec-016).

The CLI contract (subcommands and their -j output keys) is frozen here; later phases add
capability behind the same shape. sync extracts symbols/refs/resources via devantlib.extract
(P1: python/js/ts/go with call edges; generic declarations elsewhere); commands answer
honestly from whatever exists and nudge toward /devant:onboard when the index is empty.
"""
import hashlib
import json
import os
import subprocess
import sys

from .common import connect, load_meta, now, project_dir, rel_to_project
from .extract import EXTRACTOR_VERSION, MODULE_QUAL, extract, module_name
from .graphdb import (attach_intent, connect_index, fts_integrity, search as idx_search,
                      search_mode, SCHEMA_VERSION)

NUDGE = "devant graph: index empty — run /devant:onboard (or `devant graph sync`) to build it."

MAX_FILE_BYTES = 1_000_000
MAX_LINE_CHARS = 5000  # a single line longer than this is minified/generated, not source

LANG_BY_EXT = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
    ".cjs": "javascript", ".ts": "typescript", ".tsx": "typescript", ".go": "go",
    ".java": "java", ".kt": "kotlin", ".cs": "csharp", ".rb": "ruby", ".rs": "rust",
    ".php": "php", ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".hpp": "cpp",
    ".swift": "swift", ".sh": "shell", ".bash": "shell", ".sql": "sql", ".md": "markdown",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml", ".html": "html",
    ".css": "css", ".vue": "vue", ".svelte": "svelte", ".ipynb": "notebook",
}

_WALK_SKIP_DIRS = {".git", ".devant", ".codegraph", "node_modules", ".venv", "venv",
                   "__pycache__", "dist", "build", ".tox", ".mypy_cache"}


def _enumerate(proj):
    """Repo-relative candidate paths: `git ls-files -c -o --exclude-standard` (respects
    .gitignore for free), falling back to os.walk for non-git dirs. Symlinks never followed."""
    try:
        # -z: NUL-separated raw bytes — survives non-ASCII names (core.quotePath would
        # C-quote them into paths that don't exist) and newlines in filenames.
        out = subprocess.run(["git", "ls-files", "-c", "-o", "--exclude-standard", "-z"],
                             cwd=proj, capture_output=True, timeout=30)
        if out.returncode == 0:
            rels = [p.decode("utf-8", "surrogateescape") for p in out.stdout.split(b"\0") if p]
            # git only honors .gitignore/.git/info/exclude; devant's own state (and other
            # always-skip dirs) must be filtered here too, not just in the walk fallback.
            return [r for r in rels if r.split("/", 1)[0] not in _WALK_SKIP_DIRS]
    except (OSError, subprocess.TimeoutExpired):
        pass
    rels = []
    for root, dirs, files in os.walk(proj):  # followlinks=False by default
        dirs[:] = [d for d in dirs if d not in _WALK_SKIP_DIRS and
                   not os.path.islink(os.path.join(root, d))]
        for f in files:
            rels.append(rel_to_project(os.path.join(root, f), proj))
    return rels


def _scan(ab):
    """(skip_reason|None, sha256, mtime) for one absolute path."""
    if os.path.islink(ab):
        return ("symlink", None, None)
    try:
        st = os.stat(ab)
    except OSError:
        return ("unreadable", None, None)
    if st.st_size > MAX_FILE_BYTES:
        return ("too-large", None, None)
    h = hashlib.sha256()
    head = b""
    try:
        with open(ab, "rb") as fh:
            first = True
            while True:
                chunk = fh.read(65536)
                if not chunk:
                    break
                if first:
                    head = chunk[:8192]
                    first = False
                h.update(chunk)
    except OSError:
        return ("unreadable", None, None)
    if b"\0" in head:
        return ("binary", None, None)
    if any(len(ln) > MAX_LINE_CHARS for ln in head.split(b"\n")):
        return ("minified", None, None)
    return (None, h.hexdigest(), st.st_mtime)


def file_hash(ab):
    _, h, _ = _scan(ab)
    return h


def _store_extraction(conn, fid, rel, lang, text):
    """Extract one file into the index. Symbols are UPSERTED on their natural key
    (file, qualname, kind) and only vanished ones are deleted — ids stay stable so
    inbound refs/annotations survive re-index (dec-016 gap 1). Returns None or an
    error string (old symbols are kept on a syntax error mid-edit)."""
    try:
        data = extract(rel, text, lang)
    except Exception as exc:  # one hostile/broken file must never abort the whole sync
        return repr(exc)
    mod = module_name(rel)
    symbols = [{"name": mod, "qualname": MODULE_QUAL, "kind": "module",
                "line_start": 1, "line_end": text.count("\n") + 1, "sig": "",
                "visibility": "public"}] + data["symbols"]
    keep = set()
    for s in symbols:
        conn.execute(
            "INSERT INTO symbol(file,name,qualname,kind,line_start,line_end,sig,visibility) "
            "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(file,qualname,kind) DO UPDATE SET "
            "name=excluded.name, line_start=excluded.line_start, line_end=excluded.line_end, "
            "sig=excluded.sig, visibility=excluded.visibility",
            (fid, s["name"], s["qualname"], s["kind"], s["line_start"], s["line_end"],
             s["sig"], s["visibility"]))
        keep.add((s["qualname"], s["kind"]))
    for r in conn.execute("SELECT id, qualname, kind FROM symbol WHERE file=?", (fid,)).fetchall():
        if (r["qualname"], r["kind"]) not in keep:
            conn.execute("DELETE FROM ref WHERE src_symbol=?", (r["id"],))
            # inbound edges must NOT keep pointing at a dead (reusable) rowid — unbind so
            # the next _resolve_refs pass rebinds or leaves them honestly unresolved (H1)
            conn.execute("UPDATE ref SET dst_symbol=NULL WHERE dst_symbol=?", (r["id"],))
            conn.execute("DELETE FROM touches WHERE symbol=?", (r["id"],))
            conn.execute("DELETE FROM symbol WHERE id=?", (r["id"],))
    sid = {r["qualname"]: r["id"] for r in conn.execute(
        "SELECT id, qualname FROM symbol WHERE file=? ORDER BY "
        "CASE kind WHEN 'module' THEN 0 WHEN 'class' THEN 1 ELSE 2 END", (fid,)).fetchall()}
    conn.execute("DELETE FROM ref WHERE src_symbol IN (SELECT id FROM symbol WHERE file=?)", (fid,))
    for r in data["refs"]:
        src = sid.get(r["src"]) or sid.get(MODULE_QUAL)
        if src is None:
            continue
        conn.execute("INSERT INTO ref(src_symbol,dst_symbol,dst_name,kind,line,confidence) "
                     "VALUES(?,?,?,?,?,?)",
                     (src, sid.get(r["dst_name"]), r["dst_name"], r["kind"], r["line"],
                      r["confidence"]))
    conn.execute("DELETE FROM touches WHERE symbol IN (SELECT id FROM symbol WHERE file=?)", (fid,))
    for res in data["resources"]:
        src = sid.get(res["src"]) or sid.get(MODULE_QUAL)
        if src is None:
            continue
        cur = conn.execute("INSERT OR IGNORE INTO resource(kind,name) VALUES(?,?)",
                           (res["kind"], res["name"]))
        rid = conn.execute("SELECT id FROM resource WHERE kind=? AND name=?",
                           (res["kind"], res["name"])).fetchone()["id"]
        conn.execute("INSERT OR IGNORE INTO touches(symbol,resource,access,line) VALUES(?,?,?,?)",
                     (src, rid, res["access"], res["line"]))
    return None


def _resolve_refs(conn):
    """Global pass: bind dst_name to a symbol id where the target is unambiguous —
    exact qualname first, then unique bare name; cross-file binds carry a confidence
    haircut (0.9x). Same-file binds were done at store time via the sid map."""
    for r in conn.execute(
            "SELECT rowid, dst_name, confidence FROM ref "
            "WHERE dst_symbol IS NULL AND kind IN ('calls','inherits','implements')").fetchall():
        hits = conn.execute("SELECT id FROM symbol WHERE qualname=? AND kind!='module'",
                            (r["dst_name"],)).fetchall()
        if not hits and "." in r["dst_name"]:
            # module-qualified call (lib.core): head names a module symbol -> look up
            # the remainder inside that module's file.
            head, _, rest = r["dst_name"].partition(".")
            hits = conn.execute(
                "SELECT s.id FROM symbol s JOIN symbol m ON m.file = s.file "
                "WHERE m.kind='module' AND m.name=? AND s.qualname=? AND s.kind!='module'",
                (head, rest)).fetchall()
        bare = False
        if not hits and "." not in r["dst_name"]:
            hits = conn.execute("SELECT id FROM symbol WHERE name=? AND kind!='module'",
                                (r["dst_name"],)).fetchall()
            bare = True
        if len(hits) == 1:
            conf = min(round(r["confidence"] * 0.9, 2), 0.6) if bare else round(r["confidence"] * 0.9, 2)
            conn.execute("UPDATE ref SET dst_symbol=?, confidence=? WHERE rowid=?",
                         (hits[0]["id"], conf, r["rowid"]))


def cmd_graph_sync(args):
    conn = connect_index(args, create=True)
    proj = project_dir()
    counts = {"scanned": 0, "indexed": 0, "updated": 0, "removed": 0, "skipped": 0}
    present = set()
    for rel in _enumerate(proj):
        counts["scanned"] += 1
        reason, h, mtime = _scan(os.path.join(proj, rel))
        if reason:
            counts["skipped"] += 1
            continue
        present.add(rel)
        lang = LANG_BY_EXT.get(os.path.splitext(rel)[1].lower(), "other")
        row = conn.execute("SELECT id, hash, extractor_version FROM file WHERE path=?",
                           (rel,)).fetchone()
        changed = row is None or row["hash"] != h or row["extractor_version"] != EXTRACTOR_VERSION
        if row is None:
            cur = conn.execute(
                "INSERT INTO file(path,lang,hash,mtime,extractor_version) VALUES(?,?,?,?,?)",
                (rel, lang, h, mtime, EXTRACTOR_VERSION))
            fid = cur.lastrowid
            counts["indexed"] += 1
        elif changed:
            fid = row["id"]
            conn.execute("UPDATE file SET lang=?, hash=?, mtime=?, status='ok', error=NULL, "
                         "extractor_version=? WHERE id=?",
                         (lang, h, mtime, EXTRACTOR_VERSION, fid))
            counts["updated"] += 1
        if changed:
            try:
                with open(os.path.join(proj, rel), encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue
            err = _store_extraction(conn, fid, rel, lang, text)
            if err:  # keep the previous symbols; record the parse failure honestly
                conn.execute("UPDATE file SET status='error', error=? WHERE id=?", (err, fid))
    # Orphan GC: files gone from the tree take their symbols/refs/annotations with them
    # (the search index follows via triggers). dec-016 gap 15.
    for r in conn.execute("SELECT id, path FROM file").fetchall():
        if r["path"] in present:
            continue
        conn.execute("DELETE FROM ref WHERE src_symbol IN (SELECT id FROM symbol WHERE file=?)",
                     (r["id"],))
        # refs FROM surviving files into the dead file lose their binding, not their row —
        # deleting them would diverge incremental from full rescan (H2)
        conn.execute("UPDATE ref SET dst_symbol=NULL "
                     "WHERE dst_symbol IN (SELECT id FROM symbol WHERE file=?)", (r["id"],))
        conn.execute("DELETE FROM touches WHERE symbol IN (SELECT id FROM symbol WHERE file=?)",
                     (r["id"],))
        conn.execute("DELETE FROM symbol WHERE file=?", (r["id"],))
        conn.execute("DELETE FROM annotation WHERE target_type='file' AND target_key=?", (r["path"],))
        conn.execute("DELETE FROM annotation WHERE target_type='symbol' AND target_key LIKE ?",
                     (str(r["id"]) + ":%",))  # symbol keys embed the file rowid, which can be reused
        conn.execute("DELETE FROM file WHERE id=?", (r["id"],))
        counts["removed"] += 1
    _resolve_refs(conn)
    conn.commit()
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        pass
    if args.json:
        print(json.dumps(counts))
    else:
        print("sync: %(scanned)d scanned, %(indexed)d new, %(updated)d updated, "
              "%(removed)d removed, %(skipped)d skipped" % counts)
    return 0


def cmd_graph_status(args):
    conn = connect_index(args)
    if conn is None:
        if args.json:
            print(json.dumps({"schema_version": None, "files": 0, "symbols": 0,
                              "langs": {}, "fts": None}))
        else:
            print(NUDGE)
        return 0
    langs = {r["lang"]: r["c"] for r in conn.execute(
        "SELECT lang, COUNT(*) c FROM file GROUP BY lang ORDER BY c DESC").fetchall()}
    report = {
        "schema_version": int(conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'").fetchone()["value"]),
        "files": conn.execute("SELECT COUNT(*) c FROM file").fetchone()["c"],
        "symbols": conn.execute("SELECT COUNT(*) c FROM symbol").fetchone()["c"],
        "langs": langs,
        "fts": fts_integrity(conn),
    }
    if args.json:
        print(json.dumps(report))
        return 0
    print("index: %d files, %d symbols (schema v%d, search: %s/%s)" % (
        report["files"], report["symbols"], report["schema_version"],
        search_mode(conn), report["fts"]))
    for lang, c in langs.items():
        print("  %s: %d" % (lang, c))
    if not report["files"]:
        print(NUDGE)
    return 0


def _symbol_row(conn, key):
    """Resolve a search_idx symbol key 'fileid:qualname:kind' to a display dict."""
    fid, _, rest = key.partition(":")
    qual, _, kind = rest.rpartition(":")
    row = conn.execute(
        "SELECT s.qualname, s.name, s.kind, s.line_start, s.line_end, f.path "
        "FROM symbol s JOIN file f ON f.id = s.file "
        "WHERE s.file=? AND s.qualname=? AND s.kind=?", (fid, qual, kind)).fetchone()
    if row is None:
        return None
    return {"kind": "symbol", "qualname": row["qualname"], "symbol_kind": row["kind"],
            "path": row["path"], "line_start": row["line_start"], "line_end": row["line_end"]}


def _intent_hits(conn_or_none, args, text, limit=10):
    """Intent nodes matching the query — via ATTACH on the index connection when possible
    (one logical graph), else directly against intent.db."""
    like = "%" + text + "%"
    sql = ("SELECT id, kind, title FROM %s WHERE status!='superseded' "
           "AND (title LIKE ? OR body LIKE ?) ORDER BY kind, id LIMIT ?")
    if conn_or_none is not None and attach_intent(conn_or_none, args):
        rows = conn_or_none.execute(sql % "intent.node", (like, like, limit)).fetchall()
    else:
        ic = connect(args)
        if ic is None:
            return []
        rows = ic.execute(sql % "node", (like, like, limit)).fetchall()
    return [{"kind": r["kind"], "id": r["id"], "title": r["title"]} for r in rows]


def cmd_graph_search(args):
    conn = connect_index(args)
    out = []
    if conn is not None:
        for r in idx_search(conn, args.text, limit=args.limit):
            if r["target_type"] == "symbol":
                d = _symbol_row(conn, r["target_key"])
                if d:
                    out.append(d)
            else:
                out.append({"kind": "annotation", "key": r["target_key"]})
    out.extend(_intent_hits(conn, args, args.text))
    if args.json:
        print(json.dumps(out))
        return 0
    if not out:
        print(NUDGE if conn is None else "no matches.")
        return 0
    for d in out:
        if d["kind"] == "symbol":
            print("[symbol] %s (%s) %s:%s" % (d["qualname"], d["symbol_kind"], d["path"], d["line_start"]))
        elif d["kind"] == "annotation":
            print("[annotation] %s" % d["key"])
        else:
            print("[%s] %s: %s" % (d["kind"], d["id"], d["title"]))
    return 0


def _verified_span(proj, path, recorded_hash, a, b):
    """Source lines a..b of `path` ONLY if the file still matches the recorded hash —
    a stale recorded span must never be served as truth (dec-016 gap 2)."""
    ab = os.path.join(proj, path)
    if file_hash(ab) != recorded_hash:
        return None
    try:
        with open(ab, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        return None
    a = max(1, int(a or 1)); b = min(len(lines), int(b or len(lines)))
    return "".join(lines[a - 1:b])


def cmd_graph_explore(args):
    conn = connect_index(args)
    proj = project_dir()
    files, symbols = [], []
    if conn is not None:
        for r in idx_search(conn, args.text, limit=args.limit):
            if r["target_type"] != "symbol":
                continue
            d = _symbol_row(conn, r["target_key"])
            if d is None:
                continue
            fh = conn.execute("SELECT hash FROM file WHERE path=?", (d["path"],)).fetchone()
            src = _verified_span(proj, d["path"], fh["hash"] if fh else None,
                                 d["line_start"], d["line_end"])
            d["source"] = src
            d["stale"] = src is None
            symbols.append(d)
        for t in set(args.text.split()):
            for r in conn.execute("SELECT path FROM file WHERE path LIKE ? LIMIT 5",
                                  ("%" + t + "%",)).fetchall():
                if r["path"] not in files:
                    files.append(r["path"])
    intent = _intent_hits(conn, args, args.text)
    if args.json:
        print(json.dumps({"symbols": symbols, "files": files, "intent": intent}))
        return 0
    if not (symbols or files or intent):
        print(NUDGE if conn is None else "no matches.")
        return 0
    for d in symbols:
        print("== %s (%s) %s:%s%s" % (d["qualname"], d["symbol_kind"], d["path"],
                                      d["line_start"], " [STALE — re-sync]" if d["stale"] else ""))
        if d["source"]:
            print(d["source"], end="")
    for p in files:
        print("[file] %s" % p)
    for d in intent:
        print("[%s] %s: %s" % (d["kind"], d["id"], d["title"]))
    return 0


def _resolve_symbols(conn, name):
    rows = conn.execute(
        "SELECT s.id, s.qualname, s.kind, f.path FROM symbol s JOIN file f ON f.id=s.file "
        "WHERE s.qualname=? OR s.name=?", (name, name)).fetchall()
    if not rows:
        rows = conn.execute(
            "SELECT s.id, s.qualname, s.kind, f.path FROM symbol s JOIN file f ON f.id=s.file "
            "WHERE s.qualname LIKE ?", ("%" + name + "%",)).fetchall()
    return rows


def _ref_rows(conn, ids, direction):
    if not ids:
        return []
    marks = ",".join("?" for _ in ids)
    col, other = ("dst_symbol", "src_symbol") if direction == "callers" else ("src_symbol", "dst_symbol")
    return conn.execute(
        "SELECT s.qualname, s.kind AS symbol_kind, f.path, r.line, r.kind, r.confidence "
        "FROM ref r JOIN symbol s ON s.id = r.%s JOIN file f ON f.id = s.file "
        "WHERE r.%s IN (%s) AND r.kind IN ('calls','inherits','implements')" % (other, col, marks),
        list(ids)).fetchall()


def _edges_cmd(args, direction):
    conn = connect_index(args)
    out = []
    if conn is not None:
        ids = [r["id"] for r in _resolve_symbols(conn, args.symbol)]
        out = [dict(r) for r in _ref_rows(conn, ids, direction)]
    if args.json:
        print(json.dumps(out))
        return 0
    if not out:
        print(NUDGE if conn is None or not conn.execute(
            "SELECT 1 FROM symbol LIMIT 1").fetchone() else "none found.")
        return 0
    for r in out:
        print("%s (%s) %s:%s [%s, conf %.2f]" % (r["qualname"], r["symbol_kind"], r["path"],
                                                 r["line"], r["kind"], r["confidence"]))
    return 0


def cmd_graph_callers(args):
    return _edges_cmd(args, "callers")


def cmd_graph_callees(args):
    return _edges_cmd(args, "callees")


def cmd_graph_impact(args):
    conn = connect_index(args)
    symbols, seen = [], set()
    seeds = []
    if conn is not None:
        seeds = [r["id"] for r in _resolve_symbols(conn, args.symbol)]
        frontier = list(seeds)
        seen = set(frontier)
        while frontier:  # reverse closure over calls/inherits/implements
            rows = conn.execute(
                "SELECT r.src_symbol AS sid, s.qualname, s.kind AS symbol_kind, f.path, r.kind, r.confidence "
                "FROM ref r JOIN symbol s ON s.id=r.src_symbol JOIN file f ON f.id=s.file "
                "WHERE r.dst_symbol IN (%s) AND r.kind IN ('calls','inherits','implements')"
                % ",".join("?" for _ in frontier), list(frontier)).fetchall()
            frontier = []
            for r in rows:
                if r["sid"] in seen:
                    continue
                seen.add(r["sid"])
                frontier.append(r["sid"])
                symbols.append({"qualname": r["qualname"], "symbol_kind": r["symbol_kind"],
                                "path": r["path"], "via": r["kind"], "confidence": r["confidence"]})
    # Resource co-reference (dec-016 P2): two symbols touching the same env var / URL /
    # route / table are coupled even when no call edge connects them.
    if conn is not None and seeds:
        marks = ",".join("?" for _ in seeds)
        for r in conn.execute(
                "SELECT DISTINCT s.id AS sid, s.qualname, s.kind AS symbol_kind, f.path, "
                "res.kind AS rkind, res.name AS rname FROM touches t1 "
                "JOIN touches t2 ON t2.resource = t1.resource AND t2.symbol != t1.symbol "
                "JOIN symbol s ON s.id = t2.symbol JOIN file f ON f.id = s.file "
                "JOIN resource res ON res.id = t1.resource "
                "WHERE t1.symbol IN (%s)" % marks, seeds).fetchall():
            if r["sid"] in seen:
                continue
            seen.add(r["sid"])
            symbols.append({"qualname": r["qualname"], "symbol_kind": r["symbol_kind"],
                            "path": r["path"], "via": "resource:%s:%s" % (r["rkind"], r["rname"]),
                            "confidence": 0.6})
    # Concept co-reference (dec-016 P3, opt-in): annotations sharing a tag.
    if getattr(args, "semantic", False) and conn is not None and seeds:
        keys = ["%d:%s:%s" % (r["file"], r["qualname"], r["kind"]) for r in conn.execute(
            "SELECT file, qualname, kind FROM symbol WHERE id IN (%s)"
            % ",".join("?" for _ in seeds), seeds).fetchall()]
        concepts = set()
        for k in keys:
            row = conn.execute("SELECT concepts FROM annotation WHERE target_key=?", (k,)).fetchone()
            if row and row["concepts"]:
                try:
                    concepts.update(json.loads(row["concepts"]))
                except ValueError:
                    pass
        for c in sorted(concepts):
            for a in conn.execute(
                    "SELECT target_key, target_type FROM annotation WHERE concepts LIKE ?",
                    ('%"' + c + '"%',)).fetchall():
                if a["target_key"] in keys:
                    continue
                symbols.append({"qualname": a["target_key"], "symbol_kind": a["target_type"],
                                "path": a["target_key"] if a["target_type"] == "file" else "",
                                "via": "concept:" + c, "confidence": 0.5})
    # The intent<->code crossing: constraints/decisions linked to this symbol surface in the
    # blast radius — that works TODAY through code_link, extractor or not.
    intent = []
    ic = connect(args)
    if ic is not None:
        links = ic.execute("SELECT DISTINCT node FROM code_link WHERE symbol=? OR symbol LIKE ?",
                           (args.symbol, "%" + args.symbol + "%")).fetchall()
        for lk in links:
            n = ic.execute("SELECT id, kind, title FROM node WHERE id=?", (lk["node"],)).fetchone()
            if n:
                intent.append({"id": n["id"], "kind": n["kind"], "title": n["title"]})
    if args.json:
        print(json.dumps({"symbols": symbols, "intent": intent}))
        return 0
    if not (symbols or intent):
        print(NUDGE if conn is None else "no recorded impact.")
        return 0
    for s in symbols:
        print("[code] %s %s (%s, conf %.2f)" % (s["qualname"], s["path"], s["via"], s["confidence"]))
    for n in intent:
        print("[intent] %s %s: %s" % (n["kind"], n["id"], n["title"]))
    return 0


def _test_candidates(rel):
    d, base = os.path.split(rel)
    stem, ext = os.path.splitext(base)
    cands = [
        os.path.join(d, "test_" + base),
        os.path.join(d, stem + "_test" + ext),
        os.path.join(d, stem + ".test" + ext),
        os.path.join(d, stem + ".spec" + ext),
        os.path.join("tests", "test_" + base),
        os.path.join("tests", d, "test_" + base),
    ]
    if d.startswith("src/"):
        cands.append(os.path.join("tests", d[4:], "test_" + base))
    return cands


def _is_test(rel):
    base = os.path.basename(rel)
    return (base.startswith(("test_", "conftest")) or "/tests/" in ("/" + rel) or
            any(m in base for m in ("_test.", ".test.", ".spec.", "_spec.")))


def cmd_graph_affected(args):
    rels = list(args.paths or [])
    if args.stdin:
        rels.extend(p.strip() for p in sys.stdin.read().splitlines() if p.strip())
    conn = connect_index(args)
    known = set()
    if conn is not None:
        known = {r["path"] for r in conn.execute("SELECT path FROM file").fetchall()}
    out, seen = [], set()

    def add(path, via, source):
        if path not in seen:
            seen.add(path)
            out.append({"path": path, "via": via, "source": source})

    def dependents(rel):
        """Files whose import edges name this file's module — the reverse import closure
        (one level; provenance-labelled per dec-016 gap 10)."""
        if conn is None:
            return []
        stem = module_name(rel)
        rows = conn.execute(
            "SELECT DISTINCT f.path FROM ref r JOIN symbol s ON s.id=r.src_symbol "
            "JOIN file f ON f.id=s.file WHERE r.kind='imports' AND "
            "(r.dst_name=? OR r.dst_name LIKE ? OR r.dst_name LIKE ?)",
            (stem, "%." + stem, "%/" + stem)).fetchall()
        return [x["path"] for x in rows if x["path"] != rel]

    for rel in rels:
        if _is_test(rel):
            add(rel, "self", rel)
            continue
        for cand in _test_candidates(rel):
            if cand in known:
                add(cand, "convention", rel)
        for dep in dependents(rel):
            if _is_test(dep):
                add(dep, "import", rel)
            else:
                for cand in _test_candidates(dep):
                    if cand in known:
                        add(cand, "import+convention", rel)
    if args.json:
        print(json.dumps(out))
        return 0
    if not out:
        if conn is None or not known:
            print(NUDGE, file=sys.stderr)
        return 0
    for t in out:
        print(t["path"])
    return 0


def cmd_graph_hot(args):
    """Symbols ranked by inbound edges — where annotation effort pays first (dec-017)."""
    conn = connect_index(args)
    out = []
    if conn is not None:
        for r in conn.execute(
                "SELECT s.file, s.qualname, s.kind, f.path, COUNT(r.rowid) c FROM symbol s "
                "JOIN file f ON f.id = s.file LEFT JOIN ref r ON r.dst_symbol = s.id "
                "WHERE s.kind != 'module' GROUP BY s.id ORDER BY c DESC, s.qualname "
                "LIMIT ?", (args.limit,)).fetchall():
            out.append({"key": "%d:%s:%s" % (r["file"], r["qualname"], r["kind"]),
                        "qualname": r["qualname"], "kind": r["kind"], "path": r["path"],
                        "in_degree": r["c"]})
    if args.json:
        print(json.dumps(out))
        return 0
    if not out:
        print(NUDGE)
        return 0
    for d in out:
        print("%3d  %s (%s) %s  [%s]" % (d["in_degree"], d["qualname"], d["kind"], d["path"], d["key"]))
    return 0


def cmd_graph_annotate(args):
    conn = connect_index(args, create=True)
    concepts = json.dumps([c.strip() for c in (args.concepts or "").split(",") if c.strip()])
    conn.execute(
        "INSERT OR REPLACE INTO annotation(target_key,target_type,source_hash,summary,concepts,source,updated) "
        "VALUES(?,?,?,?,?,?,?)",
        (args.key, args.type, args.source_hash, args.summary, concepts, args.source, now()))
    conn.commit()
    if args.json:
        print(json.dumps({"target_key": args.key, "target_type": args.type}))
    else:
        print(args.key)
    return 0
