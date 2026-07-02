#!/usr/bin/env bash
# PreCompact: compaction summarizes away the once-per-session discipline block, so clear
# the session's primed marker — the next change-intent prompt re-injects it. The intent
# brief itself needs nothing here: SessionStart re-fires with source "compact" and
# re-injects it. Always exits 0.
LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$LIB/common.sh"

INPUT="$(cat)"
dv_enabled || exit 0
CWD="$(printf '%s' "$INPUT" | json_field cwd)"
SID="$(dv_sid "$(printf '%s' "$INPUT" | json_field session_id)")"
PROJ="$(dv_project_dir "$CWD")"
rm -f "$(dv_state_dir "$PROJ")/${SID:-_}.primed" 2>/dev/null
exit 0
