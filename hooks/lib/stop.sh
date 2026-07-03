#!/usr/bin/env bash
# Stop / SubagentStop: keep the codegraph index fresh (debounced sync) and leave
# a note for next turn — impacted tests to confirm green, unfinished markers in
# touched files (NM3), and any dangling intent->code links. Always exits 0.
LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$LIB/common.sh"

INPUT="$(cat)"
dv_enabled || exit 0
CWD="$(printf '%s' "$INPUT" | json_field cwd)"
SID="$(dv_sid "$(printf '%s' "$INPUT" | json_field session_id)")"
PROJ="$(dv_project_dir "$CWD")"
STATE="$(dv_state_dir "$PROJ")"
NOTE=""

TOUCHED="$STATE/${SID:-_}.touched"

# A subagent finishing mid-turn shares the session id; keep the index fresh for it but
# leave .touched for the real Stop — consuming it here would drop later main-turn edits.
if [ "$(printf '%s' "$INPUT" | json_field hook_event_name)" = "SubagentStop" ]; then
  [ -s "$TOUCHED" ] && dv_has_codegraph && (cd "$PROJ" 2>/dev/null && codegraph sync -q >/dev/null 2>&1)
  exit 0
fi

# Only do real work on a turn that actually edited files (no-edit turns stay cheap).
if [ -s "$TOUCHED" ]; then
  dv_has_codegraph && (cd "$PROJ" 2>/dev/null && codegraph sync -q >/dev/null 2>&1)

  NOTE="Before you claim done: deliver real, verified work — actually run it and show real output, not a report of what you would do."

  if dv_has_codegraph; then
    AFF="$(sed "s#^$PROJ/##" "$TOUCHED" | sort -u | (cd "$PROJ" 2>/dev/null && codegraph affected --stdin -q 2>/dev/null) | head -20)"
    [ -n "$AFF" ] && NOTE="${NOTE}
Impacted tests to run and confirm green (compiling is not 'done'):
$AFF"
  fi

  # Space-safe scan for unfinished markers in the files touched this turn.
  STUBS="$(while IFS= read -r f; do [ -f "$f" ] && grep -lEi 'TODO|FIXME|XXX|NotImplementedError|not implemented' -- "$f" 2>/dev/null; done < <(sort -u "$TOUCHED") | head -20)"
  if [ -n "$STUBS" ]; then
    NOTE="${NOTE:+$NOTE
}Unfinished markers (TODO/FIXME/stub) in files you touched — finish or reconcile before claiming done:
$STUBS"
  fi

  # Dangling check: remind at most once per session (don't nag every edit turn).
  if dv_has_devant && [ ! -f "$STATE/${SID:-_}.dangled" ]; then
    DANG="$(cd "$PROJ" && dv_devant dangling 2>/dev/null | head -20)"
    if [ -n "$DANG" ]; then
      NOTE="${NOTE:+$NOTE
}$DANG"
      : > "$STATE/${SID:-_}.dangled" 2>/dev/null
    fi
  fi

  rm -f "$TOUCHED" 2>/dev/null
fi

[ -n "$NOTE" ] && printf '%s\n' "$NOTE" > "$STATE/${SID:-_}.lastturn" 2>/dev/null
exit 0
