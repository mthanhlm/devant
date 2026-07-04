#!/usr/bin/env bash
# PreCompact: compaction summarizes away the once-per-session discipline block, so clear
# the session's primed marker — the next change-intent prompt re-injects it. The intent
# brief itself needs nothing here: SessionStart re-fires with source "compact" and
# re-injects it.
#
# Smart gate (dec-018): a proactive AUTO compact is deferred while the phase gate is
# 'hold' AND a fresh context signal (written by the context monitor) says there's
# headroom (<85%) — the compact then lands at the next phase boundary instead of
# mid-flight. Manual /compact is never blocked. Fail-open: no phase, no fresh signal,
# or >=85% always allows (never veto a near-limit recovery compact). Always exits 0.
LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$LIB/common.sh"

INPUT="$(cat)"
dv_enabled || exit 0
SID="$(dv_sid_from "$INPUT")"
PROJ="$(dv_proj_from "$INPUT")"
STATE="$(dv_state_dir "$PROJ")"
rm -f "$STATE/${SID:-_}.primed" 2>/dev/null

[ "$(printf '%s' "$INPUT" | json_field trigger)" = "auto" ] || exit 0
[ -f "$STATE/phase" ] && [ -f "$STATE/context.pct" ] || exit 0
[ -n "$(find "$STATE/context.pct" -mmin -5 2>/dev/null)" ] || exit 0

python3 - "$STATE/phase" "$STATE/context.pct" <<'PY' 2>/dev/null
import json, sys
try:
    with open(sys.argv[1]) as fh:
        phase = json.load(fh)
    with open(sys.argv[2]) as fh:
        pct = int("".join(c for c in fh.read() if c.isdigit()) or "100")
except Exception:
    sys.exit(0)
if phase.get("gate") != "hold" or pct >= 85:
    sys.exit(0)
print(json.dumps({
    "decision": "block",
    "reason": "[devant] deferring auto-compact: mid-phase (%s); will allow at the next "
              "phase boundary" % (phase.get("text") or "in flight"),
}))
PY
exit 0
