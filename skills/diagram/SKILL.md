---
name: diagram
user-invocable: false
allowed-tools: Bash(devant *)
description: devant specialist (router-invoked): draw professional draw.io diagrams grounded in the real codebase — C4 architecture or UML activity flow — compact spec into `devant diagram-build`, per references/drawio-guide.md.
---

# devant: diagram

Draw a diagram that a developer AND a non-technical stakeholder can both read at a glance — solid,
consistent, professional. Two supported kinds, each at one of two **altitudes** (guide §0):
*idea-level* (a ~15-second pitch of the idea, the default for plan/design asks) or
*engineering-complete* (every branch/loop/error, opt-in when detail is asked for).
- **Architecture** — C4: idea-level is Level 1 (System Context); engineering-complete is
  container/component (systems, containers, data stores, externals).
- **Activity flow** — idea-level is a milestone flow (major phases); engineering-complete is a full
  UML activity diagram (start/end, actions, decisions, loops as labelled back-edges).

The intent CLI is `devant`.

## Do this
1. **Pick the altitude, then the kind** (`references/drawio-guide.md` §0). *Altitude* first:
   **idea-level** (default when the ask is a pitch — a plan, design, idea or concept for a business/
   non-technical audience to grasp in ~15s) vs **engineering-complete** (opt-in when the ask says
   "show detail / the full flow / how it works" or the audience is engineers). Then the *kind*:
   architecture vs. activity flow. Idea-level architecture = C4 Level 1 (System Context: the system
   as one box + actors + externals, plain-language labels, a one-line caption); idea-level process =
   a milestone flow (3–6 phases, each encapsulating its sub-steps — never an activity diagram with
   branches deleted). Ambiguous altitude → default to idea-level and say so in one line; ambiguous
   kind → ask one line.
2. **Ground the content in the real code — never invent.** Use `devant graph explore`/`devant graph search`
   to get the actual containers, modules, data stores, and the real call/flow path the diagram
   depicts. A box or step that doesn't map to something in the graph doesn't belong on the diagram.
3. **Author a compact spec, not XML — the default path (dec-041).** Write the *logical* diagram as
   a small JSON spec (format: guide §6 — kind, title, nodes with types, edges with guards, loops
   **declared** with `"loop": true`), then run:
   `devant diagram-build <spec.json> -o <target.drawio>`
   It emits the styled mxGraph XML (the guide's one style system, by construction), lays the nodes
   out with real ELK (elkjs via node, dec-011/dec-012), places guard/loop labels and the legend in
   clear space, and **runs the lint gate itself** — it exits 0 only when the generated diagram is
   clean. Validation is fail-loud: an undeclared cycle, a guard-less decision branch, or an unknown
   node type is a named error, not a silent guess. The spec is a throwaway intermediate (write it
   under /tmp or the scratchpad, never the repo); the deliverable is the `.drawio`.
   **No draw.io desktop CLI and no MCP are used — ever** (dec-012; elkjs + the linter replaced
   them; the visual pass in step 6 is headless Chrome, dec-022/dec-023 — not the CLI).
4. **Escape hatch — raw mxGraph XML, only when the spec can't say it.** Swimlanes, fork/join bars,
   C4 boundary boxes, or any shape outside the spec's types: hand-author the XML per the guide
   (§1–§5 — style system, skeletons, edge routing), then `devant layout <file> --preset <p>` for
   ELK placement and fix by hand until the lint (step 6c) is clean. This path costs the fix loop
   the spec path was built to remove — take it deliberately, not by default.
5. **Write the file** to the target repo (create the dir if missing):
   - Architecture → `docs/diagrams/architecture-<name>.drawio`
   - Activity flow → `docs/diagrams/activity-<flow-name>.drawio`
   `<name>`/`<flow-name>` is a short kebab-case slug of the subject (e.g. `architecture-billing.drawio`,
   `activity-checkout.drawio`). If the file already exists, **update it in place** — don't spawn a
   `-v2` copy.
   - Default location is `docs/diagrams/` (committed, shareable). If the user asks for local-only,
     write to `.devant/docs/draw.io/` instead — that path is git-excluded.
6. **Verify it's DONE — clean, not just that it opens.** Gate delivery on this — no report-only:
   - **(a) Built clean** — `devant diagram-build` exited 0 (it already ran the lint gate). Raw-XML
     path instead: well-formed check
     (`python3 -c "import xml.dom.minidom,sys; xml.dom.minidom.parse(sys.argv[1])" <file>`),
     `devant layout`, then (c).
   - **(b) Structural changes go through the spec.** To add/remove/rename nodes or edges, edit the
     spec and re-run `diagram-build` — don't hand-edit generated geometry. Cosmetic hand fixes on
     the generated file (shorten a label, widen one node) are fine; after one, re-run (c).
   - **(c) The lint gate — stdlib, no external tool.** `devant drawio-lint <file> --fix`
     auto-fixes what it safely can and **exits non-zero** while any blocking defect remains —
     unresolved overlaps, label collisions, non-orthogonal edges, edges missing `<mxGeometry>`,
     duplicate ids, off-canvas cells. Fix by hand in the XML and re-run until it exits 0.
   - **(d) The visual pass — MANDATORY (dec-022/dec-023).** Run
     `devant drawio-preview <file>` (the onboard-installed chrome-headless-shell renders the real
     diagram; needs network for the viewer JS — the XML never leaves the machine), then **Read the
     PNG with vision** and fix what geometry can't measure — visual clutter, a confusing flow
     shape, unreadable contrast. After a fix: lint (c), then re-preview. **Loop max 3 rounds**,
     then deliver. If the command fails (shell not installed, offline), do **not** deliver
     silently: report the blocker and its fix (`/devant:onboard` installs the shell) and let the
     user decide whether to accept the diagram without the visual gate. Delete the
     `.preview.png` before finishing unless the user asked for it.

   **Done = built/laid out clean AND `drawio-lint` exits 0 AND the visual pass ran** (or its
   blocker was explicitly reported and accepted). Then tell the user it opens in draw.io /
   diagrams.net (or the VS Code Draw.io Integration extension) — for a shareable PNG they can
   keep, `devant drawio-preview <file> -o <out.png>` renders one on demand.

Keep to the two kinds and the one style system. This skill draws; it does not design the
architecture (that's `devant:architect`) or edit code.
