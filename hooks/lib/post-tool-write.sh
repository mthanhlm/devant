#!/usr/bin/env bash
# PostToolUse (Write|Edit|MultiEdit): record the touched file for the Stop reconciler.
# This runs only after a write actually happened — recording in PreToolUse counted
# edits the user denied, so the Stop note could name tests for an edit that never
# landed. Always exits 0.
LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$LIB/common.sh"

INPUT="$(cat)"
dv_enabled || exit 0
FP="$(printf '%s' "$INPUT" | json_field tool_input.file_path)"
[ -n "$FP" ] || exit 0
CWD="$(printf '%s' "$INPUT" | json_field cwd)"
SID="$(dv_sid "$(printf '%s' "$INPUT" | json_field session_id)")"
PROJ="$(dv_project_dir "$CWD")"
printf '%s\n' "$FP" >> "$(dv_state_dir "$PROJ")/${SID:-_}.touched" 2>/dev/null
exit 0
