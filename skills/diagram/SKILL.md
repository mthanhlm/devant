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
4. **The deliverable is the `.drawio` file only — do NOT export an image and do NOT open a viewer**
   unless the user explicitly asks. They read and edit the `.drawio` themselves and will tell you
   when to continue. If the `drawio` CLI is on PATH (optional, never required — detect per
   `references/drawio-cli.md`), you may run its **ELK `--layout`** pass to auto-place nodes instead
   of hand-tuning coordinates — that just rewrites the same `.drawio`. PNG/SVG/PDF export exists but
   stays **off by default**. When the CLI is absent — the default — ship the hand-authored `.drawio`
   from step 3 unchanged. **No draw.io MCP is used, and the plugin never installs or requires the
   CLI** (dec-001 zero-install stands; the CLI is an optional local tool like codegraph).
5. **Write the file** to the target repo (create the dir if missing):
   - Architecture → `docs/diagrams/architecture-<name>.drawio`
   - Activity flow → `docs/diagrams/activity-<flow-name>.drawio`
   `<name>`/`<flow-name>` is a short kebab-case slug of the subject (e.g. `architecture-billing.drawio`,
   `activity-checkout.drawio`). If the file already exists, **update it in place** — don't spawn a
   `-v2` copy.
   - Default location is `docs/diagrams/` (committed, shareable). If the user asks for local-only,
     write to `.devant/docs/draw.io/` instead — that path is git-excluded.
6. **Verify it opens.** Confirm the file is well-formed XML before claiming done
   (`python3 -c "import xml.dom.minidom,sys; xml.dom.minidom.parse(sys.argv[1])" <file>`), and tell
   the user it opens in draw.io / diagrams.net (or the VS Code Draw.io Integration extension).

Keep to the two kinds and the one style system. This skill draws; it does not design the
architecture (that's `devant:architect`) or edit code.
