---
name: slide
user-invocable: false
allowed-tools: Bash(soffice *), Bash(devant *), Bash(python3 *)
description: devant specialist (work-invoked): build a business-professional slide deck — a committed deck spec into `devant slide-build`, rendered to one editable .pptx via the LibreOffice CLI on a user-fed brand (tasteful warm-neutral default; bold flat colour, no gradient, no shadow, no cartoon). 15 seconds per slide.
---

# devant: slide

Build a deck a business audience reads in **~15 seconds per slide** and that looks like a real
enterprise design team made it — *not* an AI. One idea per slide, a headline that states the
*takeaway* (not the topic), bold flat colour, generous whitespace.

The intent CLI is `devant`; the rendering engine is the LibreOffice CLI (`soffice`).

## The pipeline
**Deliverables: `docs/slides/<name>.pptx` (the deck) + `docs/slides/<name>.deck.json` (the spec —
committed, the source of truth, dec-046).** The `.fodp` and the gate `.pdf` are temp-dir
intermediates, deleted after. `devant slide-build` computes all geometry — deterministic, aligned,
margin-safe by construction; placing absolute-cm boxes is never the model's job.

## Do this
1. **Shape the story first.** ≤1 idea per slide; write each slide's takeaway headline. Deck about
   this codebase → ground names/flows in `devant graph explore`/`search`. Arc: title → the idea →
   how it works (a milestone flow) → the outcome.
2. **Load the rules, resolve the brand.** Read `references/anti-slop.md` (non-negotiable anti-AI
   tells: zero em-dashes, one accent, kicker restraint, no decoration, copy audit) and
   `references/brand-kit.md` (token roles, grid, archetypes). Brand is a token file, first-hit-wins:
   `--brand <path>` → `docs/slides/brand.json` → `.devant/brand.json` → shipped default (Ink &
   Signal). A partial user file deep-merges over the default; a brand given in prose becomes a
   partial `$WORK/brand.json`. Never hand-copy hex or font names — `devant slide-styles` emits the
   style block, and `slide-build` embeds it automatically.
3. **The spec IS the deck — committed, patched on re-run (dec-046).**
   - New deck: write `docs/slides/<name>.deck.json` — a JSON array of slide objects,
     `{"archetype": "...", ...content}`. Prefer to *show*, not narrate: `title`,
     `section-divider`, `milestone-flow`, `metric` (hero stat + `src`), `two-column-compare`,
     `three-point`, `process-flow`. A one-off the archetypes can't express: one
     `{"archetype": "raw", "fodp": "<draw:page>…</draw:page>"}` item — ONLY for that page, start
     from `references/brand-sample.fodp` geometry and reuse its styles (its style block IS
     `slide-styles` output, test-enforced). In-slide visuals are flat geometric primitives or a
     single-colour SVG path — never cartoon/3-D/emoji; never a standalone `.drawio` (that's
     `devant:diagram`). Escape `&` `<` `>` in all text.
   - Existing deck: **read and PATCH the existing `.deck.json`** — never re-author from scratch;
     the user's tuning lives there and must survive. Announce what changed.
   - Build: `WORK=$(mktemp -d); devant slide-build docs/slides/<name>.deck.json [--brand …]
     -o $WORK/<name>.fodp` (validates fail-loud).
4. **Render:**
   ```
   soffice --headless --convert-to pptx --outdir docs/slides $WORK/<name>.fodp   # kept
   soffice --headless --convert-to pdf  --outdir $WORK       $WORK/<name>.fodp   # gate only
   ```
   `soffice` absent → do not fake it: hand over the `.fodp` (opens in Impress), name the one-time
   install, let the user decide. Never claim a look you didn't render.

## Done = rendered AND on-brand AND editable (gate it — no report-only)
- **(a)** Well-formed: `python3 -c "import xml.dom.minidom,sys; xml.dom.minidom.parse(sys.argv[1])" $WORK/<name>.fodp`.
- **(b)** Both `soffice` conversions exit clean.
- **(c) Anti-slop gate (mechanical):** `devant slide-lint $WORK/<name>.fodp [--brand PATH]` exits 0
  — blocks off-brand colours, fabricated hero figures (no `src:`/`mock:`), decorative numberless
  charts, em/en-dashes, kicker overuse. Fix the spec and re-run until clean.
- **(d) Vision pass (1 + at most 1 corrective round, dec-045):** Read the `$WORK/<name>.pdf` —
  flat colour, no gradient/shadow/cartoon, one accent used sparingly, the idea *shown*, nothing
  past the 1.6 cm margin. Geometry is deterministic — this pass catches text overflow and font
  substitution, not alignment.
- **(e)** `unzip -l docs/slides/<name>.pptx` shows one `ppt/slides/slideN.xml` per slide.
- **(f)** `rm -rf "$WORK"` — `docs/slides/` holds the `.pptx`, the `.deck.json`, and (optionally)
  `brand.json`; no stray `.fodp`/`.pdf`.

Tell the user: the `.pptx` opens editable in PowerPoint / Google Slides / Impress, and the
`.deck.json` beside it is what future re-runs patch — content edits can go to either.

## Traps (verified on LibreOffice 24.2)
- **Headless import fixes the canvas at 28 × 15.75 cm** whatever the `.fodp` declares — author to
  that canvas with a 1.6 cm safe margin; the vision pass catches overflow.
- **Fonts render only if installed** — LibreOffice substitutes silently; the gate PDF shows the
  real font. Fallback stack lives in `brand-kit.md`.
- **No gradient / no shadow is enforced in the XML**: every fill is `draw:fill="solid"` +
  `draw:shadow="hidden"` — a deck that can't accidentally look AI-made.

This skill builds decks and visualizes ideas *inside* slides. It does not design the underlying
plan (that's `devant:design`), emit standalone `.drawio` files (that's `devant:diagram`), or edit
code.
