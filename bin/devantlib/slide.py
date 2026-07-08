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
            if sizes.get(sname, 0) >= 40 and re.search(r"\d", t) and t.strip() not in allow_numbers and not has_src:
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
