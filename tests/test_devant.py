#!/usr/bin/env python3
"""Tests for the devant intent CLI. Stdlib unittest, no third-party deps.

Run: python3 tests/test_devant.py   (or: python3 -m unittest -v tests/test_devant.py)

Pure functions (path_match, first_forbid_hit, _content_tokens, secret_like) are tested in-process;
guard/why/supersede/lint behavior is tested end-to-end through the CLI against a temp --db.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "bin", "devant")
_spec = spec_from_loader("devant_mod", SourceFileLoader("devant_mod", BIN))
dv = module_from_spec(_spec)
_spec.loader.exec_module(dv)


class PureFns(unittest.TestCase):
    def test_path_match_star_does_not_cross_slash(self):
        self.assertTrue(dv.path_match("src/app.py", "src/*.py"))
        self.assertFalse(dv.path_match("src/a/b.py", "src/*.py"))
        self.assertFalse(dv.path_match("docs/README.md", "*.md"))
        self.assertTrue(dv.path_match("README.md", "*.md"))

    def test_path_match_double_star_crosses(self):
        self.assertTrue(dv.path_match("src/app.py", "src/**/*.py"))
        self.assertTrue(dv.path_match("src/a/b/c.py", "src/**/*.py"))
        self.assertTrue(dv.path_match(".env", "**/.env"))
        self.assertTrue(dv.path_match(".env", "**/*.env"))
        self.assertTrue(dv.path_match("internal/planner/poll.go", "internal/planner/**"))
        self.assertTrue(dv.path_match("internal/planner/sub/x.go", "internal/planner/**"))
        self.assertFalse(dv.path_match("internal/db/x.go", "internal/planner/**"))

    def test_exempt_subtree_is_not_overbroad(self):
        # the exact bug the grumps found: src/legacy/*.py must NOT exempt nested files
        self.assertTrue(dv.path_match("src/legacy/old.py", "src/legacy/*.py"))
        self.assertFalse(dv.path_match("src/legacy/deep/danger.py", "src/legacy/*.py"))

    def test_forbid_word_boundary(self):
        self.assertEqual(dv.first_forbid_hit("import dbutils_safe", ["import db"]), None)
        self.assertEqual(dv.first_forbid_hit("import db\n", ["import db"]), "import db")
        self.assertEqual(dv.first_forbid_hit('q = "database/sql"', ["database/sql"]), "database/sql")
        self.assertEqual(dv.first_forbid_hit("x = eval(y)", ["eval("]), "eval(")

    def test_content_tokens_drop_stopwords(self):
        toks = dv._content_tokens("rename the user avatar widget")
        self.assertIn("rename", toks)
        self.assertIn("avatar", toks)
        self.assertNotIn("the", toks)

    def test_secret_like_coverage(self):
        self.assertEqual(dv.secret_like("DB_PASSWORD=SuperSecretValue123")[1], "ask")
        self.assertEqual(dv.secret_like("DATABASE_URL=postgres://admin:Hunter2pw@db.prod/app")[1], "ask")
        self.assertEqual(dv.secret_like('tok="ghp_abcdefabcdefabcdefabcdefabcdef1234"')[1], "deny")
        self.assertIsNone(dv.secret_like("API_KEY=${SECRET_FROM_ENV}"))  # interpolation, not a literal

    def test_secret_like_no_false_positive_on_env_reads(self):
        # lowercase code vars / calls / env reads must NOT be flagged (the UX false-positive)
        self.assertIsNone(dv.secret_like("token = get_token()"))
        self.assertIsNone(dv.secret_like("password = request.form['password']"))
        self.assertIsNone(dv.secret_like("API_KEY = os.environ['API_KEY']"))

    def test_secret_prefix_has_left_boundary(self):
        # 'sk-' must NOT match inside ordinary words like task-/risk-/disk- (the iter-4 regression)
        self.assertIsNone(dv.secret_like('MODULE = "task-management-system-core"'))
        self.assertIsNone(dv.secret_like("risk-management-strategy-engine-v2"))
        self.assertEqual(dv.secret_like("key = 'sk-abcdefabcdefabcdefabcd'")[1], "deny")  # real token still caught

    def test_cg_stale_detects_drift(self):
        self.assertFalse(dv.cg_stale(None))
        self.assertFalse(dv.cg_stale({"pendingChanges": {"added": 0, "modified": 0, "removed": 0}, "worktreeMismatch": None}))
        self.assertTrue(dv.cg_stale({"pendingChanges": {"added": 0, "modified": 2, "removed": 0}}))
        self.assertTrue(dv.cg_stale({"worktreeMismatch": True}))

    def test_evaluate_bash_denies_git_write_and_destructive(self):
        for c in ("git commit -m x", "git push origin main", "git add .",
                  "git -c commit.gpgsign=false commit -m x",   # intervening -c value-opt
                  "FOO=1 git push", "sudo git push origin main", "ls && git commit -m x",
                  "git -C /repo push", "git push --force",
                  "git reset --hard HEAD~1", "git clean -fd", "git rm cached.py",
                  "git branch -D feat", "git tag -d v1", "git stash drop", "git stash clear",
                  "git checkout -- file.py", "git filter-branch --all", "git filter-repo --invert",
                  "git checkout .", "git checkout HEAD~1 file.py",   # pathspec discard, no -- needed
                  "git restore .", "git restore file.py", "git restore --staged --worktree .",
                  "git restore -SW .", "git switch --discard-changes main", "git switch -f main"):
            self.assertEqual(dv.evaluate_bash(c)[0], "deny", c)

    def test_evaluate_bash_allows_readonly_and_nongit(self):
        for c in ("git status", "git diff", "git log --grep=push", "git branch",
                  "git checkout main", "git checkout -b feat", "git checkout -b feat main",
                  "git restore --staged file.py", "git restore -S file.py",
                  "git switch main", "git switch -c feat",
                  "git reset HEAD file.py", "git clean -n",
                  "git stash", "git stash pop", "git tag -l 'v*'",
                  "ls -la && grep foo bar.txt", 'echo "remember to git push later"',
                  "npm run build && node dist/server.js", "python3 -c 'print(2+2)'"):
            self.assertEqual(dv.evaluate_bash(c)[0], "allow", c)


class CliEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = self.tmp.name
        self.db = os.path.join(self.proj, "intent.db")
        self.env = dict(os.environ, CLAUDE_PROJECT_DIR=self.proj, DEVANT_CODEGRAPH="off")

    def tearDown(self):
        self.tmp.cleanup()

    def dv(self, *args, stdin=None):
        return subprocess.run([sys.executable, BIN, "--db", self.db, *args],
                              input=stdin, capture_output=True, text=True, env=self.env)

    def guard(self, relpath, content):
        r = self.dv("guard", "--file=" + os.path.join(self.proj, relpath), "--content", "-", stdin=content)
        return json.loads(r.stdout)["decision"]

    def test_constraint_update_keeps_enforcement(self):
        self.dv("add-node", "--kind", "constraint", "--id", "con-001", "--title", "no requests",
                "--body", "use the http client", "--applies", "src/**/*.py",
                "--forbid", "import requests", "--severity", "block")
        self.assertEqual(self.guard("src/app.py", "import requests"), "deny")
        # re-add to fix the title only — must NOT silently disarm
        self.dv("add-node", "--kind", "constraint", "--id", "con-001",
                "--title", "No raw requests (HTTP)", "--body", "use the http client")
        self.assertEqual(self.guard("src/app.py", "import requests"), "deny")

    def test_decide_exempt_scopes_one_subtree_only(self):
        self.dv("add-node", "--kind", "constraint", "--id", "con-001", "--title", "no eval",
                "--body", "eval is unsafe", "--applies", "src/**/*.py", "--forbid", "eval(", "--severity", "block")
        self.dv("decide", "--title", "legacy may eval", "--body", "migration",
                "--supersedes", "con-001", "--exempt", "src/legacy/*.py")
        self.assertEqual(self.guard("src/legacy/old.py", "x = eval(1)"), "allow")     # exempt
        self.assertEqual(self.guard("src/legacy/deep/x.py", "x = eval(1)"), "deny")    # NOT exempt (real glob)
        self.assertEqual(self.guard("src/app.py", "x = eval(1)"), "deny")             # elsewhere

    def test_supersede_decision_retires_it(self):
        self.dv("add-node", "--kind", "decision", "--id", "dec-001", "--title", "old way", "--body", "r")
        self.dv("decide", "--title", "new way", "--body", "better", "--supersedes", "dec-001")
        out = json.loads(self.dv("query", "way", "-j").stdout)
        ids = [n["id"] for n in out]
        self.assertNotIn("dec-001", ids)

    def test_superseded_decision_not_surfaced_for_area(self):
        self.dv("decide", "--title", "Use Postgres for storage", "--body", "considered", "--id", "dec-old")
        self.dv("decide", "--title", "Use SQLite for storage", "--body", "single binary", "--supersedes", "dec-old")
        rows = json.loads(self.dv("constraints", "--area", "switch storage to postgres", "-j").stdout)
        ids = [r["id"] for r in rows]
        self.assertNotIn("dec-old", ids)      # retired — must not resurface as live intent
        self.assertIn("dec-001", ids)         # its successor still speaks for the topic

    def test_why_reaches_decision_and_goal_from_a_constraint_link(self):
        self.dv("add-node", "--kind", "vision", "--id", "vision-001", "--title", "maintainable", "--body", "v")
        self.dv("add-node", "--kind", "goal", "--id", "goal-001", "--title", "one db layer", "--body", "g")
        self.dv("add-edge", "goal-001", "refines", "vision-001")
        self.dv("add-node", "--kind", "constraint", "--id", "con-001", "--title", "no direct db",
                "--body", "why", "--applies", "src/**", "--forbid", "import db", "--severity", "block")
        self.dv("decide", "--title", "db via tool layer", "--body", "rationale",
                "--establishes", "con-001", "--realizes", "goal-001")
        self.dv("link", "con-001", "src.handlers.save", "--relation", "constrains",
                "--path", "src/handlers.py", "--no-resolve")
        chain = json.loads(self.dv("why", "src.handlers.save", "-j").stdout)
        kinds = {n["kind"] for n in chain}
        self.assertEqual({"constraint", "decision", "goal", "vision"}, kinds & {"constraint", "decision", "goal", "vision"})

    def test_lint_flags_toothless_constraint(self):
        self.dv("add-node", "--kind", "constraint", "--id", "con-x", "--title", "vague rule",
                "--body", "no teeth", "--applies", "src/**", "--severity", "warn")
        rep = json.loads(self.dv("lint", "-j").stdout)
        self.assertIn("con-x", rep["constraints_without_forbid"])

    def test_doctor_self_check_passes(self):
        rep = json.loads(self.dv("doctor", "-j").stdout)
        self.assertEqual(rep["guard_engine"], "ok")

    def test_invalid_meta_is_clean_error_not_traceback(self):
        r = self.dv("add-node", "--kind", "note", "--title", "t", "--meta", "{bad json")
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("valid JSON", r.stderr)

    def test_area_surfaces_relevant_block_rule_only(self):
        self.dv("add-node", "--kind", "constraint", "--id", "con-b", "--title", "planner reports, never queries db",
                "--body", "report-back", "--applies", "internal/planner/**", "--forbid", "database/sql", "--severity", "block")
        rel = json.loads(self.dv("constraints", "--area", "add db access to the planner", "-j").stdout)
        self.assertIn("con-b", [r["id"] for r in rel])        # topically relevant -> surfaced
        unrel = json.loads(self.dv("constraints", "--area", "tweak the footer css margin", "-j").stdout)
        self.assertNotIn("con-b", [r["id"] for r in unrel])   # unrelated -> not injected (anti-furnace)

    def test_block_deny_not_masked_by_secret_ask(self):
        self.dv("add-node", "--kind", "constraint", "--id", "con-e", "--title", "no eval", "--body", "unsafe",
                "--applies", "src/**/*.py", "--forbid", "eval(", "--severity", "block")
        content = "x = eval(1)\nurl = 'postgres://admin:Hunter2pw@db.prod/app'\n"  # ask-secret + block-violation
        self.assertEqual(self.guard("src/app.py", content), "deny")

    def test_constraints_surfaces_rejected_decision(self):
        self.dv("decide", "--title", "Use Postgres for storage", "--body", "considered",
                "--rejected", "Postgres", "--why-rejected", "breaks the single-binary vision",
                "--id", "dec-pg")
        # mark it rejected so it's clearly a ruled-out path
        self.dv("add-node", "--kind", "decision", "--id", "dec-pg", "--title", "Use Postgres for storage",
                "--status", "rejected")
        rows = json.loads(self.dv("constraints", "--area", "switch storage to postgres", "-j").stdout)
        self.assertIn("dec-pg", [r["id"] for r in rows])

    def test_concurrent_add_node_no_lost_writes(self):
        import concurrent.futures

        def add(i):
            return subprocess.run([sys.executable, BIN, "--db", self.db, "add-node",
                                   "--kind", "note", "--title", "n%d" % i],
                                  capture_output=True, text=True, env=self.env).stdout.strip()
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
            ids = [f.result() for f in [ex.submit(add, i) for i in range(20)]]
        rows = json.loads(self.dv("show", "-j").stdout)["nodes"]
        notes = [n for n in rows if n["kind"] == "note"]
        self.assertEqual(len(notes), 20)            # no lost writes
        self.assertEqual(len(set(n["id"] for n in notes)), 20)  # all ids distinct

    def test_dangling_reports_broken_edge(self):
        self.dv("add-node", "--kind", "decision", "--id", "dec-001", "--title", "d", "--body", "r")
        self.dv("add-edge", "dec-001", "realizes", "goal-missing")
        rep = json.loads(self.dv("dangling", "-j").stdout)
        self.assertTrue(any(e["dst"] == "goal-missing" for e in rep["edge_dangling"]))

    def test_secret_denied_in_src_but_asked_in_tests(self):
        key = "import x\nk = 'ghp_abcdefabcdefabcdefabcdefabcdef1234'\n"
        self.assertEqual(self.guard("src/aws.py", key), "deny")       # real code -> hard deny
        self.assertEqual(self.guard("tests/test_x.py", key), "ask")   # test context -> flag, don't block


class HookTests(unittest.TestCase):
    """Run the actual bash hooks end-to-end (the blind spot that let the NUL bug ship)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = self.tmp.name
        os.makedirs(os.path.join(self.proj, ".devant"), exist_ok=True)
        self.db = os.path.join(self.proj, ".devant", "intent.db")
        self.cfg_dir = os.path.join(self.proj, ".fake-claude-config")
        self.env = dict(os.environ, CLAUDE_PLUGIN_ROOT=ROOT,
                        CLAUDE_PROJECT_DIR=self.proj, DEVANT_CODEGRAPH="off",
                        CLAUDE_CONFIG_DIR=self.cfg_dir)
        subprocess.run([sys.executable, BIN, "--db", self.db, "add-node", "--kind", "constraint",
                        "--id", "con-001", "--title", "no sqlite in handlers", "--body", "use the repo layer",
                        "--applies", "src/**/*.py", "--forbid", "import sqlite3", "--severity", "block"],
                       capture_output=True, text=True, env=self.env)

    def tearDown(self):
        self.tmp.cleanup()

    def hook(self, name, event):
        return subprocess.run(["bash", os.path.join(ROOT, "hooks", "lib", name)],
                              input=json.dumps(event), capture_output=True, text=True, env=self.env)

    def decision(self, r):
        out = r.stdout.strip()
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"] if out else "allow"

    def w(self, rel, content, tool="Write", sid="h"):
        ti = {"file_path": os.path.join(self.proj, rel)}
        ti["content" if tool == "Write" else "new_string"] = content
        return self.hook("pre-tool-write.sh", {"cwd": self.proj, "session_id": sid, "tool_name": tool, "tool_input": ti})

    def test_write_hook_denies_block_constraint(self):
        self.assertEqual(self.decision(self.w("src/app.py", "import sqlite3\n")), "deny")

    def test_touched_recorded_by_post_hook_not_pre_hook(self):
        # pre-hook only decides; a denied write must never count as touched
        self.assertEqual(self.decision(self.w("src/util.py", "def add(a, b):\n    return a + b\n")), "allow")
        touched = os.path.join(self.proj, ".devant", "state", "h.touched")
        self.assertFalse(os.path.exists(touched))
        self.hook("post-tool-write.sh", {"cwd": self.proj, "session_id": "h", "tool_name": "Write",
                                         "tool_input": {"file_path": os.path.join(self.proj, "src/util.py")}})
        self.assertTrue(os.path.exists(touched))
        with open(touched) as fh:
            self.assertIn("src/util.py", fh.read())

    def test_write_hook_denies_secret_and_devant(self):
        self.assertEqual(self.decision(self.w("src/aws.py", "k = 'ghp_abcdefabcdefabcdefabcdefabcdef1234'\n")), "deny")
        self.assertEqual(self.decision(self.w(".devant/intent.db", "x", tool="Edit")), "deny")

    def test_multiedit_content_is_scanned(self):
        ev = {"cwd": self.proj, "session_id": "h", "tool_name": "MultiEdit",
              "tool_input": {"file_path": os.path.join(self.proj, "src/x.py"),
                             "edits": [{"old_string": "a", "new_string": "b"},
                                       {"old_string": "c", "new_string": "import sqlite3"}]}}
        self.assertEqual(self.decision(self.hook("pre-tool-write.sh", ev)), "deny")

    def test_bash_hook_denies_git_write_and_allows_readonly(self):
        b = lambda c: self.decision(self.hook("pre-tool-bash.sh", {"tool_name": "Bash", "tool_input": {"command": c}}))
        self.assertEqual(b("git commit -m x"), "deny")
        self.assertEqual(b("git push origin main"), "deny")
        self.assertEqual(b("git add ."), "deny")
        self.assertEqual(b("git reset --hard HEAD~1"), "deny")
        self.assertEqual(b("git status"), "allow")
        self.assertEqual(b("git log --grep=push"), "allow")              # 'push' in option value, not the subcommand
        self.assertEqual(b("ls -la && grep foo bar.txt"), "allow")

    def test_stop_hook_emits_note_after_touched(self):
        srcdir = os.path.join(self.proj, "src")
        os.makedirs(srcdir, exist_ok=True)
        fpath = os.path.join(srcdir, "h.py")
        with open(fpath, "w") as fh:
            fh.write("def f():\n    pass  # TODO: finish this\n")
        state = os.path.join(self.proj, ".devant", "state")
        os.makedirs(state, exist_ok=True)
        with open(os.path.join(state, "h.touched"), "w") as fh:
            fh.write(fpath + "\n")
        self.hook("stop.sh", {"cwd": self.proj, "session_id": "h"})
        note = os.path.join(state, "h.lastturn")
        self.assertTrue(os.path.exists(note))
        with open(note) as fh:
            self.assertIn("TODO", fh.read())

    def test_subagent_stop_preserves_touched_for_real_stop(self):
        state = os.path.join(self.proj, ".devant", "state")
        os.makedirs(state, exist_ok=True)
        touched = os.path.join(state, "h.touched")
        with open(touched, "w") as fh:
            fh.write(os.path.join(self.proj, "src", "h.py") + "\n")
        self.hook("stop.sh", {"cwd": self.proj, "session_id": "h", "hook_event_name": "SubagentStop"})
        self.assertTrue(os.path.exists(touched))                                        # not consumed
        self.assertFalse(os.path.exists(os.path.join(state, "h.lastturn")))             # no note yet

    def ctx(self, r):
        out = r.stdout.strip()
        return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else ""

    def test_session_start_emits_intent_brief(self):
        r = self.hook("session-start.sh", {"cwd": self.proj, "session_id": "ss"})
        self.assertIn("no sqlite in handlers", self.ctx(r))   # the block rule seeded in setUp

    def sysmsg(self, r):
        out = r.stdout.strip()
        return json.loads(out).get("systemMessage", "") if out else ""

    def test_session_start_enables_global_autocompact_once(self):
        settings = os.path.join(self.cfg_dir, "settings.json")
        r1 = self.hook("session-start.sh", {"cwd": self.proj, "session_id": "ss"})
        self.assertIn("autoCompactEnabled", self.sysmsg(r1))
        with open(settings) as fh:
            self.assertEqual(json.load(fh)["autoCompactEnabled"], True)

        r2 = self.hook("session-start.sh", {"cwd": self.proj, "session_id": "ss"})
        self.assertEqual(self.sysmsg(r2), "")   # already set, no repeat nudge

    def test_session_start_never_overwrites_explicit_autocompact_choice(self):
        os.makedirs(self.cfg_dir, exist_ok=True)
        settings = os.path.join(self.cfg_dir, "settings.json")
        with open(settings, "w") as fh:
            json.dump({"autoCompactEnabled": False}, fh)
        r = self.hook("session-start.sh", {"cwd": self.proj, "session_id": "ss"})
        self.assertEqual(self.sysmsg(r), "")
        with open(settings) as fh:
            self.assertEqual(json.load(fh)["autoCompactEnabled"], False)   # untouched

    def test_user_prompt_injects_on_change_verb(self):
        ctx = self.ctx(self.hook("user-prompt.sh",
                                  {"cwd": self.proj, "session_id": "up1", "prompt": "add sqlite to the handler module"}))
        self.assertIn("Before changing code", ctx)            # discipline block
        self.assertIn("no sqlite in handlers", ctx)           # topically-relevant area rule

    def test_user_prompt_injects_on_problem_phrasing(self):
        # no classic change-verb; "broken"/"sort out" must still trigger the heads-up (R5 widening)
        ctx = self.ctx(self.hook("user-prompt.sh",
                                  {"cwd": self.proj, "session_id": "up2", "prompt": "the handler is broken, sort it out"}))
        self.assertIn("Before changing code", ctx)

    def test_user_prompt_skips_pure_question(self):
        r = self.hook("user-prompt.sh", {"cwd": self.proj, "session_id": "up3", "prompt": "how does the handler work?"})
        self.assertEqual(r.stdout.strip(), "")                # info-lead, no change signal -> no injection

    def test_pre_compact_reprimes_discipline_block(self):
        ev = {"cwd": self.proj, "session_id": "pc", "prompt": "fix the handler bug"}
        self.assertIn("Before changing code", self.ctx(self.hook("user-prompt.sh", ev)))     # first change prompt primes
        self.assertNotIn("Before changing code", self.ctx(self.hook("user-prompt.sh", ev)))  # deduped while primed
        self.hook("pre-compact.sh", {"cwd": self.proj, "session_id": "pc", "trigger": "auto"})
        self.assertIn("Before changing code", self.ctx(self.hook("user-prompt.sh", ev)))     # compaction re-primes


class DrawioLint(unittest.TestCase):
    """The diagram beauty gate: geometry defects are auto-fixed; semantic ones block (exit 1)."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, xml):
        p = os.path.join(self.tmp.name, "d.drawio")
        with open(p, "w") as fh:
            fh.write(xml)
        return p

    def lint(self, path, fix=False):
        args = [sys.executable, BIN, "drawio-lint", path] + (["--fix"] if fix else [])
        return subprocess.run(args, capture_output=True, text=True)

    def _model(self, cells):
        return ('<mxfile host="devant"><diagram name="t" id="t"><mxGraphModel gridSize="10" '
                'pageWidth="1100" pageHeight="850"><root><mxCell id="0" />'
                '<mxCell id="1" parent="0" />' + cells + "</root></mxGraphModel></diagram></mxfile>")

    def vertex(self, i, x, y, w=160, h=70, style="rounded=1;"):
        return ('<mxCell id="%s" value="%s" style="%s" vertex="1" parent="1">'
                '<mxGeometry x="%s" y="%s" width="%s" height="%s" as="geometry" /></mxCell>'
                % (i, i, style, x, y, w, h))

    def test_fix_snaps_grid_and_spreads_overlap(self):
        # a is off-grid (193,47); b overlaps a
        p = self.write(self._model(self.vertex("a", 193, 47) + self.vertex("b", 210, 60)))
        self.assertEqual(self.lint(p).returncode, 1)                       # dirty before
        r = self.lint(p, fix=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)             # auto-fixed to clean
        self.assertIn("straightened", r.stdout)
        self.assertIn("spread", r.stdout)
        import xml.etree.ElementTree as ET
        geos = ET.parse(p).getroot().findall(".//mxCell[@vertex='1']/mxGeometry")
        coords = [(int(float(g.get("x"))), int(float(g.get("y")))) for g in geos]
        for x, y in coords:
            self.assertEqual((x % 10, y % 10), (0, 0))                     # on the grid
        (ax, ay), (bx, by) = coords
        self.assertTrue(abs(ax - bx) >= 160 or abs(ay - by) >= 70)        # no longer overlapping
        self.assertEqual(self.lint(p).returncode, 0)                      # idempotent: stays clean

    def test_non_orthogonal_edge_blocks(self):
        edge = ('<mxCell id="e" value="x" style="rounded=0;" edge="1" parent="1" source="a" '
                'target="b"><mxGeometry relative="1" as="geometry" /></mxCell>')
        p = self.write(self._model(self.vertex("a", 100, 100) + self.vertex("b", 100, 300) + edge))
        r = self.lint(p, fix=True)                                        # --fix can't fix routing
        self.assertEqual(r.returncode, 1)
        self.assertIn("non-orthogonal", r.stdout)
        self.assertIn("e", r.stdout)

    def test_clean_diagram_passes_untouched(self):
        edge = ('<mxCell id="e" value="calls" style="edgeStyle=orthogonalEdgeStyle;rounded=0;" '
                'edge="1" parent="1" source="a" target="b">'
                '<mxGeometry relative="1" as="geometry" /></mxCell>')
        p = self.write(self._model(self.vertex("a", 100, 100) + self.vertex("b", 100, 300) + edge))
        with open(p) as fh:
            before = fh.read()
        r = self.lint(p, fix=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("clean", r.stdout)
        with open(p) as fh:
            self.assertEqual(fh.read(), before)                           # no rewrite when nothing to fix

    def test_concentric_shapes_not_flagged_as_overlap(self):
        # UML final node: a filled core deliberately centred inside a ring — must not be an "overlap"
        ring = self.vertex("ring", 400, 710, 30, 30, "ellipse;")
        core = self.vertex("core", 407, 717, 16, 16, "ellipse;")
        p = self.write(self._model(ring + core))
        self.assertEqual(self.lint(p).returncode, 0, self.lint(p).stdout)

    def test_label_spilling_onto_sibling_blocks(self):
        # a's label is far wider than its 120px node and reaches b; nodes themselves don't overlap
        a = ('<mxCell id="a" value="InventoryReconciliationSagaCoordinator Service" '
             'style="rounded=1;" vertex="1" parent="1">'
             '<mxGeometry x="100" y="100" width="120" height="60" as="geometry" /></mxCell>')
        p = self.write(self._model(a + self.vertex("b", 260, 100, 120, 60)))
        r = self.lint(p)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("labels colliding", r.stdout)
        self.assertIn("a->b", r.stdout)

    def test_wrapped_label_stays_inside_node_and_passes(self):
        # same long text, but whiteSpace=wrap keeps it inside the node — no collision
        a = ('<mxCell id="a" value="InventoryReconciliationSagaCoordinator Service" '
             'style="rounded=1;whiteSpace=wrap;" vertex="1" parent="1">'
             '<mxGeometry x="100" y="100" width="120" height="60" as="geometry" /></mxCell>')
        p = self.write(self._model(a + self.vertex("b", 260, 100, 120, 60)))
        r = self.lint(p)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_edge_label_on_node_blocks(self):
        # a long edge label at the midpoint of a->b lands on bystander node c
        edge = ('<mxCell id="e" value="recompute the projection" '
                'style="edgeStyle=orthogonalEdgeStyle;rounded=0;" edge="1" parent="1" '
                'source="a" target="b"><mxGeometry relative="1" as="geometry" /></mxCell>')
        cells = (self.vertex("a", 100, 100) + self.vertex("b", 100, 300)
                 + self.vertex("c", 200, 200) + edge)
        r = self.lint(self.write(self._model(cells)))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("labels colliding", r.stdout)
        self.assertIn("e->c", r.stdout)


def _layout_toolchain_ok():
    node = shutil.which("node")
    if not node:
        return False
    r = subprocess.run([node, "-e", "require('elkjs')"], capture_output=True, env=dv._node_env())
    return r.returncode == 0


class ElkLayout(unittest.TestCase):
    """`devant layout` — real ELK via the elkjs node driver, end to end."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    @unittest.skipUnless(_layout_toolchain_ok(), "node + elkjs not available")
    def test_layout_untangles_stacked_chain_and_lints_clean(self):
        # pathological input: a 5-node chain all stacked on the same coordinates
        ids = ["a", "b", "c", "d", "e"]
        cells = "".join('<mxCell id="%s" value="%s" style="rounded=1;" vertex="1" parent="1">'
                        '<mxGeometry x="100" y="100" width="160" height="70" as="geometry" />'
                        '</mxCell>' % (i, i) for i in ids)
        cells += "".join('<mxCell id="e%d" style="edgeStyle=orthogonalEdgeStyle;rounded=0;" '
                         'edge="1" parent="1" source="%s" target="%s">'
                         '<mxGeometry relative="1" as="geometry" /></mxCell>'
                         % (n, ids[n], ids[n + 1]) for n in range(4))
        p = os.path.join(self.tmp.name, "chain.drawio")
        with open(p, "w") as fh:
            fh.write('<mxfile host="devant"><diagram name="t" id="t"><mxGraphModel gridSize="10" '
                     'pageWidth="1100" pageHeight="850"><root><mxCell id="0" />'
                     '<mxCell id="1" parent="0" />' + cells + "</root></mxGraphModel></diagram></mxfile>")
        r = subprocess.run([sys.executable, BIN, "layout", p, "--preset", "verticalFlow"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("laid out 5 node(s)", r.stdout)
        import xml.etree.ElementTree as ET
        by_id = {c.get("id"): c.find("mxGeometry")
                 for c in ET.parse(p).getroot().findall(".//mxCell[@vertex='1']")}
        coords = [(float(by_id[i].get("x")), float(by_id[i].get("y"))) for i in ids]
        self.assertEqual(len(set(coords)), 5)                              # no longer stacked
        ys = [y for _, y in coords]
        self.assertEqual(ys, sorted(ys))                                   # DOWN: chain order preserved
        for x, y in coords:
            self.assertEqual((x % 10, y % 10), (0.0, 0.0))                 # snapped to the grid
        lint = subprocess.run([sys.executable, BIN, "drawio-lint", p, "--fix"],
                              capture_output=True, text=True)
        self.assertEqual(lint.returncode, 0, lint.stdout + lint.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
