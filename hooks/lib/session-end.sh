#!/usr/bin/env bash
# SessionEnd: final session-memory capture plus the optional distillation pass
# (host `claude` CLI, haiku, 45s timeout, DEVANT=off inside — no hook recursion).
# Crash-safe by design: Stop already captured incrementally, so losing this hook
# loses only the distilled phrasing, never the record. Always exits 0.
LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$LIB/common.sh"

INPUT="$(cat)"
dv_enabled || exit 0
dv_has_devant || exit 0
SID="$(dv_sid_from "$INPUT")"
PROJ="$(dv_proj_from "$INPUT")"
STATE="$(dv_state_dir "$PROJ")"
[ -n "$SID" ] || exit 0

TP="$(printf '%s' "$INPUT" | json_field transcript_path)"
[ -n "$TP" ] || TP="$(cat "$STATE/transcript.path" 2>/dev/null)"
if [ -f "$TP" ]; then
  (cd "$PROJ" 2>/dev/null && DEVANT_DEADLINE_MS=3000 dv_devant session-capture --sid "$SID" --transcript "$TP" >/dev/null 2>&1)
fi
(cd "$PROJ" 2>/dev/null && dv_devant session-distill --sid "$SID" >/dev/null 2>&1)
exit 0
