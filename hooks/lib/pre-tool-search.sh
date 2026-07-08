#!/usr/bin/env bash
# PreToolUse Grep/Glob: demand-driven graph augment (dec-048, mechanism learned from
# codebase-memory-mcp). When the search pattern names an indexed symbol, inject the
# top graph hits as additionalContext beside the normal search results — context
# arrives at the moment of need instead of being pushed every prompt. Never Read
# (that would break read-before-edit), and NEVER blocks: every miss/error/timeout
# path exits 0 with no output.
LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$LIB/common.sh"

INPUT="$(cat)"
dv_enabled || exit 0
dv_graph_enabled || exit 0
dv_has_devant || exit 0
PROJ="$(dv_proj_from "$INPUT")"
PAT="$(printf '%s' "$INPUT" | json_field tool_input.pattern)"
[ -n "$PAT" ] || exit 0
# Drop regex escapes first (\bfoo\b, \w, \d …) so the escape letter can't glue onto the
# identifier ('bfoo') and silently miss the graph.
PAT="$(printf '%s' "$PAT" | sed -E 's/\\[a-zA-Z]/ /g')"

# Longest identifier-ish token, >=4 chars — short/globby patterns skip before any work.
TOKEN="$(printf '%s' "$PAT" | grep -oE '[A-Za-z_][A-Za-z0-9_]{3,}' | awk '{ print length, $0 }' | sort -rn | head -1 | cut -d' ' -f2-)"
[ -n "$TOKEN" ] || exit 0

HITS="$(cd "$PROJ" 2>/dev/null && DEVANT_DEADLINE_MS=500 dv_devant graph search "$TOKEN" --limit 5 2>/dev/null | grep '^\[symbol\]' | head -5)"
[ -n "$HITS" ] || exit 0

printf '%s\n%s' "[devant] Indexed symbols matching '$TOKEN' (source: devant graph explore <name>):" "$HITS" | dv_emit PreToolUse
exit 0
