"""Intent-graph commands (add-node/decide/link/constraints/why/…) plus the bridge to
the devant code index (graph_conn/graph_resolve). Imported lazily by the CLI — never on
the guard hot path."""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys

from .common import (EDGE_KINDS, KINDS, SPECIALISTS, SUBINVOKED_SPECIALISTS, _active,
                     _content_tokens, connect, ensure_schema, load_meta, next_id, now,
                     path_match, project_dir)
from .guard import evaluate_guard


def graph_conn(args):
    """The devant code index (index.db), or None when it hasn't been built or the
    structural lifecycle is disabled (DEVANT_CODEGRAPH=off — legacy env name kept so
    existing setups/tests keep working)."""
    if os.environ.get("DEVANT_CODEGRAPH", "on") == "off":
        return None
    from .graphdb import connect_index
    return connect_index(args)


def graph_resolve(args, symbol):
    """Resolve a symbol name to {filePath, qualifiedName} against the devant graph
    (replaces the codegraph subprocess after the dec-016 cutover). None if absent
    or ambiguous."""
    conn = graph_conn(args)
    if conn is None:
        return None
    rows = conn.execute(
        "SELECT s.qualname, f.path FROM symbol s JOIN file f ON f.id=s.file "
        "WHERE s.qualname=? AND s.kind!='module' LIMIT 2", (symbol,)).fetchall()
    if not rows:
        rows = conn.execute(
            "SELECT s.qualname, f.path FROM symbol s JOIN file f ON f.id=s.file "
            "WHERE s.name=? AND s.kind!='module' LIMIT 2", (symbol.rsplit(".", 1)[-1],)).fetchall()
    if len(rows) != 1:
        return None
    return {"filePath": rows[0]["path"], "id": None, "qualifiedName": rows[0]["qualname"]}


# -------------------------------------------------------------- write commands

def _insert_node(conn, nid, kind, title, body, status, meta):
    """Insert/update a node. Explicit id -> upsert (journaling the old row to node_history so
    in-place edits leave an audit trail). Auto id -> INSERT with collision-retry so parallel
    processes can't compute the same id and clobber each other (the next_id race)."""
    if nid is not None:
        old = conn.execute("SELECT * FROM node WHERE id=?", (nid,)).fetchone()
        # meta/status changes matter as much as prose (a block->warn downgrade is exactly
        # what the journal exists to audit) — compare and journal ALL of them.
        changed = old is not None and (
            old["title"] != title or (old["body"] or "") != (body or "")
            or (old["meta"] or "") != (meta or "") or (old["status"] or "") != (status or ""))
        if changed:
            conn.execute(
                "INSERT INTO node_history(node_id,title,body,meta,status,changed_at) VALUES(?,?,?,?,?,?)",
                (nid, old["title"], old["body"], old["meta"], old["status"], now()))
        conn.execute(
            "INSERT OR REPLACE INTO node(id,kind,title,body,status,meta,created,updated) "
            "VALUES(?,?,?,?,?,?,COALESCE((SELECT created FROM node WHERE id=?),?),?)",
            (nid, kind, title, body, status, meta, nid, now(),
             now() if changed else (old["updated"] if old is not None else None)))
        conn.commit()
        return nid
    for _ in range(64):
        cand = next_id(conn, kind)
        try:
            conn.execute(
                "INSERT INTO node(id,kind,title,body,status,meta,created) VALUES(?,?,?,?,?,?,?)",
                (cand, kind, title, body, status, meta, now()))
            conn.commit()
            return cand
        except sqlite3.IntegrityError:
            conn.rollback()
    raise sqlite3.IntegrityError("could not allocate a unique id for kind %s" % kind)


def cmd_add_node(args):
    conn = connect(args, create=True)
    # Updating an existing node? Start from its meta and only override what's passed,
    # so e.g. re-titling a constraint never silently drops its forbid/applies/severity.
    existing = conn.execute("SELECT * FROM node WHERE id=?", (args.id,)).fetchone() if args.id else None
    base = load_meta(existing) if (existing and existing["kind"] == args.kind) else {}
    meta = dict(base)
    if args.meta:
        try:
            meta.update(json.loads(args.meta))
        except (ValueError, TypeError):
            sys.stderr.write("devant: --meta must be valid JSON.\n")
            return 2
    if args.kind == "constraint":
        if args.applies:
            meta["applies_to_paths"] = args.applies
        if args.forbid:
            meta["forbid"] = args.forbid
        if args.exempt:
            meta["exempt_paths"] = args.exempt
        if args.expected:
            meta["expected"] = args.expected
        if args.severity:
            meta["severity"] = args.severity
        meta.setdefault("severity", "warn")
        if base and base.get("severity") == "block" and meta.get("severity") != "block":
            sys.stderr.write("devant: note — downgrading constraint %s from block to %s.\n" % (args.id, meta.get("severity")))
    if args.kind == "decision":
        if args.rejected:
            meta["rejected"] = args.rejected
        if args.why_rejected:
            meta["why_rejected"] = args.why_rejected
    # Keep an existing rationale on update, so re-titling a rule doesn't demand re-typing --body.
    body = args.body
    if not (body and body.strip()) and existing and existing["kind"] == args.kind:
        body = existing["body"]
    # NM5 write-hygiene: a rule without a rationale rots silently.
    if args.kind in ("decision", "constraint") and not (body and body.strip()):
        sys.stderr.write("devant: %s nodes require a non-empty --body (the rationale).\n" % args.kind)
        return 2
    nid = _insert_node(conn, args.id, args.kind, args.title, body, args.status or "active",
                       json.dumps(meta) if meta else None)
    if args.kind == "constraint":
        _warn_overlap(conn, nid, meta.get("applies_to_paths") or [])
    print(nid)
    return 0


def _warn_overlap(conn, nid, applies):
    if not applies:
        return
    for c in conn.execute(
        "SELECT * FROM node WHERE kind='constraint' AND status='active' AND id!=?", (nid,)
    ).fetchall():
        other = load_meta(c).get("applies_to_paths") or []
        if set(other) & set(applies):
            sys.stderr.write(
                "devant: note — constraint %s overlaps paths with %s; if it replaces it, "
                "run `devant add-edge %s supersedes %s`.\n" % (nid, c["id"], nid, c["id"])
            )
            return


def cmd_add_edge(args):
    conn = connect(args, create=True)
    if args.kind not in EDGE_KINDS:
        sys.stderr.write("devant: edge kind must be one of %s\n" % ", ".join(EDGE_KINDS))
        return 2
    for end in (args.src, args.dst):
        if not conn.execute("SELECT 1 FROM node WHERE id=?", (end,)).fetchone():
            sys.stderr.write("devant: warning — edge endpoint '%s' is not an existing node.\n" % end)
    conn.execute(
        "INSERT OR IGNORE INTO edge(src,kind,dst,note) VALUES(?,?,?,?)",
        (args.src, args.kind, args.dst, args.note),
    )
    if args.kind == "supersedes":
        conn.execute("UPDATE node SET status='superseded' WHERE id=? AND status!='superseded'", (args.dst,))
    conn.commit()
    return 0


def cmd_link(args):
    conn = connect(args, create=True)
    path, cg_id = args.path, args.cg_id
    if (not path or not cg_id) and not args.no_resolve:
        info = graph_resolve(args, args.symbol)
        if info:
            resolved = (info.get("qualifiedName") or "")
            want = args.symbol.lower().rsplit(".", 1)[-1]
            # graph resolution is name-based; if the hit doesn't actually contain the requested
            # name, don't silently store a wrong path/id — warn and keep just the symbol name.
            if want and want not in resolved.lower():
                sys.stderr.write("devant: warning — '%s' resolved to '%s' (%s); not storing that path/id. "
                                 "Pass --path/--no-resolve if intended.\n" % (args.symbol, resolved, info.get("filePath")))
            else:
                path = path or info.get("filePath")
                cg_id = cg_id or info.get("id")
                sys.stderr.write("devant: linked %s -> %s (%s)\n" % (args.node, resolved or args.symbol, info.get("filePath")))
    conn.execute(
        "INSERT OR REPLACE INTO code_link(node,relation,symbol,path,cg_id,note) VALUES(?,?,?,?,?,?)",
        (args.node, args.relation, args.symbol or "", path or "", cg_id, args.note),  # '' not NULL so the PK dedupes
    )
    conn.commit()
    return 0


def cmd_decide(args):
    conn = connect(args, create=True)
    if not (args.body and args.body.strip()):
        sys.stderr.write("devant: decide requires --body (the rationale).\n")
        return 2
    meta = {}
    if args.rejected:
        meta["rejected"] = args.rejected
    if args.why_rejected:
        meta["why_rejected"] = args.why_rejected
    nid = _insert_node(conn, args.id, "decision", args.title, args.body, "accepted",
                       json.dumps(meta) if meta else None)
    for end in (args.realizes or []) + (args.establishes or []) + (args.supersedes or []):
        if not conn.execute("SELECT 1 FROM node WHERE id=?", (end,)).fetchone():
            sys.stderr.write("devant: warning — '%s' is not an existing node; edge will dangle.\n" % end)
    for g in (args.realizes or []):
        conn.execute("INSERT OR IGNORE INTO edge(src,kind,dst) VALUES(?,?,?)", (nid, "realizes", g))
    for c in (args.establishes or []):
        conn.execute("INSERT OR IGNORE INTO edge(src,kind,dst) VALUES(?,?,?)", (nid, "establishes", c))
    for s in (args.supersedes or []):
        conn.execute("INSERT OR IGNORE INTO edge(src,kind,dst) VALUES(?,?,?)", (nid, "supersedes", s))
        row = conn.execute("SELECT * FROM node WHERE id=?", (s,)).fetchone()
        if args.exempt and row and row["kind"] == "constraint":
            # exempt one path: keep the constraint ACTIVE, just stop it firing there
            m = load_meta(row)
            m.setdefault("exempt_paths", [])
            m["exempt_paths"].extend(p for p in args.exempt if p not in m["exempt_paths"])
            conn.execute("UPDATE node SET meta=? WHERE id=?", (json.dumps(m), s))
        else:
            conn.execute("UPDATE node SET status='superseded' WHERE id=? AND status!='superseded'", (s,))
    conn.commit()
    print(nid)
    return 0


# -------------------------------------------------------------- read commands

def _block_constraints(conn):
    return [r for r in _active(conn, "constraint") if load_meta(r).get("severity") == "block"]


def cmd_summary(args):
    conn = connect(args)
    if conn is None:
        if args.json:
            print("{}")
        return 0
    vision = _active(conn, "vision")
    direction = _active(conn, "direction")
    blocks = _block_constraints(conn)
    if args.json:
        print(json.dumps({
            "vision": [dict(r) for r in vision],
            "direction": [dict(r) for r in direction],
            "block_constraints": [dict(r) for r in blocks],
            "empty": not (vision or direction or blocks),
        }))
        return 0
    lines = []
    if vision:
        lines.append("Vision: " + vision[0]["title"])
    if direction:
        lines.append("Direction: " + "; ".join(d["title"] for d in direction))
    if blocks:
        lines.append("Must-not (block rules):")
        for c in blocks:
            exp = load_meta(c).get("expected")
            lines.append("  - %s: %s%s" % (c["id"], c["title"], (" (use: %s)" % exp) if exp else ""))
    if lines:
        print("\n".join(lines))
    return 0


def _relevant(conn, path=None, area=None):
    out = []
    # On an area (prompt) query also consider decisions, so a request that revives a
    # rejected/superseded decision gets challenged. On a path query, only constraints/non-goals.
    kinds = "('constraint','nongoal','decision')" if area is not None else "('constraint','nongoal')"
    rows = conn.execute("SELECT * FROM node WHERE kind IN %s" % kinds).fetchall()
    for r in rows:
        m = load_meta(r)
        # All kinds are area/path-scoped (no unconditional dump). The edit guard enforces block
        # rules at write time regardless of whether they were injected, so scoping the heads-up
        # keeps prompts lean without weakening enforcement.
        if r["kind"] == "decision":
            if r["status"] == "superseded":  # retired — its successor speaks now
                continue
            # surface a decision only when the prompt overlaps its topic (title + rejected
            # alternative — NOT the rationale prose, mirroring the constraint match below), so a
            # revived rejected path is challenged without a long decision body leaking the whole
            # essay in on a shared stopword-grade token.
            if area and _content_tokens(area) & _content_tokens(
                    (r["title"] or "") + " " + (m.get("rejected") or "")):
                out.append(r)
            continue
        if r["status"] != "active":
            continue
        match = path is None and area is None
        if path:
            for g in (m.get("applies_to_paths") or []):
                if path_match(path, g):
                    match = True
            if not match:
                for lk in conn.execute(
                    "SELECT path FROM code_link WHERE node=?", (r["id"],)
                ).fetchall():
                    if lk["path"] and path_match(path, lk["path"]):
                        match = True
        if area and not match:
            toks = _content_tokens(area)
            # Match on the constraint's identifying tokens (title + expected) and its path
            # segments — NOT the rationale prose — so unrelated rules don't leak in on stopwords.
            htoks = _content_tokens((r["title"] or "") + " " + (m.get("expected") or ""))
            for g in (m.get("applies_to_paths") or []):
                htoks |= set(s.lower() for s in re.split(r"[/*.]+", g) if len(s) >= 3)
            if toks & htoks:
                match = True
        if match:
            out.append(r)
    return out


def cmd_constraints(args):
    conn = connect(args)
    if conn is None:
        if args.json:
            print("[]")
        return 0
    rows = _relevant(conn, path=args.path, area=args.area)
    if args.json:
        print(json.dumps([{**dict(r), "meta": load_meta(r)} for r in rows]))
        return 0
    budget = getattr(args, "budget", None)
    budget = 4096 if budget is None else budget
    # Rule-bearing kinds render before decision history so the byte budget can never
    # starve a BLOCK/warn rule in favor of an essay.
    rows = sorted(rows, key=lambda r: r["kind"] == "decision")
    spent, dropped = 0, []
    for r in rows:
        m = load_meta(r)
        if r["kind"] == "decision":
            # tag by STATUS only: recording a rejected ALTERNATIVE doesn't reject the decision
            tag = "REJECTED-DECISION" if r["status"] == "rejected" else "decision"
        elif r["kind"] == "nongoal":
            tag = "nongoal"
        elif m.get("severity") == "block":
            tag = "BLOCK"
        else:
            tag = "warn"
        line = "[%s] %s: %s" % (tag, r["id"], r["title"])
        if m.get("expected"):
            line += " — do: %s" % m["expected"]
        lines = [line]
        if r["body"]:
            lines.append("    %s" % r["body"])
        if m.get("rejected"):
            lines.append("    rejected alternative: %s — %s" % (m.get("rejected"), m.get("why_rejected", "")))
        entry = "\n".join(lines)
        size = len(entry.encode("utf-8")) + 1
        if budget and spent + size > budget:
            dropped.append(r["id"])
            continue
        print(entry)
        spent += size
    if dropped:
        print("    (+%d elided by byte budget: %s — `devant why <id>` or --budget 0)"
              % (len(dropped), ", ".join(dropped[:10])))
    return 0


_RECALL_KIND_W = {"constraint": 2.0, "nongoal": 2.0, "decision": 1.0, "note": 0.8}


def _recency_weight(d):
    # half-life 14 days on the last touch; undated entries sit mid-scale
    import time as _t
    if not d:
        return 0.5
    try:
        age = max(0.0, (_t.time() - _t.mktime(_t.strptime(d[:10], "%Y-%m-%d"))) / 86400.0)
    except ValueError:
        return 0.5
    return 0.5 ** (age / 14.0)


def cmd_recall(args):
    """Budgeted, ranked, titles-only recall of recorded intent for a prompt.
    Replaces the constraints --area body dump on the UserPromptSubmit hot path:
    >=2 shared tokens for decisions/notes (>=1 for rules), score = overlap x kind x
    recency, top 5 under a byte budget, bodies pulled via `devant why`. Ids already
    injected this session (--seen file) stay silent — except block rules."""
    conn = connect(args)
    if conn is None:
        return 0
    ptoks = _content_tokens(args.text)
    if not ptoks:
        return 0
    seen = set()
    if args.seen:
        try:
            with open(args.seen) as fh:
                seen = set(ln.strip() for ln in fh if ln.strip())
        except OSError:
            pass
    scored = []  # (score, rendered_line, dedupe_id, is_block, json_info)
    for r in conn.execute(
            "SELECT * FROM node WHERE kind IN ('constraint','nongoal','decision','note')").fetchall():
        if r["status"] == "superseded":
            continue
        m = load_meta(r)
        is_rule = r["kind"] in ("constraint", "nongoal")
        if is_rule and r["status"] != "active":
            continue
        ntoks = _content_tokens(" ".join(filter(None, (
            r["title"], m.get("expected"), m.get("rejected")))))
        overlap = len(ptoks & ntoks)
        if overlap < (1 if is_rule else 2):
            continue
        is_block = m.get("severity") == "block"
        if r["id"] in seen and not is_block:
            continue
        if r["kind"] == "decision":
            tag = "REJECTED-DECISION" if r["status"] == "rejected" else "decision"
        elif r["kind"] == "nongoal":
            tag = "nongoal"
        elif is_block:
            tag = "BLOCK"
        elif r["kind"] == "constraint":
            tag = "warn"
        else:
            tag = "note"
        line = "[%s] %s: %s" % (tag, r["id"], r["title"])
        if m.get("expected"):
            line += " — do: %s" % m["expected"]
        score = overlap * _RECALL_KIND_W.get(r["kind"], 1.0) * _recency_weight(
            r["updated"] or r["created"])
        scored.append((score, line[:160], r["id"], is_block,
                       {"id": r["id"], "kind": r["kind"], "title": r["title"]}))
    # what recent sessions did is recallable the same way (dec-043 Phase 2)
    if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='session'").fetchone():
        for r in conn.execute("SELECT sid, updated, summary FROM session "
                              "WHERE summary IS NOT NULL AND summary != ''").fetchall():
            overlap = len(ptoks & _content_tokens(r["summary"]))
            if overlap < 2:
                continue
            key = "session:" + r["sid"]
            if key in seen:
                continue
            score = overlap * 1.2 * _recency_weight(r["updated"])
            line = "[session %s] %s" % ((r["updated"] or "")[:10], r["summary"])
            scored.append((score, line[:160], key, False,
                           {"id": key, "kind": "session", "title": r["summary"][:120]}))
    if not scored:
        if args.json:
            print("[]")
        return 0
    scored.sort(key=lambda t: (-t[0], t[2]))
    if args.json:
        print(json.dumps([{**info, "score": round(s, 3)} for s, _, _, _, info in scored[:5]]))
        return 0
    budget = args.budget or 900
    hint = "    (details: devant why <id>)"
    spent, emitted, lines = len(hint) + 1, [], []
    for _, line, did, is_block, _info in scored[:5]:
        size = len(line.encode("utf-8")) + 1
        if spent + size > budget:
            continue
        lines.append(line)
        spent += size
        if not is_block:
            emitted.append(did)
    if not lines:
        return 0
    print("\n".join(lines))
    print(hint)
    # flush before recording ids as seen: under DEVANT_DEADLINE_MS an id must never be
    # marked seen for output the hook never received
    sys.stdout.flush()
    if args.seen and emitted:
        try:
            os.makedirs(os.path.dirname(args.seen) or ".", exist_ok=True)
            with open(args.seen, "a") as fh:
                fh.write("".join(i + "\n" for i in emitted))
        except OSError:
            pass  # dedupe degrades to per-turn injection, never an error
    return 0


def cmd_why(args):
    conn = connect(args)
    if conn is None:
        return 0
    sym = args.symbol
    if conn.execute("SELECT 1 FROM node WHERE id=?", (sym,)).fetchone():
        # the id form ("devant why dec-041") — the pull-on-demand hint that recall and
        # constraints print; resolves the node's full body plus its intent chain
        frontier = [sym]
    else:
        links = conn.execute("SELECT * FROM code_link WHERE symbol=?", (sym,)).fetchall()
        if not links:
            links = conn.execute("SELECT * FROM code_link WHERE symbol LIKE ?", ("%" + sym + "%",)).fetchall()
        frontier = [lk["node"] for lk in links]
    seen, chain = set(), []
    while frontier:
        nid = frontier.pop()
        if nid in seen:
            continue
        seen.add(nid)
        row = conn.execute("SELECT * FROM node WHERE id=?", (nid,)).fetchone()
        if row:
            chain.append(row)
        # Walk UP the intent chain: outgoing realizes/refines/relates AND incoming
        # establishes/refines/realizes (so a symbol linked to a constraint still reaches
        # the decision that established it and the goal/vision behind it).
        for e in conn.execute(
            "SELECT dst AS n FROM edge WHERE src=? AND kind IN ('realizes','refines','relates') "
            "UNION SELECT src AS n FROM edge WHERE dst=? AND kind IN ('establishes','refines','realizes')",
            (nid, nid),
        ).fetchall():
            frontier.append(e["n"])
    if args.json:
        print(json.dumps([{**dict(r), "meta": load_meta(r)} for r in chain]))
        return 0
    if not chain:
        print("No recorded intent for %s." % sym)
        return 0
    for r in chain:
        m = load_meta(r)
        line = "[%s] %s: %s" % (r["kind"], r["id"], r["title"])
        if r["body"]:
            line += " — " + r["body"]
        if m.get("rejected"):
            line += "  (rejected: %s — %s)" % (m.get("rejected"), m.get("why_rejected", ""))
        print(line)
    return 0


def cmd_direction(args):
    conn = connect(args)
    if conn is None:
        return 0
    out = {"vision": [dict(r) for r in _active(conn, "vision")],
           "direction": [dict(r) for r in _active(conn, "direction")],
           "goals": [dict(r) for r in _active(conn, "goal")]}
    if args.json:
        print(json.dumps(out))
        return 0
    if out["vision"]:
        print("Vision: " + out["vision"][0]["title"])
        if out["vision"][0]["body"]:
            print("  " + out["vision"][0]["body"])
    if out["direction"]:
        print("Next:")
        for d in out["direction"]:
            print("  - %s" % d["title"])
    if out["goals"]:
        print("Goals:")
        for g in out["goals"]:
            print("  - %s" % g["title"])
    return 0


def cmd_query(args):
    conn = connect(args)
    if conn is None:
        if args.json:
            print("[]")
        return 0
    like = "%" + args.text + "%"
    rows = conn.execute(
        "SELECT * FROM node WHERE status!='superseded' AND (title LIKE ? OR body LIKE ?) ORDER BY kind, id",
        (like, like),
    ).fetchall()
    if args.json:
        print(json.dumps([{**dict(r), "meta": load_meta(r)} for r in rows]))
        return 0
    for r in rows:
        print("[%s] %s: %s" % (r["kind"], r["id"], r["title"]))
    return 0


def cmd_show(args):
    conn = connect(args)
    if conn is None:
        if args.json:
            print("{}")
        return 0
    nodes = [{**dict(r), "meta": load_meta(r)} for r in conn.execute("SELECT * FROM node ORDER BY kind,id").fetchall()]
    edges = [dict(r) for r in conn.execute("SELECT * FROM edge").fetchall()]
    links = [dict(r) for r in conn.execute("SELECT * FROM code_link").fetchall()]
    if args.json:
        print(json.dumps({"nodes": nodes, "edges": edges, "links": links}))
        return 0
    for n in nodes:
        print("[%s] %s (%s): %s" % (n["kind"], n["id"], n["status"], n["title"]))
    print("-- %d edges, %d code links" % (len(edges), len(links)))
    return 0


def _graph_dangling(conn):
    """Intra-graph dangling refs (edges/links pointing at non-existent nodes). Pure SQL."""
    edges = conn.execute(
        "SELECT e.src, e.kind, e.dst FROM edge e "
        "WHERE NOT EXISTS(SELECT 1 FROM node WHERE id=e.src) OR NOT EXISTS(SELECT 1 FROM node WHERE id=e.dst)"
    ).fetchall()
    links = conn.execute(
        "SELECT cl.node, cl.relation, cl.symbol FROM code_link cl "
        "WHERE NOT EXISTS(SELECT 1 FROM node WHERE id=cl.node)"
    ).fetchall()
    return edges, links


def _index_stale(gconn):
    """True when the git HEAD moved since the index recorded its sync watermark — so impact/
    affected may answer from a pre-move graph. Cheap (one git call); False when not a git repo,
    no index, or no watermark yet."""
    if gconn is None:
        return False
    try:
        row = gconn.execute("SELECT value FROM meta WHERE key='synced_head'").fetchone()
    except sqlite3.Error:
        return False
    synced = row["value"] if row else None
    if not synced:
        return False
    try:
        cur = subprocess.run(["git", "-C", project_dir(), "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return cur.returncode == 0 and cur.stdout.strip() != synced


def cmd_dangling(args):
    conn = connect(args)
    if conn is None:
        return 0
    bad_edges, bad_links = _graph_dangling(conn)
    code_dangling = []
    gconn = graph_conn(args)
    if gconn is not None and gconn.execute("SELECT 1 FROM symbol LIMIT 1").fetchone():
        for lk in conn.execute("SELECT * FROM code_link WHERE symbol IS NOT NULL AND symbol!=''").fetchall():
            name = lk["symbol"].rsplit(".", 1)[-1]
            hit = gconn.execute(
                "SELECT 1 FROM symbol WHERE qualname=? OR name=? LIMIT 1",
                (lk["symbol"], name)).fetchone()
            if hit is None:
                code_dangling.append(lk)
    # stale_index: the git HEAD moved since the last `graph sync` recorded its watermark, so
    # impact/affected answer from a pre-move graph (a pull/checkout that added callers, with no
    # Claude-tool edit to trigger a resync). Was hard-coded False — a promise nothing computed.
    stale = _index_stale(gconn)
    if args.json:
        print(json.dumps({
            "code_dangling": [dict(r) for r in code_dangling],
            "edge_dangling": [dict(r) for r in bad_edges],
            "link_node_missing": [dict(r) for r in bad_links],
            "stale_index": stale,
        }))
        return 0
    if stale:
        print("Index STALE: git HEAD moved since the last sync — run `devant graph sync` before "
              "trusting impact/affected.")
    if code_dangling:
        print("Dangling intent->code links (symbol no longer resolves — re-link or update):")
        for lk in code_dangling:
            print("  - %s %s -> %s" % (lk["node"], lk["relation"], lk["symbol"]))
    if bad_edges or bad_links:
        print("Broken intent edges/links (endpoint node missing):")
        for e in bad_edges:
            print("  - edge %s %s %s" % (e["src"], e["kind"], e["dst"]))
        for lk in bad_links:
            print("  - link from missing node %s -> %s" % (lk["node"], lk["symbol"]))
    return 0


def cmd_lint(args):
    conn = connect(args)
    if conn is None:
        if args.json:
            print("{}")
        return 0
    bad_edges, bad_links = _graph_dangling(conn)
    toothless = []  # block/warn constraints that can never fire (no forbid pattern)
    for c in _active(conn, "constraint"):
        m = load_meta(c)
        if not (m.get("forbid")):
            toothless.append(c["id"])
    no_scope = []  # constraints with neither applies_to_paths nor a constrains code_link
    for c in _active(conn, "constraint"):
        m = load_meta(c)
        has_link = conn.execute(
            "SELECT 1 FROM code_link WHERE node=? AND relation='constrains' AND path!='' LIMIT 1", (c["id"],)
        ).fetchone()
        if not (m.get("applies_to_paths") or has_link):
            no_scope.append(c["id"])
    # dec-016 P3: auto-suggest code links — a decision/constraint that names an indexed
    # symbol (code-ish token: underscore or mixed case) but isn't linked to it.
    suggestions = []
    gconn = graph_conn(args)
    if gconn is not None:
        names = {r["name"] for r in gconn.execute(
            "SELECT DISTINCT name FROM symbol WHERE kind!='module' AND length(name)>=4").fetchall()
            if "_" in r["name"] or not r["name"].islower()}
        if names:
            for n in conn.execute(
                    "SELECT * FROM node WHERE kind IN ('decision','constraint') "
                    "AND status NOT IN ('superseded','rejected')").fetchall():
                toks = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", (n["title"] or "") + " " + (n["body"] or "")))
                have = {lk["symbol"] for lk in conn.execute(
                    "SELECT symbol FROM code_link WHERE node=?", (n["id"],)).fetchall()}
                for h in sorted(toks & names):
                    if not any(h in (s0 or "") for s0 in have):
                        suggestions.append({"node": n["id"], "symbol": h})
                if len(suggestions) >= 10:
                    break
    report = {
        "broken_edges": [dict(r) for r in bad_edges],
        "broken_links": [dict(r) for r in bad_links],
        "constraints_without_forbid": toothless,
        "constraints_without_scope": no_scope,
        "link_suggestions": suggestions[:10],
    }
    if args.json:
        print(json.dumps(report))
        return 0
    clean = True
    for label, items in [
        ("Edges with a missing endpoint", [f"{e['src']} {e['kind']} {e['dst']}" for e in bad_edges]),
        ("Code links from a missing node", [f"{lk['node']} -> {lk['symbol']}" for lk in bad_links]),
        ("Constraints that can never fire (no --forbid)", toothless),
        ("Constraints with no path scope (won't match any edit)", no_scope),
    ]:
        if items:
            clean = False
            print("%s:" % label)
            for it in items:
                print("  - %s" % it)
    if clean:
        print("intent graph: clean.")
    for sug in suggestions[:10]:
        print("suggest: devant link %s %s   (mentioned in %s but not linked)"
              % (sug["node"], sug["symbol"], sug["node"]))
    return 0


def cmd_doctor(args):
    """Self-check: prove the guard engine actually denies, and report wiring/health.
    Exits non-zero if the guard engine is broken (a canary against a silently-dead guard)."""
    mem = sqlite3.connect(":memory:")
    mem.row_factory = sqlite3.Row
    ensure_schema(mem)
    mem.execute(
        "INSERT INTO node(id,kind,title,body,status,meta) VALUES('con-self','constraint','self-test','t','active',?)",
        (json.dumps({"applies_to_paths": ["**/*.py"], "forbid": ["__devant_selftest__"], "severity": "block"}),),
    )
    deny, _ = evaluate_guard("x.py", "y = __devant_selftest__\n", mem)
    allow, _ = evaluate_guard("x.py", "y = 1\n", mem)
    sec_deny, _ = evaluate_guard("s.py", "k = 'ghp_" + "a" * 24 + "'\n", None)
    engine_ok = (deny == "deny" and allow == "allow" and sec_deny == "deny")

    conn = connect(args)
    counts = {}
    if conn is not None:
        for k in KINDS:
            counts[k] = conn.execute("SELECT COUNT(*) c FROM node WHERE kind=?", (k,)).fetchone()["c"]
    usage, dead = _usage_counts()
    node_bin = shutil.which("node")
    elkjs = "absent"
    if node_bin:
        from .drawio import _node_env
        try:
            r = subprocess.run([node_bin, "-e", "require('elkjs')"], capture_output=True,
                               text=True, env=_node_env(), timeout=20)
            elkjs = "available" if r.returncode == 0 else "absent"
        except (OSError, subprocess.TimeoutExpired):
            pass
    gconn = graph_conn(args)
    gfiles = gsyms = 0
    if gconn is not None:
        gfiles = gconn.execute("SELECT COUNT(*) c FROM file").fetchone()["c"]
        gsyms = gconn.execute("SELECT COUNT(*) c FROM symbol WHERE kind!='module'").fetchone()["c"]
    report = {
        "guard_engine": "ok" if engine_ok else "BROKEN",
        "graph_index": ("%d files, %d symbols" % (gfiles, gsyms)) if gfiles
                       else "empty — run `devant graph sync` (or /devant:onboard)",
        "node": "available" if node_bin else "absent",
        "elkjs": elkjs,
        "intent_graph": "present" if conn is not None else "not onboarded (run /devant:onboard)",
        "node_counts": counts,
        "specialist_usage": usage,
        "never_used_specialists": dead,
    }
    remedy = {
        "elkjs": "cd \"$CLAUDE_PLUGIN_DATA\" && npm i elkjs",
        "node": "install Node.js (e.g. via nvm)",
    }
    if args.json:
        print(json.dumps(report))
    else:
        def line(key, label):
            v = report[key]
            print("%s %s" % (label, v if v == "available" else "%s — install: %s" % (v, remedy[key])))
        print("guard engine: %s" % report["guard_engine"])
        print("graph index:  %s" % report["graph_index"])
        line("node", "node:        ")
        line("elkjs", "elkjs:       ")
        print("intent graph: %s" % report["intent_graph"])
        if counts:
            print("nodes:        " + ", ".join("%s=%d" % (k, counts[k]) for k in KINDS if counts.get(k)))
        if usage:
            print("specialists:  " + ", ".join("%s=%d" % (s, usage[s]) for s in SPECIALISTS))
            if dead:
                print("never used:   " + ", ".join(dead) + " (best-effort; logged by the router)")
        if not engine_ok:
            print("WARNING: the edit-guard engine did not behave as expected — block enforcement may be broken.")
    return 0 if engine_ok else 1


def _usage_counts():
    log = os.path.join(project_dir(), ".devant", "state", "usage.log")
    counts = {s: 0 for s in SPECIALISTS}
    try:
        with open(log) as fh:
            for line in fh:
                first = line.strip().split()
                if first and first[0] in counts:
                    counts[first[0]] += 1
    except FileNotFoundError:
        pass
    dead = [s for s, c in counts.items() if c == 0 and s not in SUBINVOKED_SPECIALISTS]
    return counts, dead


def cmd_phase(args):
    """Get/set the project phase state (dec-018): free text plus a compaction gate.
    gate=open -> auto-compact may land now (phase boundary); gate=hold -> the PreCompact
    hook defers proactive auto-compacts until the next boundary."""
    state = os.path.join(project_dir(), ".devant", "state")
    path = os.path.join(state, "phase")
    if args.set is not None:
        os.makedirs(state, exist_ok=True)
        gate = "hold" if args.hold else "open"
        with open(path, "w") as fh:
            json.dump({"text": args.set, "gate": gate, "ts": now()}, fh)
        print(gate)
        return 0
    try:
        with open(path) as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        print("{}" if args.json else "no phase recorded.")
        return 0
    if args.json:
        print(json.dumps(d))
        return 0
    print("[%s] %s (%s)" % (d.get("gate", "open"), d.get("text", ""), d.get("ts", "")))
    return 0


def cmd_goal(args):
    """Get/set/clear the current task's definition of done (P1): the acceptance criteria the
    change must satisfy. Surfaced in the Stop note and re-hydrated at SessionStart so a long
    multi-turn task never loses its own done-conditions. A reminder surface, never a gate — the
    model that sets the criteria also meets them, so a hard gate here could only rubber-stamp
    or falsely wedge; §5 stop-when-stuck still governs when a criterion can't be met."""
    path = os.path.join(project_dir(), ".devant", "state", "goal")
    if args.clear:
        try:
            os.remove(path)
        except OSError:
            pass
        return 0
    if args.set is not None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            json.dump({"text": args.set, "ts": now()}, fh)
        print("set")
        return 0
    try:
        with open(path) as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        print("{}" if args.json else "no goal recorded.")
        return 0
    print(json.dumps(d) if args.json else d.get("text", ""))
    return 0


def cmd_log(args):
    """Append a route to the local usage log (powers dead-skills)."""
    state = os.path.join(project_dir(), ".devant", "state")
    os.makedirs(state, exist_ok=True)
    with open(os.path.join(state, "usage.log"), "a") as fh:
        fh.write("%s %s\n" % (args.specialist, " ".join(args.intent or [])))
    return 0


def cmd_export(args):
    """Dump the intent graph (nodes+edges+links) as JSON. The store is normally local-only and
    gitignored, so a fresh clone / a teammate starts with no rules; committing this export and
    `devant import`-ing it makes 'what NOT to do' travel with the repo (the collaboration artifact)."""
    conn = connect(args)
    if conn is None:
        sys.stderr.write("devant: no intent graph to export (run /devant:onboard first).\n")
        return 1
    data = {
        "nodes": [{**dict(r), "meta": load_meta(r)} for r in
                  conn.execute("SELECT * FROM node ORDER BY kind, id").fetchall()],
        "edges": [dict(r) for r in conn.execute("SELECT src, kind, dst, note FROM edge").fetchall()],
        "links": [dict(r) for r in
                  conn.execute("SELECT node, relation, symbol, path, cg_id, note FROM code_link").fetchall()],
    }
    out = json.dumps(data, indent=2, ensure_ascii=False)
    if getattr(args, "out", None):
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(out + "\n")
        print(args.out)
    else:
        print(out)
    return 0


def cmd_import(args):
    """Load an exported intent graph, upserting by id (existing nodes are updated + journaled, not
    duplicated). Lets a fresh clone / teammate inherit the recorded decisions, constraints, and
    non-goals instead of re-running the onboarding interview."""
    conn = connect(args, create=True)
    try:
        with open(args.file, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        sys.stderr.write("devant: cannot read export %s: %s\n" % (args.file, exc))
        return 1
    n_nodes = n_edges = n_links = 0
    for nd in data.get("nodes", []):
        if not (nd.get("id") and nd.get("kind") and nd.get("title")):
            continue  # skip a malformed row rather than crash the whole import
        meta = nd.get("meta")
        _insert_node(conn, nd["id"], nd["kind"], nd["title"], nd.get("body"),
                     nd.get("status") or "active", json.dumps(meta) if meta else None)
        n_nodes += 1
    for e in data.get("edges", []):
        if not (e.get("src") and e.get("kind") and e.get("dst")):
            continue
        conn.execute("INSERT OR IGNORE INTO edge(src, kind, dst, note) VALUES(?,?,?,?)",
                     (e["src"], e["kind"], e["dst"], e.get("note")))
        n_edges += 1
    for lk in data.get("links", []):
        if not lk.get("node"):
            continue
        conn.execute("INSERT OR REPLACE INTO code_link(node, relation, symbol, path, cg_id, note) "
                     "VALUES(?,?,?,?,?,?)",
                     (lk["node"], lk.get("relation") or "implemented_by", lk.get("symbol") or "",
                      lk.get("path") or "", lk.get("cg_id"), lk.get("note")))
        n_links += 1
    conn.commit()
    print("imported %d nodes, %d edges, %d links" % (n_nodes, n_edges, n_links))
    return 0


def cmd_dead_skills(args):
    counts, dead = _usage_counts()
    if args.json:
        print(json.dumps({"counts": counts, "dead": dead}))
        return 0
    print("Specialist usage: " + ", ".join("%s=%d" % (s, counts[s]) for s in SPECIALISTS))
    if dead:
        print("Never used: " + ", ".join(dead))
    return 0
