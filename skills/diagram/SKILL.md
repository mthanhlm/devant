---
name: diagram
user-invocable: false
allowed-tools: Bash(devant *)
description: devant specialist (work-invoked): draw professional draw.io diagrams grounded in the real codebase — C4 architecture or UML activity flow — a committed JSON spec into `devant diagram-build`, per references/drawio-guide.md.
---

# devant: diagram

Draw a diagram a developer AND a non-technical stakeholder can both read at a glance. Two kinds,
each at one of two **altitudes** (guide §0): *idea-level* (a ~15-second pitch — the default for
plan/design asks) or *engineering-complete* (every branch/loop/error path, opt-in).
- **Architecture** — C4: idea-level is Level 1 (System Context); engineering-complete is
  container/component.
- **Activity flow** — idea-level is a milestone flow; engineering-complete is a full UML activity
  diagram (loops as labelled back-edges).

The intent CLI is `devant`.

## Do this
1. **Pick the altitude, then the kind** (guide §0). Ambiguous altitude → default to idea-level and
   say so in one line; ambiguous kind → ask one line.
2. **Ground in the real code — never invent.** `devant graph explore`/`search` for the actual
   containers, modules, stores, and the real flow. A box that maps to nothing in the graph doesn't
   belong on the diagram.
3. **The spec IS the source of truth — committed, not throwaway (dec-046).**
   - New diagram: write the logical spec (guide §6 — kind, title, nodes, edges with guards, loops
     declared `"loop": true`) to `docs/diagrams/<name>.spec.json`.
   - Existing diagram: **read and PATCH the existing spec** — never regenerate from scratch; the
     user's hand-tuning lives there and must survive.
   - Then `devant diagram-build docs/diagrams/<name>.spec.json -o docs/diagrams/<name>.drawio`.
     It emits the styled XML, lays out with real ELK, and **runs the lint gate itself** — exit 0
     means clean by construction. Validation is fail-loud, never a silent guess.
   - Names: `architecture-<slug>` / `activity-<slug>`. Update in place; no `-v2` copies. Local-only
     on request → `.devant/docs/draw.io/` (git-excluded).
   - **No draw.io desktop CLI, no MCP — ever** (dec-012).
4. **Escape hatch — raw mxGraph XML, only when the spec can't say it** (swimlanes, fork/join bars,
   C4 boundary boxes). ONLY THEN read `references/raw-xml-escape.md` (§1–§5, §7), hand-author,
   `devant layout <file> --preset <p>`, and fix until `devant drawio-lint <file> --fix` exits 0.
   This path pays the fix loop the spec path removed — take it deliberately, not by default.
5. **Done = built clean (dec-045).**
   - Spec path: `diagram-build` exited 0 — that IS the lint gate; deliver.
   - Raw path: well-formed check
     (`python3 -c "import xml.dom.minidom,sys; xml.dom.minidom.parse(sys.argv[1])" <file>`),
     `devant layout`, then `devant drawio-lint <file> --fix` until it exits 0.
   - Structural changes go through the spec; cosmetic hand-fixes on the generated file are fine —
     re-run the lint after one.
6. **Visual pass — ON DEMAND, not a gate (dec-045).** Run `devant drawio-preview <file>` and Read
   the PNG with vision only when (a) the user asks to see/verify it, or (b) the lint needed manual
   fixing, or (c) the raw path was taken. At most one corrective round, then deliver. If the
   preview tool is missing, name the fix (`/devant:onboard` installs chrome-headless-shell) and let
   the user decide — never block delivery on an optional render. Delete the `.preview.png` after,
   unless asked to keep it.

Tell the user the `.drawio` opens in draw.io / diagrams.net / the VS Code Draw.io extension, the
spec sits beside it for future edits, and `devant drawio-preview <file> -o <out.png>` renders a
shareable PNG on demand.

Keep to the two kinds and the one style system. This skill draws; it does not design the
architecture (that's `devant:design`) or edit code.
