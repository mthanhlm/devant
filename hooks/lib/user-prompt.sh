#!/usr/bin/env bash
# UserPromptSubmit: on a code-intent prompt inject the lean discipline (ladder,
# blast-radius sizing, push-back, verification bar, grounded-or-flagged +
# private-rationale norms) plus the recorded do/don'ts for the touched area. The
# heavy block is injected once per session (NM7 dedupe); the area rules are
# injected every relevant turn. (The last-turn note is now delivered natively by
# the Stop hook in the same turn — no carry-forward here.)
# Soft (context only) — never blocks. Exits 0.
LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$LIB/common.sh"

INPUT="$(cat)"
dv_enabled || exit 0
PROMPT="$(printf '%s' "$INPUT" | json_field prompt)"
SID="$(dv_sid_from "$INPUT")"
PROJ="$(dv_proj_from "$INPUT")"
STATE="$(dv_state_dir "$PROJ")"

CTX=""
# Inject change-discipline only when there's a change verb AND the prompt isn't an
# information question. "could you add…/can you fix…/should we refactor…" are REQUESTS (inject);
# "why did we add…/how does…/what is…" lead with an info word (skip — asking, not editing).
INFO_LEAD=0
printf '%s' "$PROMPT" | grep -qiE '^[[:space:]]*(how|why|what|which|who|whose|when|where|does|do|did|is|are|am|was|were|explain|show|list|tell|describe)\b' && INFO_LEAD=1
# Fire on change-verbs AND on problem/imperative phrasings ("it's broken", "the parser is slow",
# "sort out the login") so the heads-up isn't limited to a narrow verb list. Pure "how/why" questions
# still lead with an info word and are skipped — the edit guard enforces block rules regardless.
if [ "$INFO_LEAD" = "0" ] && printf '%s' "$PROMPT" | grep -qiE '\b(implement|add|fix|refactor|creat|build|chang|updat|writ|renam|delet|remov|migrat|optimi|debug|wire|integrat|introduc|support|broke|break|fail|error|bug|issue|crash|slow|speed|faster|sort out|handl|clean up|get rid|deprecat|replac|tidy|harden|simplif|rework|rewrit|upgrad|bump|disabl|enabl|configur|tweak|patch|resolv|repair)'; then
  PRIMED="$STATE/${SID:-_}.primed"
  if [ ! -f "$PRIMED" ]; then
    : > "$PRIMED" 2>/dev/null
    CTX="[devant] Before changing code:
- Necessity/Reuse ladder: 1) does it need to exist? 2) already here? (search codegraph, reuse — don't rewrite) 3) stdlib 4) platform 5) existing dep 6) one line 7) only then the minimum that works.
- Size by BLAST RADIUS (codegraph impact/callers), not lines. No fixed pipeline: trivial -> one fast pass, no ceremony; wide fan-out -> a brief visible outline, then execute. Never quarter a small change.
- Route substantial work to the specialist instead of inlining it; trivial work, just do it.
- PUSH BACK if the request is wrong-layer, debt-prone, or contradicts recorded intent — name the cheaper correct path BEFORE editing. The user is not always right.
- Done = verified: a bug needs a FAILING repro test first; run the codegraph affected subset; lint changed files. Compiling is NOT 'done'. Show real output. A test that can't fail before the fix proves nothing.
- Cite codegraph/intent for claims about the code, or flag them as assumptions. Keep private intent (vision, decisions, rejected paths) out of commits, PRs, and code comments unless asked."
  fi
  RULES=""
  dv_has_devant && RULES="$(cd "$PROJ" && dv_devant constraints --area "$PROMPT" 2>/dev/null | head -40)"
  if [ -n "$RULES" ]; then
    CTX="${CTX:+$CTX
}[devant] Recorded do/don'ts for this area (block rules are enforced by the edit guard):
$RULES"
  fi
fi

[ -z "$CTX" ] && exit 0
printf '%s' "$CTX" | dv_emit UserPromptSubmit
exit 0
