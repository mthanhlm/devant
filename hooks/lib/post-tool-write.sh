#!/usr/bin/env bash
# PostToolUse (Write|Edit|MultiEdit|NotebookEdit): record the touched file for the Stop
# reconciler. This runs only after a write actually happened — recording in PreToolUse
# counted edits the user denied, so the Stop note could name tests for an edit that never
# landed. Always exits 0.
LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$LIB/common.sh"

INPUT="$(cat)"
dv_enabled || exit 0
FP="$(printf '%s' "$INPUT" | json_field tool_input.file_path)"
[ -n "$FP" ] || FP="$(printf '%s' "$INPUT" | json_field tool_input.notebook_path)"
[ -n "$FP" ] || exit 0
SID="$(dv_sid_from "$INPUT")"
PROJ="$(dv_proj_from "$INPUT")"
printf '%s\n' "$FP" >> "$(dv_state_dir "$PROJ")/${SID:-_}.touched" 2>/dev/null
exit 0
