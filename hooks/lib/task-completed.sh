#!/usr/bin/env bash
# TaskCompleted: exit 2 blocks the task from being marked complete — the mechanical
# teeth behind "done = verified". A task claiming completion while files touched this
# session still carry unfinished markers is not complete. Fail-open on any gap
# (no state, no tracking, DEVANT=off): never wedge task flow. dec-019.
LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$LIB/common.sh"

INPUT="$(cat)"
dv_enabled || exit 0
SID="$(dv_sid_from "$INPUT")"
PROJ="$(dv_proj_from "$INPUT")"
TOUCHED="$(dv_state_dir "$PROJ")/${SID:-_}.touched"
[ -s "$TOUCHED" ] || exit 0

STUBS="$(while IFS= read -r f; do [ -f "$f" ] && grep -lEi "$DV_STUB_RE" -- "$f" 2>/dev/null; done < <(sort -u "$TOUCHED") | head -5)"
[ -z "$STUBS" ] && exit 0
echo "[devant] Task not complete: unfinished markers (TODO/FIXME/stub) remain in touched files: $(printf '%s' "$STUBS" | tr '\n' ' ')— finish or reconcile them first." >&2
exit 2
