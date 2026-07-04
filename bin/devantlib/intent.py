"""Intent-graph commands (add-node/decide/link/constraints/why/…) and the codegraph
subprocess helpers. Imported lazily by the CLI — never on the guard hot path."""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys

from .common import (EDGE_KINDS, KINDS, SPECIALISTS, _active, _content_tokens, connect,
                     ensure_schema, load_meta, next_id, now, path_match, project_dir)
from .guard import evaluate_guard


def cg_available():
    """True if the codegraph CLI is usable (and not disabled)."""
    return os.environ.get("DEVANT_CODEGRAPH", "on") != "off" and shutil.which("codegraph") is not None


def cg_resolve(symbol):
    """Resolve a symbol to {filePath, id, qualifiedName} via codegraph, or None."""
    if not cg_available():
        return None
    try:
        out = subprocess.run(
            ["codegraph", "query", symbol, "-j", "-l", "1"],
            capture_output=True, text=True, timeout=20,
        )
        data = json.loads(out.stdout)
    except Exception:
        return None
    items = data if isinstance(data, list) else (data.get("results") or data.get("nodes") or [])
    if not items:
        return None
    it = items[0]
    node = it.get("node") if isinstance(it.get("node"), dict) else it  # `codegraph query -j` nests fields under .node
    return {
        "filePath": node.get("filePath") or node.get("file") or node.get("path"),
        "id": node.get("id"),
        "qualifiedName": node.get("qualifiedName") or node.get("name"),
    }


def cg_status():
    """Parsed `codegraph status -j`, or None when codegraph is unavailable/unreadable."""
    if not cg_available():
        return None
    try:
        out = subprocess.run(["codegraph", "status", "-j"], capture_output=True, text=True, timeout=20)
        return json.loads(out.stdout)
    except Exception:
        return None


def cg_stale(status):
    """True if the index lags the working tree (uncommitted drift). Lets readers warn before
    trusting a stale index — the watcher is off on some filesystems (e.g. WSL2 /mnt)."""
    if not status:
        return False
    if status.get("worktreeMismatch"):
        return True
    pc = status.get("pendingChanges") or {}
    return any(pc.get(k) for k in ("added", "modified", "removed"))


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
        info = cg_resolve(args.symbol)
        if info:
            resolved = (info.get("qualifiedName") or "")
            want = args.symbol.lower().rsplit(".", 1)[-1]
            # codegraph query is fuzzy; if the top hit doesn't actually contain the requested
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
            # surface a decision only when the prompt overlaps its topic (title/body/rejected),
            # so a revived rejected path is challenged; skip generic accepted decisions.
            if area and _content_tokens(area) & _content_tokens(
                    (r["title"] or "") + " " + (r["body"] or "") + " " + (m.get("rejected") or "")):
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
    for r in rows:
        m = load_meta(r)
        if r["kind"] == "decision":
            tag = "REJECTED-DECISION" if (r["status"] == "rejected" or m.get("rejected")) else "decision"
        elif r["kind"] == "nongoal":
            tag = "nongoal"
        elif m.get("severity") == "block":
            tag = "BLOCK"
        else:
            tag = "warn"
        line = "[%s] %s: %s" % (tag, r["id"], r["title"])
        if m.get("expected"):
            line += " — do: %s" % m["expected"]
        print(line)
        if r["body"]:
            print("    %s" % r["body"])
        if m.get("rejected"):
            print("    rejected alternative: %s — %s" % (m.get("rejected"), m.get("why_rejected", "")))
    return 0


def cmd_why(args):
    conn = connect(args)
    if conn is None:
        return 0
    sym = args.symbol
    links = conn.execute("SELECT * FROM code_link WHERE symbol=?", (sym,)).fetchall()
    if not links:
        links = conn.execute("SELECT * FROM code_link WHERE symbol LIKE ?", ("%" + sym + "%",)).fetchall()
    seen, frontier, chain = set(), [lk["node"] for lk in links], []
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
    """Intra-graph dangling refs (edges/links pointing at non-existent nodes). Pure SQL, no codegraph."""
    edges = conn.execute(
        "SELECT e.src, e.kind, e.dst FROM edge e "
        "WHERE NOT EXISTS(SELECT 1 FROM node WHERE id=e.src) OR NOT EXISTS(SELECT 1 FROM node WHERE id=e.dst)"
    ).fetchall()
    links = conn.execute(
        "SELECT cl.node, cl.relation, cl.symbol FROM code_link cl "
        "WHERE NOT EXISTS(SELECT 1 FROM node WHERE id=cl.node)"
    ).fetchall()
    return edges, links


def cmd_dangling(args):
    conn = connect(args)
    if conn is None:
        return 0
    bad_edges, bad_links = _graph_dangling(conn)
    code_dangling = []
    stale = False
    if cg_available():
        stale = cg_stale(cg_status())  # a stale index makes symbol re-resolution unreliable (R2)
        for lk in conn.execute("SELECT * FROM code_link WHERE symbol IS NOT NULL AND symbol!=''").fetchall():
            if cg_resolve(lk["symbol"]) is None:
                code_dangling.append(lk)
    if args.json:
        print(json.dumps({
            "code_dangling": [dict(r) for r in code_dangling],
            "edge_dangling": [dict(r) for r in bad_edges],
            "link_node_missing": [dict(r) for r in bad_links],
            "stale_index": stale,
        }))
        return 0
    if stale:
        print("Note: codegraph index looks stale (uncommitted changes not yet synced) — run "
              "'codegraph sync' first; intent->code results below may be unreliable.")
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
    report = {
        "broken_edges": [dict(r) for r in bad_edges],
        "broken_links": [dict(r) for r in bad_links],
        "constraints_without_forbid": toothless,
        "constraints_without_scope": no_scope,
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
    report = {
        "guard_engine": "ok" if engine_ok else "BROKEN",
        "codegraph": "available" if cg_available() else "absent",
        "node": "available" if node_bin else "absent",
        "elkjs": elkjs,
        "intent_graph": "present" if conn is not None else "not onboarded (run /devant:onboard)",
        "node_counts": counts,
        "specialist_usage": usage,
        "never_used_specialists": dead,
    }
    remedy = {
        "codegraph": "npm i -g @colbymchenry/codegraph",
        "elkjs": "npm i -g elkjs",
        "node": "install Node.js (e.g. via nvm)",
    }
    if args.json:
        print(json.dumps(report))
    else:
        def line(key, label):
            v = report[key]
            print("%s %s" % (label, v if v == "available" else "%s — install: %s" % (v, remedy[key])))
        print("guard engine: %s" % report["guard_engine"])
        line("codegraph", "codegraph:   ")
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
    dead = [s for s, c in counts.items() if c == 0 and s != "onboard"]
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


def cmd_log(args):
    """Append a route to the local usage log (powers dead-skills)."""
    state = os.path.join(project_dir(), ".devant", "state")
    os.makedirs(state, exist_ok=True)
    with open(os.path.join(state, "usage.log"), "a") as fh:
        fh.write("%s %s\n" % (args.specialist, " ".join(args.intent or [])))
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
