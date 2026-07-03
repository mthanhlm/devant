# Changelog

Notable changes to devant. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [0.6.0] - 2026-07-03

### Added
- `devant:diagram` **real-done beauty gate** — a diagram is no longer "done" just because it opens;
  it must be provably clean (no overlaps, crooked nodes, or tangled edges) before delivery.
  - New **`devant drawio-lint <file> [--fix]`** subcommand (stdlib `xml.etree`, dec-001 holds).
    `--fix` **auto-fixes** what's safe — grid-snaps crooked nodes straight, spreads real overlaps to
    a 40px gap — and **exits non-zero** while any judgment-needing defect remains (unresolved
    overlaps, non-orthogonal edges, edges missing geometry, duplicate ids, off-canvas cells). Only
    *position* snaps (not sizes); nested/concentric shapes (e.g. a UML final-node core) are left
    alone. Recorded as `dec-008`.
  - `SKILL.md` step 6 is now a two-tier gate: **(always)** `drawio-lint --fix` until it exits 0;
    **(draw.io CLI present — the real "done")** ELK layout, export a plain PNG, *read it*, and fix
    the perceptual defects the linter can't measure (label collisions, tangle) — ≤2 rounds.
    Degrades gracefully with no CLI (dec-007 core preserved: the CLI is never required).
  - `README` names **codegraph + the draw.io CLI** as the prerequisites for the full experience;
    the `drawio-cli.md`/`drawio-guide.md` references flip from "export off by default" to the
    plain-PNG visual self-check.

### Changed
- Plugin-wide **no report-only** discipline: the Stop hook now leads every edit turn with "deliver
  real, verified work — actually run it and show real output, not a report of what you would do."
  Read-only-by-design specialists (`ask`/`architect`/`review`) stay non-editing by contract.
  Recorded as `dec-009`.

## [0.5.0] - 2026-07-03

### Changed
- Make devant a **grounded debating peer, not a servant** — applies the "goal loop" discipline
  (define done, ground in real code/data, debate to shared clarity) as prose, with no
  `/loop`·`/schedule`·`/goal` runtime and zero new deps (dec-001 holds). Recorded as direction
  `dir-003`.
  - `devant:architect` — grounding is now a **gate**: the current-design section must cite the
    real symbols/files and data model actually read (else "N/A — stateless"). New `§1.5`
    **case-awareness** gate: design for the actual scenario in *this* system and settle materially
    different readings with the user *before* designing. `§2` **depth floor**: unfinished until
    failure-mode/data-model/blast-radius axes carry concrete consequences tied to grounded symbols
    and name the pattern that fits this stack — a generic happy-path sketch is a failed run.
  - `devant:router` — push-back upgraded from a one-shot veto to a **sustained, grounded,
    bounded, scoped debate**: challenge with evidence, concede only to better evidence (never to
    insistence), and hand the user a clean decision on genuine judgment calls; trivial/clear
    requests keep the fast path.
  - `devant:ask` — challenge a question's premise when the code/intent contradicts it, grounded
    and read-only, instead of answering as asked.
  - `devant:code` — `§4` makes **green the explicit exit** ("done" = verification actually green;
    red you caused is not done → fix and re-verify). `§5`'s evidence-based stop is unchanged.

## [0.4.1] - 2026-07-03

### Changed
- `devant:diagram` + `devant:architect` clarity rules — diagrams must show *enough* that a
  first-time reader (dev or not) understands the whole story with no walkthrough, and no more.
  Added to the draw.io guide (and surfaced in both SKILL.md files):
  - **Completeness bar**: show every real step, branch, loop, and error path that changes what
    happens, plus key edge data; fold away anything that doesn't. Bar = minimal questions.
  - **Loops-as-loops**: a repeat is a single labelled back-edge (`[retry ≤ 3]`), routed out with
    a waypoint — never cloned nodes. Ships a copy-ready loop-edge snippet.
  - **Arc line-jumps**: unavoidable edge crossings use `jumpStyle=arc;jumpSize=10;` so a crossing
    reads as an arc hop, not an ambiguous intersection.
  - **Label-overlap avoidance**: an edge label must never sit on a node's text or another label;
    ordered fixes (reroute → white background → offset along edge) and ≥ 40 px between parallel
    edges. Extended the pre-save eyeball list and section-6 checklist accordingly.

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
