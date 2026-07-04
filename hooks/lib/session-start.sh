#!/usr/bin/env bash
# SessionStart: ensure the codegraph index exists, keep devant artifacts out of
# git (.git/info/exclude), enable global auto-compact on first-ever run, and
# inject the project-intent brief (or nudge onboarding when the intent graph
# is empty). Always exits 0.
LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$LIB/common.sh"

INPUT="$(cat)"
dv_enabled || exit 0
PROJ="$(dv_proj_from "$INPUT")"
mkdir -p "$PROJ/.devant" 2>/dev/null
dv_ensure_local_ignore "$PROJ"

# autoCompactEnabled defaults to true since Claude Code v2.1.119 — devant no longer
# touches the user's global settings; it only warns when auto-compact is disabled,
# because the smart-compaction scheduler (dec-018) depends on it.
SYSMSG=""
[ -n "${DISABLE_AUTO_COMPACT:-}" ] && SYSMSG="[devant] DISABLE_AUTO_COMPACT is set — smart compaction (dec-018) can't schedule anything; long sessions will hit the context limit."

# Hygiene: drop per-session state from long-gone sessions and cap the usage log.
STATE="$(dv_state_dir "$PROJ")"
find "$STATE" -maxdepth 1 -type f \( -name '*.primed' -o -name '*.dangled' -o -name '*.lastturn' -o -name '*.touched' \) -mtime +7 -delete 2>/dev/null

# Persist what the context monitor can't discover on its own: this session's transcript
# path (fixes the two-sessions-one-repo mixup) and the model (window-size fallback).
TP="$(printf '%s' "$INPUT" | json_field transcript_path)"
[ -n "$TP" ] && printf '%s' "$TP" > "$STATE/transcript.path" 2>/dev/null
MODEL="$(printf '%s' "$INPUT" | json_field model)"
[ -n "$MODEL" ] && printf '%s' "$MODEL" > "$STATE/model" 2>/dev/null
if [ -s "$STATE/usage.log" ] && [ "$(wc -l < "$STATE/usage.log" 2>/dev/null)" -gt 5000 ]; then
  tail -n 1000 "$STATE/usage.log" > "$STATE/usage.log.new" 2>/dev/null && mv "$STATE/usage.log.new" "$STATE/usage.log"
fi

CTX=""
if dv_has_codegraph; then
  ST="$(cd "$PROJ" 2>/dev/null && codegraph status -j 2>/dev/null)"
  FILES="$(printf '%s' "$ST" | json_field fileCount)"
  if [ "$(printf '%s' "$ST" | json_field initialized)" = "true" ] && [ -n "$FILES" ] && [ "$FILES" != "0" ]; then
    CTX="CodeGraph index ready ($FILES files)."
  elif [ "$(printf '%s' "$ST" | json_field initialized)" = "true" ]; then
    CTX="CodeGraph initialized but 0 files indexed (it resolves nothing yet) — run /devant:onboard or 'codegraph sync'."
  else
    # Don't block the session on a full index here — onboarding owns `codegraph init -i`.
    CTX="CodeGraph not indexed yet — run /devant:onboard to build the index and capture project intent."
  fi
else
  CTX="codegraph CLI not found (mandatory — install: npm i -g @colbymchenry/codegraph, or run /devant:onboard which installs it) — structural queries fall back to Read/Grep until then."
fi

SUMMARY=""
dv_has_devant && SUMMARY="$(cd "$PROJ" && dv_devant summary 2>/dev/null)"
if [ -n "$SUMMARY" ]; then
  CTX="$CTX
[devant] Project intent (honor it; the guard enforces block rules):
$SUMMARY"
else
  CTX="$CTX
[devant] No project intent captured yet — run /devant:onboard to scan this repo and capture its vision, direction, non-goals, and rules. Until then I answer from codegraph alone."
fi

# Phase re-hydration (dec-018): after a compact (or resume) the conversation summary may
# drop where we are — the phase file is the durable answer, so inject it for all sources.
if [ -f "$STATE/phase" ]; then
  PHASE="$(python3 -c "import json,sys;d=json.load(open(sys.argv[1]));print('[devant] Phase: [%s] %s' % (d.get('gate','open'), d.get('text','')))" "$STATE/phase" 2>/dev/null)"
  [ -n "$PHASE" ] && CTX="$CTX
$PHASE"
fi

printf '%s' "$CTX" | dv_emit SessionStart "$SYSMSG"
exit 0
