#!/usr/bin/env bash
# SessionStart: ensure the codegraph index exists, keep devant artifacts out of
# git (.git/info/exclude), enable global auto-compact on first-ever run, and
# inject the project-intent brief (or nudge onboarding when the intent graph
# is empty). Always exits 0.
LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$LIB/common.sh"

INPUT="$(cat)"
CWD="$(printf '%s' "$INPUT" | json_field cwd)"
PROJ="$(dv_project_dir "$CWD")"
dv_enabled || exit 0
mkdir -p "$PROJ/.devant" 2>/dev/null
dv_ensure_local_ignore "$PROJ"

SYSMSG=""
[ "$(dv_ensure_global_autocompact)" = "set" ] && SYSMSG="[devant] Enabled autoCompactEnabled in ~/.claude/settings.json (one-time, global) so long sessions auto-compact instead of hitting the context limit. Edit that file to turn it back off."

# Hygiene: drop per-session state from long-gone sessions and cap the usage log.
STATE="$(dv_state_dir "$PROJ")"
find "$STATE" -maxdepth 1 -type f \( -name '*.primed' -o -name '*.dangled' -o -name '*.lastturn' -o -name '*.touched' \) -mtime +7 -delete 2>/dev/null
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

printf '%s' "$CTX" | dv_emit SessionStart "$SYSMSG"
exit 0
