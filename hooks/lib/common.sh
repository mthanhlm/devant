#!/usr/bin/env bash
# devant — shared hook helpers. Pure stdlib (bash + python3). Never aborts a
# session: callers always exit 0 and degrade when codegraph / the devant CLI
# are absent.

# Resolve the devant CLI. Prefer the plugin root Claude Code injects; fall back
# to a path relative to this file (hooks/lib -> plugin root) so hooks are
# testable standalone.
_DV_LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEVANT_BIN="${CLAUDE_PLUGIN_ROOT:-$_DV_LIB/../..}/bin/devant"

# dv_enabled: master switch. DEVANT=off disables all devant hook behavior.
dv_enabled() { [ "${DEVANT:-on}" != "off" ]; }

# dv_has_codegraph: is the codegraph CLI usable? DEVANT_CODEGRAPH=off disables
# the codegraph lifecycle (structural features then degrade to Read/Grep).
dv_has_codegraph() { [ "${DEVANT_CODEGRAPH:-on}" != "off" ] && command -v codegraph >/dev/null 2>&1; }

# dv_has_devant: is the devant CLI present and python3 available?
dv_has_devant() { [ -f "$DEVANT_BIN" ] && command -v python3 >/dev/null 2>&1; }

# dv_devant <args...>: invoke the devant CLI (no-op-safe; prints nothing on failure).
dv_devant() { python3 "$DEVANT_BIN" "$@" 2>/dev/null; }

# json_field <key>: read a JSON object on stdin, print the value at <key>
# (dotted path supported, e.g. tool_input.file_path). Objects/arrays are
# re-encoded as JSON; missing keys print empty.
json_field() {
  python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    print(""); sys.exit(0)
v = d
for part in sys.argv[1].split("."):
    if isinstance(v, dict) and part in v:
        v = v[part]
    else:
        print(""); sys.exit(0)
if isinstance(v, bool):
    print("true" if v else "false")   # JSON booleans -> lowercase for shell string compares
elif isinstance(v, (dict, list)):
    print(json.dumps(v))
elif v is None:
    print("")
else:
    print(v)
' "$1"
}

# dv_project_dir <cwd>: locate the project root. Honors CLAUDE_PROJECT_DIR,
# else walks up from <cwd> to the nearest .git/.devant, else echoes <cwd>.
dv_project_dir() {
  if [ -n "${CLAUDE_PROJECT_DIR:-}" ] && [ -d "${CLAUDE_PROJECT_DIR}" ]; then
    printf '%s' "$CLAUDE_PROJECT_DIR"; return
  fi
  local d="${1:-$PWD}"
  while [ -n "$d" ] && [ "$d" != "/" ]; do
    if [ -d "$d/.git" ] || [ -d "$d/.devant" ]; then printf '%s' "$d"; return; fi
    d="$(dirname "$d")"
  done
  printf '%s' "${1:-$PWD}"
}

# dv_sid <session_id>: slug a session id so it can't traverse paths when used in a filename.
dv_sid() { printf '%s' "${1:-_}" | tr -c 'A-Za-z0-9_.-' '_'; }

# dv_state_dir <proj>: ensure and echo the gitignored local state dir.
dv_state_dir() {
  local s="$1/.devant/state"
  mkdir -p "$s" 2>/dev/null
  printf '%s' "$s"
}

# dv_ensure_local_ignore <proj>: keep devant artifacts out of git WITHOUT
# touching the shared .gitignore — write to .git/info/exclude (per-clone, never
# committed). Handles worktrees via `git rev-parse`. No-op outside a git repo.
dv_ensure_local_ignore() {
  local proj="$1" excl
  command -v git >/dev/null 2>&1 || return 0
  ( cd "$proj" 2>/dev/null && git rev-parse --is-inside-work-tree >/dev/null 2>&1 ) || return 0
  excl="$(cd "$proj" 2>/dev/null && git rev-parse --git-path info/exclude 2>/dev/null)"
  [ -n "$excl" ] || return 0
  case "$excl" in /*) : ;; *) excl="$proj/$excl" ;; esac
  mkdir -p "$(dirname "$excl")" 2>/dev/null
  touch "$excl" 2>/dev/null || return 0
  local pat
  for pat in ".devant/" ".codegraph/"; do
    grep -qxF "$pat" "$excl" 2>/dev/null || printf '%s\n' "$pat" >> "$excl"
  done
}

# dv_emit <eventName>: read context text on stdin, emit the hook JSON that
# injects it as additionalContext. Prints nothing for empty input.
dv_emit() {
  python3 -c '
import sys, json
ctx = sys.stdin.read()
if ctx.strip():
    print(json.dumps({"hookSpecificOutput": {"hookEventName": sys.argv[1], "additionalContext": ctx}}))
' "$1"
}
