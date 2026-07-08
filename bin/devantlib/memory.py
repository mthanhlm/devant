"""Session memory (dec-043 Phase 2): unconditional, hook-driven capture of what each
session did — prompts, files edited, commands (failures kept preferentially), errors,
end-of-turn conclusions, intent refs — into ONE bounded row per session in intent.db.
Capture parses the transcript JSONL from a per-session byte offset, so every Stop is a
cheap delta and a crash loses at most the final turn. The extractive floor never
depends on a model; `session-distill` (the host `claude` CLI, if present) is optional
garnish. Retrieval: `session-brief` at SessionStart; summaries also feed recall."""
import json
import os
import re
import shutil
import subprocess
import time

from .common import connect, project_dir

CAPS = {"prompts": 20, "files": 30, "commands": 20, "errors": 10, "tails": 5, "refs": 10}
RECORD_BYTES = 4096
SUMMARY_BYTES = 600
KEEP_FULL = 30      # newest N sessions keep their full record
KEEP_ROWS = 200     # older rows keep summary only, beyond this deleted
READ_CAP = 2 * 1024 * 1024  # bound one capture's work on a huge unseen backlog

_REF_RE = re.compile(r"\b(?:dec|con|nongoal|goal|dir)-[a-z0-9]+\b")


def ensure_session_schema(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS session(
      sid TEXT PRIMARY KEY, proj TEXT, started TEXT, updated TEXT, ended TEXT,
      summary TEXT, record TEXT, t_offset INTEGER DEFAULT 0);
    CREATE INDEX IF NOT EXISTS session_proj ON session(proj, updated);
    """)
    conn.commit()


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _texts(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _fresh_record():
    return {"prompts": [], "files": [], "commands": [], "errors": [],
            "tails": [], "refs": [], "n_prompts": 0}


def _note_refs(rec, text):
    for ref in _REF_RE.findall(text or ""):
        if ref not in rec["refs"]:
            rec["refs"].append(ref)


def _extract_line(rec, cmds, line):
    d = json.loads(line)
    if d.get("isSidechain"):
        return
    t = d.get("type")
    m = d.get("message") or {}
    c = m.get("content")
    if t == "user":
        if d.get("isMeta"):
            return
        if isinstance(c, str):
            s = c.strip()
            # command wrappers, caveats and task notifications all lead with a tag
            if s and not s.startswith("<"):
                rec["prompts"].append(s[:160])
                rec["n_prompts"] += 1
                _note_refs(rec, s)
        elif isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error"):
                    txt = _texts(b.get("content"))[:120]
                    if txt:
                        rec["errors"].append(txt)
                    tid = b.get("tool_use_id")
                    if tid in cmds:
                        cmds[tid]["ok"] = False
    elif t == "assistant" and isinstance(c, list):
        for b in c:
            if not isinstance(b, dict):
                continue
            bt = b.get("type")
            if bt == "text":
                tail = (b.get("text") or "").strip()
                if tail:
                    rec["tails"].append(tail[-300:])
                    _note_refs(rec, tail)
            elif bt == "tool_use":
                name = b.get("name") or ""
                inp = b.get("input") or {}
                if not isinstance(inp, dict):
                    continue
                if name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
                    p = inp.get("file_path") or inp.get("notebook_path")
                    if p and p not in rec["files"]:
                        rec["files"].append(p)
                elif name == "Bash":
                    cmd = (inp.get("command") or "").strip()[:100]
                    if cmd:
                        cmds[b.get("id") or "c%d" % len(cmds)] = {"cmd": cmd, "ok": True}


def _trim(rec):
    # failures are the memory markdown plugins capture and devant used to lose —
    # keep every failure first, newest successes fill the rest
    fails = [c for c in rec["commands"] if not c.get("ok")][-15:]
    okays = [c for c in rec["commands"] if c.get("ok")]
    rec["commands"] = fails + okays[-(CAPS["commands"] - len(fails)):]
    if len(rec["prompts"]) > CAPS["prompts"]:
        rec["prompts"] = rec["prompts"][:3] + rec["prompts"][-(CAPS["prompts"] - 3):]
    rec["files"] = rec["files"][-CAPS["files"]:]
    rec["errors"] = rec["errors"][-CAPS["errors"]:]
    tails = []
    for tl in rec["tails"]:
        if not tails or tails[-1] != tl:
            tails.append(tl)
    rec["tails"] = tails[-CAPS["tails"]:]
    rec["refs"] = rec["refs"][:CAPS["refs"]]
    # hard byte cap: shed the bulkiest context first, never error
    for drop in ("tails", "prompts", "errors", "commands", "files"):
        while len(json.dumps(rec)) > RECORD_BYTES and len(rec[drop]) > 1:
            rec[drop].pop(0)
    return rec


def _summarize(rec):
    parts = []
    if rec["files"]:
        names = ", ".join(os.path.basename(f) for f in rec["files"][:4])
        parts.append("did: edited %d file(s) [%s]" % (len(rec["files"]), names))
    elif rec["prompts"]:
        parts.append("discussed: %s" % rec["prompts"][0][:120])
    nfail = sum(1 for c in rec["commands"] if not c.get("ok"))
    if rec["commands"]:
        parts.append("%d cmds (%d failed)" % (len(rec["commands"]), nfail))
    if rec["tails"]:
        parts.append("last: %s" % rec["tails"][-1][:220])
    if rec["refs"]:
        parts.append("refs: %s" % " ".join(rec["refs"][:5]))
    return " · ".join(parts)[:SUMMARY_BYTES]


def _evict(conn, proj):
    keep_full = [r[0] for r in conn.execute(
        "SELECT sid FROM session WHERE proj=? ORDER BY updated DESC LIMIT ?",
        (proj, KEEP_FULL)).fetchall()]
    conn.execute(
        "UPDATE session SET record=NULL WHERE proj=? AND record IS NOT NULL AND sid NOT IN (%s)"
        % ",".join("?" * len(keep_full)), [proj, *keep_full])
    keep_rows = [r[0] for r in conn.execute(
        "SELECT sid FROM session WHERE proj=? ORDER BY updated DESC LIMIT ?",
        (proj, KEEP_ROWS)).fetchall()]
    conn.execute(
        "DELETE FROM session WHERE proj=? AND sid NOT IN (%s)" % ",".join("?" * len(keep_rows)),
        [proj, *keep_rows])
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 180 * 86400))
    conn.execute("DELETE FROM session WHERE proj=? AND updated < ?", (proj, cutoff))


def cmd_session_capture(args):
    conn = connect(args, create=True)
    if conn is None:
        return 0
    ensure_session_schema(conn)
    proj = project_dir()
    row = conn.execute("SELECT * FROM session WHERE sid=?", (args.sid,)).fetchone()
    offset = (row["t_offset"] or 0) if row else 0
    try:
        size = os.path.getsize(args.transcript)
    except OSError:
        return 0
    if size < offset:  # rotated/replaced transcript — start over
        offset = 0
    rec = _fresh_record()
    if row and row["record"]:
        try:
            saved = json.loads(row["record"])
            rec.update({k: saved.get(k, v) for k, v in rec.items()})
        except ValueError:
            pass
    cmds = {}
    consumed = offset
    if size > offset:
        with open(args.transcript, "rb") as fh:
            fh.seek(offset)
            chunk = fh.read(min(size - offset, READ_CAP))
        end = chunk.rfind(b"\n")
        if end >= 0:
            consumed = offset + end + 1
            for line in chunk[:end].splitlines():
                try:
                    _extract_line(rec, cmds, line.decode("utf-8", "replace"))
                except Exception:
                    continue  # transcript format is not an API; a bad line never breaks capture
        elif len(chunk) == READ_CAP:
            # a single line >= READ_CAP (huge paste/tool result) can never parse — skip
            # past its newline so the cursor can't wedge for the rest of the session
            with open(args.transcript, "rb") as fh:
                fh.seek(offset + READ_CAP)
                while True:
                    blk = fh.read(READ_CAP)
                    if not blk:
                        break  # newline not written yet — retry on the next capture
                    nl = blk.find(b"\n")
                    if nl >= 0:
                        consumed = fh.tell() - len(blk) + nl + 1
                        break
    rec["commands"].extend(cmds.values())
    rec = _trim(rec)
    ts = _now_iso()
    conn.execute(
        "INSERT INTO session(sid, proj, started, updated, summary, record, t_offset) "
        "VALUES(?,?,?,?,?,?,?) ON CONFLICT(sid) DO UPDATE SET "
        "updated=excluded.updated, summary=excluded.summary, record=excluded.record, "
        "t_offset=excluded.t_offset",
        (args.sid, proj, ts, ts, _summarize(rec), json.dumps(rec), consumed))
    _evict(conn, proj)
    conn.commit()
    return 0


def cmd_session_brief(args):
    conn = connect(args)
    if conn is None:
        return 0
    ensure_session_schema(conn)
    rows = conn.execute(
        "SELECT * FROM session WHERE proj=? AND summary IS NOT NULL AND summary != '' "
        "ORDER BY updated DESC LIMIT ?", (project_dir(), args.last)).fetchall()
    if args.json:
        print(json.dumps([{"sid": r["sid"], "updated": r["updated"], "summary": r["summary"]}
                          for r in rows]))
        return 0
    budget, spent = args.budget or 600, 0
    for r in rows:
        line = "[session %s] %s" % ((r["updated"] or "")[:10], r["summary"])
        size = len(line.encode("utf-8")) + 1
        if spent + size > budget and spent:
            break
        print(line[:budget])
        spent += size
    return 0


def cmd_session_distill(args):
    """Optional one-shot Haiku compression of the extractive record into the summary.
    Every failure path is silent: the extractive floor is the guaranteed tier."""
    if os.environ.get("DEVANT_MEM_DISTILL", "on") == "off":
        return 0
    claude = shutil.which("claude")
    if not claude:
        return 0
    conn = connect(args)
    if conn is None:
        return 0
    ensure_session_schema(conn)
    row = conn.execute("SELECT * FROM session WHERE sid=?", (args.sid,)).fetchone()
    if not row or not row["record"]:
        return 0
    prompt = ("Compress this coding-session record into <=500 characters of plain text, "
              "format: 'did: ...; decided: ...; rejected: ...; open: ...'. Omit empty "
              "sections. No markdown, no preamble.\n\n" + row["record"])
    try:
        # DEVANT=off stops the nested claude's own devant hooks — no recursion
        r = subprocess.run([claude, "-p", "--model", "haiku"], input=prompt,
                           capture_output=True, text=True, timeout=45,
                           env=dict(os.environ, DEVANT="off"))
        out = (r.stdout or "").strip()
        if r.returncode == 0 and 20 <= len(out) <= 800:
            conn.execute("UPDATE session SET summary=?, ended=? WHERE sid=?",
                         (out[:SUMMARY_BYTES], _now_iso(), args.sid))
            conn.commit()
    except (OSError, subprocess.SubprocessError):
        pass
    return 0
