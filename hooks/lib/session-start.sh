#!/usr/bin/env bash
# SessionStart: ensure the codegraph index exists, keep devant artifacts out of
# git (.git/info/exclude), and inject the project-intent brief (or nudge
# onboarding when the intent graph is empty). Always exits 0.
LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$LIB/common.sh"

INPUT="$(cat)"
CWD="$(printf '%s' "$INPUT" | json_field cwd)"
PROJ="$(dv_project_dir "$CWD")"
dv_enabled || exit 0
mkdir -p "$PROJ/.devant" 2>/dev/null
dv_ensure_local_ignore "$PROJ"

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
  CTX="codegraph CLI not found — structural queries fall back to Read/Grep."
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

printf '%s' "$CTX" | dv_emit SessionStart
exit 0
