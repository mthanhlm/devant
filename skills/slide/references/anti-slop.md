# Anti-slop rules for decks

Adapted from **leonxlnx/taste-skill** (MIT) — an anti-slop *frontend* skill. It isn't for slides, but
its rules are the sharpest catalogue of "this looks AI-made" tells in existence, and they transfer
directly to presentation design. Read this BEFORE authoring, and run the pre-flight BEFORE delivering.

The goal: a deck that looks like a design team made it, not a template a model filled in. Most slop
comes from reaching for the same defaults. Reach past them on purpose.

## Two hard bans (non-negotiable)

1. **ZERO em-dashes.** `—` and `–` are the #1 AI writing tell. Banned in every visible string:
   titles, kickers, body, captions, labels, wordmarks. Rewrite instead — a period, a comma, a colon,
   parentheses, or a line break. Ranges use a plain hyphen (`2018-2026`, not `2018–2026`). The only
   dash allowed on a slide is the hyphen `-`. **Pre-flight greps for `—`/`–`; a single hit fails.**
2. **One accent, locked.** A neutral base (warm near-black + clean paper + one grey) plus **exactly
   one** accent colour, used sparingly and consistently on every slide. Two accents (the blue+cyan
   mistake) is slop. Specifically avoid the LLM-default palettes: AI purple / blue-glow, the
   dark-tech cyan/teal SaaS look, warm cream+brass "premium" beige. Accent saturation stays sensible;
   pick it for *meaning*, then audit that nothing else on the deck is coloured.

## Structural tells to kill

- **Kicker restraint.** The small UPPERCASE label above a headline (`THE PROBLEM`, `HOW IT WORKS`)
  is fine **once, maybe twice in a whole deck** — not on every slide. It produces the templated
  rhythm that screams AI. Default: drop it. The headline alone says what the slide is.
- **No `01 / 06` pagination** as decoration, and **no per-slide footer strip** (`brand · tagline`).
  If the audience can count slides they don't need the number. A single small wordmark on a slide is
  fine; a tagline strip repeated on all of them is decoration.
- **Middle-dot `·` is rationed** — max one per line, never the default separator for everything.
- **No three equal cards in a row** to fill space. Use asymmetry, a vertical list with hairline
  dividers, a 2+1 split, or grouped clusters. A grid is honest only when you have N real items and
  show exactly N cells (a real 3×3 of nine things is fine; three equal cards padding a row is not).
- **No fake data viz.** Decorative bar charts, progress tracks, or scoring bars with no real numbers
  are banned. A number appears only if it is real or explicitly a mock. No invented precision
  (`92%`, `3.2×`) to look quantitative.
- **No decorative status dots**, no crosshair/hairline grids drawn just to "feel designed."
- **No shouty ALL-CAPS word** mid-headline for emphasis. Emphasise with weight or italic of the
  **same** font. Never switch font family for one word.
- **Consistency locks:** one corner-radius scale for the whole deck; one type family; the accent is
  the accent everywhere.

## Copy self-audit (before ship)

Re-read every visible string and rewrite anything that:
- uses a **filler verb** (Elevate, Seamless, Unleash, Leverage, Next-Gen, Revolutionize, Empower),
- is **AI-cute** (forced metaphor, mock-humble craftsmanship, poetic micro-meta), or
- uses a **generic step label** (`Stage 1 / 2 / 3`). The step's real content is the label.

Plain functional sentences beat clever ones. A headline states the takeaway in plain language.

## Typography

- **Avoid Inter as the default** (an LLM tell). Noto Sans (installed) is an acceptable neutral;
  a sans *display* cut is better where one is installed. **Serif is a tell as a default** — reach for
  it only on genuinely editorial / heritage briefs, and never inject a serif word into a sans
  headline.
- Control hierarchy with **weight + size + colour**, not just an oversized H1 that screams.

## Palette discipline

- **Warm near-black**, not pure `#000000`. **Clean paper**, not warm cream/beige. One mid grey, one
  hairline. **One accent**, chosen for meaning, locked across the deck.

## Pre-flight check (run `devant slide-lint <deck.fodp>` before delivering; any failure = rewrite)

`devant slide-lint` mechanizes most of this: it exits non-zero on an off-brand colour, a fabricated
hero figure (a big number with no `src:`/`mock:` on its slide), a decorative numberless chart,
em/en-dashes, and kicker overuse. It is the gate; the list below is what it (and your eye) check:

1. Em/en-dashes → must be **0** (slide-lint blocks any).
2. UPPERCASE kickers → **≤ ceil(slides / 3)** (slide-lint enforces).
3. Every fill/text colour is a `brand.json` token — neutrals **plus exactly one** accent hue
   (slide-lint blocks an off-brand hex; the single-accent lock is structural).
4. No `0X / 0Y` pagination string; no tagline footer repeated on every slide.
5. Every number is real or labelled mock — a big unsourced figure and a numberless bar chart both
   fail slide-lint.
6. Corner radius and font family are single-valued across all slides.
