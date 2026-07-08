#!/usr/bin/env bash
# UserPromptSubmit: inject (a) the lean change-discipline block once per session on
# code-intent prompts (NM7 dedupe via .primed), and (b) `devant recall` — budgeted,
# ranked, titles-only recorded-intent hits for THIS prompt — on EVERY prompt,
# questions included ("why did we…?" is exactly where past decisions matter). Ids
# inject once per session (.seen; block rules exempt); bodies stay pull-on-demand
# via `devant why`. (dec-043 Phase 1 — replaces the constraints --area body dump.)
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
    # Quoted heredoc: nothing expands, so the `devant graph affected` backticks reach the
    # model as literal text instead of executing at prompt time (dec-043 Phase 0).
    CTX="$(cat <<'DEVANT_DISCIPLINE'
[devant] Before changing code:
- Necessity/Reuse ladder: 1) does it need to exist? 2) already here? (search the devant graph, reuse — don't rewrite) 3) stdlib 4) platform 5) existing dep 6) one line 7) only then the minimum that works.
- Size by BLAST RADIUS (devant graph impact/callers), not lines. No fixed pipeline: trivial -> one fast pass, no ceremony; wide fan-out -> a brief visible outline, then execute. Never quarter a small change.
- Substantial change: post a short visible plan first. Design/review/docs/diagrams/slides go to their specialist skill; trivial work, just do it.
- PUSH BACK if the request is wrong-layer, debt-prone, or contradicts recorded intent — name the cheaper correct path BEFORE editing. The user is not always right.
- Done = verified: a bug needs a FAILING repro test first; run the `devant graph affected` subset; lint changed files. Compiling is NOT 'done'. Show real output. A test that can't fail before the fix proves nothing.
- Cite the devant graph/intent for claims about the code, or flag them as assumptions. Keep private intent (vision, decisions, rejected paths) out of commits, PRs, and code comments unless asked.
DEVANT_DISCIPLINE
)"
  fi
fi

RULES=""
dv_has_devant && RULES="$(cd "$PROJ" && DEVANT_DEADLINE_MS=1500 dv_devant recall --budget 900 --seen "$STATE/${SID:-_}.seen" -- "$PROMPT" 2>/dev/null)"
if [ -n "$RULES" ]; then
  CTX="${CTX:+$CTX
}[devant] Recorded intent related to this prompt (block rules are machine-enforced by the edit guard):
$RULES"
fi

[ -z "$CTX" ] && exit 0
printf '%s' "$CTX" | dv_emit UserPromptSubmit
exit 0
