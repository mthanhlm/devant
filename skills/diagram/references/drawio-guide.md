# draw.io diagram guide — architecture & activity flow

The style system and two ready-to-copy skeletons the `diagram` skill uses. Goal: every diagram
devant draws looks like part of one set — clean, consistent, and readable by a developer *and* a
non-technical stakeholder. Follow this; don't freehand styles.

For the optional draw.io CLI (ELK auto-layout + PNG/SVG/PDF export — never required), see
`drawio-cli.md`. Authoring conventions here are informed by the official draw.io skill
(jgraph/drawio-mcp, Apache-2.0) and Agents365-ai/drawio-skill (MIT).

A `.drawio` file is XML: `<mxfile>` → `<diagram>` → `<mxGraphModel>` → `<root>`. `<root>` always
starts with cell `id="0"` and cell `id="1"` (the default layer); every shape/edge is a `<mxCell>`
parented to `"1"` (or to a container). Vertices carry `vertex="1"` + `<mxGeometry ... as="geometry"/>`;
edges carry `edge="1"` + `source`/`target`. Both skeletons below are valid and open as-is in
draw.io / diagrams.net or the VS Code "Draw.io Integration" extension.

---

## 1. Style system (use these exact values)

**Palette** (draw.io's built-in swatches — familiar, colour-blind-friendly, and print-safe):

| Role | Fill | Stroke | Use for |
|---|---|---|---|
| Primary | `#DAE8FC` | `#6C8EBF` | main containers / the happy-path actions |
| Secondary | `#D5E8D4` | `#82B366` | supporting components / success end |
| Data store | `#E1D5E7` | `#9673A6` | databases, caches, queues, buckets |
| External | `#F5F5F5` | `#666666` | third-party systems, actors outside your control |
| Decision | `#FFF2CC` | `#D6B656` | decision diamonds / callouts needing attention |
| Error | `#F8CECC` | `#B85450` | error/failure paths and states |

**Typography** — `fontFamily=Helvetica`. Title **bold** `fontSize=13`; sub-label / tech tag
`fontSize=11` `fontColor=#555555`. Keep every label ≤ 4 words + an optional bracketed tag; detail
goes on the edge, not in the box.

**Nodes** — rounded rectangles (`rounded=1`), min size **160×70**, 40 px gap between siblings.
Align to the 10 px grid (all coordinates multiples of 10). `whiteSpace=wrap;html=1` on every node so
labels wrap and render markup.

**Edges** — orthogonal (`edgeStyle=orthogonalEdgeStyle;rounded=0`), single arrowhead, always
labelled with the interaction ("Calls (HTTPS/JSON)", "Reads/Writes (SQL)"). `strokeColor=#666666`.
Route to minimise crossings; if two edges must cross, that's usually a layout smell — move a node.

**Layout** — architecture flows **top→down by dependency** (user/actor on top, data stores at the
bottom); activity flows **top→down in execution order**. One primary direction only. Leave a margin;
don't crowd the canvas edge.

**Legend** — every diagram gets a small legend box (bottom-left) explaining any colour used, so a
first-time reader needs no verbal walkthrough. See the block at the end of each skeleton.

---

## 2. Architecture diagram (C4 container style)

Backbone is the **C4 model** — show the *system* as a boundary, the **containers** inside it
(apps, services, datastores — each tagged `[Container: <tech>]`), the **people/actors** who use it,
and the **external systems** it talks to. Ground every box in codegraph (a real deployable/module),
every edge in a real call. Two-line labels: bold name + a `[Container: tech]` tag.

> Swap the C4 stencil library in (`shape=mxgraph.c4.container;...`) if you want richer C4 visuals;
> the plain styled rectangles below always render and print cleanly.

```xml
<mxfile host="devant">
  <diagram name="Architecture" id="arch">
    <mxGraphModel dx="900" dy="620" grid="1" gridSize="10" guides="1" tooltips="1" connect="1"
                  arrows="1" fold="1" page="1" pageScale="1" pageWidth="1100" pageHeight="850"
                  math="0" shadow="0">
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />

        <!-- actor -->
        <mxCell id="person" value="&lt;b&gt;Customer&lt;/b&gt;&lt;br&gt;&lt;font color=&quot;#555555&quot;&gt;[Person]&lt;/font&gt;"
                style="rounded=1;whiteSpace=wrap;html=1;fillColor=#F5F5F5;strokeColor=#666666;fontFamily=Helvetica;fontSize=13;"
                vertex="1" parent="1">
          <mxGeometry x="280" y="40" width="170" height="60" as="geometry" />
        </mxCell>

        <!-- system boundary (drawn first so it sits behind the containers) -->
        <mxCell id="boundary" value="Billing System [Software System]"
                style="rounded=0;dashed=1;fillColor=none;strokeColor=#666666;verticalAlign=top;fontStyle=2;fontColor=#555555;fontFamily=Helvetica;fontSize=12;"
                vertex="1" parent="1">
          <mxGeometry x="150" y="150" width="520" height="330" as="geometry" />
        </mxCell>

        <!-- containers -->
        <mxCell id="web" value="&lt;b&gt;Web App&lt;/b&gt;&lt;br&gt;&lt;font color=&quot;#555555&quot;&gt;[Container: React]&lt;/font&gt;"
                style="rounded=1;whiteSpace=wrap;html=1;fillColor=#DAE8FC;strokeColor=#6C8EBF;fontFamily=Helvetica;fontSize=13;"
                vertex="1" parent="1">
          <mxGeometry x="190" y="210" width="180" height="70" as="geometry" />
        </mxCell>
        <mxCell id="api" value="&lt;b&gt;API Service&lt;/b&gt;&lt;br&gt;&lt;font color=&quot;#555555&quot;&gt;[Container: Python / FastAPI]&lt;/font&gt;"
                style="rounded=1;whiteSpace=wrap;html=1;fillColor=#DAE8FC;strokeColor=#6C8EBF;fontFamily=Helvetica;fontSize=13;"
                vertex="1" parent="1">
          <mxGeometry x="450" y="210" width="180" height="70" as="geometry" />
        </mxCell>
        <mxCell id="db" value="&lt;b&gt;Database&lt;/b&gt;&lt;br&gt;&lt;font color=&quot;#555555&quot;&gt;[Container: PostgreSQL]&lt;/font&gt;"
                style="shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;fillColor=#E1D5E7;strokeColor=#9673A6;fontFamily=Helvetica;fontSize=13;"
                vertex="1" parent="1">
          <mxGeometry x="320" y="360" width="180" height="90" as="geometry" />
        </mxCell>

        <!-- external system (outside the boundary) -->
        <mxCell id="pay" value="&lt;b&gt;Payment Gateway&lt;/b&gt;&lt;br&gt;&lt;font color=&quot;#555555&quot;&gt;[External System]&lt;/font&gt;"
                style="rounded=1;whiteSpace=wrap;html=1;fillColor=#F5F5F5;strokeColor=#666666;fontFamily=Helvetica;fontSize=13;"
                vertex="1" parent="1">
          <mxGeometry x="730" y="210" width="180" height="70" as="geometry" />
        </mxCell>

        <!-- edges: labelled with the real interaction -->
        <mxCell id="e1" value="Uses" style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;strokeColor=#666666;fontFamily=Helvetica;fontSize=11;fontColor=#555555;"
                edge="1" parent="1" source="person" target="web">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>
        <mxCell id="e2" value="Calls (HTTPS/JSON)" style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;strokeColor=#666666;fontFamily=Helvetica;fontSize=11;fontColor=#555555;"
                edge="1" parent="1" source="web" target="api">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>
        <mxCell id="e3" value="Reads/Writes (SQL)" style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;strokeColor=#666666;fontFamily=Helvetica;fontSize=11;fontColor=#555555;"
                edge="1" parent="1" source="api" target="db">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>
        <mxCell id="e4" value="Charges (REST)" style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;strokeColor=#666666;fontFamily=Helvetica;fontSize=11;fontColor=#555555;"
                edge="1" parent="1" source="api" target="pay">
          <mxGeometry relative="1" as="geometry" />
        </mxCell>

        <!-- legend -->
        <mxCell id="legend" value="&lt;b&gt;Legend&lt;/b&gt;&lt;br&gt;&lt;font color=&quot;#6C8EBF&quot;&gt;&#9632;&lt;/font&gt; Container&#160;&#160;&lt;font color=&quot;#9673A6&quot;&gt;&#9632;&lt;/font&gt; Data store&lt;br&gt;&lt;font color=&quot;#666666&quot;&gt;&#9632;&lt;/font&gt; External / person&lt;br&gt;&#8594; labelled with the interaction"
                style="rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=top;fillColor=#FFFFFF;strokeColor=#CCCCCC;fontFamily=Helvetica;fontSize=11;spacingLeft=6;spacingTop=4;"
                vertex="1" parent="1">
          <mxGeometry x="150" y="520" width="300" height="110" as="geometry" />
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
```

---

## 3. Activity flow (standard UML activity diagram)

Standard notation: a filled **initial node** (●), rounded **actions**, a **decision** diamond
(labelled question; each outgoing edge labelled with its guard `[yes]`/`[no]`), a **fork/join** bar
for parallel work, and a **final node** (◉). Flow runs top→down in execution order. Ground each
action/decision in the real code path (codegraph the flow). Colour error paths/states red.

```xml
<mxfile host="devant">
  <diagram name="Activity" id="act">
    <mxGraphModel dx="900" dy="760" grid="1" gridSize="10" guides="1" tooltips="1" connect="1"
                  arrows="1" fold="1" page="1" pageScale="1" pageWidth="850" pageHeight="1100"
                  math="0" shadow="0">
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />

        <!-- initial node -->
        <mxCell id="start" value="" style="ellipse;fillColor=#000000;strokeColor=#000000;html=1;"
                vertex="1" parent="1">
          <mxGeometry x="400" y="40" width="30" height="30" as="geometry" />
        </mxCell>

        <mxCell id="a1" value="Add item to cart" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#DAE8FC;strokeColor=#6C8EBF;fontFamily=Helvetica;fontSize=13;"
                vertex="1" parent="1">
          <mxGeometry x="335" y="110" width="160" height="60" as="geometry" />
        </mxCell>

        <!-- decision -->
        <mxCell id="d1" value="Logged in?" style="rhombus;whiteSpace=wrap;html=1;fillColor=#FFF2CC;strokeColor=#D6B656;fontFamily=Helvetica;fontSize=13;"
                vertex="1" parent="1">
          <mxGeometry x="345" y="210" width="140" height="80" as="geometry" />
        </mxCell>

        <mxCell id="a2" value="Show login" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#DAE8FC;strokeColor=#6C8EBF;fontFamily=Helvetica;fontSize=13;"
                vertex="1" parent="1">
          <mxGeometry x="120" y="220" width="160" height="60" as="geometry" />
        </mxCell>

        <!-- fork bar: parallel work -->
        <mxCell id="fork" value="" style="rounded=0;fillColor=#000000;strokeColor=#000000;html=1;"
                vertex="1" parent="1">
          <mxGeometry x="320" y="340" width="190" height="8" as="geometry" />
        </mxCell>
        <mxCell id="a3" value="Reserve inventory" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#DAE8FC;strokeColor=#6C8EBF;fontFamily=Helvetica;fontSize=13;"
                vertex="1" parent="1">
          <mxGeometry x="230" y="380" width="160" height="60" as="geometry" />
        </mxCell>
        <mxCell id="a4" value="Charge card" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#DAE8FC;strokeColor=#6C8EBF;fontFamily=Helvetica;fontSize=13;"
                vertex="1" parent="1">
          <mxGeometry x="440" y="380" width="160" height="60" as="geometry" />
        </mxCell>
        <!-- join bar -->
        <mxCell id="join" value="" style="rounded=0;fillColor=#000000;strokeColor=#000000;html=1;"
                vertex="1" parent="1">
          <mxGeometry x="320" y="470" width="190" height="8" as="geometry" />
        </mxCell>

        <mxCell id="d2" value="Payment OK?" style="rhombus;whiteSpace=wrap;html=1;fillColor=#FFF2CC;strokeColor=#D6B656;fontFamily=Helvetica;fontSize=13;"
                vertex="1" parent="1">
          <mxGeometry x="345" y="510" width="140" height="80" as="geometry" />
        </mxCell>

        <mxCell id="a5" value="Show error" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#F8CECC;strokeColor=#B85450;fontFamily=Helvetica;fontSize=13;"
                vertex="1" parent="1">
          <mxGeometry x="120" y="520" width="160" height="60" as="geometry" />
        </mxCell>
        <mxCell id="a6" value="Create order" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#D5E8D4;strokeColor=#82B366;fontFamily=Helvetica;fontSize=13;"
                vertex="1" parent="1">
          <mxGeometry x="335" y="620" width="160" height="60" as="geometry" />
        </mxCell>

        <!-- final node (ring + filled core) -->
        <mxCell id="end_ring" value="" style="ellipse;fillColor=none;strokeColor=#000000;strokeWidth=2;html=1;"
                vertex="1" parent="1">
          <mxGeometry x="400" y="710" width="30" height="30" as="geometry" />
        </mxCell>
        <mxCell id="end_core" value="" style="ellipse;fillColor=#000000;strokeColor=#000000;html=1;"
                vertex="1" parent="1">
          <mxGeometry x="407" y="717" width="16" height="16" as="geometry" />
        </mxCell>

        <!-- edges (guards on decision branches) -->
        <mxCell id="f1" style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;strokeColor=#666666;" edge="1" parent="1" source="start" target="a1"><mxGeometry relative="1" as="geometry" /></mxCell>
        <mxCell id="f2" style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;strokeColor=#666666;" edge="1" parent="1" source="a1" target="d1"><mxGeometry relative="1" as="geometry" /></mxCell>
        <mxCell id="f3" value="[no]" style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;strokeColor=#666666;fontFamily=Helvetica;fontSize=11;fontColor=#555555;" edge="1" parent="1" source="d1" target="a2"><mxGeometry relative="1" as="geometry" /></mxCell>
        <mxCell id="f4" style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;strokeColor=#666666;" edge="1" parent="1" source="a2" target="d1"><mxGeometry relative="1" as="geometry" /></mxCell>
        <mxCell id="f5" value="[yes]" style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;strokeColor=#666666;fontFamily=Helvetica;fontSize=11;fontColor=#555555;" edge="1" parent="1" source="d1" target="fork"><mxGeometry relative="1" as="geometry" /></mxCell>
        <mxCell id="f6" style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;strokeColor=#666666;" edge="1" parent="1" source="fork" target="a3"><mxGeometry relative="1" as="geometry" /></mxCell>
        <mxCell id="f7" style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;strokeColor=#666666;" edge="1" parent="1" source="fork" target="a4"><mxGeometry relative="1" as="geometry" /></mxCell>
        <mxCell id="f8" style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;strokeColor=#666666;" edge="1" parent="1" source="a3" target="join"><mxGeometry relative="1" as="geometry" /></mxCell>
        <mxCell id="f9" style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;strokeColor=#666666;" edge="1" parent="1" source="a4" target="join"><mxGeometry relative="1" as="geometry" /></mxCell>
        <mxCell id="f10" style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;strokeColor=#666666;" edge="1" parent="1" source="join" target="d2"><mxGeometry relative="1" as="geometry" /></mxCell>
        <mxCell id="f11" value="[no]" style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;strokeColor=#B85450;fontFamily=Helvetica;fontSize=11;fontColor=#B85450;" edge="1" parent="1" source="d2" target="a5"><mxGeometry relative="1" as="geometry" /></mxCell>
        <mxCell id="f12" value="[yes]" style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;strokeColor=#666666;fontFamily=Helvetica;fontSize=11;fontColor=#555555;" edge="1" parent="1" source="d2" target="a6"><mxGeometry relative="1" as="geometry" /></mxCell>
        <mxCell id="f13" style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;strokeColor=#666666;" edge="1" parent="1" source="a6" target="end_ring"><mxGeometry relative="1" as="geometry" /></mxCell>

        <!-- legend -->
        <mxCell id="legend" value="&lt;b&gt;Legend&lt;/b&gt;&lt;br&gt;&#9679; start&#160;&#160;&#9678; end&#160;&#160;&#9670; decision&lt;br&gt;&#9644; fork/join (parallel)&lt;br&gt;&lt;font color=&quot;#B85450&quot;&gt;&#9632;&lt;/font&gt; error path&#160;&#160;[guard] on branches"
                style="rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=top;fillColor=#FFFFFF;strokeColor=#CCCCCC;fontFamily=Helvetica;fontSize=11;spacingLeft=6;spacingTop=4;"
                vertex="1" parent="1">
          <mxGeometry x="620" y="40" width="200" height="110" as="geometry" />
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
```

**Swimlanes / partitions (optional).** To assign actions to responsible parties (e.g. *Customer* vs
*System*), wrap the flow in a `swimlane` pool with one lane per party and parent each action to its
lane (child coordinates are relative to the lane):

```xml
<mxCell id="pool" value="Checkout" style="swimlane;html=1;horizontal=0;fontFamily=Helvetica;fontStyle=1;startSize=24;" vertex="1" parent="1">
  <mxGeometry x="40" y="40" width="760" height="300" as="geometry" />
</mxCell>
<mxCell id="lane_customer" value="Customer" style="swimlane;html=1;horizontal=0;fontFamily=Helvetica;startSize=24;fillColor=none;" vertex="1" parent="pool">
  <mxGeometry x="24" y="0" width="368" height="300" as="geometry" />
</mxCell>
<mxCell id="lane_system" value="System" style="swimlane;html=1;horizontal=0;fontFamily=Helvetica;startSize=24;fillColor=none;" vertex="1" parent="pool">
  <mxGeometry x="392" y="0" width="368" height="300" as="geometry" />
</mxCell>
<!-- then: parent="lane_customer" (or lane_system) on each action, with x/y relative to that lane -->
```

---

## 4. XML well-formedness (get this wrong and the file won't open)

A malformed `.drawio` opens blank or errors. Hard rules:
- **Never emit XML comments (`<!-- -->`) in the file you write.** The `<!-- ... -->` notes in the
  skeletons above are teaching annotations — strip them from real output. A stray `--` inside a
  comment is itself a parse error.
- **Escape every special char in attribute values:** `&` → `&amp;`, `<` → `&lt;`, `>` → `&gt;`,
  `"` → `&quot;`. (That's why the HTML labels above are written `&lt;b&gt;…&lt;/b&gt;`.)
- **Every `id` is unique.** Duplicate ids silently drop cells.
- **Every edge needs its child geometry** — `<mxCell edge="1" …><mxGeometry relative="1" as="geometry"/></mxCell>`.
  A self-closed edge (`<mxCell edge="1" … />`) does not render.
- **The root always has cells `id="0"` and `id="1"`**; every shape/edge is `parent="1"` (or a
  container id). Missing these two → blank canvas.
- Validate before claiming done:
  `python3 -c "import xml.dom.minidom,sys; xml.dom.minidom.parse(sys.argv[1])" <file>`.

## 5. Edge routing & avoiding crossings

Crossing or shape-piercing edges are what make a diagram look amateur. Keep them clean:
- **Distribute connection points** so parallel edges don't stack on one anchor. Set explicit
  exit/entry ratios on the edge style, e.g. `exitX=1;exitY=0.5;entryX=0;entryY=0.5;` (0–1 along the
  node's width/height). Two edges leaving the same node should use different `exitY` values.
- **Route around an obstructing shape with waypoints** instead of letting a line cut through it:
  ```xml
  <mxCell id="e" style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;strokeColor=#666666;" edge="1" parent="1" source="a" target="b">
    <mxGeometry relative="1" as="geometry">
      <Array as="points"><mxPoint x="480" y="300" /></Array>
    </mxGeometry>
  </mxCell>
  ```
- **Give edge labels a white background** (`labelBackgroundColor=#FFFFFF`) so they stay legible where
  a line passes behind them.
- **Spacing scales with size** — more nodes ⇒ more gap. If two shapes ever visually touch, push them
  ≥ 120 px apart rather than shrinking them.
- **One dominant direction.** If you find yourself drawing an edge *backwards* against the flow
  (bottom→top in a top-down diagram), reconsider node order first; only then add waypoints.

Before saving, eyeball the layout as if it were exported and fix: overlapping shapes, clipped
labels (widen the node), arrows that don't touch their target, off-canvas cells, edges crossing an
unrelated shape, and stacked/overlapping edges. These are the same defects a rendered self-check
would catch — catch them here since devant draws XML-only with no render step.

## 6. Checklist before saving
- Every box/step maps to something real in codegraph — no invented components.
- Colours used only per the palette table; a legend explains them.
- Every edge is labelled (interaction for architecture; guard for decision branches).
- One flow direction; minimal edge crossings; coordinates on the 10 px grid.
- Filename: `docs/diagrams/architecture-<name>.drawio` or `activity-<flow-name>.drawio`
  (kebab-case slug). Update in place if it exists.
- Well-formed XML (`python3 -c "import xml.dom.minidom,sys; xml.dom.minidom.parse(sys.argv[1])" <file>`)
  and confirmed it opens in draw.io / diagrams.net.
