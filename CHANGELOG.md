# Changelog

Notable changes to devant. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [0.18.0] - 2026-07-09

The dec-043 restructure (phases 0–4): per-turn injection cut ~94% (20–24KB → ≤1.5KB worst turn),
hook-driven session memory, skills 11→8 around a single `work` entry point, spec-first artifacts
with committed specs. Grounded in a 55-agent audit (36 confirmed findings) and an adversarial
12-agent diff review (8 majors found and fixed pre-release). Four mechanisms adapted from
DeusData/codebase-memory-mcp as native stdlib implementations (dec-048 — reference design only,
never a dependency).

### Added
- **`devant recall <text> [--budget 900] [--seen FILE]`**: ranked, titles-only recall of recorded
  intent for a prompt — ≥2 shared tokens for decisions/notes (≥1 for rules), score = overlap ×
  kind × 14-day-half-life recency, top 5 under a byte budget, bodies pulled via `devant why <id>`.
  Ids inject once per session (`.seen`; block rules exempt); fires on question prompts too, which
  previously got zero intent context.
- **Session memory (`bin/devantlib/memory.py`, stdlib)**: every Stop/PreCompact/SessionEnd runs
  `devant session-capture` — an extractive transcript-delta parse (prompts, files edited,
  commands with failures kept preferentially, errors, end-of-turn conclusions, dec-refs) into ONE
  bounded row per session in intent.db, behind a crash-safe byte-offset cursor (oversized ≥2MiB
  lines are skipped, never wedge). Two-stage eviction: 30 full records → 200 summary-only →
  180-day delete (~220KB ceiling, zero markdown files). `devant session-brief` injects the last
  sessions' digests at SessionStart; digests are recall candidates. Optional
  `devant session-distill` (host `claude -p --model haiku`, 45s timeout, `DEVANT=off` inside,
  fail-open to the extractive floor).
- **PreToolUse Grep/Glob graph augment (`hooks/lib/pre-tool-search.sh`)**: a search pattern that
  names an indexed symbol gets the top-5 graph hits injected beside the results — demand-driven
  context instead of per-prompt push. Regex escapes stripped (`\bfoo\b` works), min-token gate,
  500ms deadline, never intercepts Read, every miss/error path exits 0 silently.
- **`DEVANT_DEADLINE_MS`** (`common.maybe_arm_deadline`, armed in CLI main): hard in-process
  deadline for hook hot paths — on expiry the process exits 0 with unflushed output discarded,
  so a hook sees a clean no-op, never a stall or a partial payload.
- **`skills/work`** (replaces router+code+ask+intent): dispatch table, hook-recall trust, blast-
  radius sizing, code's evidence-not-claims verification section verbatim, one 3-item
  hold-position evidence test. **`skills/design`** (replaces architect + always-on debate):
  step-0 keep/bend/replace verdict — "prototype/known-bad" flips grounding to replace mode —
  2–3 triaged axes, inline 3-objection red-team (one mandatorily incumbent-fitness), recorded-
  decision staleness + `--supersedes` offer at the gate, debate as a priced opt-in escalation.
- `devant why <id>` resolves intent-node ids (the pull-on-demand hint recall prints) — previously
  only code-link symbols resolved.
- `devant constraints --budget N` (default 4096, 0 = unlimited): in-process byte cap; rule-bearing
  kinds render before decision history; elided ids are named, never silent.

### Changed
- **UserPromptSubmit** injects the ≤900B recall instead of the `constraints --area` body dump
  (measured 10–24KB/turn, ~95% noise, single-token matching, growing with the store). Worst
  first-prompt payload on this repo's live store: 24,184B → ≤1,463B. Identifier tokens split on
  case/underscore boundaries so prose prompts match code-ish titles.
- **Stop note is content-gated**: fires only on real findings (goal/affected tests/stubs/
  dangling) — the unconditional sermon cost one model turn on every clean edit turn.
- **Skills 11→8** (`work`, `design`, `debate`, `review`, `document`, `onboard`, `diagram`,
  `slide`); `commands/run.md` targets `devant:work`; debate demoted to escalation-only
  (dec-044 supersedes dec-024/dec-037), keeping evidence tiers + kill-shot protocol + Opus pin
  for the elected path; `quality.md` moves to `skills/work/references/`.
- **Artifacts are spec-first with COMMITTED specs (dec-045/046/047)**: `docs/diagrams/<n>.spec.json`
  and `docs/slides/<n>.deck.json` are the source of truth — re-runs read and PATCH them, so
  hand-tuning survives regeneration. Visual gates on-demand (user ask / lint failure / raw path;
  slide keeps 1+1); lint stays the always-on floor. `drawio-guide.md` splits: ~8KB default read
  (header + §0 + §6); §1–§5 + §7 move to a lazily-read `raw-xml-escape.md` (~25KB). A diagram
  request's ingest drops ~46.6KB → ~12KB; studio stays in-repo behind the lazy references.
- Tags in text output are by STATUS only — accepted decisions no longer render as
  `[REJECTED-DECISION]` just for recording a rejected alternative (every emitted tag was a
  mislabel).

### Fixed
- Unescaped backticks in the discipline block executed `devant graph affected` at prompt time and
  ate the command name from the injected instruction — now a quoted heredoc, snapshot-tested.
- Transcript cursor wedge on a single ≥2MiB JSONL line; stale-offset reset on shrunk/replaced
  transcripts; recall ids flushed to stdout before being marked seen; `--` argv guard so a prompt
  like `--help` can't hit argparse; review/document/README/raw-escape references to deleted
  skills updated.

## [0.17.0] - 2026-07-08

Diagram pipeline speed + comprehensibility: spec-first generator over hardened ELK (dec-041/042).

### Added
- **`devant diagram-build <spec.json> [-o out.drawio]`** (new stdlib generator in `drawio.py`):
  emits a styled, ELK-laid-out `.drawio` from a compact logical spec (kind, nodes with types,
  edges with guards, loops **declared** via `loop:true`) and runs the `drawio-lint` gate itself —
  exit 0 means the diagram is already clean. Measurement showed the tools were never the
  bottleneck (layout 0.33s, lint 0.05s, preview 1.9s); the cost was model-time hand-authoring
  ~13KB mxGraph XML plus a fix loop repairing defects the mandatory layout pass itself created.
  A 16-node/2-loop flow now builds lint-clean first pass in ~0.5s from a ~620-token spec
  (was ~3,300 tokens of XML). Declared loop edges are pre-reversed in the ELK input (dec-042) so
  cycle breaking never guesses — narrative order is preserved in spec order; guard/loop labels
  get a deterministic ride-position scan reusing the linter's own font metrics; the legend is
  placed from the post-layout bounding box. Validation fails loud: undeclared cycles are named
  (with the `loop:true` hint), decision branches must carry guards, unknown types list what's
  allowed.

### Changed
- **`elk-layout.cjs` / `devant layout` hardened (dec-041)**: layered presets gain
  `GREEDY_MODEL_ORDER` cycle breaking + `considerModelOrder=NODES_AND_EDGES` (authored order is
  the narrative order); edge labels are passed through with real font-metric sizes so ELK
  reserves inter-layer space for them; edge-less vertices (legends, captions) are excluded from
  the graph and keep their coordinates instead of being dragged into a layer. Previously one
  layout run scrambled a clean cyclic activity diagram (start node mid-canvas, 3 fresh label
  collisions).
- **Diagram skill workflow (`skills/diagram/SKILL.md`, dec-041)**: step 3 now authors a
  throwaway `spec.json` and runs `diagram-build`; raw mxGraph XML authoring is demoted to an
  escape hatch (swimlanes, fork/join bars, C4 boundaries). The self-defeating "re-run layout
  after each fix" instruction is deleted (it re-scrambled nodes and re-stripped waypoints every
  round). The dec-023 3-round vision gate is unchanged. `references/drawio-guide.md` gains the
  spec format section (§6).

## [0.16.0] - 2026-07-08

Slide pipeline speed + quality: deterministic geometry generator (dec-040).

### Added
- **`devant slide-build <spec.json>`** (new stdlib generator in `slide.py`): authors a whole
  `.fodp` deck from a compact JSON slide spec, computing per-archetype geometry deterministically
  instead of hand-writing absolute-cm XML. Measurement showed `soffice` render (~2s/round) was
  never the bottleneck — the 20-30 min/deck was model-time spent emitting ~6,800 tokens of XML
  plus a 3-round vision loop. slide-build collapses authoring to a few-hundred-token spec and makes
  alignment correct by construction. Seven archetypes (title, section-divider, milestone-flow,
  metric, two-column-compare, three-point, process-flow) reuse the existing brand style names so
  `slide-lint`/brand fidelity stay automatic, plus a per-slide `raw` escape for bespoke pages.
  Spec validation fails loud (clean nonzero exit) on an unknown archetype, a missing/mistyped
  field, or an over-long column; cards/columns are equal-width, equal-gutter, and margin-safe
  (geometry-assertion tests cover all seven).

### Changed
- **Slide skill workflow (`skills/slide/SKILL.md`, dec-040)**: step 3 now authors a `spec.json`
  and runs `slide-build` rather than hand-authoring `.fodp` XML; the visual gate drops from
  **3 rounds to 1 pass + 1 corrective** (geometry is deterministic, so the pass only guards text
  overflow and font substitution). Single-`.pptx` deliverable, temp-dir, and cleanup unchanged.
- **`slide-lint` hero-figure threshold 40pt → 60pt**: a numeric *headline* (pH1w, 40pt) is no
  longer misflagged as a fabricated hero stat; a real hero figure (pFig, 80pt) is still caught.

## [0.15.1] - 2026-07-08

### Changed
- **Skill frontmatter (dec-039, amends dec-006)**: `effort:` pinning narrowed to `architect` and
  `review` only; `ask`, `code`, `diagram`, `document`, `intent`, `onboard`, `router`, `slide` now
  inherit the invoking session's model and effort tier with no pin at all. `debate` keeps
  `effort: xhigh` and gains a new `model: opus` pin — the first model pin since dec-003/dec-006
  removed model pins repo-wide — since adversarial cross-examination benefits from a fixed strong
  model regardless of session tier.

## [0.15.0] - 2026-07-08

A review-driven hardening pass plus the slide and debate redesigns.

### Added
- **`devant slide-styles` + `devant slide-lint`** (new stdlib `slide.py`): slide branding is now
  **user-fed** via a `brand.json` token file (resolution `--brand` → `docs/slides/brand.json` →
  `.devant/brand.json` → the shipped Ink & Signal default). `slide-styles` emits the ODF
  `<office:automatic-styles>` block from tokens (the sample's block equals generator output,
  test-enforced, so it can't drift); `slide-lint` mechanically gates off-brand colour, a fabricated
  hero figure, and a decorative numberless chart — the anti-slop tells the eyeball pass missed (dec-038).
- **`devant export` / `devant import`**: dump the intent graph as committable JSON and load it on a
  fresh clone, so decisions/constraints/non-goals travel with the repo and stay enforceable after
  import (import upserts by id). The live `.devant/` store stays local/gitignored.
- **Graph sync mtime+size fast-path**: unchanged files skip the read+hash, removing the full-tree
  re-hash stall on every sync. A **git-HEAD watermark** now powers a real `stale_index` in
  `devant dangling` (was hard-coded `false`), so a `git pull`/checkout that moved HEAD is flagged.

### Changed
- **debate (dec-037)**: on-by-default and broad for every design (dec-024's no-size-gate re-affirmed,
  not reversed), but **user-skippable** via a per-request phrase; **one forked round by default**,
  escalating only on an unsettled kill-shot/load-bearing challenge; the architect **threads its §1
  grounding** so debate verifies rather than re-grounds each round; a 3-tier source-authority bar and
  kill-shot-first prioritisation raise signal.
- **router**: `devant log` accepts `slide`/`debate`/`review`; `review` is reachable from the dispatch
  table; a compound-request tie-break and an "is this a good approach?" discriminator; carries a
  debate skip/re-enable phrase verbatim to the architect.
- **onboard**: stable node ids so a re-run updates instead of duplicating; the ~150 MB preview
  renderer is gated behind an explicit ask (a non-diagram repo downloads nothing large); honest
  cheap-model/out-of-pocket-cost wording for the annotation fan-out.
- **Leaner context injection**: decisions match a prompt on title + rejected-alternative only, not
  the rationale prose, so a long decision body no longer floods the prompt on a shared token.
- **Skill sharpening**: `document` (quality bar + accuracy check), `intent` (search-before-record,
  `show`, export/import), `ask` (graph-miss fallback), `review` (obtains the diff itself),
  `code` (paste command + output receipts), `diagram` (layout strips waypoints; route via edge
  exit/entry).

### Fixed
- **git guard covers wrapper-prefixed writes**: `sudo git push` / `env git commit` / `FOO=1 git push`
  were silently bypassing the guard (the `hooks.json` `if: "Bash(git *)"` matcher never saw through
  the wrappers) while the tests "proved" they were denied. The git filter moved into the hook script,
  closing the bypass and making it testable.
- **extract.py resource false-coupling**: `sql_table` resources are extracted only from string
  literals shaped like a real SQL statement — prose such as `"update stats from cache"` no longer
  fabricates coupling edges, and multi-line queries now resolve their tables.

## [0.14.1] - 2026-07-07

Two `drawio-lint` fixes for diagrams that author edge labels and UML final nodes as their own cells.

### Fixed
- **Edge-through-node false positive**: a standalone `text;` label cell placed on an edge path (the
  common "edge label as its own cell" pattern) was counted as a bystander node, so every edge got a
  "routes through a node" warning for meeting its own label — printed alongside `clean.` and
  re-emitted each diagram round. The routing check now skips boxless cells (`text` elements, or
  cells with neither fill nor stroke); real bystander shapes still warn (dec-021 no-false-positive).
- **Crooked UML final node**: the bullseye is authored as two ellipses (ring + core), and a few-px
  concentric-offset error left the core off-centre — the linter skipped nested/concentric shapes
  without checking they were actually concentric, so it reported `clean` on a crooked node. `--fix`
  now re-centres a near-concentric nested shape exactly on its container (within one grid cell; a
  deliberate corner badge is left alone); without `--fix` it is reported as cosmetic, like off-grid.

## [0.14.0] - 2026-07-07

Full-plugin review-driven hardening: fix shipped defects, harden the "done = verified" contract,
and make the graph's health honest. A runtime "solidity ratchet" was designed and debated, then
deferred (dec-028) as theater without a declared-invariant foundation and diff-scoped attribution.

### Added
- **`devant goal` — per-task definition of done (P1)**: a reminder-ledger storing the task's
  acceptance criteria (`.devant/state/goal`), surfaced in the Stop note and re-hydrated at
  SessionStart so a long multi-turn task never loses its own done-conditions. A reminder surface,
  never a gate — the model that sets the criteria also meets them, so a hard gate could only
  rubber-stamp or falsely wedge; code §5 stop-when-stuck still governs.
- **`graph status` surfaces parse errors (dec-028)**: files whose extractor raised
  (`status='error'`, 0 symbols) were hidden behind the totals — status now reports
  `parse_errors`/`error_files` and a warning list, so hollow files can't hide behind
  "N files, M symbols".
- **`skills/code/references/quality.md`**: a distilled solid + lean engineering bar (grounded in
  Anthropic's agent-engineering posture and long-standing practice), cited by both `code` §6 and
  `review` — de-duplicating the rubric that was ~70% copied across the two.

### Changed
- **code §5 tightened**: "new evidence" is now defined concretely (a changed failure signature or
  an eliminated hypothesis), and a stuck stop must show real failing output tagged
  "BLOCKED — not done" — closing the doorway to a report-instead-of-work hand-back (dec-009).
- **router §4 repro seam closed**: a behavior-changing edit owes a failing repro/asserting test
  even when done inline; only pure no-behavior edits skip it.
- **`review` rubric** now cites `quality.md` instead of restating it.

### Fixed
- **Extractor decl-tier revived**: `_extract_generic` referenced an unbound `lineof`, so all 9
  declaration-tier languages (java/kotlin/c#/ruby/rust/php/c/cpp/swift/shell) raised `NameError`
  and were silently recorded as parse errors. `EXTRACTOR_VERSION` bumped 1→2 so already-onboarded
  repos re-extract; a regression test now iterates every declared language.
- **Done-gate over-block**: `DV_STUB_RE` matched substrings (`todos`, `0xXXXX`, `mastodon`) and
  scanned whole files, so a task that merely touched a file with a pre-existing `TODO` could never
  complete. Now word-boundary-anchored and scoped to added lines (git diff; whole-file fallback for
  new/untracked/non-git, fail-open) via a shared `dv_scan_stubs` helper that de-dups the two hooks.
- **Guard secret scan** capped at 1MB on the PreToolUse hot path; block-rule teeth stay uncapped.
- **Fragile `sed`** path relativization in the Stop hook replaced with metachar-safe bash.
- **Retired `codegraph`** removed from user-facing copy (plugin.json description/keyword, README).

## [0.13.0] - 2026-07-05

### Added
- **`devant:debate` specialist (dec-024)**: an INDEPENDENT design cross-examiner — forked
  read-only context (Explore agent, effort xhigh), invoked by the architect before EVERY
  approval gate (no size gate; user-owned call) and router-dispatchable on an explicit
  "debate/challenge this". Four mandatory lenses (customer value, technical soundness,
  cost, industry precedent); every challenge carries evidence — a devant-graph symbol, a
  recorded intent rule, or a WebFetch'd source cited with URL + quote — else it is tagged
  `[hypothesis — unverified]`. First specialist with `WebSearch`/`WebFetch`; web queries
  must never contain project code or identifiers (generic pattern questions only), and
  offline degrades with labels instead of blocking. The exchange is capped at 3 rounds;
  what stays contested goes to the user at a gate that now shows a
  challenged/conceded/defended/open table. "No substantive challenge found" is a valid
  result — disagreement is never manufactured.

### Changed
- **Architect no longer auto-draws on approval (dec-025)**: designing and diagramming are
  independent tasks. `devant:diagram` runs only on an explicit ask ("draw it", "show me the
  diagram"), before or after approval; offering it in one line at the gate is fine,
  producing it unasked is a contract violation.
- **Approval locks the design only (dec-026)**: the architect hands off to `devant:code`
  only when the user's intent includes building (design-then-build ask, or "build it" at
  the gate). A design-only ask ends at approval with a one-line offer of next steps —
  design, diagram, and implementation are three independent tasks sequenced by user
  intent, never by a fixed pipeline.
- `devant:review` scope sharpened: designs before approval belong to `devant:debate`;
  review judges code diffs after implementation.

## [0.12.0] - 2026-07-04

### Added
- **`devant drawio-preview <file> [-o out.png]` (dec-022/dec-023)**: renders a diagram to PNG
  for the visual self-check — stdlib builds a viewer.diagrams.net URL (the XML travels in the
  `#fragment`, never uploaded to any server) and the plugin-installed chrome-headless-shell
  screenshots it at 2000 px. Resolves ONLY the shell in `${CLAUDE_PLUGIN_DATA}/browsers`
  (dec-023) — system Chrome/Edge and the WSL-side `.exe`s are never consulted; when the shell
  is missing it prints the exact install fix and exits 1.
- **Onboard installs the preview renderer**: `npx --yes @puppeteer/browsers install
  chrome-headless-shell@stable` into the plugin data dir when missing (~150MB, no sudo) —
  users never install a browser by hand.
- **`drawio-lint` edge-routing warnings + `--score` (dec-021)**: edges with explicit waypoints
  are checked for routing through a bystander node and for edge-edge crossings — warnings,
  never blocking (auto-routed edges are exempt: their path isn't stored, so checking them
  would guess; adapted from Agents365-ai/drawio-skill, MIT). `--score` prints
  `20·through + 10·cross + 5·overlap` (lower is better) for comparing layout variants.

### Changed
- **The diagram done-path gains a mandatory visual pass (dec-022/dec-023)**: after
  `drawio-lint` exits 0, render the preview, read the PNG with vision, fix perceptual defects
  the geometry can't measure, re-layout/lint/preview — loop max 3 rounds. If the preview
  cannot run (shell not installed, offline) the skill reports the blocker explicitly instead
  of delivering silently.
- Guide: `devant drawio-preview` documented as the sanctioned PNG path, plus recorded vision
  traps (2576×2576 px vision ceiling; drawio CLI `-e` IEND truncation; `--no-sandbox` must be
  the last argument); edge-label placement rules referenced by the new lint warnings.

## [0.11.0] - 2026-07-04

### Changed
- **Onboard extras are default-on (dec-020)**: the compaction floor applies silently
  (gitignored `settings.local.json` only), the native guard backstop applies without asking
  when `.claude/settings.json` is absent or untracked (still asks before touching a
  committed/shared file), and semantic annotation runs by default with a one-line cost
  estimate (asks only above ~1M read tokens). Each applied step is announced in one line.
- **Backstop deny list covers destructive git**: `reset --hard`, `clean -f`, `branch -D`,
  `checkout .`, `restore .` (force-push subsumed by `git push*`) — the native layer now
  mirrors a typical global dangerous-git hook, so onboarded repos don't need one.

### Fixed
- **Context monitor startup false alarm (dec-018)**: on the first poll after session start,
  the newest transcript by mtime (and a stale `transcript.path`) still pointed at the
  PREVIOUS session — often ending near the window limit — firing a bogus
  "compaction imminent". The monitor now only trusts a transcript written since it started
  (`usable_transcript`), which also stops stale data reaching `context.pct`.

## [0.10.1] - 2026-07-04

### Removed
- Post-cutover residue: hooks no longer write `.codegraph/` into `.git/info/exclude`;
  stale codegraph wording in comments/help text; orphaned `.gitignore` entries
  (`timing_ss.txt`, `.codegraph/`); local `__pycache__` build litter; the repo's own
  `docs/` folder (example diagrams — the diagram skill writes into the USER's repo, not here).

## [0.10.0] - 2026-07-04

### Added — the racing-wheel pair is complete (dec-016 P1–P3)
- **Self-built extractor** (`bin/devantlib/extract.py`, stdlib only): Python via `ast`
  (full call edges with local `var = Class()` / `super()` inference), JS/TS + Go via a
  comment/string-aware tokenizer with brace-span scoping (declarations, imports,
  confidence-scored calls), declaration-tier for java/kotlin/csharp/ruby/rust/php/c/cpp/
  swift/shell (imports + symbols, never fabricated call edges), Vue/Svelte `<script>`
  delegation, `.ipynb` code-cell extraction, and resource scanning (env vars, URLs,
  routes, SQL tables).
- **`devant graph sync` now extracts**: symbols upsert on their natural key (ids stable
  across re-index), refs resolve same-file → module-qualified (`lib.core`) → unique name
  with confidence haircuts, syntax errors keep the previous symbols. Proven by the
  benchmark gate (recall/precision floors per language) and a decay contract test
  (N incremental syncs ≡ one full rescan).
- **Impact across three layers**: reverse call/inherit closure ∪ resource co-reference
  (two functions touching the same env var/table are coupled without any call edge) ∪
  `--semantic` shared annotation concepts. `devant graph hot` ranks symbols by in-degree
  (where dec-017 annotation effort pays first). `affected` adds one-level reverse-import
  closure with provenance labels.
- **`devant lint` suggests missing code links** when a decision/constraint names an
  indexed symbol it isn't linked to.
- Onboard gains the semantic-annotation pipeline stage (taxonomy → hot symbols →
  Haiku fan-out, dec-017).

### Changed — codegraph cutover (benchmark-gated, dec-016)
- The external `@colbymchenry/codegraph` npm CLI is fully replaced: `link`/`dangling`/
  `doctor` resolve against the internal index; hooks run `devant graph sync`/`affected`;
  session-start injects a graph-CLI cheatsheet; skills ground in `devant graph
  explore/search/impact/callers`; onboard no longer installs codegraph (Node.js is now
  optional, diagrams only). `DEVANT_CODEGRAPH=off` remains the lifecycle switch.
  Uninstall when ready: `npm uninstall -g @colbymchenry/codegraph` and remove
  `.codegraph/` dirs + your codegraph MCP entry.

## [0.9.0] - 2026-07-04

### Added
- **devant-graph P0** (`dec-014`/`dec-016`): the foundation of the self-owned code+intent graph
  replacing codegraph. One logical graph, two physical stores — `intent.db` untouched (zero
  migration) + new `.devant/index.db` (derived, rebuildable; `auto_vacuum=INCREMENTAL` at
  creation, WAL, FTS5 search index maintained by triggers with a LIKE fallback). Full fixed CLI
  contract: `devant graph sync|status|search|explore|callers|callees|impact|affected|annotate` —
  sync is git-ls-files-scoped, sha256-incremental with orphan GC + wal_checkpoint; explore
  verifies file hashes before serving stored line ranges; search/impact join intent nodes
  (ATTACH) so blast radius surfaces the constraints/decisions governing a symbol. Benchmark
  fixtures + thresholds checked in as the P1 cutover gate. `bin/devant` split into a thin entry
  (PEP 562 lazy re-export) + `bin/devantlib/` package with lazy per-subcommand imports — the
  Write/Edit guard hot path now loads only `common`+`guard` (~6ms), proven by a sys.modules test.
- **Intent node history**: in-place edits journal the old row to `node_history` (title, body,
  meta, status — a block→warn downgrade leaves an audit trail) and stamp `updated`.
- **Smart compaction scheduler** (`dec-018`): `devant phase --set … --open|--hold` records the
  project phase + compaction gate; the PreCompact hook defers proactive auto-compacts mid-phase
  and lands them at phase boundaries (manual `/compact` never blocked; fail-open without a fresh
  signal or at ≥85%); a native plugin background monitor polls the session transcript, writes
  `.devant/state/context.pct`, and notifies only on zone transitions; SessionStart re-hydrates
  the intent brief + phase after every compact. `userConfig`: smart_compact, compact_floor_pct,
  context_window_tokens.
- **TaskCompleted gate** (`dec-019`): a task cannot be marked complete while files touched this
  session still carry unfinished markers (TODO/FIXME/stub) — exit-2 hook, fail-open.
- **`devant phase`** subcommand, `architecture-devant-graph.drawio` (the approved P0 design),
  bench fixtures (`tests/fixtures/bench/`), and a "Developing devant" README section
  (`--plugin-dir`, `/reload-plugins --force`, `--init-only --debug hooks`).

### Changed (nativization, `dec-019`)
- Skills call the CLI as bare **`devant`** (plugin `bin/` is on the Bash PATH) with
  `allowed-tools: Bash(devant *)` — no more per-call permission prompts.
- The Stop-hook note (impacted tests, unfinished markers, dangling links) is delivered natively
  via `additionalContext` **in the same turn** (was a `.lastturn` file replayed next prompt);
  `stop_hook_active` loop guard added.
- Hooks prefer the guaranteed `CLAUDE_PROJECT_DIR`/`CLAUDE_CODE_SESSION_ID` env (JSON parse kept
  as fallback); git-guard hook only spawns for git commands (`"if": "Bash(git *)"`); SubagentStop
  sync runs async; `NotebookEdit` and `Monitor` added to guard/tracking matchers.
- Warn-severity intent rules inform via PreToolUse `additionalContext` instead of a modal ask;
  architect/intent are read-only by mechanism (`disallowed-tools`).
- devant no longer writes `autoCompactEnabled` into the user's global settings (Claude Code
  defaults it to true; a warning fires only if `DISABLE_AUTO_COMPACT` is set).
- `commands/onboard.md` wrapper removed (the skill itself is `/devant:onboard`,
  `disable-model-invocation: true`); elkjs now installs into `${CLAUDE_PLUGIN_DATA}` instead of
  `npm -g`; hook bytecode goes to `PYTHONPYCACHEPREFIX`; plugin.json gains
  `$schema`/`repository`/`license` + required `userConfig` titles; specialist descriptions
  trimmed for the shared skill-metadata budget.

### Fixed
- `evaluate_bash` false positive: a quoted pipe (`grep "a\|b"`) was split into an
  unbalanced-quote segment and denied — segments are now split quote-aware.
- Context monitor no longer guesses the transcript by newest-mtime (wrong session when two run
  in one repo); SessionStart persists this session's `transcript_path` + `model`.
- Parallel `add-node` no longer loses writes when racing the new `updated`-column ALTER.

## [0.8.0] - 2026-07-04

### Added
- **`devant layout <file> --preset <p>`** — real ELK auto-layout for `.drawio` diagrams via the
  new `bin/elk-layout.cjs` driver (elkjs, installed globally at onboarding; resolved through
  `NODE_PATH=$(npm root -g)`). Python owns all XML with stdlib `xml.etree`; the node script is
  JSON-in/JSON-out only, so `con-stdlib` holds. Presets: `verticalFlow`, `horizontalFlow`,
  `verticalTree`, `horizontalTree`, `radialTree`, `organic`. Stale hand-routed edge waypoints are
  dropped so draw.io re-routes. End-to-end tested (stacked 5-node chain → laid out, on-grid,
  lint-clean).
- **`drawio-lint` label-collision gate** — estimated Helvetica 12px font metrics (stdlib) catch
  the perceptual defects the retired PNG pass used to: a label spilling onto a sibling node,
  labels on labels, an edge label landing on a node (straight-line midpoint approximation with a
  6px tolerance). Blocking, report-only (`--fix` never guesses a wording/size fix). Edge-riding
  labels (`relative="1"`) are now exempt from grid/off-canvas checks. Red/green proven against
  the 0.7.0 binary.
- **`devant doctor`** now reports `node` and `elkjs` presence, and every absent tool ships its
  remedy one-liner (`npm i -g @colbymchenry/codegraph`, `npm i -g elkjs`).
- **Anti-sycophancy debate contract** (`dec-013`) — router step 2 and architect step 3 now require
  holding ONE grounded recommendation through option discussions: a counter-question ("isn't B
  better?") is a probe, not evidence; switch only on new evidence (concede explicitly) or an
  explicit user-owned override (comply, restate the standing recommendation, record the decision
  as user-owned). Adjacent-turn flip-flops with no new facts are a defect.

### Changed
- **codegraph is now mandatory** (`dec-011`): `/devant:onboard` installs it (and elkjs) itself via
  `npm i -g` when absent (user-space, no sudo); the plugin still degrades gracefully without it.
  README Requirements rewritten; the missing-codegraph SessionStart nudge now names the install
  command.
- **draw.io desktop CLI dropped entirely** (`dec-012`, supersedes the dec-007/dec-008 optional-CLI
  path): the diagram done-path is now `devant layout` (ELK) + `devant drawio-lint --fix`
  (geometry + label collisions). `skills/diagram/references/drawio-cli.md` deleted; SKILL, guide,
  and README updated — no PNG export step, no xvfb, no Electron.

## [0.7.0] - 2026-07-03

### Added
- Router **step 1.5 "Sharpen the ask"** — a scoped prompt-engineering pre-pass grounded in
  Anthropic's published prompting best practices (and the Console prompt improver's scoping):
  a clear or trivial request skips it with zero ceremony; a vague one is restated as
  **outcome + scope + done-condition** in a ≤3-line "Treating this as: … object if wrong"
  restatement; materially different readings hard-stop and ask which one. Specialists now
  receive the *sharpened* ask. Recorded as `dec-010` (rejected: hook-based rewriting — hooks
  can only inject context, and bash vagueness heuristics misfire; always-on gate — taxes the
  fast path).
  - New `skills/router/references/prompt-guide.md` — distilled, stable Anthropic principles
    (done-condition first, golden rule, clear-and-direct, motivation, positive instructions,
    minimal restatement) plus complex-ask-only techniques (XML tags, 3–5 examples, role framing).
  - New `docs/diagrams/activity-router.drawio` — the router pipeline with step 1.5, drawn and
    visually verified via the dec-008 gate (lint 0 + PNG read).
  - Markdown-only: no Python, hooks, or tests touched (con-stdlib and dec-001 zero-install hold).

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
