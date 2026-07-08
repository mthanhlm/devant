"""Shared constants and small pure helpers. This module is on the guard hot path
(hooks exec it per Write/Edit), so keep it lean — no subprocess/shutil/ET here."""
import functools
import json
import os
import re
import sqlite3
import time

KINDS = ["vision", "direction", "goal", "idea", "decision", "constraint", "nongoal", "note"]
PREFIX = {
    "vision": "vision", "direction": "dir", "goal": "goal", "idea": "idea",
    "decision": "dec", "constraint": "con", "nongoal": "nongoal", "note": "note",
}
EDGE_KINDS = ["refines", "realizes", "supersedes", "rejects", "establishes", "constrains", "relates"]
SPECIALISTS = ["ask", "code", "document", "intent", "architect", "diagram", "slide", "debate", "review", "onboard"]
# Specialists that are invoked as a sub-step (review by code, debate by architect) or via a
# command (onboard), not (only) a router route — a zero router-log count doesn't mean unused,
# so they're excluded from the dead-skills "never used" signal.
SUBINVOKED_SPECIALISTS = {"onboard", "review", "debate"}
LAYOUT_PRESETS = ["verticalFlow", "horizontalFlow", "verticalTree", "horizontalTree",
                  "radialTree", "organic"]


# ---------------------------------------------------------------- location/db

def project_dir():
    p = os.environ.get("CLAUDE_PROJECT_DIR")
    if p and os.path.isdir(p):
        return p
    d = os.getcwd()
    while d and d != "/":
        if os.path.isdir(os.path.join(d, ".git")) or os.path.isdir(os.path.join(d, ".devant")):
            return d
        nd = os.path.dirname(d)
        if nd == d:
            break
        d = nd
    return os.getcwd()


def db_path(args):
    if getattr(args, "db", None):
        return args.db
    return os.path.join(project_dir(), ".devant", "intent.db")


def connect(args, create=False):
    path = db_path(args)
    if create:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
    elif not os.path.exists(path):
        return None
    conn = sqlite3.connect(path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:  # survive parallel hooks/tool calls hitting the store at once
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:
        pass
    ensure_schema(conn)
    return conn


def ensure_schema(conn):
    conn.executescript(
        """
    CREATE TABLE IF NOT EXISTS node(
      id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL,
      body TEXT, status TEXT DEFAULT 'active', meta TEXT, created TEXT);
    CREATE INDEX IF NOT EXISTS node_kind ON node(kind);
    CREATE TABLE IF NOT EXISTS edge(
      src TEXT NOT NULL, kind TEXT NOT NULL, dst TEXT NOT NULL, note TEXT,
      PRIMARY KEY(src, kind, dst));
    CREATE INDEX IF NOT EXISTS edge_dst ON edge(dst);
    CREATE TABLE IF NOT EXISTS code_link(
      node TEXT NOT NULL, relation TEXT NOT NULL, symbol TEXT, path TEXT,
      cg_id TEXT, note TEXT, PRIMARY KEY(node, relation, symbol, path));
    CREATE INDEX IF NOT EXISTS code_link_symbol ON code_link(symbol);
    CREATE INDEX IF NOT EXISTS code_link_path ON code_link(path);
    CREATE TABLE IF NOT EXISTS node_history(
      node_id TEXT NOT NULL, title TEXT, body TEXT, meta TEXT, status TEXT, changed_at TEXT);
    CREATE INDEX IF NOT EXISTS node_history_node ON node_history(node_id);
    """
    )
    for table, col in (("node", "updated"), ("node_history", "meta"), ("node_history", "status")):
        cols = [r[1] for r in conn.execute("PRAGMA table_info(%s)" % table).fetchall()]
        if col not in cols:
            try:
                conn.execute("ALTER TABLE %s ADD COLUMN %s TEXT" % (table, col))
            except sqlite3.OperationalError:
                pass  # a parallel process won the ALTER race between our check and this statement
    conn.commit()


# ------------------------------------------------------------------- helpers

def now():
    return time.strftime("%Y-%m-%d")


def load_meta(row):
    try:
        return json.loads(row["meta"]) if row["meta"] else {}
    except Exception:
        return {}


def next_id(conn, kind):
    pre = PREFIX[kind]
    n = 0
    for r in conn.execute("SELECT id FROM node WHERE kind=?", (kind,)).fetchall():
        m = re.search(r"(\d+)$", r["id"])
        if m:
            n = max(n, int(m.group(1)))
    return "%s-%03d" % (pre, n + 1)


@functools.lru_cache(maxsize=512)
def _glob_to_re(glob):
    # Real glob semantics: '*' does NOT cross '/', '**' (and '**/') does, '?' is one non-slash.
    out, i, n = [], 0, len(glob)
    while i < n:
        if glob.startswith("**/", i):
            out.append("(?:.*/)?"); i += 3
        elif glob.startswith("**", i):
            out.append(".*"); i += 2
        elif glob[i] == "*":
            out.append("[^/]*"); i += 1
        elif glob[i] == "?":
            out.append("[^/]"); i += 1
        else:
            out.append(re.escape(glob[i])); i += 1
    return re.compile("^" + "".join(out) + "$")


def path_match(path, glob):
    if not path or not glob:
        return False
    return _glob_to_re(glob).match(path) is not None


def rel_to_project(f, proj):
    if not f:
        return ""
    try:
        return os.path.relpath(os.path.abspath(f), proj).replace("\\", "/")
    except Exception:
        return f.replace("\\", "/")


def is_under(rel, top):
    if rel.startswith("./"):
        rel = rel[2:]
    return rel == top or rel.startswith(top + "/")


STOPWORDS = set((
    "the and for this that with you your are not use can how why what where does did "
    "was has have had will would should could about into over from when which who any "
    "all but our out via add fix get set let its new now then than them they need want "
    "make code file files test help please change update remove delete create build run "
    "the a an to of in on at by is it be do we i me my so or if as no yes also just like"
).split())


def _content_tokens(s):
    # Meaningful tokens for relevance matching: drop short words and English stopwords
    # so unrelated constraints don't surface just because two strings share 'the'.
    return set(w for w in re.findall(r"[a-z0-9_]+", (s or "").lower()) if len(w) >= 3 and w not in STOPWORDS)


def first_forbid_hit(content, patterns):
    for p in patterns:
        if not p:
            continue
        # Literal, word-boundary match FIRST so 'import db' doesn't fire on 'import dbutils'
        # and 'config.json' isn't mis-read as a regex matching 'configXjson'.
        left = r"\b" if (p[:1].isalnum() or p[:1] == "_") else ""
        right = r"\b" if (p[-1:].isalnum() or p[-1:] == "_") else ""
        if re.search(left + re.escape(p) + right, content):
            return p
        # Only if the literal didn't hit and it looks like a regex, honor it as one.
        if re.search(r"[\\^$.|?*+()\[\]{}]", p):
            try:
                if re.search(p, content):
                    return p
            except re.error:
                pass
    return None


SECRET_PATTERNS = [
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "private key block", "deny"),
    (r"(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}", "AWS access key id", "deny"),
    # left boundary so 'sk-' doesn't match inside 'task-…'/'risk-…' etc.
    (r"(?<![A-Za-z0-9_-])(ghp_|gho_|github_pat_|xox[baprs]-|sk-ant-|sk_live_|sk-|AIza|glpat-)[A-Za-z0-9_-]{16,}", "provider API token", "deny"),
    (r"eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]+", "JWT", "ask"),
    (r"(?i)\b(postgres|postgresql|mysql|mongodb(\+srv)?|redis|amqps?)://[^\s:@/]+:[^\s:@/${}]{3,}@", "connection string with password", "ask"),
    (r"(?i)(api[_-]?key|secret|token|password|passwd|access[_-]?key)\s*[:=]\s*['\"][A-Za-z0-9_\-./+]{12,}['\"]",
     "hard-coded credential", "ask"),
    # Env-style assignment: UPPER_SNAKE name (no `i` flag, so lowercase code vars like
    # `token = get_token()` don't match) assigned a literal value (not $VAR, {{tpl}}, a call,
    # an attribute read, or os.environ/getenv/process.env).
    (r"(?m)^[ \t]*(?:export[ \t]+)?[A-Z0-9_]*(?:PASSWORD|SECRET|TOKEN|APIKEY|API_KEY|PASSWD|ACCESS_KEY)[A-Z0-9_]*[ \t]*=[ \t]*(?![\"']?\$|[\"']?\{\{|os\.|getenv|process\.env|[A-Za-z_][A-Za-z0-9_.]*[ \t]*[(\[])[^\s#]{8,}", "credential in env assignment", "ask"),
]

# Fixture/example context where credential-shaped strings are usually placeholders: 'ask'-severity
# hits are suppressed here and non-private-key 'deny' hits are downgraded to 'ask'. Deliberately
# NARROW — .md/.txt/docs are real config homes, so secrets there are still flagged.
DOC_TEST_CTX = re.compile(
    r"\.(example|sample|dist|template)$"
    r"|(^|/)(tests?|spec|specs|fixtures?|testdata|examples?|mocks?|__tests__)/"
    r"|(^|/)(test_|conftest)|(_test|_spec|\.test|\.spec)\."
)


def secret_like(content):
    if not content:
        return None
    for pat, label, sev in SECRET_PATTERNS:
        if re.search(pat, content):
            return (label, sev)
    return None


def _active(conn, kind):
    return conn.execute(
        "SELECT * FROM node WHERE kind=? AND status='active' ORDER BY id", (kind,)
    ).fetchall()
