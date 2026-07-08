"""drawio-lint (geometry + label-collision gate) and ELK layout via elkjs. Heavy imports
(xml.etree, html) live here so the guard/intent paths never pay for them."""
import base64
import glob
import html
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import xml.etree.ElementTree as ET
import zlib

from .common import LAYOUT_PRESETS  # noqa: F401 — re-exported for the CLI's choices

DRAWIO_GRID = 10
DRAWIO_GAP = 40  # min clear space between sibling nodes (guide §1)


def _drawio_style(style):
    """Parse a draw.io style string ('k=v;flag;') into a dict; flags map to True."""
    d = {}
    for part in (style or "").split(";"):
        part = part.strip()
        if not part:
            continue
        k, sep, v = part.partition("=")
        d[k.strip()] = v.strip() if sep else True
    return d


def _snap(v):
    return int(round(v / DRAWIO_GRID)) * DRAWIO_GRID


class _Box:
    __slots__ = ("cell", "geo", "x", "y", "w", "h", "parent", "moved")

    def __init__(self, cell, geo, x, y, w, h):
        self.cell, self.geo = cell, geo
        self.x, self.y, self.w, self.h = x, y, w, h
        self.parent = cell.get("parent")
        self.moved = False


def _contains(a, b):
    """True if box b sits fully inside box a (deliberate nesting, e.g. a UML final-node core)."""
    return a.x <= b.x and a.y <= b.y and a.x + a.w >= b.x + b.w and a.y + a.h >= b.y + b.h


def _overlaps(a, b):
    """True only for a real collision: the boxes intersect and neither encloses the other.
    Merely-close-but-separated nodes (normal for connected flow steps) are not flagged."""
    if _contains(a, b) or _contains(b, a):
        return False
    dx = max(b.x - (a.x + a.w), a.x - (b.x + b.w))
    dy = max(b.y - (a.y + a.h), a.y - (b.y + b.h))
    return dx < 0 and dy < 0


def _concentric_target(b, hosts):
    """If b sits *nearly* centred inside a larger box (a UML final-node core, a badge dot), return
    the (x, y) making it exactly concentric with the smallest such box — else None. 'Nearly' = the
    centres are within one grid cell: a deliberately corner-placed shape sits far from centre and is
    left alone. Fixes the crooked-bullseye left when the outer ring alone gets grid-snapped."""
    host = min((o for o in hosts if o is not b and _contains(o, b)),
               key=lambda o: o.w * o.h, default=None)
    if host is None:
        return None
    tx = host.x + host.w / 2 - b.w / 2
    ty = host.y + host.h / 2 - b.h / 2
    if abs(tx - b.x) <= DRAWIO_GRID and abs(ty - b.y) <= DRAWIO_GRID and (tx, ty) != (b.x, b.y):
        return (tx, ty)
    return None


def _font_px(style):
    """The Helvetica fontSize (px) a cell's style declares — draw.io's default 12 when unset.
    The collision estimate must scale with this: a 15px label is 25% wider than the 12px the
    linter once assumed, so a larger font is exactly where a real spill would slip the gate."""
    try:
        return float(style.get("fontSize") or 12)
    except (TypeError, ValueError):
        return 12.0


def _line_h(size):
    return 1.25 * size

_TAG_RE = re.compile(r"<[^>]+>")
_BREAK_RE = re.compile(r"<br\s*/?>|</div>\s*<div[^>]*>|</p>\s*<p[^>]*>", re.I)


def _text_w(s, size=12):
    """Approximate rendered width of one line in Helvetica <size>px. Exact metrics need a font
    engine; per-class advance-width factors are within ~10% — enough to catch real spill."""
    w = 0.0
    for ch in s:
        if ch in "iljI.,:;!|' ":
            w += 0.30
        elif ch in "ftr()[]{}\"-/\\":
            w += 0.40
        elif ch in "mwMW@%":
            w += 0.95
        elif ch.isupper() or ch.isdigit():
            w += 0.68
        else:
            w += 0.54
    return w * size


def _label_lines(value):
    """Visible text lines of a cell value (draw.io values may carry HTML markup)."""
    if not value:
        return []
    text = html.unescape(_TAG_RE.sub("", _BREAK_RE.sub("\n", value)))
    return [ln.strip() for ln in text.split("\n") if ln.strip()]


def _vertex_label_rect(box, cell):
    """Estimated bounding rect (x, y, w, h) of a vertex's centred label, or None if unlabeled."""
    lines = _label_lines(cell.get("value"))
    if not lines:
        return None
    st = _drawio_style(cell.get("style"))
    size = _font_px(st)
    widths = [_text_w(ln, size) for ln in lines]
    if st.get("whiteSpace") == "wrap":
        cap = max(box.w - 8, 20)
        n = sum(max(1, int((w + cap - 1) // cap)) for w in widths)
        lw, lh = min(max(widths), cap), n * _line_h(size)
    else:
        lw, lh = max(widths), len(lines) * _line_h(size)
    return (box.x + box.w / 2 - lw / 2, box.y + box.h / 2 - lh / 2, lw, lh)


def _rect_overlap(a, b, pad):
    """True when rects a and b intersect by more than <pad> px on both axes."""
    ox = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    oy = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return ox > pad and oy > pad


def _spills(rect, box):
    """True when a label rect extends beyond its own node's box (with 2px slack)."""
    x, y, w, h = rect
    return (x < box.x - 2 or y < box.y - 2
            or x + w > box.x + box.w + 2 or y + h > box.y + box.h + 2)


def _seg_cross(p1, p2, p3, p4):
    """True when segments p1p2 and p3p4 properly cross (interior intersection). Collinear
    overlap and shared endpoints don't count, so edges meeting at a common node aren't flagged."""
    def orient(a, b, c):
        v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        return 0 if abs(v) < 1e-9 else (1 if v > 0 else -1)
    o1, o2 = orient(p1, p2, p3), orient(p1, p2, p4)
    o3, o4 = orient(p3, p4, p1), orient(p3, p4, p2)
    return o1 != o2 and o3 != o4 and 0 not in (o1, o2, o3, o4)


def _is_label_only(cell):
    """True for a cell that draws no box — a draw.io 'text' element, or one with neither fill nor
    stroke. Such a cell is a floating label (edge labels are often authored as their own text cell),
    so an edge passing 'through' it is meeting a label, not a bystander node to route around."""
    st = _drawio_style(cell.get("style"))
    return st.get("text") is True or (st.get("fillColor") == "none" and st.get("strokeColor") == "none")


def _route_hits_box(pts, box):
    """True when polyline pts enters the box's interior or crosses its border."""
    x, y, w, h = box
    corners = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    borders = list(zip(corners, corners[1:] + corners[:1]))
    for a, b in zip(pts, pts[1:]):
        if any(x + 1e-6 < p[0] < x + w - 1e-6 and y + 1e-6 < p[1] < y + h - 1e-6 for p in (a, b)):
            return True
        if any(_seg_cross(a, b, c, d) for c, d in borders):
            return True
    return False


def cmd_drawio_lint(args):
    """Check (and with --fix, auto-fix) a .drawio for the defects that make diagrams look
    amateur: off-grid coords, overlapping/too-close nodes, non-orthogonal edges, off-canvas
    cells, duplicate ids, edges missing geometry. Exit 0 only when nothing remains."""
    path = args.file
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        sys.stderr.write("devant: %s is not well-formed XML: %s\n" % (path, exc))
        return 1
    root = tree.getroot()
    model = root.find(".//mxGraphModel")
    groot = model.find("root") if model is not None else None
    if groot is None:
        sys.stderr.write("devant: %s has no <mxGraphModel><root> (compressed, or not a .drawio?)\n" % path)
        return 1
    cells = groot.findall("mxCell")

    seen, dup_ids, parents = set(), [], set()
    for c in cells:
        cid = c.get("id")
        if cid in seen:
            dup_ids.append(cid)
        seen.add(cid)
        if c.get("parent"):
            parents.add(c.get("parent"))

    boxes, skips, negative, edge_children = [], [], [], []
    for c in cells:
        if c.get("vertex") != "1":
            continue
        geo = c.find("mxGeometry")
        if geo is None:
            continue
        if geo.get("relative") == "1":
            # a label riding its parent edge — positioned by a [-1,1] parameter, not absolute
            # coordinates; grid/overlap rules don't apply, the label pass below handles it.
            edge_children.append(c)
            continue
        try:
            x = float(geo.get("x", "0")); y = float(geo.get("y", "0"))
            w = float(geo.get("width", "0")); h = float(geo.get("height", "0"))
        except (TypeError, ValueError):
            continue
        if x < 0 or y < 0:
            negative.append(c.get("id"))
        st = _drawio_style(c.get("style"))
        # containers, swimlanes and dashed boundary boxes legitimately enclose other cells —
        # never move them and never count them as overlapping their own children.
        contains = (c.get("id") in parents or "swimlane" in st
                    or (st.get("dashed") == "1" and st.get("fillColor") == "none"))
        (skips if contains else boxes).append(_Box(c, geo, x, y, w, h))

    # a box centred inside another (e.g. a UML final-node core) is deliberately placed — grid
    # alignment is about position of free-standing nodes, so leave nested/concentric shapes alone.
    def nested(b):
        return any(o is not b and _contains(o, b) for o in boxes + skips)

    off_grid = [b.cell.get("id") for b in boxes
                if not nested(b) and (b.x % DRAWIO_GRID or b.y % DRAWIO_GRID)]

    fixing = bool(args.fix)
    if fixing:  # snap only x/y (position), and only for free-standing nodes — not sizes, not nested shapes
        for b in boxes:
            if nested(b):
                continue
            nx, ny = _snap(b.x), _snap(b.y)
            if (nx, ny) != (b.x, b.y):
                b.x, b.y = nx, ny
                b.moved = True

    groups = {}
    for b in boxes:
        groups.setdefault(b.parent, []).append(b)

    def overlaps():
        out = []
        for grp in groups.values():
            for i in range(len(grp)):
                for j in range(i + 1, len(grp)):
                    if _overlaps(grp[i], grp[j]):
                        out.append((grp[i], grp[j]))
        return out

    initial_overlaps = overlaps()
    if fixing:
        for _ in range(40):  # bounded: one move can create a new overlap; a few passes settle it
            pairs = overlaps()
            if not pairs:
                break
            for a, m in pairs:  # move the later sibling (m) clear of a, minimal non-negative shift
                cands = [(a.x + a.w + DRAWIO_GAP, m.y), (m.x, a.y + a.h + DRAWIO_GAP)]  # right, down
                if a.x - DRAWIO_GAP - m.w >= 0:
                    cands.append((a.x - DRAWIO_GAP - m.w, m.y))                          # left
                if a.y - DRAWIO_GAP - m.h >= 0:
                    cands.append((m.x, a.y - DRAWIO_GAP - m.h))                          # up
                nx, ny = min(cands, key=lambda p: abs(p[0] - m.x) + abs(p[1] - m.y))
                m.x, m.y = _snap(nx), _snap(ny)
                m.moved = True
    unresolved = [(a.cell.get("id"), b.cell.get("id")) for a, b in overlaps()]

    # Concentric shapes (a final-node core inside its ring) must be *exactly* centred; a few-px
    # offset — often left when the outer ring alone gets grid-snapped — reads as a crooked bullseye.
    # Computed after snap/spread so the target uses the container's final position; --fix re-centres,
    # otherwise it's reported like off-grid (cosmetic, never blocking).
    hosts = boxes + skips
    off_center = []
    for b in boxes:
        tgt = _concentric_target(b, hosts)
        if tgt is None:
            continue
        off_center.append(b.cell.get("id"))
        if fixing:
            b.x, b.y = tgt
            b.moved = True

    # Label collisions — the perceptual defect the retired PNG visual pass used to catch
    # (dec-012): a label wider than its node spilling onto a sibling, or an edge label landing
    # on a node. Estimated font metrics; computed on post-fix coordinates. Report-only: a good
    # fix (shorten, wrap, widen, move) is a judgment call, so --fix never guesses one.
    vmap = {b.cell.get("id"): b for b in boxes + skips}
    cmap = {c.get("id"): c for c in cells}
    label_rects = []  # (rect, owner_id, owner_box|None, parent_group, pad)
    for b in boxes:
        r = _vertex_label_rect(b, b.cell)
        if r is not None and _spills(r, b):
            label_rects.append((r, b.cell.get("id"), b, b.parent, 2))
    riders = [(c, c) for c in cells if c.get("edge") == "1"]
    riders += [(ch, cmap.get(ch.get("parent"))) for ch in edge_children]
    for label_cell, edge in riders:
        lines = _label_lines(label_cell.get("value"))
        if not lines or edge is None or edge.get("edge") != "1":
            continue
        src, tgt = vmap.get(edge.get("source")), vmap.get(edge.get("target"))
        if src is None or tgt is None:
            continue
        geo = label_cell.find("mxGeometry")
        gx, off = 0.0, (0.0, 0.0)
        if geo is not None:
            try:
                gx = float(geo.get("x", "0") or 0)
            except (TypeError, ValueError):
                gx = 0.0
            pt = next((p for p in geo.findall("mxPoint") if p.get("as") == "offset"), None)
            if pt is not None:
                off = (float(pt.get("x", "0") or 0), float(pt.get("y", "0") or 0))
        t = 0.5 + max(-1.0, min(1.0, gx)) / 2.0  # straight-line approximation of the edge path
        sx, sy = src.x + src.w / 2, src.y + src.h / 2
        tx, ty = tgt.x + tgt.w / 2, tgt.y + tgt.h / 2
        esize = _font_px(_drawio_style(label_cell.get("style")))
        lw = max(_text_w(ln, esize) for ln in lines)
        lh = len(lines) * _line_h(esize)
        rect = (sx + t * (tx - sx) + off[0] - lw / 2, sy + t * (ty - sy) + off[1] - lh / 2, lw, lh)
        # pad 6: the approximation can drift from the routed path — only flag clear hits
        label_rects.append((rect, label_cell.get("id"), None, edge.get("parent"), 6))
    label_hits = []
    for rect, owner, obox, par, pad in label_rects:
        for b in groups.get(par, []):
            if obox is b:
                continue
            if obox is not None and (_contains(b, obox) or _contains(obox, b)):
                continue  # nested/concentric shapes deliberately layer their labels
            if _rect_overlap(rect, (b.x, b.y, b.w, b.h), pad):
                label_hits.append("%s->%s" % (owner, b.cell.get("id")))
    for i in range(len(label_rects)):
        for j in range(i + 1, len(label_rects)):
            ra, rb = label_rects[i], label_rects[j]
            if ra[3] == rb[3] and ra[1] != rb[1] and _rect_overlap(ra[0], rb[0], max(ra[4], rb[4])):
                label_hits.append("%s<->%s" % (ra[1], rb[1]))

    non_ortho, no_geo = [], []
    for c in cells:
        if c.get("edge") != "1":
            continue
        if "orthogonalEdgeStyle" not in (c.get("style") or ""):
            non_ortho.append(c.get("id"))
        if c.find("mxGeometry") is None:
            no_geo.append(c.get("id"))

    # Edge-routing checks — only for edges carrying explicit <Array as="points"> waypoints: an
    # auto-routed edge stores no path (draw.io computes it at render time), so checking it would
    # guess. Warnings, never blocking: waypoints are rare hand-routing, and `devant layout` drops
    # them anyway so draw.io re-routes.
    def abs_box(b):
        x, y, pid, seen = b.x, b.y, b.parent, set()
        while pid in vmap and pid not in seen:
            seen.add(pid)
            p = vmap[pid]
            x, y, pid = x + p.x, y + p.y, p.parent
        return (x, y, b.w, b.h)

    routed = []  # (edge_id, absolute polyline, {source_id, target_id})
    for c in cells:
        if c.get("edge") != "1":
            continue
        geo = c.find("mxGeometry")
        arr = next((a for a in geo.findall("Array") if a.get("as") == "points"),
                   None) if geo is not None else None
        if arr is None:
            continue
        wpts = []
        for pt in arr.findall("mxPoint"):
            try:
                wpts.append((float(pt.get("x", "0") or 0), float(pt.get("y", "0") or 0)))
            except (TypeError, ValueError):
                pass
        src, tgt = vmap.get(c.get("source")), vmap.get(c.get("target"))
        if not wpts or src is None or tgt is None:
            continue
        st = _drawio_style(c.get("style"))
        ends = []
        for b, kx, ky in ((src, "exitX", "exitY"), (tgt, "entryX", "entryY")):
            bx, by, bw, bh = abs_box(b)
            try:
                fx, fy = float(st.get(kx, 0.5)), float(st.get(ky, 0.5))
            except (TypeError, ValueError):
                fx = fy = 0.5
            ends.append((bx + fx * bw, by + fy * bh))
        routed.append((c.get("id"), [ends[0]] + wpts + [ends[1]],
                       {c.get("source"), c.get("target")}))

    through, crossings = [], []
    for eid, pts, ends in routed:
        for b in boxes:  # leaves only — a route legitimately traverses containers
            if b.cell.get("id") in ends or _is_label_only(b.cell):
                continue  # skip endpoints and boxless labels — only real bystander shapes count
            if _route_hits_box(pts, abs_box(b)):
                through.append("%s->%s" % (eid, b.cell.get("id")))
    for i in range(len(routed)):
        for j in range(i + 1, len(routed)):
            if any(_seg_cross(a1, a2, b1, b2)
                   for a1, a2 in zip(routed[i][1], routed[i][1][1:])
                   for b1, b2 in zip(routed[j][1], routed[j][1][1:])):
                crossings.append("%s<->%s" % (routed[i][0], routed[j][0]))

    if fixing and any(b.moved for b in boxes):
        def num(v):
            return str(int(v)) if float(v).is_integer() else str(v)
        for b in boxes:
            if b.moved:
                b.geo.set("x", num(b.x)); b.geo.set("y", num(b.y))
                b.geo.set("width", num(b.w)); b.geo.set("height", num(b.h))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(ET.tostring(root, encoding="unicode"))
            fh.write("\n")

    if fixing:
        if off_grid:
            print("fixed: straightened %d off-grid node(s) to the %dpx grid" % (len(off_grid), DRAWIO_GRID))
        resolved = len(initial_overlaps) - len(unresolved)
        if resolved > 0:
            print("fixed: spread %d overlapping node pair(s)" % resolved)
        if off_center:
            print("fixed: re-centred %d nested shape(s) on their container" % len(off_center))
    # Only genuine defects fail the gate. Off-grid is a straightening nicety (auto-fixed above),
    # never a reason to block delivery.
    blocking = False
    for label, items in [
        ("overlapping nodes (couldn't auto-resolve — space them by hand)", unresolved),
        ("labels colliding (shorten/wrap the label, widen the node, or move the label)", label_hits),
        ("non-orthogonal edges (add edgeStyle=orthogonalEdgeStyle)", non_ortho),
        ("edges missing <mxGeometry> (won't render)", no_geo),
        ("duplicate ids (cells silently drop)", dup_ids),
        ("off-canvas cells (negative x/y)", negative),
    ]:
        if items:
            blocking = True
            print("%s: %s" % (label, ", ".join(str(i) for i in items)))
    if not fixing and off_grid:
        print("off-grid nodes (cosmetic; run --fix to straighten): %s" % ", ".join(off_grid))
    if not fixing and off_center:
        print("off-centre nested shapes (cosmetic; run --fix to centre): %s" % ", ".join(off_center))
    for label, items in [
        ("edge routes through a node (warning; move the waypoint to go around it)", through),
        ("edges cross (warning; reroute, or mark with jumpStyle=arc;jumpSize=10)", crossings),
    ]:
        if items:
            print("%s: %s" % (label, ", ".join(items)))
    if getattr(args, "score", False):
        print("score: %d (20*through + 10*cross + 5*overlap; lower is better)"
              % (20 * len(through) + 10 * len(crossings) + 5 * len(unresolved)))
    if not blocking:
        print("%s: clean." % os.path.basename(path))
    return 1 if blocking else 0


# ------------------------------------------------------ preview (headless chrome)

VIEWER_PREFIX = "https://viewer.diagrams.net/?tags=%7B%7D&lightbox=1&edit=_blank#R"


def _viewer_url(xml):
    """diagrams.net viewer URL carrying the XML in the #fragment (never sent to the server).
    The viewer runs JS decodeURIComponent AFTER inflate, so the XML must be percent-encoded
    (encodeURIComponent semantics) BEFORE raw-deflate — otherwise a literal '%' or non-ASCII
    label breaks the loader with 'URI malformed'."""
    pre = urllib.parse.quote(xml, safe="!~*'()")
    c = zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS)
    payload = base64.b64encode(c.compress(pre.encode("utf-8")) + c.flush()).decode("ascii")
    return VIEWER_PREFIX + urllib.parse.quote(payload, safe="")


def _find_browser():
    """Path of the onboard-installed chrome-headless-shell in the plugin data dir, or None.
    Deliberately the ONLY renderer (dec-023): one deterministic binary, one behavior, on every
    platform — system Chrome/Edge (including Windows .exe from WSL) is never consulted."""
    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if not data:
        return None
    hits = sorted(glob.glob(os.path.join(
        data, "browsers", "chrome-headless-shell", "*", "*", "chrome-headless-shell*")))
    hits = [h for h in hits if os.access(h, os.X_OK) and not h.endswith(".txt")]
    return hits[-1] if hits else None


def cmd_drawio_preview(args):
    """Render a .drawio to PNG for the mandatory visual self-check (dec-022/dec-023): stdlib
    builds a diagrams.net viewer URL, the plugin-installed chrome-headless-shell screenshots it."""
    path = args.file
    try:
        with open(path, encoding="utf-8") as fh:
            xml = fh.read()
    except OSError as exc:
        sys.stderr.write("devant: cannot read %s: %s\n" % (path, exc))
        return 1
    browser = _find_browser()
    if not browser:
        sys.stderr.write(
            "devant: chrome-headless-shell not installed — run /devant:onboard, or:\n"
            "  npx --yes @puppeteer/browsers install chrome-headless-shell@stable "
            "--path \"$CLAUDE_PLUGIN_DATA/browsers\"\n")
        return 1
    out = args.out or (os.path.splitext(path)[0] + ".preview.png")
    cmd = [browser, "--disable-gpu", "--window-size=2000,1400", "--virtual-time-budget=15000",
           "--screenshot=%s" % out, _viewer_url(xml)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    except (OSError, subprocess.TimeoutExpired) as exc:
        sys.stderr.write("devant: preview render failed: %s\n" % exc)
        return 1
    if not os.path.isfile(out) or os.path.getsize(out) == 0:
        sys.stderr.write("devant: browser wrote no screenshot (offline? viewer JS needs "
                         "network)%s\n" % ((": " + proc.stderr.strip()[-300:]) if proc.stderr else ""))
        return 1
    print("%s (render fetches viewer JS from diagrams.net; the diagram XML stays in the "
          "URL fragment — never uploaded)" % out)
    return 0


# ------------------------------------------------------------ layout (elkjs)

def _node_env():
    """os.environ plus NODE_PATH so the elk driver's require('elkjs') resolves: the plugin
    data dir first (where /devant:onboard installs it — survives plugin updates), then the
    global npm root as the legacy fallback."""
    env = dict(os.environ)
    paths = []
    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if data:
        paths.append(os.path.join(data, "node_modules"))
    npm = shutil.which("npm")
    if npm:
        try:
            root = subprocess.run([npm, "root", "-g"], capture_output=True, text=True,
                                  timeout=15).stdout.strip()
            if root:
                paths.append(root)
        except (OSError, subprocess.TimeoutExpired):
            pass
    if env.get("NODE_PATH"):
        paths.append(env["NODE_PATH"])
    if paths:
        env["NODE_PATH"] = os.pathsep.join(paths)
    return env


def _edge_label_metrics(value, style):
    """{text,width,height} for an edge label, sized with the lint's own font metrics so ELK
    reserves real inter-layer space for it — or None when the edge is unlabelled."""
    lines = _label_lines(value)
    if not lines:
        return None
    size = _font_px(_drawio_style(style))
    return {"text": lines[0],
            "width": max(_text_w(ln, size) for ln in lines),
            "height": len(lines) * _line_h(size)}


def _run_elk(preset, nodes, edges):
    """Run the elkjs driver on a logical graph; returns {id: {x, y}} or raises RuntimeError
    with the driver's message (node missing, elkjs missing, layout failure)."""
    node_bin = shutil.which("node")
    if not node_bin:
        raise RuntimeError("node not found — layout needs Node.js (e.g. via nvm), "
                           "then: npm i -g elkjs")
    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "elk-layout.cjs")
    proc = subprocess.run([node_bin, script],
                          input=json.dumps({"preset": preset, "nodes": nodes, "edges": edges}),
                          capture_output=True, text=True, env=_node_env(), timeout=60)
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip() or "elk layout failed")
    return json.loads(proc.stdout)["positions"]


def cmd_layout(args):
    """Auto-place the top-level nodes of a .drawio with real ELK (elkjs via node). Python owns
    all XML (stdlib); the node driver only computes positions. Nested cells move with their
    parent (child geometry is parent-relative), so containers keep their internal layout."""
    path = args.file
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        sys.stderr.write("devant: %s is not well-formed XML: %s\n" % (path, exc))
        return 1
    model = tree.getroot().find(".//mxGraphModel")
    groot = model.find("root") if model is not None else None
    if groot is None:
        sys.stderr.write("devant: %s has no <mxGraphModel><root> (compressed, or not a .drawio?)\n" % path)
        return 1
    cells = groot.findall("mxCell")
    parent_of = {c.get("id"): c.get("parent") for c in cells if c.get("id")}
    nodes, geos = [], {}
    for c in cells:
        if c.get("vertex") != "1" or c.get("parent") != "1":
            continue
        geo = c.find("mxGeometry")
        if geo is None or geo.get("relative") == "1":
            continue
        try:
            w = float(geo.get("width", "0") or 0)
            h = float(geo.get("height", "0") or 0)
        except (TypeError, ValueError):
            continue
        if w <= 0 or h <= 0:
            continue
        nodes.append({"id": c.get("id"), "width": w, "height": h})
        geos[c.get("id")] = geo

    def top_ancestor(cid):
        seen = set()
        while cid and cid not in seen:
            if cid in geos:
                return cid
            seen.add(cid)
            cid = parent_of.get(cid)
        return None

    edges, edge_cells = [], []
    for c in cells:
        if c.get("edge") != "1":
            continue
        s, t = top_ancestor(c.get("source")), top_ancestor(c.get("target"))
        if s and t and s != t:
            e = {"source": s, "target": t}
            label = _edge_label_metrics(c.get("value"), c.get("style"))
            if label:
                e["label"] = label
            edges.append(e)
            edge_cells.append(c)

    # A vertex no edge touches (a legend, a caption) is not part of the flow — feeding it to
    # ELK drags it into a layer and the flow around it (dec-041). Leave it where it was placed.
    connected = {e["source"] for e in edges} | {e["target"] for e in edges}
    nodes = [n for n in nodes if n["id"] in connected]
    if len(nodes) < 2:
        print("nothing to lay out (fewer than 2 connected top-level nodes)")
        return 0

    try:
        positions = _run_elk(args.preset, nodes, edges)
    except RuntimeError as exc:
        sys.stderr.write("devant: %s\n" % exc)
        return 1
    margin = 40
    for nid, p in positions.items():
        g = geos.get(nid)
        if g is None:
            continue
        g.set("x", str(_snap(float(p["x"]) + margin)))
        g.set("y", str(_snap(float(p["y"]) + margin)))
    for c in edge_cells:  # hand-routed waypoints fight the new positions; drop so draw.io re-routes
        g = c.find("mxGeometry")
        if g is not None:
            for arr in list(g.findall("Array")):
                if arr.get("as") == "points":
                    g.remove(arr)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(ET.tostring(tree.getroot(), encoding="unicode"))
        fh.write("\n")
    print("laid out %d node(s), %d edge(s) with ELK '%s' — now run: devant drawio-lint %s --fix"
          % (len(nodes), len(edges), args.preset, path))
    return 0


# ------------------------------------------------------ diagram-build (dec-041)
# The model used to hand-author full mxGraph XML (~4k tokens for a 16-node flow) and the ELK
# pass then scrambled it. Here the model writes a compact logical spec; ELK owns ALL geometry
# (no bespoke routing — settled by debate), styles/legend come from the guide's one style
# system, and the lint gate runs before the command reports success.

_EDGE = "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;strokeWidth=2;strokeColor=#666666;"
_EDGE_LBL = _EDGE + "fontFamily=Helvetica;fontSize=12;fontColor=#555555;labelBackgroundColor=#FFFFFF;"
_EDGE_LOOP = _EDGE_LBL + "jumpStyle=arc;jumpSize=10;exitX=1;exitY=0.5;entryX=1;entryY=0.5;"
_BOX = "rounded=1;whiteSpace=wrap;html=1;fontFamily=Helvetica;fontSize=15;strokeWidth=2;"

_NODE_STYLES = {
    "start": "ellipse;fillColor=#000000;strokeColor=#000000;html=1;",
    "end": "ellipse;fillColor=none;strokeColor=#000000;strokeWidth=2;html=1;",
    "decision": "rhombus;whiteSpace=wrap;html=1;fillColor=#FFF2CC;strokeColor=#D6B656;"
                "fontFamily=Helvetica;fontSize=15;strokeWidth=2;",
    "action": _BOX + "fillColor=#DAE8FC;strokeColor=#6C8EBF;",
    "success": _BOX + "fillColor=#D5E8D4;strokeColor=#82B366;",
    "error": _BOX + "fillColor=#F8CECC;strokeColor=#B85450;",
    "external": _BOX + "fillColor=#F5F5F5;strokeColor=#666666;",
    "actor": _BOX + "fillColor=#F5F5F5;strokeColor=#666666;",
    "system": _BOX + "fillColor=#DAE8FC;strokeColor=#6C8EBF;",
    "container": _BOX + "fillColor=#DAE8FC;strokeColor=#6C8EBF;",
    "store": "shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;"
             "fillColor=#E1D5E7;strokeColor=#9673A6;fontFamily=Helvetica;fontSize=15;strokeWidth=2;",
}
_NODE_SIZES = {"start": (30, 30), "end": (30, 30), "decision": (140, 80), "actor": (170, 60),
               "system": (200, 80), "container": (180, 70), "store": (180, 90)}
_KIND_TYPES = {
    "activity": {"start", "end", "action", "decision", "success", "error", "external"},
    "c4-context": {"actor", "system", "external"},
    "c4-container": {"actor", "container", "store", "external"},
}
_LEGEND_ROLES = [  # (type, colour square, caption) — only roles the spec used are listed
    ("action", "#6C8EBF", "action"), ("success", "#82B366", "success"),
    ("error", "#B85450", "error path"), ("external", "#666666", "external / degraded"),
    ("system", "#6C8EBF", "system"), ("container", "#6C8EBF", "container"),
    ("store", "#9673A6", "data store"), ("actor", "#666666", "person / external"),
]


def _req(obj, what, *fields):
    for f in fields:
        if obj.get(f) in (None, "", [], {}):
            raise ValueError("%s: missing required field %r" % (what, f))


def _find_cycle(ids, adj):
    """First cycle in the directed graph as [a, b, …, a], or None. Iterative DFS, stdlib."""
    color, order = {i: 0 for i in ids}, list(ids)
    for root in order:
        if color[root]:
            continue
        stack = [(root, iter(adj.get(root, ())))]
        color[root] = 1
        while stack:
            nid, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                color[nid] = 2
                stack.pop()
            elif color[nxt] == 1:
                path = [s for s, _ in stack]
                return path[path.index(nxt):] + [nxt]
            elif color[nxt] == 0:
                color[nxt] = 1
                stack.append((nxt, iter(adj.get(nxt, ()))))
    return None


def _fit(lines, size, w, h):
    """Grow (w, h) minimally until the wrapped label passes the lint's own spill metrics
    (_vertex_label_rect/_spills), so generated nodes are label-clean by construction."""
    while True:
        cap = max(w - 8, 20)
        n = sum(max(1, int((_text_w(ln, size) + cap - 1) // cap)) for ln in lines)
        if n * _line_h(size) <= h + 2:
            return w, h
        if w < 300:
            w += 20
        else:
            h += DRAWIO_GRID


def _value_lines(node):
    if node["type"] in ("start", "end"):
        return []
    return [node["label"]] + (["[%s]" % node["note"]] if node.get("note") else [])


def _value_html(node):
    lines = _value_lines(node)
    if not lines:
        return ""
    head = lines[0] if node["type"] == "decision" else "<b>%s</b>" % lines[0]
    if len(lines) == 1:
        return head
    return '%s<br><font color="#555555">%s</font>' % (head, lines[1])


def _legend_lines(kind, used, any_guard):
    lines = ["<b>Legend</b>"]
    if kind == "activity":
        lines.append("● start  ◎ end  ◆ decision")
    swatches = ['<font color="%s">■</font> %s' % (c, cap)
                for t, c, cap in _LEGEND_ROLES if t in used]
    lines.extend("  ".join(swatches[i:i + 2]) for i in range(0, len(swatches), 2))
    if kind == "activity" and any_guard:
        lines.append("[guard] on branches")
    elif kind != "activity":
        lines.append("→ labelled with the interaction")
    return lines


def _build_diagram(spec):
    if not isinstance(spec, dict):
        raise ValueError("spec must be a JSON object {kind, title, nodes, edges}")
    _req(spec, "spec", "kind", "title", "nodes")
    kind = spec["kind"]
    if kind not in _KIND_TYPES:
        raise ValueError("unknown kind %r (supported: %s)" % (kind, ", ".join(sorted(_KIND_TYPES))))
    allowed = _KIND_TYPES[kind]
    edges = spec.get("edges") or []
    nodes = {}
    for n in spec["nodes"]:
        if not isinstance(n, dict):
            raise ValueError("node must be an object, got %r" % (n,))
        _req(n, "node %r" % n.get("id"), "id", "type")
        nid, ntype = n["id"], n["type"]
        if ntype not in allowed:
            raise ValueError("node %r: type %r not valid for kind %r (allowed: %s)"
                             % (nid, ntype, kind, ", ".join(sorted(allowed))))
        if ntype not in ("start", "end"):
            _req(n, "node %r" % nid, "label")
        if nid in nodes or nid in ("0", "1", "legend"):
            raise ValueError("duplicate or reserved node id %r" % nid)
        nodes[nid] = n

    fwd, loops = [], []
    for i, e in enumerate(edges):
        _req(e, "edge #%d" % i, "from", "to")
        for end in ("from", "to"):
            if e[end] not in nodes:
                raise ValueError("edge #%d: unknown node %r" % (i, e[end]))
        if e.get("loop"):
            if not e.get("label"):
                raise ValueError("edge %s->%s: a loop edge needs its repeat guard as the label "
                                 "(e.g. '[retry ≤ 3]')" % (e["from"], e["to"]))
            loops.append(e)
        else:
            if nodes[e["from"]]["type"] == "decision" and not e.get("label"):
                raise ValueError("edge %s->%s: an edge leaving a decision needs its guard as "
                                 "the label (e.g. '[yes]')" % (e["from"], e["to"]))
            fwd.append(e)
    adj = {}
    for e in fwd:
        adj.setdefault(e["from"], []).append(e["to"])
    cyc = _find_cycle(list(nodes), adj)
    if cyc:
        raise ValueError("cycle among non-loop edges: %s — mark the back-edge with loop:true"
                         % " -> ".join(cyc))

    dims = {}
    for nid, n in nodes.items():
        w, h = _NODE_SIZES.get(n["type"], (170, 70))
        lines = _label_lines(_value_html(n))
        if lines:
            w, h = _fit(lines, 15, w, h)
        dims[nid] = (w, h)

    elk_nodes = [{"id": nid, "width": dims[nid][0], "height": dims[nid][1]} for nid in nodes]
    elk_edges = []
    for e in fwd + loops:
        # Loop edges are declared, so ELK never has to guess the cycle break: hand it the
        # acyclic graph by pre-reversing them (greedy cycle breaking picks a non-declared
        # edge when cycles overlap — observed on the 2-loop fixture). Only node positions
        # come back; the drawn edge keeps its true direction and arrow.
        loop = bool(e.get("loop"))
        d = {"source": e["to" if loop else "from"], "target": e["from" if loop else "to"]}
        if e.get("label"):
            d["label"] = {"text": e["label"], "width": _text_w(e["label"], 12),
                          "height": _line_h(12)}
        elk_edges.append(d)
    positions = _run_elk("verticalFlow", elk_nodes, elk_edges)

    margin = 40
    pos = {nid: (_snap(float(p["x"]) + margin), _snap(float(p["y"]) + margin))
           for nid, p in positions.items()}

    mxfile = ET.Element("mxfile", host="devant")
    slug = re.sub(r"[^a-z0-9]+", "-", spec["title"].lower()).strip("-") or "diagram"
    diagram = ET.SubElement(mxfile, "diagram", name=spec["title"], id=slug)
    model = ET.SubElement(diagram, "mxGraphModel", dx="900", dy="760", grid="1", gridSize="10",
                          guides="1", tooltips="1", connect="1", arrows="1", fold="1", page="1",
                          pageScale="1", math="0", shadow="0")
    groot = ET.SubElement(model, "root")
    ET.SubElement(groot, "mxCell", id="0")
    ET.SubElement(groot, "mxCell", id="1", parent="0")

    def emit(cid, value, style, x, y, w, h):
        c = ET.SubElement(groot, "mxCell", id=cid, value=value, style=style,
                          vertex="1", parent="1")
        g = ET.SubElement(c, "mxGeometry", x=str(x), y=str(y), width=str(w), height=str(h))
        g.set("as", "geometry")

    for nid, n in nodes.items():
        (x, y), (w, h) = pos[nid], dims[nid]
        emit(nid, _value_html(n), _NODE_STYLES[n["type"]], x, y, w, h)
        if n["type"] == "end":  # final node = ring + concentric core, placed as one
            emit(nid + "__core", "", _NODE_STYLES["start"], x + 7, y + 7, 16, 16)

    boxes = [(pos[nid][0], pos[nid][1], dims[nid][0], dims[nid][1]) for nid in nodes]
    placed = []  # label rects already chosen — labels must clear each other too

    def label_param(e):
        """(ride, offset) that clears every node AND placed label under the lint's own label
        math (a label anchors at t=0.5+x/2 along the source→target line, plus its offset
        point). Nothing clears → default; the lint gate then reports it for a hand fix."""
        lw, lh = _text_w(e["label"], 12), _line_h(12)
        (sx, sy), (sw, sh) = pos[e["from"]], dims[e["from"]]
        (tx, ty), (tw, th) = pos[e["to"]], dims[e["to"]]
        sx, sy, tx, ty = sx + sw / 2, sy + sh / 2, tx + tw / 2, ty + th / 2
        # UML puts a guard near its decision, so out-edges of a decision prefer ride spots
        # close to the source (t→0 ⇔ gx→-1). Loop back-edges ride their side lane, where the
        # mid-edge point sits in clear lane space — so loops prefer the middle, as does the rest.
        home = -0.7 if nodes[e["from"]]["type"] == "decision" and not e.get("loop") else 0.0
        for gx in sorted((k / 20.0 for k in range(-19, 20)), key=lambda v: abs(v - home)):
            for off in ((0, 0), (lw / 2 + 20, 0), (-lw / 2 - 20, 0)):
                t = 0.5 + gx / 2
                rect = (sx + t * (tx - sx) + off[0] - lw / 2,
                        sy + t * (ty - sy) + off[1] - lh / 2, lw, lh)
                # pad -12 demands a 12px clear gap — stricter than the lint gate (pad 6,
                # which tolerates small overlaps), so a chosen spot clears it with margin
                if not any(_rect_overlap(rect, b, -12) for b in boxes + placed):
                    placed.append(rect)
                    return (gx, off)
        placed.append((sx + 0.5 * (tx - sx) - lw / 2, sy + 0.5 * (ty - sy) - lh / 2, lw, lh))
        return None

    for i, e in enumerate(fwd + loops):
        style = _EDGE_LOOP if e.get("loop") else (_EDGE_LBL if e.get("label") else _EDGE)
        c = ET.SubElement(groot, "mxCell", id="e%d" % i, style=style, edge="1", parent="1",
                          source=e["from"], target=e["to"])
        g = ET.SubElement(c, "mxGeometry", relative="1")
        g.set("as", "geometry")
        if e.get("label"):
            c.set("value", e["label"])
            spot = label_param(e)
            if spot is not None:
                gx, off = spot
                if gx:
                    g.set("x", str(gx))
                if off != (0, 0):
                    p = ET.SubElement(g, "mxPoint", x=str(int(off[0])), y=str(int(off[1])))
                    p.set("as", "offset")

    max_x = max(pos[nid][0] + dims[nid][0] for nid in nodes)
    max_y = max(pos[nid][1] + dims[nid][1] for nid in nodes)
    if spec.get("legend", True):
        used = {n["type"] for n in nodes.values()}
        lines = _legend_lines(kind, used, any(e.get("label") for e in edges))
        lw, lh = _fit([_TAG_RE.sub("", ln) for ln in lines], 12, 220, 40)
        emit("legend", "<br>".join(lines),
             "rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=top;fillColor=#FFFFFF;"
             "strokeColor=#CCCCCC;fontFamily=Helvetica;fontSize=12;spacingLeft=6;spacingTop=4;",
             _snap(max_x + margin), _snap(min(p[1] for p in pos.values())), lw, lh)
        max_x += margin + lw
    model.set("pageWidth", str(_snap(max_x + margin)))
    model.set("pageHeight", str(_snap(max_y + margin)))
    return mxfile, len(nodes), len(edges)


def cmd_diagram_build(args):
    """Emit a styled, ELK-laid-out .drawio from a compact JSON spec (dec-041), then run the
    lint gate on the result — exit 0 only when the generated diagram is clean."""
    try:
        with open(args.spec, encoding="utf-8") as fh:
            spec = json.load(fh)
    except (OSError, ValueError) as exc:
        sys.stderr.write("devant: cannot read spec %s: %s\n" % (args.spec, exc))
        return 1
    try:
        mxfile, n_nodes, n_edges = _build_diagram(spec)
    except (ValueError, RuntimeError) as exc:
        sys.stderr.write("devant: diagram-build: %s\n" % exc)
        return 1
    out = args.out or (os.path.splitext(args.spec)[0] + ".drawio")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(ET.tostring(mxfile, encoding="unicode"))
        fh.write("\n")
    print("diagram-build: wrote %s (%d nodes, %d edges)" % (out, n_nodes, n_edges))

    class _LintArgs:
        file, fix, score = out, True, False
    return cmd_drawio_lint(_LintArgs)
