---
name: slide
user-invocable: false
allowed-tools: Bash(soffice *), Bash(devant *), Bash(python3 *)
description: devant specialist (router-invoked): build a business-professional slide deck — the deliverable is a single editable .pptx (hand-authored flat-ODP source + PDF visual-gate are throwaway intermediates), rendered via the LibreOffice CLI on a brand the user feeds as a small token file (a tasteful warm-neutral default is the fallback; bold flat colour, no gradient, no shadow, no cartoon), ideas shown as in-slide diagrams. 15 seconds per slide.
---

# devant: slide

Build a deck a business audience reads in **~15 seconds per slide** and that looks like a real
enterprise design team made it — *not* an AI. One idea per slide, a headline that states the
*takeaway* (not the topic), bold flat colour, generous whitespace. Communicating the plan is part
of the work (dec-029): the deck exists to get the idea understood and bought, not to list detail.

The intent CLI is `devant`. The rendering engine is the LibreOffice CLI (`soffice`, dec-029/dec-030).

## The pipeline (why it's shaped this way)
**The only deliverable is `<name>.pptx`.** The `.fodp` (hand-authored source) and the `.pdf`
(internal visual gate) are throwaway intermediates — author/render them in a **temp dir** and
delete them, so a slide request leaves exactly one file in the user's folder. Author each slide as
**flat ODF-presentation XML (`.fodp`)** by hand — the same competency devant uses to author
`.drawio` XML — then convert with `soffice`:
- `soffice --headless --convert-to pptx --outdir <docs/slides> <work>/<deck>.fodp` → the **editable
  deliverable** kept in the repo (opens in PowerPoint / Google Slides / Impress). devant does NOT
  read your edits back: a re-run regenerates the deck from the story + brand and overwrites this
  file (step 5), so keep manual tweaks in the `.pptx` or hand devant the updated content on re-run.
- `soffice --headless --convert-to pdf --outdir <work> <work>/<deck>.fodp` → the **internal visual
  gate**: Read the PDF pages with vision to confirm it reads, then delete it. Never delivered.
Full control of the XML is what lets us *guarantee* the anti-AI look — no gradient, no shadow, no
cartoon — by construction, rather than hoping a template avoids them.

## Do this
1. **Shape the story first, not the slides.** Decide the ≤1 idea per slide and write each slide's
   **takeaway headline**. If the deck is about this codebase, ground names/flows in
   `devant graph explore`/`search` (don't invent); otherwise use the user's material. Keep the
   arc tight: title → the idea → how it works (a milestone flow) → the outcome. Not too much text,
   not too little — a viewer should neither read a paragraph nor be left asking "so what?".
2. **Load the rules, then resolve the brand.** Read `references/anti-slop.md` (the non-negotiable
   anti-AI-tell rules: zero em-dashes, one accent, kicker restraint, no decoration, copy audit) and
   `references/brand-kit.md` (the token roles, the layout grid, the archetypes). The brand is a
   **token file, not baked in** — resolve `brand.json` first-hit-wins: `--brand <path>`, else
   `docs/slides/brand.json`, else `.devant/brand.json`, else the shipped default
   `references/brand.json` (Ink & Signal). A user file is deep-merged over the default, so
   `{"palette":{"accent":"#0B5FFF"}}` re-brands the whole deck; if the user gave a brand in prose (a
   colour or two, a font), map it to tokens, write that partial to `$WORK/brand.json`, and pass
   `--brand $WORK/brand.json`. **Do not hand-copy hex or font names** — run
   `devant slide-styles [--brand PATH]` and paste its output as the deck's `<office:automatic-styles>`
   block. Start from `references/brand-sample.fodp` for archetype GEOMETRY only: its style block IS
   `slide-styles`' default output (test-enforced, so it can't drift) — reuse those styles, don't
   freehand new ones.
3. **Author the `.fodp` in a temp dir** (`WORK=$(mktemp -d)`; write `$WORK/<name>.fodp`) on the
   **fixed 28 × 15.75 cm canvas** (16:9), everything inside a 1.6 cm margin. **Prefer to visualize,
   not narrate** — carry the idea with an *in-slide diagram* (a flat flow of boxes + arrows, a
   milestone row, a compare, numbered steps, a bar mark), not a paragraph. Compose from the
   archetypes (title, section divider, milestone-flow, metric/outcome, two-column compare,
   three-point, **process-flow**). Every icon/diagram is **flat geometric primitives**
   (`draw:rect`/`draw:ellipse`/`draw:line`/`draw:polyline` filled in brand colours, arrows via
   `draw:line` with `marker-end`) or a simple single-colour inline SVG path — never a cartoon, 3-D,
   or emoji glyph. These diagrams live *inside the slide*; do NOT emit a standalone `.drawio`
   (that's `devant:diagram`). Escape `&`→`&amp;`, `<`→`&lt;`, `>`→`&gt;` in all text.
4. **Render — deliverable is only the `.pptx`:**
   ```
   soffice --headless --convert-to pptx --outdir <docs/slides> $WORK/<name>.fodp   # kept
   soffice --headless --convert-to pdf  --outdir $WORK          $WORK/<name>.fodp   # gate only
   ```
   If `soffice` is absent (`command -v soffice` empty), **do not fake it**: hand the user the
   `.fodp` (it opens in LibreOffice Impress), say the `.pptx` and the visual gate need LibreOffice,
   and let them decide — mirror how the diagram skill degrades when a tool is missing. Never claim a
   look you didn't render.
5. **Write location & cleanup.** The one kept file is `docs/slides/<name>.pptx` (`<name>` a short
   kebab-case slug). If it exists, devant **re-authors the whole deck from the current request and
   overwrites it** (no `-v2`, no incremental edit) — announce that and confirm before clobbering,
   because a re-run does NOT read the existing `.pptx` back, so edits made directly in
   PowerPoint/Impress since the last run are lost unless handed back. After the visual gate passes,
   **`rm -rf "$WORK"`** so the `.fodp`/`.pdf` don't linger. The only optional persisted extra is
   `docs/slides/brand.json`, written when the user wants a reproducible/committed brand; otherwise a
   slide request leaves exactly the one `.pptx`.

## Done = rendered AND on-brand AND editable (gate it — no report-only)
- **(a)** Well-formed XML: `python3 -c "import xml.dom.minidom,sys; xml.dom.minidom.parse(sys.argv[1])" <deck.fodp>`.
- **(b)** `soffice` converts to the `.pptx` (kept) and the `.pdf` (in `$WORK`) without error.
- **(c) Anti-slop gate (mechanical, run on the `.fodp` before rendering):**
  `devant slide-lint <deck.fodp> [--brand PATH]` must **exit 0**. It blocks on an off-brand colour
  (any hex not a `brand.json` token), a fabricated hero figure (a big number with no `src:`/`mock:`
  on its slide — `--allow-number "<v>"` for a real one), a decorative numberless chart
  (`--allow-chart` to accept a genuine mark), em/en-dashes, and kicker overuse (> ceil(slides/3)).
  Fix the XML and re-run until clean — this is what catches the fabricated-stat and decorative-chart
  tells the eyeball pass misses.
- **(d)** **Read the `$WORK/<name>.pdf` with vision** and confirm, per slide: **flat** colour, no
  gradient, **no drop-shadow**, **no cartoon/3-D icon**; the neutral base carries it with the one
  accent used sparingly; the key idea is *shown* (an in-slide diagram/flow), not just written;
  **nothing overflows the 1.6 cm margin** (LibreOffice fixes the canvas at 28 × 15.75 cm, see traps).
  Fix in the XML and re-render; **loop max 3 rounds**, then deliver.
- **(e)** Confirm the `.pptx` is a real editable deck: `unzip -l <name>.pptx` shows
  `ppt/slides/slide1.xml …` (one per slide).
- **(f)** **Clean up:** `rm -rf "$WORK"`, then `ls docs/slides/` shows **only `<name>.pptx`**, no
  stray `.fodp`/`.pdf`.

Tell the user the one file — `docs/slides/<name>.pptx` — opens editable in PowerPoint / Google
Slides / Impress. Show the render inline if useful, but the PDF itself is not delivered.

## Traps (verified on LibreOffice 24.2 — heed them)
- **LibreOffice ignores a `.fodp`'s page size on headless import** — it always renders the deck at
  its default **28 × 15.75 cm** (16:9), whatever `fo:page-width` you set. So author to that canvas
  and keep a 1.6 cm safe margin; the (c) visual gate is what catches any overflow if a future
  LibreOffice default differs.
- **Fonts render only if installed** — the brand font (Noto Sans) falls back through the stack in
  `brand-kit.md`; LibreOffice substitutes silently, so the internal `.pdf` gate shows the *real*
  font. Noto Sans ships on most LibreOffice installs; if the gate shows a fallback, install it or
  drop to Carlito / Liberation Sans.
- **No gradient / no shadow is enforced in the XML**: every filled shape carries
  `draw:fill="solid"` and `draw:shadow="hidden"`; never emit `draw:fill="gradient"` or a shadow
  property. That is the whole point — a deck that can't accidentally look AI-made.

This skill builds decks — and **visualizes ideas with in-slide diagrams** (flat flows, boxes +
arrows, milestone rows). It does not design the underlying plan (that's `devant:architect`), emit a
standalone `.drawio` file (that's `devant:diagram` — the slide skill draws its visuals *inside the
slide*), or edit code.
