# Changelog

Notable changes to devant. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

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
