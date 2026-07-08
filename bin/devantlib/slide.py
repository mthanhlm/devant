"""Slide brand tokens -> ODF style block, plus the anti-slop .fodp linter (dec-036 redesign).
Stdlib only (con-stdlib): json, os, re, sys, xml.dom.minidom. Lazy-imported by the CLI.

`slide-styles` emits the <office:automatic-styles> block from a brand.json token file, so a
re-brand is one edit and the shipped sample's block can't drift from the generator. `slide-lint`
gates a .fodp on the anti-slop rules geometry can actually check: off-brand colour, a fabricated
hero figure, and a decorative (numberless) bar chart — the tells the old inline grep gate missed.
"""
import json
import os
import re
import sys
from xml.dom import minidom

_DEFAULT_BRAND = os.path.join(os.path.dirname(__file__), "..", "..",
                              "skills", "slide", "references", "brand.json")

# paragraph style-name -> (pt size, bold, palette token, text-align, extra text-props)
_PARA = [
    ("pH1w", 40, True, "paper", "start", ""),
    ("pSubL", 18, False, "mist", "start", ""),
    ("pEyeA", 12, True, "accent", "start", ' fo:letter-spacing="0.11cm"'),
    ("pH2i", 27, True, "ink", "start", ""),
    ("pNumA", 23, True, "accent", "start", ""),
    ("pNumW", 23, True, "paper", "start", ""),
    ("pCardI", 16, True, "ink", "start", ""),
    ("pCardW", 16, True, "paper", "start", ""),
    ("pDescS", 11, False, "grey", "start", ""),
    ("pDescW", 11, False, "accentTint", "start", ""),
    ("pChev", 20, True, "grey", "center", ""),
    ("pFig", 80, True, "accent", "start", ""),
    ("pH2w", 24, True, "paper", "start", ""),
    ("pBodyS", 14, False, "mist", "start", ""),
]
# solid-fill graphic style-name -> palette token (gText, the transparent frame, is emitted apart)
_GRAPHIC = [("gCardPanel", "panel"), ("gCardAccent", "accent"), ("gAccent", "accent"),
            ("gGrey", "grey"), ("gHair", "hairline")]


def _hex(s):
    return bool(re.match(r"^#[0-9A-Fa-f]{6}$", s or ""))


def _lerp(a, b, t):
    def ch(i):
        x, y = int(a[1 + 2 * i:3 + 2 * i], 16), int(b[1 + 2 * i:3 + 2 * i], 16)
        return round(x + (y - x) * t)
    return "#%02X%02X%02X" % (ch(0), ch(1), ch(2))


def _load_brand(path):
    """Resolve default <- user file (deep-merged), deriving any absent neutral from ink->paper so a
    user who feeds only ink/paper/accent still gets a harmonised ramp."""
    with open(_DEFAULT_BRAND) as fh:
        brand = json.load(fh)
    if path:
        with open(path) as fh:
            user = json.load(fh)
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(brand.get(k), dict):
                brand[k].update(v)
            else:
                brand[k] = v
    p = brand.setdefault("palette", {})
    if not (_hex(p.get("ink")) and _hex(p.get("paper")) and _hex(p.get("accent"))):
        raise ValueError("brand palette needs valid ink/paper/accent hex")
    ink, paper, accent = p["ink"], p["paper"], p["accent"]
    for tok, t in (("panel", 0.06), ("hairline", 0.12), ("mist", 0.40), ("grey", 0.58)):
        if not _hex(p.get(tok)):
            p[tok] = _lerp(ink, paper, t)
    if not _hex(p.get("accentTint")):
        p["accentTint"] = _lerp(accent, paper, 0.78)
    brand.setdefault("font", {}).setdefault("family", "Noto Sans")
    return brand


def _style_block(brand):
    p, font = brand["palette"], brand["font"]["family"]
    L = ["<office:automatic-styles>"]
    L.append('  <style:page-layout style:name="PL"><style:page-layout-properties '
             'fo:page-width="28cm" fo:page-height="15.75cm" style:print-orientation="landscape"/></style:page-layout>')
    L.append('  <style:style style:name="dpDark" style:family="drawing-page"><style:drawing-page-properties '
             'draw:fill="solid" draw:fill-color="%s"/></style:style>' % p["ink"])
    L.append('  <style:style style:name="dpPaper" style:family="drawing-page"><style:drawing-page-properties '
             'draw:fill="solid" draw:fill-color="%s"/></style:style>' % p["paper"])
    L.append('  <style:style style:name="gText" style:family="graphic"><style:graphic-properties '
             'draw:fill="none" draw:stroke="none" draw:shadow="hidden" draw:auto-grow-height="true"/></style:style>')
    for name, tok in _GRAPHIC:
        L.append('  <style:style style:name="%s" style:family="graphic"><style:graphic-properties '
                 'draw:fill="solid" draw:fill-color="%s" draw:stroke="none" draw:shadow="hidden"/></style:style>'
                 % (name, p[tok]))
    for name, size, bold, tok, align, extra in _PARA:
        w = ' fo:font-weight="bold"' if bold else ""
        L.append('  <style:style style:name="%s" style:family="paragraph"><style:paragraph-properties '
                 'fo:text-align="%s"/><style:text-properties style:font-name="%s" fo:font-size="%dpt"%s '
                 'fo:color="%s"%s/></style:style>' % (name, align, font, size, w, p[tok], extra))
    L.append("</office:automatic-styles>")
    return "\n".join(L)


def cmd_slide_styles(args):
    try:
        brand = _load_brand(getattr(args, "brand", None))
    except (OSError, ValueError, json.JSONDecodeError) as e:
        sys.stderr.write("devant: brand load failed: %s\n" % e)
        return 1
    print(_style_block(brand))
    return 0


def _text(node):
    if node.nodeType == node.TEXT_NODE:
        return node.data
    return "".join(_text(c) for c in node.childNodes)


def cmd_slide_lint(args):
    try:
        brand = _load_brand(getattr(args, "brand", None))
    except (OSError, ValueError, json.JSONDecodeError) as e:
        sys.stderr.write("devant: brand load failed: %s\n" % e)
        return 1
    try:
        dom = minidom.parse(args.file)
    except Exception as e:  # any malformed-XML error -> clean message, not a traceback
        sys.stderr.write("devant: cannot parse %s: %s\n" % (args.file, e))
        return 1
    allowed = {v.upper() for v in brand["palette"].values() if _hex(v)}
    allow_numbers = set(getattr(args, "allow_number", None) or [])
    fails = []

    sizes, solid = {}, set()
    for st in dom.getElementsByTagName("style:style"):
        name = st.getAttribute("style:name")
        for tp in st.getElementsByTagName("style:text-properties"):
            fs = tp.getAttribute("fo:font-size")
            if fs.endswith("pt"):
                try:
                    sizes[name] = float(fs[:-2])
                except ValueError:
                    pass
        for gp in st.getElementsByTagName("style:graphic-properties"):
            if gp.getAttribute("draw:fill") == "solid":
                solid.add(name)

    hexes = set()
    for el in dom.getElementsByTagName("*"):
        for attr in ("draw:fill-color", "fo:color", "svg:stroke-color"):
            v = el.getAttribute(attr)
            if v.startswith("#"):
                hexes.add(v.upper())
    for h in sorted(hexes - allowed):
        fails.append("off-brand colour %s (not a brand.json palette token)" % h)

    dashes = sum(1 for tp in dom.getElementsByTagName("text:p") if "—" in _text(tp) or "–" in _text(tp))
    if dashes:
        fails.append("%d em/en dash(es) in visible text (use a hyphen)" % dashes)

    pages = dom.getElementsByTagName("draw:page")
    kickers = sum(1 for tp in dom.getElementsByTagName("text:p") if tp.getAttribute("text:style-name") == "pEyeA")
    cap = -(-len(pages) // 3) if pages else 0
    if kickers > cap:
        fails.append("%d UPPERCASE kickers > cap %d (ceil(pages/3)) — drop the templated rhythm" % (kickers, cap))

    for pi, page in enumerate(pages, 1):
        tps = [(tp.getAttribute("text:style-name"), _text(tp)) for tp in page.getElementsByTagName("text:p")]
        has_src = any(re.search(r"(?i)\b(src|source|mock|est)[:.]", t) for _, t in tps)
        has_num = any(re.search(r"\d", t) for _, t in tps)
        for sname, t in tps:
            if sizes.get(sname, 0) >= 60 and re.search(r"\d", t) and t.strip() not in allow_numbers and not has_src:
                fails.append("page %d: hero figure %r has no source (add a src:/mock: line on the "
                             "page, or --allow-number) — a fabricated stat is slop" % (pi, t.strip()))
        rects = [r for r in page.getElementsByTagName("draw:rect") if r.getAttribute("draw:style-name") in solid]
        heights = {r.getAttribute("svg:height") for r in rects}
        if not getattr(args, "allow_chart", False) and len(rects) >= 3 and len(heights) >= 2 and not has_num:
            fails.append("page %d: probable decorative chart (%d solid bars, %d heights, no numbers) "
                         "— use real numbers or drop it" % (pi, len(rects), len(heights)))

    if fails:
        sys.stderr.write("slide-lint: %d issue(s) in %s:\n" % (len(fails), args.file))
        for f in fails:
            sys.stderr.write("  - %s\n" % f)
        return 1
    print("slide-lint: clean (%d pages)" % len(pages))
    return 0


# ---- slide-build: deterministic geometry from a compact spec (dec-040) ------------------------
# The model authored dense absolute-cm XML slide-by-slide (slow + it is not a layout engine, so
# alignment drifted). Here Python computes the geometry so a slide is a few content tokens, not a
# few hundred XML tokens, and cards/columns land equal-width and margin-safe by construction.
CANVAS_W, CANVAS_H, MARGIN = 28.0, 15.75, 1.6
_CONTENT_L, _CONTENT_R = MARGIN, CANVAS_W - MARGIN            # 1.6 .. 26.4

_DOC_OPEN = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<office:document xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
    'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
    'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" '
    'xmlns:presentation="urn:oasis:names:tc:opendocument:xmlns:presentation:1.0" '
    'office:version="1.3" office:mimetype="application/vnd.oasis.opendocument.presentation">')
_MASTER = ('<office:master-styles><style:master-page style:name="Master" '
           'style:page-layout-name="PL"/></office:master-styles>')


def _cm(v):
    return ("%.4f" % v).rstrip("0").rstrip(".") + "cm"


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _rect(style, x, y, w, h):
    return ('<draw:rect draw:style-name="%s" svg:width="%s" svg:height="%s" svg:x="%s" svg:y="%s"/>'
            % (style, _cm(w), _cm(h), _cm(x), _cm(y)))


def _frame(pstyle, text, x, y, w, h):
    return ('<draw:frame draw:style-name="gText" svg:width="%s" svg:height="%s" svg:x="%s" svg:y="%s">'
            '<draw:text-box><text:p text:style-name="%s">%s</text:p></draw:text-box></draw:frame>'
            % (_cm(w), _cm(h), _cm(x), _cm(y), pstyle, _esc(text)))


def _row(n, gutter, left=_CONTENT_L, right=_CONTENT_R):
    """n equal cells filling [left, right] with (n-1) equal gutters -> [(x, width), ...]."""
    w = (right - left - (n - 1) * gutter) / n
    return [(left + i * (w + gutter), w) for i in range(n)]


def _need(item, *fields):
    for f in fields:
        if item.get(f) in (None, "", [], {}):
            raise ValueError("archetype %r: missing required field %r" % (item.get("archetype"), f))


def _a_title(item):
    _need(item, "title")
    els = [_rect("gAccent", MARGIN, 4.4, 0.6, 0.6),
           _frame("pH1w", item["title"], MARGIN, 5.4, 24.8, 3.0),
           _rect("gAccent", MARGIN, 9.1, 5.0, 0.08)]
    if item.get("subtitle"):
        els.append(_frame("pSubL", item["subtitle"], MARGIN, 9.5, 22.0, 1.6))
    return "dpDark", els


def _a_section(item):
    _need(item, "title")
    els = [_rect("gAccent", MARGIN, 4.4, 5.0, 0.08)]
    ty = 5.4
    if item.get("kicker"):
        els.append(_frame("pEyeA", item["kicker"], MARGIN, 5.0, 20.0, 0.9))
        ty = 6.0
    els.append(_frame("pH1w", item["title"], MARGIN, ty, 24.8, 4.0))
    return "dpDark", els


def _a_milestone(item):
    _need(item, "heading", "cards")
    cards = item["cards"]
    if not 2 <= len(cards) <= 5:
        raise ValueError("milestone-flow needs 2-5 cards, got %d" % len(cards))
    els = []
    if item.get("kicker"):
        els.append(_frame("pEyeA", item["kicker"], MARGIN, 1.6, 20.0, 0.6))
    els.append(_frame("pH2i", item["heading"], MARGIN, 2.3, 24.8, 1.6))
    cells = _row(len(cards), 0.6)
    cy, ch = 6.2, 4.6
    for i, (x, w) in enumerate(cells):
        c = cards[i]
        if not isinstance(c, dict):
            raise ValueError("milestone-flow card %d must be an object" % (i + 1))
        _need({**c, "archetype": "milestone-flow card"}, "title")
        last = i == len(cells) - 1                       # last card accented (breaks equal-cards look)
        panel = "gCardAccent" if last else "gCardPanel"
        num_s, ttl_s, dsc_s = ("pNumW", "pCardW", "pDescW") if last else ("pNumA", "pCardI", "pDescS")
        els.append(_rect(panel, x, cy, w, ch))
        els.append(_frame(num_s, c.get("num") or "%02d" % (i + 1), x + 0.4, 6.6, w - 0.8, 1.1))
        els.append(_frame(ttl_s, c["title"], x + 0.4, 8.1, w - 0.8, 0.9))
        if c.get("desc"):
            els.append(_frame(dsc_s, c["desc"], x + 0.4, 9.1, w - 0.8, 1.6))
    for i in range(len(cells) - 1):                      # chevrons sit in the gutters
        x, w = cells[i]
        els.append(_frame("pChev", ">", x + w - 0.15, 8.0, 0.9, 1.0))
    return "dpPaper", els


def _a_metric(item):
    els = [_rect("gAccent", MARGIN, 4.4, 5.0, 0.08)]
    if item.get("stat"):
        _need(item, "src")                               # a hero figure without a source is slop (slide-lint)
        els.append(_frame("pFig", item["stat"], MARGIN, 4.9, 24.8, 3.2))
        if item.get("label"):
            els.append(_frame("pH2w", item["label"], MARGIN, 8.6, 24.0, 1.4))
        els.append(_frame("pBodyS", "src: " + str(item["src"]), MARGIN, 12.0, 20.0, 1.0))
    else:
        _need(item, "title")
        els.append(_frame("pH1w", item["title"], MARGIN, 5.0, 24.8, 4.0))
        if item.get("body"):
            els.append(_frame("pBodyS", item["body"], MARGIN, 9.0, 22.0, 2.4))
    return "dpDark", els


def _a_compare(item):
    _need(item, "heading", "left", "right")
    els = []
    if item.get("kicker"):
        els.append(_frame("pEyeA", item["kicker"], MARGIN, 1.6, 20.0, 0.6))
    els.append(_frame("pH2i", item["heading"], MARGIN, 2.3, 24.8, 1.6))
    py0, ph = 4.6, 8.8
    for i, (x, w) in enumerate(_row(2, 0.8)):
        col = item["right"] if i else item["left"]
        if not isinstance(col, dict):
            raise ValueError("two-column-compare %s must be an object" % ("right" if i else "left"))
        _need({**col, "archetype": "two-column-compare column"}, "title", "points")
        if len(col["points"]) > 6:
            raise ValueError("two-column-compare column %r has %d points (max 6)"
                             % (col["title"], len(col["points"])))
        accent = i == 1
        els.append(_rect("gCardAccent" if accent else "gCardPanel", x, py0, w, ph))
        els.append(_frame("pCardW" if accent else "pCardI", col["title"], x + 0.5, py0 + 0.5, w - 1.0, 1.0))
        dsc = "pDescW" if accent else "pDescS"
        y = py0 + 2.0
        for pt in col["points"]:
            els.append(_frame(dsc, "- " + str(pt), x + 0.5, y, w - 1.0, 0.9))
            y += 1.0
    return "dpPaper", els


def _a_threepoint(item):
    _need(item, "heading", "points")
    pts = item["points"]
    if len(pts) != 3:
        raise ValueError("three-point needs exactly 3 points, got %d" % len(pts))
    els = []
    if item.get("kicker"):
        els.append(_frame("pEyeA", item["kicker"], MARGIN, 1.6, 20.0, 0.6))
    els.append(_frame("pH2i", item["heading"], MARGIN, 2.3, 24.8, 1.6))
    for (x, w), p in zip(_row(3, 0.8), pts):             # accent rule + text, not filled cards
        if not isinstance(p, dict):
            raise ValueError("three-point point must be an object")
        _need({**p, "archetype": "three-point point"}, "title")
        els.append(_rect("gAccent", x, 6.0, min(2.4, w), 0.08))
        els.append(_frame("pCardI", p["title"], x, 6.4, w, 1.0))
        if p.get("desc"):
            els.append(_frame("pDescS", p["desc"], x, 7.5, w, 3.0))
    return "dpPaper", els


def _a_process(item):
    _need(item, "heading", "steps")
    steps = item["steps"]
    if not 2 <= len(steps) <= 5:
        raise ValueError("process-flow needs 2-5 steps, got %d" % len(steps))
    els = [_frame("pH2w", item["heading"], MARGIN, 2.1, 24.8, 1.6)]
    for i, ((x, w), s) in enumerate(zip(_row(len(steps), 0.8), steps)):
        label = s.get("label") if isinstance(s, dict) else s
        if not label:
            raise ValueError("process-flow step %d needs a label" % (i + 1))
        els.append(_rect("gAccent" if i == 0 else "gGrey", x, 7.2, 0.6, 0.6))
        els.append(_frame("pNumW", "%d" % (i + 1), x + 0.75, 7.05, w - 0.75, 0.9))
        els.append(_frame("pDescW", label, x, 8.4, w, 2.0))
    return "dpDark", els


_ARCHETYPES = {"title": _a_title, "section-divider": _a_section, "milestone-flow": _a_milestone,
               "metric": _a_metric, "two-column-compare": _a_compare, "three-point": _a_threepoint,
               "process-flow": _a_process}


def _build_pages(spec):
    pages = []
    for idx, item in enumerate(spec):
        if not isinstance(item, dict):
            raise ValueError("slide %d is not a JSON object" % (idx + 1))
        arch = item.get("archetype")
        if arch == "raw":
            _need(item, "fodp")
            pages.append(item["fodp"])
            continue
        fn = _ARCHETYPES.get(arch)
        if fn is None:
            raise ValueError("slide %d: unknown archetype %r (known: raw, %s)"
                             % (idx + 1, arch, ", ".join(sorted(_ARCHETYPES))))
        dp, els = fn(item)
        name = item.get("name") or "%s%d" % (arch, idx + 1)
        body = "".join("\n    " + e for e in els)
        pages.append('   <draw:page draw:name="%s" draw:style-name="%s" draw:master-page-name="Master">'
                     '%s\n   </draw:page>' % (_esc(name), dp, body))
    return pages


def _build_fodp(spec, brand):
    parts = [_DOC_OPEN, " " + _style_block(brand), " " + _MASTER,
             " <office:body>\n  <office:presentation>"]
    parts.extend(_build_pages(spec))
    parts.append("  </office:presentation>\n </office:body>\n</office:document>\n")
    return "\n".join(parts)


def cmd_slide_build(args):
    try:
        brand = _load_brand(getattr(args, "brand", None))
    except (OSError, ValueError, json.JSONDecodeError) as e:
        sys.stderr.write("devant: brand load failed: %s\n" % e)
        return 1
    try:
        with open(args.spec) as fh:
            spec = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        sys.stderr.write("devant: cannot read spec %s: %s\n" % (args.spec, e))
        return 1
    if not isinstance(spec, list) or not spec:
        sys.stderr.write("devant: spec must be a non-empty JSON array of slide objects\n")
        return 1
    try:
        fodp = _build_fodp(spec, brand)
    except ValueError as e:
        sys.stderr.write("devant: %s\n" % e)
        return 1
    out = getattr(args, "out", None)
    if out:
        with open(out, "w") as fh:
            fh.write(fodp)
        print("slide-build: wrote %s (%d slides)" % (out, len(spec)))
    else:
        sys.stdout.write(fodp)
    return 0
