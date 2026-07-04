---
name: diagram
user-invocable: false
effort: medium
allowed-tools: Bash(devant *)
description: devant specialist (router-invoked): draw professional draw.io diagrams grounded in the real codebase — C4 architecture or UML activity flow — clean mxGraph XML in docs/diagrams/, per references/drawio-guide.md.
---

# devant: diagram

Draw a diagram that a developer AND a non-technical stakeholder can both read at a glance — solid,
consistent, professional. Two supported kinds:
- **Architecture** — C4 container/component style (systems, containers, data stores, externals).
- **Activity flow** — standard UML activity diagram (start/end, actions, decisions, fork/join,
  optional swimlanes).

The intent CLI is `devant`.

## Do this
1. **Pick the kind** from the request (architecture vs. activity flow). If ambiguous, ask one line.
2. **Ground the content in the real code — never invent.** Use `devant graph explore`/`devant graph search`
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
4. **The deliverable is the `.drawio` file.** Don't open a viewer unless asked. Author with
   *approximate* coordinates, then let real ELK place the nodes:
   `devant layout <file> --preset <p>` — it runs the elkjs
   engine (installed globally by `/devant:onboard`, dec-011/dec-012) via node and rewrites the same
   `.drawio`. Presets: `verticalFlow` (activity flows, pipelines), `horizontalFlow`
   (request/response chains), `verticalTree`/`horizontalTree` (hierarchies, layered architecture),
   `radialTree` (hub-and-spoke), `organic` (many-edge networks). If node/elkjs is missing the
   command says exactly what to install (elkjs into `${CLAUDE_PLUGIN_DATA}`) — pass that on, and ship the
   hand-placed XML meanwhile. **No draw.io desktop CLI and no MCP are used — ever** (dec-012
   dropped them; elkjs + the linter replace them; the visual pass in step 6d is headless
   Chrome, dec-022 — not the CLI).
5. **Write the file** to the target repo (create the dir if missing):
   - Architecture → `docs/diagrams/architecture-<name>.drawio`
   - Activity flow → `docs/diagrams/activity-<flow-name>.drawio`
   `<name>`/`<flow-name>` is a short kebab-case slug of the subject (e.g. `architecture-billing.drawio`,
   `activity-checkout.drawio`). If the file already exists, **update it in place** — don't spawn a
   `-v2` copy.
   - Default location is `docs/diagrams/` (committed, shareable). If the user asks for local-only,
     write to `.devant/docs/draw.io/` instead — that path is git-excluded.
6. **Verify it's DONE — clean, not just that it opens.** A diagram that opens but has overlapping
   boxes, crooked nodes, tangled edges, or labels sitting on other cells is *not* done. Gate
   delivery on this — no report-only, no "looks fine to me":
   - **(a) Well-formed XML** — `python3 -c "import xml.dom.minidom,sys; xml.dom.minidom.parse(sys.argv[1])" <file>`.
   - **(b) Layout** — run `devant layout <file> --preset <p>` (step 4) so node placement comes from
     ELK, not hand-tuning. Skip only if node/elkjs is genuinely unavailable.
   - **(c) The lint gate — ALWAYS, stdlib, no external tool.** Run
     `devant drawio-lint <file> --fix`. It auto-fixes what it
     safely can (straightens off-grid nodes, spreads overlapping ones) and **exits non-zero** while
     any *blocking* defect remains — overlaps it couldn't resolve, **label collisions** (a label
     spilling onto a sibling node or another label, an edge label landing on a node — estimated
     Helvetica metrics, the perceptual check that used to need a PNG render), non-orthogonal edges,
     edges missing `<mxGeometry>`, duplicate ids, off-canvas cells. Fix those **by hand in the XML**
     (shorten or `whiteSpace=wrap` the label, widen the node, move the label along its edge, add
     `edgeStyle=orthogonalEdgeStyle`, give the edge its child geometry, dedupe the id) and
     **re-run until it exits 0.** This is real mechanical cleanup, not a report.
   - **(d) The visual pass — MANDATORY (dec-022/dec-023).** Run
     `devant drawio-preview <file>` (the onboard-installed chrome-headless-shell renders the real
     diagram; needs network for the viewer JS — the XML never leaves the machine), then **Read the
     PNG with vision** and fix what geometry can't measure — visual clutter, a confusing flow
     shape, unreadable contrast — re-running layout → lint → preview after each fix. **Loop max
     3 rounds**, then deliver. If the command fails (shell not installed, offline), do **not**
     deliver silently: report the blocker and its fix (`/devant:onboard` installs the shell) and
     let the user decide whether to accept the diagram without the visual gate. Delete the
     `.preview.png` before finishing unless the user asked for it.

   **Done = well-formed AND laid out AND `drawio-lint` exits 0 AND the visual pass ran** (or its
   blocker was explicitly reported and accepted). Then tell the user it opens in draw.io /
   diagrams.net (or the VS Code Draw.io Integration extension) — for a shareable PNG they can
   keep, `devant drawio-preview <file> -o <out.png>` renders one on demand.

Keep to the two kinds and the one style system. This skill draws; it does not design the
architecture (that's `devant:architect`) or edit code.
