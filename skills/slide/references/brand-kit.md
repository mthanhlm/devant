# devant slide brand kit — the enterprise default

One fixed design language so every deck looks like the same team made it. Editorial, restrained,
flat, generous whitespace, strong type hierarchy. Read **`references/anti-slop.md` first** — it is
the rulebook this kit obeys (zero em-dashes, one accent, kicker restraint, no decoration). This kit
prevents the cartoon look (no childish/3-D/emoji icons, no gradients, no drop-shadows) AND the
"obviously AI" look (no dark-tech blue/cyan SaaS palette, no purple glow, no per-slide kicker+footer
template).

## Palette — "Ink & Signal" (neutral base + ONE accent; use the hex verbatim)

A near-monochrome editorial base with a single signal-red accent, chosen for meaning: devant
**guards** intent and **pushes back**, so red carries the moments that matter (the one thing to look
at on each slide). Mostly ink and paper; the accent is rare, which is what makes it read as
designed, not decorated.

| Token | Hex | Use for |
|---|---|---|
| **Ink** | `#1B1A17` | warm near-black — dark backgrounds, headlines on light, body text (never pure `#000`) |
| **Paper** | `#FFFFFF` | default light background; text on Ink and on the accent |
| **Panel** | `#F2F1EE` | subtle off-white band for grouping on a light slide (neutral, not cream) |
| **Grey** | `#6E6B64` | captions, sub-labels, secondary text on light |
| **Mist** | `#9C9A93` | secondary text on the Ink background |
| **Hairline** | `#E4E2DC` | dividers, table rules, the 1px lines that organise real content |
| **Accent** (Signal) | `#C4351F` | THE one accent — a rule, a key word, the active item, the guard/pushback moment |

**One accent, locked (anti-slop.md).** `#C4351F` is the only hue on the deck; everything else is
Ink / Paper / Grey / Hairline. Do not add a second accent. On an accent fill, secondary text uses a
light tint `#F5D9D2`. Use the accent sparingly: if half the slide is red, nothing stands out.

These are the **default** tokens, encoded verbatim in `references/brand.json`. To use your own
brand, feed a `brand.json` (the skill's step 2): the whole deck derives from those tokens, so it
re-brands from one file, and `devant slide-lint` checks every colour against them.

## Type
- **Brand font:** Noto Sans. **Stack (fallback):** `Noto Sans, "Helvetica Neue", Arial, "Liberation Sans", sans-serif`.
  Noto Sans is a clean modern humanist sans that ships on most Linux/LibreOffice installs (unlike
  Inter, which usually isn't installed). LibreOffice substitutes silently if it's absent — the
  internal `.pdf` gate shows what actually rendered, so check it. If Noto Sans is missing, fall back
  to Carlito (Calibri-metric) or Liberation Sans before Arial.
- **Scale (pt, on the 28 × 15.75 cm canvas):** display figure 80 · H1 40 · H2 27 · card title 16 ·
  body 14–18 · eyebrow 12 (bold, letter-spaced, UPPERCASE) · caption 11. Weight: bold for
  headlines/figures/eyebrows, regular for body. Left-aligned; never centre body text.
- Headlines state the **takeaway**, not the topic ("Four phases, one straight line to cash", not
  "Process Overview"). ≤ ~3 supporting lines per slide.

## Layout grid
- **Canvas: 28 × 15.75 cm, 16:9** (LibreOffice fixes this on headless import — don't fight it).
- **Margin: 1.6 cm** all sides — nothing crosses it. Eyebrow at y≈1.3–1.6, headline below it,
  content band from y≈6.
- Multi-item rows: equal-width blocks, equal gaps (~0.6 cm). Align everything to a column; ragged
  left edges read as amateur.

## Hard rules (the anti-AI-look contract — enforced in the XML)
1. **Fills are solid.** Every shape: `draw:fill="solid"`. **Never** `draw:fill="gradient"`.
2. **No shadows.** Every shape: `draw:shadow="hidden"`. **Never** a shadow property.
3. **Icons/graphics are flat and geometric** — built from `draw:rect` / `draw:ellipse` / `draw:line`
   / `draw:polyline` in brand colours, or one simple single-colour inline SVG path. No cartoon,
   no 3-D, no emoji, no clip-art.
4. **≤ 3 colours per slide**, one Accent pop. Bold, not neon; confident, not toy.
5. **Whitespace is a feature** — one idea per slide, big type, room to breathe.

## Slide archetypes (in `brand-sample.fodp`, ready to copy)
- **Title** — Ink full-bleed, an Accent square mark, H1 in Paper, an Accent rule, a Grey/Mist subtitle.
- **Milestone flow** — Paper slide, eyebrow + takeaway headline, 3–6 equal Cloud cards left→right
  (the last card filled Accent = the outcome), numbered, `>` chevrons between them. The
  15-second "how it works".
- **Process flow (in-slide diagram)** — *visualize the logic, don't narrate it.* Flat boxes
  connected by real arrows (`draw:line` with a `draw:marker-end` triangle, defined once in
  `<office:styles>`), left→right or top→down; a decision as an Accent-outlined box; a **loop**
  as a return arrow labelled with its guard. This is how a data-flow / control-flow / "how it works"
  logic lands in one slide — the diagram devant draws *inside* the deck (a standalone `.drawio` is
  `devant:diagram`, a different tool).
- **Metric / outcome** — Ink slide, a large Accent figure (only if the number is **real**), a Paper
  takeaway line, a Grey/Mist support line. No decorative bar chart — a fabricated chart is slop
  (anti-slop.md); show a real number or none.
- Add **section divider**, **two-column compare**, **three-point** by recombining the same styles.

**Arrow marker** (define once in `<office:styles>`, reference from a line style):
```xml
<draw:marker draw:name="tri" svg:viewBox="0 0 10 10" svg:d="M5 0 0 10 10 10 z"/>
```
```xml
<style:style style:name="flow" style:family="graphic"><style:graphic-properties draw:stroke="solid"
  svg:stroke-width="0.06cm" svg:stroke-color="#1B1A17" draw:marker-end="tri"
  draw:marker-end-width="0.35cm" draw:shadow="hidden"/></style:style>
```
then `<draw:line draw:style-name="flow" svg:x1=".." svg:y1=".." svg:x2=".." svg:y2=".."/>`.

## The reusable style block
Don't hand-copy hex — run **`devant slide-styles [--brand PATH]`** to emit the full
`<office:automatic-styles>` block (page layout, drawing-page fills `dpDark`/`dpPaper`, the
no-fill/no-shadow text style `gText`, card/shape styles `gCardPanel`/`gCardAccent`/`gGrey`/`gHair`,
and every paragraph style `pH1w`/`pH2i`/`pNumA`/`pCardI`/`pDescS`/`pFig`/…) from the resolved
`brand.json` tokens, and paste it as the deck's style block. `references/brand-sample.fodp` carries
exactly that default output (test-enforced to equal the generator, so it can't drift) plus one
example of each archetype — copy its geometry and add slide content. Two rules are baked into every
graphic style: `draw:stroke="none"` and `draw:shadow="hidden"`.
