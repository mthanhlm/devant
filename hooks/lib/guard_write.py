#!/usr/bin/env python3
"""PreToolUse(Write|Edit|MultiEdit) edit-guard helper.

Reads the hook event JSON on stdin, evaluates the devant edit guard in-process (no shell
field-splitting — the previous bash NUL round-trip silently broke the guard), records the
touched file for the Stop reconciler, and prints the PreToolUse decision JSON (deny/ask) or
nothing (allow). Always exits 0.
"""
import json
import os
import re
import sys
from importlib.machinery import SourceFileLoader

_HERE = os.path.dirname(os.path.abspath(__file__))
_BIN = None
for cand in (
    os.path.join(os.environ.get("CLAUDE_PLUGIN_ROOT", ""), "bin", "devant"),
    os.path.normpath(os.path.join(_HERE, "..", "..", "bin", "devant")),
):
    if cand and os.path.isfile(cand):
        _BIN = cand
        break


def main():
    if not _BIN:
        return 0
    try:
        dv = SourceFileLoader("devant_mod", _BIN).load_module()
        d = json.load(sys.stdin)
    except Exception:
        return 0  # degrade silently; never block the session
    ti = d.get("tool_input") or {}
    content = ti.get("content")
    if content is None:
        content = ti.get("new_string")
    if content is None:
        content = "\n".join(e.get("new_string", "") for e in (ti.get("edits") or []))
    content = content or ""
    fp = ti.get("file_path") or ""
    if not fp:
        return 0
    cwd = d.get("cwd") or ""
    sid = re.sub(r"[^A-Za-z0-9_.-]", "_", d.get("session_id") or "_")  # slug: never let SID traverse paths
    if cwd and not os.environ.get("CLAUDE_PROJECT_DIR"):
        try:
            os.chdir(cwd)
        except OSError:
            pass

    try:
        proj = dv.project_dir()
        rel = dv.rel_to_project(fp, proj)
        db = os.path.join(proj, ".devant", "intent.db")
        conn = None
        if os.path.exists(db):
            import sqlite3
            conn = sqlite3.connect(db, timeout=5.0)
            conn.row_factory = sqlite3.Row
            dv.ensure_schema(conn)
        decision, reason = dv.evaluate_guard(rel, content, conn, file_exists=os.path.exists(fp))
    except Exception:
        return 0

    if decision != "deny":
        # allow/ask -> the edit will proceed; record it for the Stop reconciler.
        try:
            state = os.path.join(proj, ".devant", "state")
            os.makedirs(state, exist_ok=True)
            with open(os.path.join(state, sid + ".touched"), "a") as fh:
                fh.write(fp + "\n")
        except OSError:
            pass

    if decision in ("deny", "ask"):
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
