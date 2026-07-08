#!/usr/bin/env bash
# Stop / SubagentStop: keep the devant graph index fresh (debounced sync) and feed the
# reconciliation note — impacted tests to confirm green, unfinished markers in touched
# files (NM3), dangling intent->code links — back to Claude IN THE SAME TURN via the
# Stop hook's native additionalContext (it used to be a .lastturn file replayed on the
# next prompt, which arrived after "done" was already claimed). Always exits 0.
LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$LIB/common.sh"

INPUT="$(cat)"
dv_enabled || exit 0
# Loop guard: when this Stop was itself triggered by our continue-feedback, do nothing.
[ "$(printf '%s' "$INPUT" | json_field stop_hook_active)" = "true" ] && exit 0
SID="$(dv_sid_from "$INPUT")"
PROJ="$(dv_proj_from "$INPUT")"
STATE="$(dv_state_dir "$PROJ")"
NOTE=""

TOUCHED="$STATE/${SID:-_}.touched"

# A subagent finishing mid-turn shares the session id; keep the index fresh for it but
# leave .touched for the real Stop — consuming it here would drop later main-turn edits.
if [ "$(printf '%s' "$INPUT" | json_field hook_event_name)" = "SubagentStop" ]; then
  [ -s "$TOUCHED" ] && dv_graph_enabled && dv_has_devant && (cd "$PROJ" 2>/dev/null && dv_devant graph sync >/dev/null 2>&1)
  exit 0
fi

# Session memory capture (dec-043 Phase 2): unconditional and silent, EVERY main turn —
# a pure-conversation turn still lands in the record. Crash-safe: parses only the
# transcript delta past a stored byte offset.
TP="$(printf '%s' "$INPUT" | json_field transcript_path)"
[ -n "$TP" ] || TP="$(cat "$STATE/transcript.path" 2>/dev/null)"
if dv_has_devant && [ -n "$SID" ] && [ -f "$TP" ]; then
  (cd "$PROJ" 2>/dev/null && DEVANT_DEADLINE_MS=2000 dv_devant session-capture --sid "$SID" --transcript "$TP" >/dev/null 2>&1)
fi

# Only do real work on a turn that actually edited files (no-edit turns stay cheap).
if [ -s "$TOUCHED" ]; then
  dv_graph_enabled && dv_has_devant && (cd "$PROJ" 2>/dev/null && dv_devant graph sync >/dev/null 2>&1)

  # The note is content-gated (dec-043 Phase 0): it fires only when there is a real
  # finding (goal, affected tests, stubs, dangling) — the unconditional "deliver real
  # verified work" sermon cost one extra model turn on every clean edit turn.
  GOAL="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('text',''))" "$STATE/goal" 2>/dev/null)"
  [ -n "$GOAL" ] && NOTE="Acceptance criteria you set for this task — confirm each is met AND verified before claiming done:
$GOAL"

  if dv_graph_enabled && dv_has_devant; then
    AFF="$(while IFS= read -r f; do printf '%s\n' "${f#"$PROJ"/}"; done < "$TOUCHED" | sort -u | (cd "$PROJ" 2>/dev/null && DEVANT_DEADLINE_MS=2000 dv_devant graph affected --stdin 2>/dev/null) | head -20)"
    [ -n "$AFF" ] && NOTE="${NOTE:+$NOTE
}Impacted tests to run and confirm green (compiling is not 'done'):
$AFF"
  fi

  # Unfinished markers the change ADDED in files touched this turn (added-lines scan).
  STUBS="$(sort -u "$TOUCHED" | dv_scan_stubs "$PROJ" | head -20)"
  if [ -n "$STUBS" ]; then
    NOTE="${NOTE:+$NOTE
}Unfinished markers (TODO/FIXME/stub) in files you touched — finish or reconcile before claiming done:
$STUBS"
  fi

  # Dangling check: remind at most once per session (don't nag every edit turn).
  if dv_has_devant && [ ! -f "$STATE/${SID:-_}.dangled" ]; then
    DANG="$(cd "$PROJ" && DEVANT_DEADLINE_MS=2000 dv_devant dangling 2>/dev/null | head -20)"
    if [ -n "$DANG" ]; then
      NOTE="${NOTE:+$NOTE
}$DANG"
      : > "$STATE/${SID:-_}.dangled" 2>/dev/null
    fi
  fi

  rm -f "$TOUCHED" 2>/dev/null
fi

[ -n "$NOTE" ] && printf '%s' "$NOTE" | dv_emit Stop
exit 0
