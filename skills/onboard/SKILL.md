---
name: onboard
disable-model-invocation: true
effort: high
allowed-tools: Bash(devant *)
description: One-time project onboarding — build the devant graph index, scan the codebase to understand it, interview only the gaps a scan can't infer, and seed the local intent graph (vision, direction, non-goals, layering rules, conventions). Re-runnable to refresh. Target of /devant:onboard.
---

# devant: onboard

Scan first, then ask only what a scan can't know. One pass, one confirmation, no document
explosion. The intent CLI is `devant` (on the Bash PATH while this plugin is enabled). Output
goes only into the local intent graph — never commit anything.

## 1. Toolchain + init + scan (write only the index)
- **Layout engine (optional, diagrams only):** ensure elkjs in the plugin's data dir
  (survives plugin updates, no global npm pollution):
  `node -e "require('elkjs')"` (with `NODE_PATH="${CLAUDE_PLUGIN_DATA}/node_modules"`) — if it
  fails: `mkdir -p "${CLAUDE_PLUGIN_DATA}" && cd "${CLAUDE_PLUGIN_DATA}" && npm i elkjs`. If npm
  is missing, continue degraded — diagrams still ship hand-laid-out.
- **Preview renderer (diagrams, required for the visual gate, dec-022/dec-023):** ensure
  chrome-headless-shell in the plugin's data dir — the ONLY renderer `devant drawio-preview`
  uses (system Chrome/Edge is never consulted). If
  `ls "${CLAUDE_PLUGIN_DATA}/browsers/chrome-headless-shell" 2>/dev/null` is empty:
  `npx --yes @puppeteer/browsers install chrome-headless-shell@stable --path "${CLAUDE_PLUGIN_DATA}/browsers"`
  (~150MB into the plugin data dir, no sudo — tell the user what's downloading and why). If npx
  is missing, continue and say so: the diagram skill's mandatory visual pass will report this as
  a blocker until onboard is re-run with Node present.
- `devant graph sync` (builds/refreshes the self-owned index — no external tool, dec-016).
- **Native guard backstop (dec-019, default-on):** seed the project's `.claude/settings.json` with
  `permissions.deny: ["Bash(git commit*)", "Bash(git push*)", "Bash(git add*)",
  "Bash(git reset --hard*)", "Bash(git clean -f*)", "Bash(git branch -D*)",
  "Bash(git checkout .*)", "Bash(git restore .*)", "Edit(.devant/**)"]`
  (force-push is subsumed by `git push*`). The destructive set mirrors a typical global
  dangerous-git hook, so onboarded repos don't need one. The native rules also cover the
  Monitor tool and Bash file-writes like `sed -i` into
  `.devant/`, and they survive `DEVANT=off` (devant's own hooks are cooperative). Apply without
  asking ONLY when `.claude/settings.json` is absent or untracked (`git ls-files` empty for it);
  if the file is committed/shared, ask first — silently editing a collaborator-visible file is
  not ours to decide. Either way, state in one line what was written (it's plain JSON, trivially
  reversible). Skipping is fine — the hook guard still enforces block rules.
- **Smart compaction floor (dec-018, default-on):** write `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`
  (default 50) and `CLAUDE_CODE_AUTO_COMPACT_WINDOW` (default 500000) into the `env` block of
  `.claude/settings.local.json` (gitignored; NEVER the shared settings.json). Apply without
  asking — the file is local-only, so there is no externality; state in one line what was
  written. Long sessions then auto-compact early and devant's PreCompact gate defers each
  compact to the next phase boundary.
- `devant graph search` / file listing for layout; read manifests (package.json / pyproject.toml / go.mod / …) for
  the stack; `devant graph explore` on entrypoints (main/index/app/server/cmd) to see how work
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

## Annotate the graph (semantic layer, dec-016 P3 / dec-017)
After the index is built and intent is seeded, add the semantic layer — taxonomy-first hybrid:
1. **Taxonomy once (you, the session model):** from `devant graph status` + the module layout,
   fix ~30–60 concept tags (auth, billing, retry, migration, …). Keep the list in this chat.
2. **Hot symbols (you):** `devant graph hot --limit <5% of symbols>` — annotate each with
   `devant graph annotate --key <key> --type symbol --summary "<1–2 sentences>" --concepts a,b`.
3. **The tail (Haiku fan-out, dec-017):** spawn subagents on Haiku with the FIXED taxonomy in
   their prompt — they read files and emit `devant graph annotate` calls; they apply the
   vocabulary, never invent tags. Runs by default: state the token estimate (files × ~10
   tok/line) in one line and proceed. Ask first only when the estimate is large (> ~1M read
   tokens) — then offer to scope (hot modules only) or skip. Re-runs are incremental
   (`--source-hash` skips unchanged).
Semantic queries then work: `devant graph search <concept>`, `devant graph impact <sym> --semantic`.
