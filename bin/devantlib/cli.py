"""Argument parsing + lazy dispatch. Parsers know only ("module", "function") pairs; the
handler module is imported after parse, so `devant guard` never pays for drawio/graph code."""
import argparse
import importlib
import sqlite3
import sys

from .common import EDGE_KINDS, KINDS, LAYOUT_PRESETS, SPECIALISTS


def build_parser():
    p = argparse.ArgumentParser(prog="devant", description="Local intent graph for the devant companion.")
    p.add_argument("--db", help="override the intent.db path (default: <project>/.devant/intent.db)")
    p.add_argument("--index-db", dest="index_db",
                   help="override the index.db path (default: <project>/.devant/index.db)")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add-node", help="add or update an intent node")
    a.add_argument("--kind", required=True, choices=KINDS)
    a.add_argument("--title", required=True)
    a.add_argument("--id")
    a.add_argument("--body")
    a.add_argument("--status")
    a.add_argument("--meta", help="raw JSON meta object")
    a.add_argument("--applies", action="append", help="constraint: glob path it applies to (repeatable)")
    a.add_argument("--forbid", action="append", help="constraint: forbidden substring/regex (repeatable)")
    a.add_argument("--exempt", action="append", help="constraint: exempt glob path (repeatable)")
    a.add_argument("--expected", help="constraint: the sanctioned pattern/path to name in denials")
    a.add_argument("--severity", choices=["block", "warn"])
    a.add_argument("--rejected", help="decision: the rejected alternative")
    a.add_argument("--why-rejected", dest="why_rejected", help="decision: why it was rejected")
    a.set_defaults(_mod="intent", _func="cmd_add_node")

    e = sub.add_parser("add-edge", help="add a typed edge between nodes")
    e.add_argument("src")
    e.add_argument("kind", choices=EDGE_KINDS)
    e.add_argument("dst")
    e.add_argument("--note")
    e.set_defaults(_mod="intent", _func="cmd_add_edge")

    lk = sub.add_parser("link", help="link an intent node to a code symbol")
    lk.add_argument("node")
    lk.add_argument("symbol")
    lk.add_argument("--relation", default="implemented_by",
                    choices=["implemented_by", "governs", "constrains"])
    lk.add_argument("--path")
    lk.add_argument("--cg-id", dest="cg_id")
    lk.add_argument("--note")
    lk.add_argument("--no-resolve", action="store_true", help="don't resolve against the graph to fill path/id")
    lk.set_defaults(_mod="intent", _func="cmd_link")

    d = sub.add_parser("decide", help="record a decision (+ supersede/establish/realize/exempt)")
    d.add_argument("--title", required=True)
    d.add_argument("--body", required=True)
    d.add_argument("--id")
    d.add_argument("--rejected")
    d.add_argument("--why-rejected", dest="why_rejected")
    d.add_argument("--realizes", action="append")
    d.add_argument("--establishes", action="append")
    d.add_argument("--supersedes", action="append")
    d.add_argument("--exempt", action="append", help="exempt path added to a superseded constraint")
    d.set_defaults(_mod="intent", _func="cmd_decide")

    for name, func in [
        ("summary", "cmd_summary"),
        ("direction", "cmd_direction"),
        ("show", "cmd_show"),
        ("dangling", "cmd_dangling"),
        ("lint", "cmd_lint"),
        ("doctor", "cmd_doctor"),
        ("dead-skills", "cmd_dead_skills"),
    ]:
        s = sub.add_parser(name)
        s.add_argument("-j", "--json", action="store_true")
        s.set_defaults(_mod="intent", _func=func)

    c = sub.add_parser("constraints", help="active constraints/non-goals for a path or area")
    c.add_argument("--path")
    c.add_argument("--area")
    c.add_argument("-j", "--json", action="store_true")
    c.set_defaults(_mod="intent", _func="cmd_constraints")

    g = sub.add_parser("guard", help="evaluate a proposed edit against constraints/content rules")
    g.add_argument("--file", required=True)
    g.add_argument("--content", default="-", help="content, or '-' to read stdin (default)")
    g.set_defaults(_mod="guard", _func="cmd_guard")

    w = sub.add_parser("why", help="intent attached to a code symbol")
    w.add_argument("symbol")
    w.add_argument("-j", "--json", action="store_true")
    w.set_defaults(_mod="intent", _func="cmd_why")

    q = sub.add_parser("query", help="search intent nodes")
    q.add_argument("text")
    q.add_argument("-j", "--json", action="store_true")
    q.set_defaults(_mod="intent", _func="cmd_query")

    ph = sub.add_parser("phase", help="get/set the project phase state + compaction gate (dec-018)")
    ph.add_argument("--set", dest="set", help="phase text to record (omit to print the current phase)")
    gate = ph.add_mutually_exclusive_group()
    gate.add_argument("--open", dest="hold", action="store_false",
                      help="phase boundary — auto-compact may land now (default)")
    gate.add_argument("--hold", dest="hold", action="store_true",
                      help="mid-phase — defer proactive auto-compacts until the next boundary")
    ph.set_defaults(hold=False)
    ph.add_argument("-j", "--json", action="store_true")
    ph.set_defaults(_mod="intent", _func="cmd_phase")

    gl = sub.add_parser("goal", help="get/set/clear the current task's definition of done (acceptance criteria)")
    gl.add_argument("--set", dest="set", help="acceptance criteria to record (omit to print the current goal)")
    gl.add_argument("--clear", action="store_true", help="clear the recorded goal (task done)")
    gl.add_argument("-j", "--json", action="store_true")
    gl.set_defaults(_mod="intent", _func="cmd_goal")

    lg = sub.add_parser("log", help="record which specialist the router used")
    lg.add_argument("specialist", choices=SPECIALISTS)
    lg.add_argument("intent", nargs="*")
    lg.set_defaults(_mod="intent", _func="cmd_log")

    ex = sub.add_parser("export", help="dump the intent graph as JSON (commit it to share rules across a team/clone)")
    ex.add_argument("-o", "--out", help="write to this path (default: stdout)")
    ex.set_defaults(_mod="intent", _func="cmd_export")

    im = sub.add_parser("import", help="load an exported intent graph (upserts nodes/edges/links by id)")
    im.add_argument("file")
    im.set_defaults(_mod="intent", _func="cmd_import")

    dl = sub.add_parser("drawio-lint", help="check/auto-fix a .drawio for grid/overlap/edge/label defects")
    dl.add_argument("file")
    dl.add_argument("--fix", action="store_true", help="grid-snap + spread overlaps in place")
    dl.add_argument("--score", action="store_true",
                    help="print a readability score (lower is better) for comparing layout variants")
    dl.set_defaults(_mod="drawio", _func="cmd_drawio_lint")

    ly = sub.add_parser("layout", help="auto-layout a .drawio with real ELK (elkjs via node)")
    ly.add_argument("file")
    ly.add_argument("--preset", default="verticalFlow", choices=LAYOUT_PRESETS,
                    help="ELK algorithm preset (default: verticalFlow)")
    ly.set_defaults(_mod="drawio", _func="cmd_layout")

    dp = sub.add_parser("drawio-preview",
                        help="render a .drawio to PNG via headless Chrome for a visual check "
                             "(needs network for the viewer JS)")
    dp.add_argument("file")
    dp.add_argument("-o", "--out", help="output PNG path (default: <file>.preview.png)")
    dp.set_defaults(_mod="drawio", _func="cmd_drawio_preview")

    ss = sub.add_parser("slide-styles",
                        help="emit the ODF <office:automatic-styles> block from brand tokens")
    ss.add_argument("--brand", help="path to a brand.json (default: the shipped Ink & Signal tokens)")
    ss.set_defaults(_mod="slide", _func="cmd_slide_styles")

    sl = sub.add_parser("slide-lint",
                        help="anti-slop gate on a .fodp deck (off-brand colour / fabricated stat / decorative chart)")
    sl.add_argument("file")
    sl.add_argument("--brand", help="brand.json to check colours against (default: shipped tokens)")
    sl.add_argument("--allow-number", action="append", default=[],
                    help="a hero figure value to accept (repeatable)")
    sl.add_argument("--allow-chart", action="store_true", help="accept a bar-like graphic on a page")
    sl.set_defaults(_mod="slide", _func="cmd_slide_lint")

    sb = sub.add_parser("slide-build",
                        help="emit a complete .fodp deck from a compact JSON slide spec")
    sb.add_argument("spec", help="path to a JSON array of slide objects ({archetype, ...tokens})")
    sb.add_argument("--brand", help="brand.json for the style block (default: shipped tokens)")
    sb.add_argument("-o", "--out", help="write the .fodp here (default: stdout)")
    sb.set_defaults(_mod="slide", _func="cmd_slide_build")

    gr = sub.add_parser("graph", help="the devant code/intent graph (index.db)")
    gsub = gr.add_subparsers(dest="gcmd", required=True)

    gy = gsub.add_parser("sync", help="scan the repo into index.db (hash-incremental + orphan GC)")
    gy.add_argument("-j", "--json", action="store_true")
    gy.set_defaults(_mod="graphcmds", _func="cmd_graph_sync")

    gt = gsub.add_parser("status", help="index health: files/symbols per language, search integrity")
    gt.add_argument("-j", "--json", action="store_true")
    gt.set_defaults(_mod="graphcmds", _func="cmd_graph_status")

    gs = gsub.add_parser("search", help="search symbols, annotations and intent in one query")
    gs.add_argument("text")
    gs.add_argument("--limit", type=int, default=20)
    gs.add_argument("-j", "--json", action="store_true")
    gs.set_defaults(_mod="graphcmds", _func="cmd_graph_search")

    ge = gsub.add_parser("explore", help="matching symbols with verified source, files, and intent")
    ge.add_argument("text")
    ge.add_argument("--limit", type=int, default=10)
    ge.add_argument("-j", "--json", action="store_true")
    ge.set_defaults(_mod="graphcmds", _func="cmd_graph_explore")

    for name, func in [("callers", "cmd_graph_callers"), ("callees", "cmd_graph_callees"),
                       ("impact", "cmd_graph_impact")]:
        gc = gsub.add_parser(name)
        gc.add_argument("symbol")
        if name == "impact":
            gc.add_argument("--semantic", action="store_true",
                            help="also traverse shared annotation concepts")
        gc.add_argument("-j", "--json", action="store_true")
        gc.set_defaults(_mod="graphcmds", _func=func)

    gh = gsub.add_parser("hot", help="symbols ranked by inbound edges (annotate these first)")
    gh.add_argument("--limit", type=int, default=20)
    gh.add_argument("-j", "--json", action="store_true")
    gh.set_defaults(_mod="graphcmds", _func="cmd_graph_hot")

    ga = gsub.add_parser("affected", help="test files affected by the given source paths")
    ga.add_argument("paths", nargs="*")
    ga.add_argument("--stdin", action="store_true", help="also read newline-separated paths from stdin")
    ga.add_argument("-j", "--json", action="store_true")
    ga.set_defaults(_mod="graphcmds", _func="cmd_graph_affected")

    gn = gsub.add_parser("annotate", help="attach a model-written summary/concepts to a symbol or file")
    gn.add_argument("--key", required=True, help="target key (file path, or fileid:qualname:kind)")
    gn.add_argument("--type", required=True, choices=["symbol", "file"])
    gn.add_argument("--summary", required=True)
    gn.add_argument("--concepts", help="comma-separated concept tags")
    gn.add_argument("--source-hash", dest="source_hash")
    gn.add_argument("--source", default="model")
    gn.add_argument("-j", "--json", action="store_true")
    gn.set_defaults(_mod="graphcmds", _func="cmd_graph_annotate")

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    func = getattr(importlib.import_module("devantlib." + args._mod), args._func)
    try:
        return func(args) or 0
    except BrokenPipeError:
        return 0
    except (sqlite3.Error, ValueError, OSError) as exc:
        sys.stderr.write("devant: %s\n" % exc)  # degrade with a clean message, never a traceback
        return 1
