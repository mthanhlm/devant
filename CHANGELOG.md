# Changelog

Notable changes to devant. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [0.4.0] - 2026-07-03

### Added
- Two new router-only specialist skills (dec-007):
  - `devant:architect` — design-first pass grounded in codegraph + the intent graph that
    surfaces the critical decisions/failure modes a request glosses over (data model,
    failure handling, concurrency, migration/rollback, security, scaling, coupling,
    testing), presents current-vs-proposed in chat, approval-gates, then renders the design
    via `devant:diagram` and hands off to `devant:code`. Never writes code or plan files.
  - `devant:diagram` — draws C4-style architecture and standard UML activity diagrams as
    self-contained `.drawio` (mxGraph XML) into `docs/diagrams/`, grounded in real code.
    Ships a full style + template guide (palette, layout, edge-crossing rules, XML
    well-formedness, valid skeletons). Optional `drawio` desktop CLI is used only for ELK
    auto-layout; the plugin never installs or requires it (zero-install baseline holds), and
    no draw.io MCP is used. Default deliverable is the `.drawio` file only — no image export.
- Router routing table gains `design`/`architect` and `draw`/`diagram` rows; `architect` and
  `diagram` added to the specialist set so routes are logged.

## [0.3.3] - 2026-07-02

### Changed
- Skills no longer pin `model` (dec-006, supersedes dec-005): every skill runs on whatever
  model the invoking session uses. Per-skill `effort` is now graded by role instead of a
  flat default: router=low, intent=low, ask=medium, document=medium, code=high, onboard=high,
  review=xhigh.

## [0.3.2] - 2026-07-02

### Added
- `SessionStart` enables `autoCompactEnabled` in the user's global settings.json
  (`CLAUDE_CONFIG_DIR`, default `~/.claude`) the first time it's ever absent, with a
  one-time visible message. Never overwrites an explicit `true`/`false` the user already
  set. There is no install-time hook in Claude Code, so this approximates "on install"
  via a no-op-after-first-run check on every `SessionStart`.

## [0.3.1] - 2026-07-02

### Changed
- Skills pin `model` again (dec-004, supersedes dec-003): sonnet baseline across the board,
  `review` pins opus so the independent reviewer is a stronger, different model than the
  writer. Effort tiers unchanged (code=high, review=xhigh, rest=medium). Accepted trade-off:
  a routed skill runs its pinned model even when the session runs a higher tier.

## [0.3.0] - 2026-07-02

### Fixed
- Git guard closes the remaining worktree-discard gaps: `git restore` (unless purely
  `--staged`), `git checkout .` / `git checkout <ref> <pathspec>`, and
  `git switch --discard-changes`/`-f` are now denied.
- Superseded decisions no longer resurface in `constraints --area` as live intent;
  only their successor speaks for the topic.
- `SubagentStop` no longer consumes the session's touched-file list mid-turn; it only
  refreshes the codegraph index and leaves reconciliation to the real Stop.
- Touched files are recorded by a new PostToolUse hook instead of PreToolUse, so a
  write the user denies is no longer counted as an edit.
- Replaced deprecated `load_module()` in the hook helpers and tests — its removal in a
  future Python would have silently disabled both guards.

### Changed
- Skills no longer pin `model` (a SKILL.md model is a turn-scoped override that silently
  replaced the user's chosen model); per-skill `effort` tiers remain
  (code=high, review=xhigh, others=medium).
- New PreCompact hook clears the session's primed marker so the change-discipline block
  is re-injected after compaction (the intent brief already re-injects via SessionStart's
  `compact` source).
- SessionStart prunes per-session state files older than 7 days and caps `usage.log`.

### Added
- MIT `LICENSE`, GitHub Actions CI (Python 3.10–3.13), and this changelog.

## [0.2.4]
- Per-skill model/effort defaults; always-visible plan-before-code step in `devant:code`;
  plainer push-back in the router.

## [0.2.3]
- Enforced git guard (deny commit/push/add and destructive git); codegraph
  index-freshness check; bounded fix loops; read-only `ask` fork and high-risk-only
  `review` skill.

## [0.2.2]
- Dropped the advisory PreToolUse Bash guard (reinstated as an enforced deny in 0.2.3).

## [0.2.1]
- Renamed the main command to `/devant:run`.

## [0.2.0]
- First single-command release: router + specialist skills, local intent-graph CLI,
  edit guard, codegraph onboarding.
