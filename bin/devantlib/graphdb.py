"""index.db — the derived code-index side of the devant graph (dec-016).

One logical graph, two physical files: intent.db (precious, owned by common/intent) and
this index.db (always rebuildable). Queries ATTACH intent.db so intent<->code joins work.
The search index (FTS5 when available, a plain token table otherwise) is maintained by
TRIGGERS so writers can never desync it; the camelCase/snake_case token splitter is
registered as an SQLite function on every connection this module opens.
"""
import json
import os
import re
import sqlite3

from .common import db_path, project_dir

SCHEMA_VERSION = 1

REF_KINDS = ["contains", "imports", "calls", "inherits", "implements", "references"]


def index_db_path(args):
    if getattr(args, "index_db", None):
        return args.index_db
    return os.path.join(project_dir(), ".devant", "index.db")


def split_tokens(s):
    """Search tokens for a symbol name: the raw words plus camelCase/snake_case parts,
    lowercased and de-duplicated, space-joined (what the search index stores)."""
    out, seen = [], set()
    for word in re.findall(r"[A-Za-z0-9_]+", s or ""):
        parts = [p for p in word.split("_") if p]
        camel = []
        for p in parts:
            camel.extend(re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+", p))
        for t in [word] + parts + camel:
            t = t.lower()
            if t and t not in seen:
                seen.add(t)
                out.append(t)
    return " ".join(out)


def fts_available(conn):
    if os.environ.get("DEVANT_FTS", "on") == "off":  # test plumbing, like DEVANT_CODEGRAPH
        return False
    try:
        conn.execute("CREATE VIRTUAL TABLE temp.__fts_probe USING fts5(x)")
        conn.execute("DROP TABLE temp.__fts_probe")
        return True
    except sqlite3.OperationalError:
        return False


def connect_index(args, create=False):
    path = index_db_path(args)
    if not create and not os.path.exists(path):
        return None
    new = not os.path.exists(path)
    if create:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.create_function("devant_tokens", 1, split_tokens)
    try:
        if new:
            # auto_vacuum only takes effect before the first table exists (else it needs a
            # full VACUUM) — set it here or never (dec-016 gap 15).
            conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA journal_mode=WAL")
        # INSERT OR REPLACE only fires DELETE triggers when this is ON — without it a
        # REPLACE on annotation/symbol leaves the old search_idx row behind (desync).
        conn.execute("PRAGMA recursive_triggers=ON")
    except sqlite3.Error:
        pass
    ensure_index_schema(conn)
    return conn


def _search_mode(conn):
    row = conn.execute("SELECT value FROM meta WHERE key='fts'").fetchone()
    return row["value"] if row else None


def ensure_index_schema(conn):
    conn.executescript(
        """
    CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS file(
      id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, lang TEXT, hash TEXT, mtime REAL,
      status TEXT DEFAULT 'ok', error TEXT, extractor_version INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS symbol(
      id INTEGER PRIMARY KEY, file INTEGER NOT NULL, name TEXT NOT NULL, qualname TEXT NOT NULL,
      kind TEXT NOT NULL, line_start INTEGER, line_end INTEGER, sig TEXT, visibility TEXT,
      UNIQUE(file, qualname, kind));
    CREATE INDEX IF NOT EXISTS symbol_name ON symbol(name);
    CREATE INDEX IF NOT EXISTS symbol_qualname ON symbol(qualname);
    CREATE TABLE IF NOT EXISTS ref(
      src_symbol INTEGER NOT NULL, dst_symbol INTEGER, dst_name TEXT,
      kind TEXT NOT NULL CHECK(kind IN ('contains','imports','calls','inherits','implements','references')),
      line INTEGER, confidence REAL DEFAULT 1.0);
    CREATE INDEX IF NOT EXISTS ref_src ON ref(src_symbol);
    CREATE INDEX IF NOT EXISTS ref_dst ON ref(dst_symbol);
    CREATE TABLE IF NOT EXISTS resource(
      id INTEGER PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, UNIQUE(kind, name));
    CREATE TABLE IF NOT EXISTS touches(
      symbol INTEGER NOT NULL, resource INTEGER NOT NULL, access TEXT DEFAULT 'unknown',
      line INTEGER, PRIMARY KEY(symbol, resource, line));
    CREATE TABLE IF NOT EXISTS annotation(
      target_key TEXT NOT NULL, target_type TEXT NOT NULL CHECK(target_type IN ('symbol','file')),
      source_hash TEXT, summary TEXT, concepts TEXT, source TEXT DEFAULT 'model', updated TEXT,
      PRIMARY KEY(target_key, target_type));
    """
    )
    mode = _search_mode(conn)
    if mode is None:
        mode = "fts5" if fts_available(conn) else "like"
        if mode == "fts5":
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS search_idx "
                "USING fts5(target_key UNINDEXED, target_type UNINDEXED, text)")
        else:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS search_idx(target_key TEXT, target_type TEXT, text TEXT)")
            conn.execute("CREATE INDEX IF NOT EXISTS search_idx_key ON search_idx(target_key)")
        # The trigger bodies are identical for both modes — that's the point: one write
        # protocol, no code path that can forget the index (dec-016 gap 9).
        conn.executescript(
            """
        CREATE TRIGGER IF NOT EXISTS symbol_ai AFTER INSERT ON symbol BEGIN
          INSERT INTO search_idx(target_key, target_type, text)
          VALUES(NEW.file || ':' || NEW.qualname || ':' || NEW.kind, 'symbol',
                 devant_tokens(NEW.name || ' ' || NEW.qualname));
        END;
        CREATE TRIGGER IF NOT EXISTS symbol_au AFTER UPDATE ON symbol BEGIN
          DELETE FROM search_idx
           WHERE target_type='symbol' AND target_key = OLD.file || ':' || OLD.qualname || ':' || OLD.kind;
          INSERT INTO search_idx(target_key, target_type, text)
          VALUES(NEW.file || ':' || NEW.qualname || ':' || NEW.kind, 'symbol',
                 devant_tokens(NEW.name || ' ' || NEW.qualname));
        END;
        CREATE TRIGGER IF NOT EXISTS symbol_ad AFTER DELETE ON symbol BEGIN
          DELETE FROM search_idx
           WHERE target_type='symbol' AND target_key = OLD.file || ':' || OLD.qualname || ':' || OLD.kind;
        END;
        CREATE TRIGGER IF NOT EXISTS annotation_ai AFTER INSERT ON annotation BEGIN
          INSERT INTO search_idx(target_key, target_type, text)
          VALUES(NEW.target_key, 'annotation', devant_tokens(NEW.summary || ' ' || COALESCE(NEW.concepts, '')));
        END;
        CREATE TRIGGER IF NOT EXISTS annotation_au AFTER UPDATE ON annotation BEGIN
          DELETE FROM search_idx WHERE target_type='annotation' AND target_key = OLD.target_key;
          INSERT INTO search_idx(target_key, target_type, text)
          VALUES(NEW.target_key, 'annotation', devant_tokens(NEW.summary || ' ' || COALESCE(NEW.concepts, '')));
        END;
        CREATE TRIGGER IF NOT EXISTS annotation_ad AFTER DELETE ON annotation BEGIN
          DELETE FROM search_idx WHERE target_type='annotation' AND target_key = OLD.target_key;
        END;
        """
        )
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('fts',?)", (mode,))
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)",
                     (str(SCHEMA_VERSION),))
    conn.commit()


def search_mode(conn):
    return _search_mode(conn) or "like"


def search(conn, text, limit=20):
    """Rows of {target_key, target_type} matching the query tokens, best-first."""
    toks = split_tokens(text).split()
    if not toks:
        return []
    if search_mode(conn) == "fts5":
        q = " OR ".join('"%s"' % t.replace('"', '') for t in toks)
        try:
            return conn.execute(
                "SELECT target_key, target_type FROM search_idx WHERE search_idx MATCH ? "
                "ORDER BY bm25(search_idx) LIMIT ?", (q, limit)).fetchall()
        except sqlite3.OperationalError:
            return []
    where = " OR ".join("text LIKE ?" for _ in toks)
    params = ["%" + t + "%" for t in toks] + [limit]
    return conn.execute(
        "SELECT target_key, target_type FROM search_idx WHERE %s LIMIT ?" % where, params).fetchall()


def fts_integrity(conn):
    """'ok' | 'corrupt' for fts5; 'like' when running on the fallback table."""
    if search_mode(conn) != "fts5":
        return "like"
    try:
        conn.execute("INSERT INTO search_idx(search_idx) VALUES('integrity-check')")
        return "ok"
    except sqlite3.Error:
        return "corrupt"


def attach_intent(conn, args):
    """ATTACH intent.db (read) so queries can join intent nodes — one logical graph."""
    path = db_path(args)
    if not os.path.exists(path):
        return False
    try:
        conn.execute("ATTACH DATABASE ? AS intent", (path,))
        return True
    except sqlite3.Error:
        return False
