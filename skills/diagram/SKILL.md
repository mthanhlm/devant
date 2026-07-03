---
name: diagram
user-invocable: false
effort: medium
description: devant specialist (router-invoked) to draw professional draw.io (.drawio / diagrams.net) diagrams grounded in the real codebase — two kinds: a C4-style architecture diagram, and a standard UML activity flow. Produces clean, consistent, business-and-dev-readable mxGraph XML written to docs/diagrams/ (overridable). Follows the full style + template guide in references/drawio-guide.md.
---

# devant: diagram

Draw a diagram that a developer AND a non-technical stakeholder can both read at a glance — solid,
consistent, professional. Two supported kinds:
- **Architecture** — C4 container/component style (systems, containers, data stores, externals).
- **Activity flow** — standard UML activity diagram (start/end, actions, decisions, fork/join,
  optional swimlanes).

The intent CLI is `python3 "${CLAUDE_PLUGIN_ROOT}/bin/devant"`.

## Do this
1. **Pick the kind** from the request (architecture vs. activity flow). If ambiguous, ask one line.
2. **Ground the content in the real code — never invent.** Use `codegraph_explore`/`codegraph_search`
   to get the actual containers, modules, data stores, and the real call/flow path the diagram
   depicts. A box or step that doesn't map to something in the graph doesn't belong on the diagram.
3. **Author the styled mxGraph XML — the always-available baseline.** Build it by following
   `references/drawio-guide.md` (read it — palette with hex, node sizing, edge conventions, the
   completeness bar (show *enough* that a first-time reader needs no walkthrough — every real
   branch, loop, and error path — but no clutter), loops-as-loops (a repeat is a labelled
   back-edge, never cloned nodes), arc line-jumps on unavoidable crossings, keeping labels off other
   text, layout rules, the legend block, the XML well-formedness rules, and a
   ready-to-copy valid skeleton for each kind). devant's `.drawio` XML is self-contained — it needs
   no tool to produce or to open. Don't freehand styles; reuse the system so every diagram looks
   like one set.
4. **The deliverable is the `.drawio` file.** Don't open a viewer unless asked. If the `drawio`
   CLI is on PATH (optional, never required — detect per `references/drawio-cli.md`), you may run its
   **ELK `--layout`** pass to auto-place nodes instead of hand-tuning coordinates — that just rewrites
   the same `.drawio`. When the CLI is absent — the default — ship the hand-authored `.drawio` from
   step 3. PNG export is no longer "off by default": step 6 uses a plain-PNG render as the visual
   self-check when the CLI is present (that's how devant proves the diagram is clean, not just valid).
   **No draw.io MCP is used, and the plugin never installs or requires the CLI** (dec-001 zero-install
   stands; the CLI is an optional local tool like codegraph — it accelerates, it is never mandatory).
5. **Write the file** to the target repo (create the dir if missing):
   - Architecture → `docs/diagrams/architecture-<name>.drawio`
   - Activity flow → `docs/diagrams/activity-<flow-name>.drawio`
   `<name>`/`<flow-name>` is a short kebab-case slug of the subject (e.g. `architecture-billing.drawio`,
   `activity-checkout.drawio`). If the file already exists, **update it in place** — don't spawn a
   `-v2` copy.
   - Default location is `docs/diagrams/` (committed, shareable). If the user asks for local-only,
     write to `.devant/docs/draw.io/` instead — that path is git-excluded.
6. **Verify it's DONE — clean, not just that it opens.** A diagram that opens but has overlapping
   boxes, crooked nodes, or tangled edges is *not* done. Gate delivery on this — no report-only, no
   "looks fine to me":
   - **(a) Well-formed XML** — `python3 -c "import xml.dom.minidom,sys; xml.dom.minidom.parse(sys.argv[1])" <file>`.
   - **(b) Geometry gate — ALWAYS, no CLI needed.** Run
     `python3 "${CLAUDE_PLUGIN_ROOT}/bin/devant" drawio-lint <file> --fix`. It auto-fixes what it
     safely can (straightens off-grid nodes, spreads overlapping ones) and **exits non-zero** while
     any *blocking* defect remains — overlaps it couldn't resolve, non-orthogonal edges, edges
     missing `<mxGeometry>`, duplicate ids, off-canvas cells. Fix those **by hand in the XML** (add
     `edgeStyle=orthogonalEdgeStyle`, give the edge its child geometry, dedupe the id, move the node)
     and **re-run until it exits 0.** This is real mechanical cleanup, not a report.
   - **(c) Visual gate — the real "done" when the `drawio` CLI is on PATH.** Run ELK `--layout`, then
     export a **plain PNG** (no `-e`; `xvfb-run` on Linux/WSL — see `references/drawio-cli.md`) and
     **actually read the PNG yourself.** Fix the perceptual defects the geometry gate can't see —
     labels sitting on a node's text or on another label, visual tangle, crowding — in the XML,
     re-export and re-read. **Up to 2 rounds**, then deliver (note any residual issue rather than
     looping forever).
   - **(d) No CLI?** Deliver the geometry-clean `.drawio` and tell the user that installing the
     draw.io CLI (see `references/drawio-cli.md`) unlocks the full visual self-check. Graceful
     degradation — dec-007 core holds: the CLI is never required.

   **Done = well-formed AND `drawio-lint` exits 0 AND (CLI present → visually verified).** Then tell
   the user it opens in draw.io / diagrams.net (or the VS Code Draw.io Integration extension).

Keep to the two kinds and the one style system. This skill draws; it does not design the
architecture (that's `devant:architect`) or edit code.
