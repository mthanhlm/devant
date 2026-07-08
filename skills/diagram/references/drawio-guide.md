# draw.io diagram guide — architecture & activity flow

The style system and two ready-to-copy skeletons the `diagram` skill uses. Goal: every diagram
devant draws looks like part of one set — clean, consistent, and readable by a developer *and* a
non-technical stakeholder. Follow this; don't freehand styles.

The default authoring path is a compact JSON spec into `devant diagram-build` (§6 — it emits this
style system and runs ELK + the lint itself, dec-041). Sections §1–§5 govern the raw-XML escape
hatch (shapes the spec can't say: swimlanes, fork/join, C4 boundaries), where node placement comes
from `devant layout <file> --preset <p>` (elkjs via node); no draw.io CLI or MCP is used (dec-012).
Authoring conventions here are informed by the official draw.io skill (jgraph/drawio-mcp,
Apache-2.0) and Agents365-ai/drawio-skill (MIT).

A `.drawio` file is XML: `<mxfile>` → `<diagram>` → `<mxGraphModel>` → `<root>`. `<root>` always
starts with cell `id="0"` and cell `id="1"` (the default layer); every shape/edge is a `<mxCell>`
parented to `"1"` (or to a container). Vertices carry `vertex="1"` + `<mxGeometry ... as="geometry"/>`;
edges carry `edge="1"` + `source`/`target`. Both skeletons below are valid and open as-is in
draw.io / diagrams.net or the VS Code "Draw.io Integration" extension.

**Above all — completeness with restraint (engineering-complete altitude).** This bar governs the
*engineering-complete* altitude (§0); the *idea-level* altitude has its own, lighter bar there. In
engineering-complete mode a devant diagram must let a first-time reader (dev or not) understand the
*whole* story **without a verbal walkthrough** — and then stop. Show every step, branch, **loop**,
and error path that changes what happens, plus the key data on each edge; fold away anything that
doesn't change the reader's understanding. Both extremes fail equally: a skeleton that hides the
real branches/loops leaves the reader asking "but what happens when…?", and a wall of boxes nobody
can trace is just as useless. The bar is **minimal questions** — if a reasonable reader would have
to ask, the answer belongs on the diagram. (At idea-level you draw *fewer* boxes at a higher
altitude — but the honesty rule is identical: never draw a step or branch that isn't real.)

---

## 0. Altitude — pick it before anything else

Before you choose architecture vs. activity, decide the **altitude**, because it sets the
completeness bar. Two altitudes, chosen by the *intent* of the request:

**Idea-level (default when the request is a pitch).** When the ask is to show a *plan, design, idea,
or concept* — anything a business or non-technical audience must grasp in **~15 seconds** — draw the
*idea*, not the implementation. A first-time viewer should see *what it is, where it starts, and how
value flows* with no walkthrough and no glossary.
- **Architecture idea-level = C4 Level 1 (System Context).** The system as **one** box, the
  people/actors who use it, and the external systems it talks to — nothing *inside* the box. Edge
  labels are plain language ("places an order", "sends receipt"), never `[Container: tech]` tags or
  protocols. One clear flow direction, and a one-line caption under the title saying what the whole
  picture is for.
- **Process idea-level = a milestone flow.** The 3–6 major phases in order, each a box that
  legitimately **encapsulates** its sub-steps ("Checkout", "Fulfilment", "Settlement"). A phase is a
  real thing, so this is honest abstraction — *not* an activity diagram with its branches deleted.
  Plain verbs, one direction, a caption.
- **Its completeness bar:** every box still maps to something real (no invented components); the
  picture answers *what / who / where does it start / how does value flow* on sight. It need **not**
  show branches, loops, or error paths — but it must never *pretend* to. Draw fewer things, at a
  higher level; whatever you *do* draw must be true.

**Engineering-complete (opt-in, for detail).** When the ask is to *show the detail / the full flow /
how it actually works*, or the audience is engineers building it, use the complete bar in "Above
all" and the full notation: C4 container/component (§2) or UML activity (§3) — every real step,
branch, loop, and error path, grounded box-by-box in codegraph.

**How to choose the altitude:**
- pitch / plan / design / idea / "show the concept" / a business or exec audience → **idea-level**.
- "show detail" / "full flow" / "how it works" / "the actual states" / an engineering audience →
  **engineering-complete**.
- Ambiguous → default to **idea-level** and say so in one line; the user will ask for detail when
  they want it.

Both altitudes share the one style system (§1) and neither invents — idea-level *groups and
abstracts* real code, it doesn't fabricate. Not too much text, not too little: the viewer should
neither squint at a wall of boxes nor be left interrogating a near-empty one.

A caption is a plain text cell under the title (no box): `text;html=1;fontFamily=Helvetica;`
`fontSize=12;fontColor=#555555;` — one sentence naming what the picture is and why it matters.

---

Sections §1–§5 (raw-XML style system, skeletons, well-formedness, edge routing) and §7 (the
hand-authoring checklist) live in `references/raw-xml-escape.md` — read that file ONLY when the
spec's types can't express the shape (swimlanes, fork/join bars, C4 boundary boxes) and you must
hand-author mxGraph XML. The default path never needs it.
## 6. The diagram spec — `devant diagram-build` (default path, dec-041)

Author the *logical* diagram as a small JSON file; Python + ELK own every coordinate. Styles,
sizing, guard/loop label placement, and the legend come from this guide by construction, and the
command runs `drawio-lint` on its output — exit 0 means the diagram is already clean.

```json
{
  "kind": "activity",
  "title": "Checkout flow",
  "nodes": [
    {"id": "start", "type": "start"},
    {"id": "cart",  "type": "action",   "label": "Add item to cart", "note": "cart service"},
    {"id": "auth",  "type": "decision", "label": "Logged in?"},
    {"id": "login", "type": "action",   "label": "Show login"},
    {"id": "pay",   "type": "error",    "label": "Show error"},
    {"id": "done",  "type": "success",  "label": "Create order"},
    {"id": "end",   "type": "end"}
  ],
  "edges": [
    {"from": "start", "to": "cart"},
    {"from": "cart",  "to": "auth"},
    {"from": "auth",  "to": "login", "label": "[no]"},
    {"from": "auth",  "to": "done",  "label": "[yes]"},
    {"from": "login", "to": "auth",  "label": "[retry]", "loop": true},
    {"from": "done",  "to": "end"}
  ]
}
```

Rules the command enforces (fail-loud, named errors — never a silent guess):
- **`kind`**: `activity` | `c4-context` | `c4-container`.
- **Node `type` by kind** — activity: `start`, `end`, `action`, `decision`, `success`, `error`,
  `external`; c4-context: `actor`, `system`, `external`; c4-container: `actor`, `container`,
  `store`, `external`. `label` is required except on `start`/`end`; an optional `note` becomes the
  grey bracketed sub-line (`[router: ground + push back]`, `[Container: FastAPI]`).
- **Loops are declared, never inferred**: a repeat is `"loop": true` on the back-edge, with its
  repeat guard as the `label`. A cycle among non-loop edges is a validation error naming the cycle
  — ELK is handed an acyclic narrative, which is what keeps the flow top-down in spec order.
- **Every decision branch carries its guard** as the edge `label` (`[yes]`/`[no]`/`[cap hit]`).
- Node/edge **order is narrative order** — list them in execution order; the layout follows it.
- `"legend": false` omits the auto-legend (it's on by default and placed outside the flow).

The spec is a COMMITTED build input (dec-046): `docs/diagrams/<name>.spec.json` lives beside the
`.drawio` and re-runs read and patch it, so hand-tuning survives regeneration. Structural changes
(add/remove/rename nodes or edges) edit the spec and re-run `diagram-build`; cosmetic hand fixes
on the generated XML are fine, followed by `drawio-lint`.

