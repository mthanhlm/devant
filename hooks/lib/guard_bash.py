#!/usr/bin/env python3
"""PreToolUse(Bash) git-guard helper.

Reads the hook event JSON on stdin, evaluates the devant Bash guard in-process via evaluate_bash()
in bin/devant, and prints the PreToolUse decision JSON (deny) or nothing (allow). Always exits 0.
"""
import json
import os
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
    command = (d.get("tool_input") or {}).get("command") or ""
    try:
        decision, reason = dv.evaluate_bash(command)
    except Exception:
        return 0
    if decision in ("deny", "ask"):
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
