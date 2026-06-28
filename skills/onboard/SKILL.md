---
name: onboard
user-invocable: false
description: One-time project onboarding — run codegraph init, scan the codebase to understand it, interview only the gaps a scan can't infer, and seed the local intent graph (vision, direction, non-goals, layering rules, conventions). Re-runnable to refresh. Target of /devant:onboard.
---

# devant: onboard

Scan first, then ask only what a scan can't know. One pass, one confirmation, no document
explosion. The intent CLI is `python3 "${CLAUDE_PLUGIN_ROOT}/bin/devant"` (`devant` below). Output
goes only into the local intent graph — never commit anything.

## 1. Init + scan (write only the index)
- `codegraph init -i` (builds/refreshes the local index for this repo).
- `codegraph_files` for layout; read manifests (package.json / pyproject.toml / go.mod / …) for
  the stack; `codegraph_explore` on entrypoints (main/index/app/server/cmd) to see how work
  flows. Derive candidate **modules** (id/path/role) and candidate **layer boundaries**.

## 2. Auto-draft + ask for docs
- Draft, silently, an architecture summary, the module list, and likely conventions
  (test framework, error/logging idiom) from the scan. Auto-read `README` if present.
- Ask once: "Point me at anything that already captures intent — README, ADRs, a roadmap,
  design notes — I'll read it instead of asking you to retype."

## 3. Interview — ONLY the gaps, each prefilled with your guess, batched into one reply
1. What is this & who is it for? *(guess: …)*
2. The **vision** / north-star.
3. The **direction** — next 1–2 milestones.
4. **Non-goals** — what's out of scope / what should I refuse or push back on?
5. **Layering rules** — "I detected these boundaries: […]. Which are real rules? For each:
   **block** (deny the edit) or **warn** (ask)?"
6. **Conventions** — tests / errors / logging *(prefilled — confirm or correct)*.
Don't ask anything the scan already answered. Accept "looks right" as confirmation.

## 4. Confirm → seed in one pass (idempotent; stable ids so re-runs update, never duplicate)
Show a compact preview (vision · direction · non-goals · rules · conventions · modules), then on
confirmation write it with the CLI:
- `devant add-node --kind vision --id vision-001 --title "…" --body "…"`
- `devant add-node --kind direction --title "…"` (one per milestone); `devant add-edge <dir> refines vision-001`
- `devant add-node --kind nongoal --title "…" --body "…"`
- `devant add-node --kind constraint --id <slug> --title "…" --body "<why>" --applies "<glob>" --forbid "<substr>" [--expected "<sanctioned path>"] --severity block|warn`
- `devant add-node --kind decision --title "…" --body "<why>" [--rejected "…" --why-rejected "…"]`
- Link rules/modules to code: `devant link <id> <qualifiedName> --relation constrains|governs|implemented_by`
Constraint and decision nodes REQUIRE a rationale (`--body`). One confirmation, one write pass.
