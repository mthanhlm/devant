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


LABEL_LINE_H = 15  # draw.io line height at its default Helvetica 12px

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
    widths = [_text_w(ln) for ln in lines]
    if st.get("whiteSpace") == "wrap":
        cap = max(box.w - 8, 20)
        n = sum(max(1, int((w + cap - 1) // cap)) for w in widths)
        lw, lh = min(max(widths), cap), n * LABEL_LINE_H
    else:
        lw, lh = max(widths), len(lines) * LABEL_LINE_H
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
        lw = max(_text_w(ln) for ln in lines)
        lh = len(lines) * LABEL_LINE_H
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
    if len(nodes) < 2:
        print("nothing to lay out (fewer than 2 top-level nodes)")
        return 0

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
            edges.append({"source": s, "target": t})
            edge_cells.append(c)

    node_bin = shutil.which("node")
    if not node_bin:
        sys.stderr.write("devant: node not found — layout needs Node.js "
                         "(e.g. via nvm), then: npm i -g elkjs\n")
        return 1
    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "elk-layout.cjs")
    proc = subprocess.run([node_bin, script],
                          input=json.dumps({"preset": args.preset, "nodes": nodes, "edges": edges}),
                          capture_output=True, text=True, env=_node_env(), timeout=60)
    if proc.returncode:
        sys.stderr.write(proc.stderr or "devant: elk layout failed\n")
        return 1
    positions = json.loads(proc.stdout)["positions"]
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
