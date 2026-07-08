#!/usr/bin/env python3
"""Tests for the devant intent CLI. Stdlib unittest, no third-party deps.

Run: python3 tests/test_devant.py   (or: python3 -m unittest -v tests/test_devant.py)

Pure functions (path_match, first_forbid_hit, _content_tokens, secret_like) are tested in-process;
guard/why/supersede/lint behavior is tested end-to-end through the CLI against a temp --db.
"""
import json
import os
import re
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

    def test_evaluate_bash_quoted_pipe_is_not_a_segment_break(self):
        # regression: the pre-shlex split on '|' broke quoted patterns into an
        # unbalanced-quote segment, and the conservative fallback denied a read-only grep.
        self.assertEqual(dv.evaluate_bash('grep "a\\|git commit" f.txt')[0], "allow")
        self.assertEqual(dv.evaluate_bash("grep 'x;git add' f.txt")[0], "allow")
        self.assertEqual(dv.evaluate_bash("ls | git commit -m x")[0], "deny")  # real pipe still splits

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

    def test_log_accepts_every_dispatchable_specialist(self):
        # the router dispatches slide/debate (table rows) and code invokes review — `devant log`
        # must accept them all, not error at the disclosure step.
        for s in ("slide", "debate", "review", "code", "diagram"):
            r = self.dv("log", s, "did", "x")
            self.assertEqual(r.returncode, 0, "%s: %s" % (s, r.stderr))
        counts = json.loads(self.dv("dead-skills", "-j").stdout)["counts"]
        self.assertEqual((counts["slide"], counts["debate"], counts["review"]), (1, 1, 1))

    def test_dead_skills_excludes_subinvoked_specialists(self):
        # review/debate are invoked as sub-steps (and onboard via a command), so a zero
        # router-log count is not "never used" — they must not be flagged; a pure router
        # route (slide) that is genuinely unused still is.
        dead = json.loads(self.dv("dead-skills", "-j").stdout)["dead"]
        for s in ("onboard", "review", "debate"):
            self.assertNotIn(s, dead)
        self.assertIn("slide", dead)

    def test_decision_body_prose_does_not_leak_into_area(self):
        # a decision surfaces on an area query via its title/rejected topic, NOT its rationale
        # prose — so a long body can't flood the prompt on a shared stopword-grade token.
        self.dv("decide", "--title", "Adopt event sourcing", "--id", "dec-body",
                "--body", "we may switch storage to postgres eventually, but not now")
        rows = json.loads(self.dv("constraints", "--area", "switch storage to postgres", "-j").stdout)
        self.assertNotIn("dec-body", [r["id"] for r in rows])   # body-only overlap -> not injected
        self.dv("decide", "--title", "Switch storage to Postgres", "--body", "perf", "--id", "dec-title")
        rows = json.loads(self.dv("constraints", "--area", "switch storage to postgres", "-j").stdout)
        self.assertIn("dec-title", [r["id"] for r in rows])     # title overlap -> still surfaced

    def test_intent_export_import_roundtrip_preserves_enforcement(self):
        # the collaboration lever: a fresh clone inherits the rules via export/import, and a block
        # constraint's meta (forbid/applies/severity) survives so the guard still denies.
        self.dv("decide", "--id", "dec-x", "--title", "Use SQLite", "--body", "single binary",
                "--rejected", "Postgres", "--why-rejected", "ops weight")
        self.dv("add-node", "--kind", "constraint", "--id", "con-x", "--title", "no raw sqlite",
                "--body", "use the repo layer", "--applies", "src/**", "--forbid", "import sqlite3",
                "--severity", "block")
        exp = os.path.join(self.proj, "intent.export.json")
        self.assertEqual(self.dv("export", "-o", exp).returncode, 0)
        self.assertTrue(os.path.exists(exp))
        db2 = os.path.join(self.proj, "intent2.db")

        def dv2(*a, stdin=None):
            return subprocess.run([sys.executable, BIN, "--db", db2, *a], input=stdin,
                                  capture_output=True, text=True, env=self.env)
        self.assertEqual(dv2("import", exp).returncode, 0)
        ids = {n["id"] for n in json.loads(dv2("show", "-j").stdout)["nodes"]}
        self.assertIn("dec-x", ids)
        self.assertIn("con-x", ids)
        g = dv2("guard", "--file=" + os.path.join(self.proj, "src/a.py"), "--content", "-",
                stdin="import sqlite3\n")
        self.assertEqual(json.loads(g.stdout)["decision"], "deny")   # rule enforceable after import


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
                        CLAUDE_CODE_SESSION_ID="h",
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

    def test_secret_scan_capped_but_block_teeth_uncapped(self):
        big = "x" * 1_200_000                                                     # past the 1MB secret cap
        # a leading secret is still caught despite a huge trailing paste
        self.assertEqual(self.decision(self.w("src/a.py",
                         "k = 'ghp_abcdefabcdefabcdefabcdefabcdef1234'\n" + big)), "deny")
        # a block-rule violation PAST the secret cap is still denied — teeth see the whole write
        self.assertEqual(self.decision(self.w("src/b.py", big + "\nimport sqlite3\n")), "deny")

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

    def test_bash_hook_denies_wrapper_prefixed_git_via_script(self):
        # regression: hooks.json `if: Bash(git *)` never saw through sudo/env/VAR= wrappers, so
        # these bypassed the guard in production though evaluate_bash "denied" them. The script now
        # does its own 'git' filtering, so the real hook path denies wrapper-prefixed git too.
        b = lambda c: self.decision(self.hook("pre-tool-bash.sh", {"tool_name": "Bash", "tool_input": {"command": c}}))
        self.assertEqual(b("sudo git push origin main"), "deny")
        self.assertEqual(b("FOO=1 git push"), "deny")
        self.assertEqual(b("env git commit -m x"), "deny")
        self.assertEqual(b("ls -la"), "allow")                           # no 'git' -> fast-path allow, no python spawn

    def test_stop_hook_emits_note_after_touched(self):
        # dec-019: the note is native Stop additionalContext (same turn), not a .lastturn relay.
        srcdir = os.path.join(self.proj, "src")
        os.makedirs(srcdir, exist_ok=True)
        fpath = os.path.join(srcdir, "h.py")
        with open(fpath, "w") as fh:
            fh.write("def f():\n    pass  # TODO: finish this\n")
        state = os.path.join(self.proj, ".devant", "state")
        os.makedirs(state, exist_ok=True)
        with open(os.path.join(state, "h.touched"), "w") as fh:
            fh.write(fpath + "\n")
        r = self.hook("stop.sh", {"cwd": self.proj, "session_id": "h"})
        self.assertIn("TODO", self.ctx(r))
        self.assertFalse(os.path.exists(os.path.join(state, "h.lastturn")))

    def test_stop_hook_surfaces_task_goal(self):
        state = os.path.join(self.proj, ".devant", "state")
        os.makedirs(state, exist_ok=True)
        with open(os.path.join(state, "goal"), "w") as fh:
            json.dump({"text": "auth check added; failing repro green", "ts": "t"}, fh)
        with open(os.path.join(state, "h.touched"), "w") as fh:
            fh.write(os.path.join(self.proj, "x.py") + "\n")
        r = self.hook("stop.sh", {"cwd": self.proj, "session_id": "h"})
        self.assertIn("auth check added", self.ctx(r))

    def test_stop_hook_active_short_circuits(self):
        state = os.path.join(self.proj, ".devant", "state")
        os.makedirs(state, exist_ok=True)
        with open(os.path.join(state, "h.touched"), "w") as fh:
            fh.write(os.path.join(self.proj, "x.py") + "\n")
        r = self.hook("stop.sh", {"cwd": self.proj, "session_id": "h", "stop_hook_active": True})
        self.assertEqual(r.stdout.strip(), "")                                   # loop guard
        self.assertTrue(os.path.exists(os.path.join(state, "h.touched")))        # nothing consumed

    def test_task_completed_blocks_on_stub_markers(self):
        srcdir = os.path.join(self.proj, "src")
        os.makedirs(srcdir, exist_ok=True)
        fpath = os.path.join(srcdir, "t.py")
        with open(fpath, "w") as fh:
            fh.write("def f():\n    raise NotImplementedError\n")
        state = os.path.join(self.proj, ".devant", "state")
        os.makedirs(state, exist_ok=True)
        with open(os.path.join(state, "h.touched"), "w") as fh:
            fh.write(fpath + "\n")
        r = self.hook("task-completed.sh", {"cwd": self.proj, "session_id": "h"})
        self.assertEqual(r.returncode, 2)                                        # blocks completion
        self.assertIn("unfinished markers", r.stderr.lower())
        with open(fpath, "w") as fh:
            fh.write("def f():\n    return 1\n")
        r = self.hook("task-completed.sh", {"cwd": self.proj, "session_id": "h"})
        self.assertEqual(r.returncode, 0)                                        # clean -> allow

    def test_task_completed_ignores_substring_false_positives(self):
        # 'todos' contains 'todo', '0xXXXX' contains 'xxx' — neither is an unfinished marker.
        srcdir = os.path.join(self.proj, "src")
        os.makedirs(srcdir, exist_ok=True)
        fpath = os.path.join(srcdir, "s.py")
        with open(fpath, "w") as fh:
            fh.write("def list_todos():\n    return 0xXXXX  # mastodon feed\n")
        state = os.path.join(self.proj, ".devant", "state")
        os.makedirs(state, exist_ok=True)
        with open(os.path.join(state, "h.touched"), "w") as fh:
            fh.write(fpath + "\n")
        r = self.hook("task-completed.sh", {"cwd": self.proj, "session_id": "h"})
        self.assertEqual(r.returncode, 0)                                        # no real marker -> must not block

    def test_task_completed_scopes_stub_scan_to_added_lines(self):
        # A task that merely TOUCHED a file carrying a pre-existing (committed) TODO must
        # still complete; only a stub the change itself ADDED should block.
        def git(*a):
            subprocess.run(["git", *a], cwd=self.proj, capture_output=True, text=True, env=self.env)
        git("init")
        git("config", "user.email", "t@t")
        git("config", "user.name", "t")
        git("config", "commit.gpgsign", "false")
        srcdir = os.path.join(self.proj, "src")
        os.makedirs(srcdir, exist_ok=True)
        fpath = os.path.join(srcdir, "p.py")
        with open(fpath, "w") as fh:
            fh.write("def f():\n    pass  # TODO: legacy, not mine\n")
        git("add", "-A")
        git("commit", "-m", "seed")
        state = os.path.join(self.proj, ".devant", "state")
        os.makedirs(state, exist_ok=True)
        with open(os.path.join(state, "h.touched"), "w") as fh:
            fh.write(fpath + "\n")
        with open(fpath, "a") as fh:                                             # unrelated, complete change
            fh.write("def g():\n    return 2\n")
        r = self.hook("task-completed.sh", {"cwd": self.proj, "session_id": "h"})
        self.assertEqual(r.returncode, 0)                                        # pre-existing TODO must not block
        with open(fpath, "a") as fh:                                             # now the change itself adds a stub
            fh.write("def h():\n    pass  # TODO: mine, unfinished\n")
        r = self.hook("task-completed.sh", {"cwd": self.proj, "session_id": "h"})
        self.assertEqual(r.returncode, 2)                                        # newly-added stub still blocks

    def test_warn_rule_informs_without_blocking(self):
        # dec-019: warn-severity constraints surface as allow+additionalContext, not a modal ask.
        subprocess.run([sys.executable, BIN, "--db", self.db, "add-node", "--kind", "constraint",
                        "--id", "con-w", "--title", "prefer the http client", "--body", "r",
                        "--applies", "src/**/*.py", "--forbid", "import urllib3", "--severity", "warn"],
                       capture_output=True, text=True, env=self.env)
        r = self.w("src/warned.py", "import urllib3\n")
        out = json.loads(r.stdout)["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "allow")
        self.assertIn("warn rule", out["additionalContext"])

    def test_notebook_edit_is_guarded_and_tracked(self):
        ev = {"cwd": self.proj, "session_id": "h", "tool_name": "NotebookEdit",
              "tool_input": {"notebook_path": os.path.join(self.proj, "src", "n.ipynb"),
                             "new_string": "k = 'ghp_abcdefabcdefabcdefabcdefabcdef1234'"}}
        self.assertEqual(self.decision(self.hook("pre-tool-write.sh", ev)), "deny")
        self.hook("post-tool-write.sh", {"cwd": self.proj, "session_id": "h", "tool_name": "NotebookEdit",
                                         "tool_input": {"notebook_path": os.path.join(self.proj, "src", "n.ipynb")}})
        with open(os.path.join(self.proj, ".devant", "state", "h.touched")) as fh:
            self.assertIn("n.ipynb", fh.read())

    def test_subagent_stop_preserves_touched_for_real_stop(self):
        state = os.path.join(self.proj, ".devant", "state")
        os.makedirs(state, exist_ok=True)
        touched = os.path.join(state, "h.touched")
        with open(touched, "w") as fh:
            fh.write(os.path.join(self.proj, "src", "h.py") + "\n")
        r = self.hook("stop.sh", {"cwd": self.proj, "session_id": "h", "hook_event_name": "SubagentStop"})
        self.assertTrue(os.path.exists(touched))                                        # not consumed
        self.assertEqual(r.stdout.strip(), "")                                          # no note yet

    def ctx(self, r):
        out = r.stdout.strip()
        return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else ""

    def test_session_start_emits_intent_brief(self):
        r = self.hook("session-start.sh", {"cwd": self.proj, "session_id": "ss"})
        self.assertIn("no sqlite in handlers", self.ctx(r))   # the block rule seeded in setUp

    def test_session_start_persists_transcript_path(self):
        tp = os.path.join(self.proj, "fake-transcript.jsonl")
        open(tp, "w").close()
        self.hook("session-start.sh", {"cwd": self.proj, "session_id": "ss",
                                       "transcript_path": tp, "model": "claude-sonnet-5"})
        state = os.path.join(self.proj, ".devant", "state")
        with open(os.path.join(state, "transcript.path")) as fh:
            self.assertEqual(fh.read().strip(), tp)
        with open(os.path.join(state, "model")) as fh:
            self.assertEqual(fh.read().strip(), "claude-sonnet-5")

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


class GraphP0(unittest.TestCase):
    """P0 contract for the devant graph (dec-016): index.db schema, the frozen -j output
    shape of every `devant graph` subcommand, node_history journaling, and the guard
    hot-path isolation guarantee of the devantlib split."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = self.tmp.name
        self.db = os.path.join(self.proj, ".devant", "intent.db")
        self.idx = os.path.join(self.proj, ".devant", "index.db")
        self.env = dict(os.environ, CLAUDE_PROJECT_DIR=self.proj, DEVANT_CODEGRAPH="off")

    def tearDown(self):
        self.tmp.cleanup()

    def dv(self, *args, stdin=None, env=None):
        return subprocess.run([sys.executable, BIN, "--db", self.db, "--index-db", self.idx, *args],
                              input=stdin, capture_output=True, text=True, env=env or self.env)

    def put(self, rel, content):
        p = os.path.join(self.proj, rel)
        d = os.path.dirname(p)
        if d:
            os.makedirs(d, exist_ok=True)
        mode = "wb" if isinstance(content, bytes) else "w"
        with open(p, mode) as fh:
            fh.write(content)

    def test_contract_output_shapes_frozen(self):
        # The -j key sets below ARE the P0 CLI contract — later phases may only add keys.
        self.put("src/app.py", "def f():\n    return 1\n")
        r = json.loads(self.dv("graph", "sync", "-j").stdout)
        self.assertEqual(set(r), {"scanned", "indexed", "updated", "removed", "skipped"})
        r = json.loads(self.dv("graph", "status", "-j").stdout)
        self.assertEqual(set(r), {"schema_version", "files", "symbols", "parse_errors",
                                  "error_files", "langs", "fts"})
        self.assertIsInstance(json.loads(self.dv("graph", "search", "app", "-j").stdout), list)
        r = json.loads(self.dv("graph", "explore", "app", "-j").stdout)
        self.assertEqual(set(r), {"symbols", "files", "intent"})
        self.assertIsInstance(json.loads(self.dv("graph", "callers", "f", "-j").stdout), list)
        self.assertIsInstance(json.loads(self.dv("graph", "callees", "f", "-j").stdout), list)
        r = json.loads(self.dv("graph", "impact", "f", "-j").stdout)
        self.assertEqual(set(r), {"symbols", "intent"})
        self.assertIsInstance(json.loads(self.dv("graph", "affected", "src/app.py", "-j").stdout), list)
        r = json.loads(self.dv("graph", "annotate", "--key", "src/app.py", "--type", "file",
                               "--summary", "entry point", "-j").stdout)
        self.assertEqual(set(r), {"target_key", "target_type"})

    def test_sync_is_hash_incremental_with_gc(self):
        self.put("a.py", "x = 1\n")
        self.put("b.py", "y = 2\n")
        r = json.loads(self.dv("graph", "sync", "-j").stdout)
        self.assertEqual((r["indexed"], r["updated"], r["removed"]), (2, 0, 0))
        r = json.loads(self.dv("graph", "sync", "-j").stdout)          # nothing changed
        self.assertEqual((r["indexed"], r["updated"], r["removed"]), (0, 0, 0))
        self.put("a.py", "x = 42\n")                                    # content changed
        os.remove(os.path.join(self.proj, "b.py"))                      # file deleted
        r = json.loads(self.dv("graph", "sync", "-j").stdout)
        self.assertEqual((r["indexed"], r["updated"], r["removed"]), (0, 1, 1))
        st = json.loads(self.dv("graph", "status", "-j").stdout)
        self.assertEqual(st["files"], 1)                                # GC really removed the row

    def test_sync_skips_binary_large_and_symlink(self):
        self.put("ok.py", "x = 1\n")
        self.put("blob.bin", b"\x00\x01\x02data")
        self.put("huge.js", "a" * 1_100_000)
        os.symlink(os.path.join(self.proj, "ok.py"), os.path.join(self.proj, "lnk.py"))
        r = json.loads(self.dv("graph", "sync", "-j").stdout)
        self.assertGreaterEqual(r["skipped"], 3)
        st = json.loads(self.dv("graph", "status", "-j").stdout)
        self.assertEqual(st["files"], 1)

    def test_node_history_journals_overwrite(self):
        self.dv("add-node", "--kind", "note", "--id", "note-1", "--title", "first", "--body", "b")
        self.dv("add-node", "--kind", "note", "--id", "note-1", "--title", "second", "--body", "b")
        import sqlite3
        conn = sqlite3.connect(self.db)
        hist = [t for (t,) in conn.execute(
            "SELECT title FROM node_history WHERE node_id='note-1'").fetchall()]
        self.assertIn("first", hist)                                    # old row journaled
        (updated,) = conn.execute("SELECT updated FROM node WHERE id='note-1'").fetchone()
        self.assertTrue(updated)                                        # edit stamped

    def test_index_created_with_incremental_autovacuum(self):
        self.put("a.py", "x = 1\n")
        self.dv("graph", "sync")
        import sqlite3
        av = sqlite3.connect(self.idx).execute("PRAGMA auto_vacuum").fetchone()[0]
        self.assertEqual(av, 2)                                         # INCREMENTAL

    def test_fts_fallback_still_searches(self):
        env = dict(self.env, DEVANT_FTS="off")
        self.put("m.py", "x = 1\n")
        self.dv("graph", "sync", env=env)
        self.dv("graph", "annotate", "--key", "m.py", "--type", "file",
                "--summary", "handles auth flows", "--concepts", "auth", env=env)
        st = json.loads(self.dv("graph", "status", "-j", env=env).stdout)
        self.assertEqual(st["fts"], "like")
        hits = json.loads(self.dv("graph", "search", "auth", "-j", env=env).stdout)
        self.assertTrue(any(h.get("kind") == "annotation" for h in hits))

    def test_search_joins_intent_nodes(self):
        self.dv("decide", "--title", "Use bcrypt for auth hashing", "--body", "r", "--id", "dec-a")
        self.put("m.py", "x = 1\n")
        self.dv("graph", "sync")
        hits = json.loads(self.dv("graph", "search", "auth", "-j").stdout)
        self.assertTrue(any(h.get("kind") == "decision" and h.get("id") == "dec-a" for h in hits))

    def test_impact_crosses_into_intent_links(self):
        self.dv("add-node", "--kind", "constraint", "--id", "con-a", "--title", "guarded fn",
                "--body", "r", "--applies", "src/**", "--forbid", "eval(", "--severity", "block")
        self.dv("link", "con-a", "src.handlers.save", "--relation", "constrains",
                "--path", "src/handlers.py", "--no-resolve")
        self.put("m.py", "x = 1\n")
        self.dv("graph", "sync")
        r = json.loads(self.dv("graph", "impact", "src.handlers.save", "-j").stdout)
        self.assertTrue(any(n["id"] == "con-a" for n in r["intent"]))

    def test_affected_maps_by_convention_with_provenance(self):
        self.put("src/util.py", "def add(a, b):\n    return a + b\n")
        self.put("tests/test_util.py", "import unittest\n")
        self.dv("graph", "sync")
        rows = json.loads(self.dv("graph", "affected", "src/util.py", "-j").stdout)
        self.assertEqual([(r["path"], r["via"]) for r in rows], [("tests/test_util.py", "convention")])
        rows = json.loads(self.dv("graph", "affected", "tests/test_util.py", "-j").stdout)
        self.assertEqual(rows[0]["via"], "self")

    def test_reannotate_replaces_search_row(self):
        # INSERT OR REPLACE only fires the search_idx DELETE trigger with
        # recursive_triggers=ON — without it, stale rows accumulate forever.
        self.put("m.py", "x = 1\n")
        self.dv("graph", "sync")
        self.dv("graph", "annotate", "--key", "m.py", "--type", "file", "--summary", "auth handling")
        self.dv("graph", "annotate", "--key", "m.py", "--type", "file", "--summary", "billing handling")
        hits = json.loads(self.dv("graph", "search", "auth", "-j").stdout)
        self.assertFalse(any(h.get("kind") == "annotation" for h in hits))
        import sqlite3
        n = sqlite3.connect(self.idx).execute(
            "SELECT COUNT(*) FROM search_idx WHERE target_key='m.py'").fetchone()[0]
        self.assertEqual(n, 1)

    def test_git_scan_survives_non_ascii_and_skips_devant(self):
        subprocess.run(["git", "init", "-q"], cwd=self.proj, capture_output=True)
        self.put("café.py", "x = 1\n")
        self.dv("graph", "sync")                    # creates .devant/index.db(+wal) mid-tree
        self.dv("graph", "sync")                    # second pass must not index devant's own state
        import sqlite3
        paths = [p for (p,) in sqlite3.connect(self.idx).execute("SELECT path FROM file").fetchall()]
        self.assertIn("café.py", paths)        # -z beats core.quotePath mangling
        self.assertFalse(any(p.startswith(".devant/") for p in paths))

    def test_node_history_journals_meta_downgrade(self):
        self.dv("add-node", "--kind", "constraint", "--id", "con-1", "--title", "t", "--body", "b",
                "--applies", "src/**", "--forbid", "eval(", "--severity", "block")
        self.dv("add-node", "--kind", "constraint", "--id", "con-1", "--title", "t", "--severity", "warn")
        self.dv("add-node", "--kind", "constraint", "--id", "con-1", "--title", "t", "--severity", "warn")
        import sqlite3
        rows = sqlite3.connect(self.db).execute(
            "SELECT meta FROM node_history WHERE node_id='con-1'").fetchall()
        self.assertEqual(len(rows), 1)              # downgrade journaled once; identical re-add is not
        self.assertIn("block", rows[0][0])          # the pre-downgrade meta is what's preserved

    def test_guard_hot_path_never_imports_heavy_modules(self):
        # Mirrors exactly what hooks/lib/guard_write.py + guard_bash.py touch. The devantlib
        # split exists so this stays true as graph/drawio code grows (dec-016).
        code = (
            "from importlib.machinery import SourceFileLoader\n"
            "from importlib.util import module_from_spec, spec_from_loader\n"
            "import sys\n"
            "spec = spec_from_loader('devant_mod', SourceFileLoader('devant_mod', %r))\n"
            "dv = module_from_spec(spec)\n"
            "spec.loader.exec_module(dv)\n"
            "dv.project_dir; dv.rel_to_project; dv.ensure_schema\n"
            "dv.evaluate_guard; dv.evaluate_bash\n"
            "bad = [m for m in ('devantlib.intent', 'devantlib.drawio', 'devantlib.graphdb',\n"
            "                   'devantlib.graphcmds', 'devantlib.cli') if m in sys.modules]\n"
            "print(','.join(bad) or 'CLEAN')\n"
        ) % BIN
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=self.env)
        self.assertEqual(r.stdout.strip(), "CLEAN", r.stdout + r.stderr)

    def test_resolver_never_binds_across_languages(self):
        # A JS `readConfig` calling a bare `load()` must not bind to a Python `load`:
        # a static call/inherit edge never crosses languages, so a cross-lang bind is
        # noise, not a low-confidence guess (dec-016 honest degradation; dec-032).
        self.put("py_mod.py", "def load():\n    return 1\n")
        self.put("js_mod.js", "function readConfig() {\n  return load();\n}\n")
        self.dv("graph", "sync")
        import sqlite3
        conn = sqlite3.connect(self.idx)
        conn.row_factory = sqlite3.Row
        crossed = conn.execute(
            "SELECT sf.lang AS src_lang, df.lang AS dst_lang, ref.dst_name FROM ref "
            "JOIN symbol ss ON ss.id = ref.src_symbol JOIN file sf ON sf.id = ss.file "
            "JOIN symbol ds ON ds.id = ref.dst_symbol JOIN file df ON df.id = ds.file "
            "WHERE ref.kind IN ('calls','inherits','implements') AND sf.lang != df.lang"
        ).fetchall()
        self.assertEqual([dict(r) for r in crossed], [])          # no edge crosses languages
        (js_load_dst,) = conn.execute(
            "SELECT ref.dst_symbol FROM ref "
            "JOIN symbol ss ON ss.id = ref.src_symbol JOIN file sf ON sf.id = ss.file "
            "WHERE sf.lang='javascript' AND ref.dst_name='load' AND ref.kind='calls'"
        ).fetchone()
        self.assertIsNone(js_load_dst)                            # left honestly unresolved


class BenchmarkGate(unittest.TestCase):
    """dec-016 cutover gate: the self-built extractor must hit the recall/precision
    floors in tests/fixtures/bench/thresholds.json on every language fixture before
    codegraph may be removed. Golden = expected.json next to each sample."""
    BENCH = os.path.join(ROOT, "tests", "fixtures", "bench")

    def _index(self, lang):
        src = os.path.join(self.BENCH, lang)
        sample = next(f for f in sorted(os.listdir(src)) if not f.endswith(".json"))
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        shutil.copy(os.path.join(src, sample), os.path.join(tmp.name, sample))
        idx = os.path.join(tmp.name, "index.db")
        env = dict(os.environ, CLAUDE_PROJECT_DIR=tmp.name, DEVANT_CODEGRAPH="off")
        r = subprocess.run([sys.executable, BIN, "--index-db", idx, "graph", "sync"],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        import sqlite3
        conn = sqlite3.connect(idx)
        conn.row_factory = sqlite3.Row
        qual = {}
        for s2 in conn.execute("SELECT id, qualname, kind, name FROM symbol").fetchall():
            qual[s2["id"]] = s2["name"] if s2["kind"] == "module" else s2["qualname"]
        syms = {(s2["qualname"], s2["kind"]) for s2 in conn.execute(
            "SELECT qualname, kind FROM symbol WHERE kind!='module'").fetchall()}
        refs = [{"src": qual[r2["src_symbol"]],
                 "dst_qual": qual.get(r2["dst_symbol"]), "dst_name": r2["dst_name"],
                 "kind": r2["kind"]}
                for r2 in conn.execute("SELECT * FROM ref").fetchall()]
        return syms, refs

    def _gate(self, lang):
        exp = json.load(open(os.path.join(self.BENCH, lang, "expected.json")))
        th = json.load(open(os.path.join(self.BENCH, "thresholds.json")))
        syms, refs = self._index(lang)
        want_syms = {(s["qualname"], s["kind"]) for s in exp["symbols"]}
        hit = want_syms & syms
        s_recall = len(hit) / len(want_syms)
        s_prec = len(hit) / len(syms) if syms else 0
        self.assertGreaterEqual(s_recall, th["symbols"]["recall"],
                                "%s symbol recall: missing %s" % (lang, want_syms - syms))
        self.assertGreaterEqual(s_prec, th["symbols"]["precision"],
                                "%s symbol precision: extra %s" % (lang, syms - want_syms))

        def matches(e, g):
            if e["src"] != g["src"] or e["kind"] != g["kind"]:
                return False
            want = e.get("dst") or e.get("dst_name")
            return want in (g["dst_qual"], g["dst_name"])

        want_refs = exp["refs"]
        matched = [e for e in want_refs if any(matches(e, g) for g in refs)]
        r_recall = len(matched) / len(want_refs)
        # precision over refs the extractor CLAIMS are meaningful: resolved targets,
        # qualified externals, imports and inherits — bare unresolved names are excluded
        # (they're honest "references by text", not asserted edges).
        claimed = [g for g in refs if g["kind"] != "contains" and (
            g["dst_qual"] or "." in (g["dst_name"] or "") or "/" in (g["dst_name"] or "")
            or g["kind"] in ("imports", "inherits"))]
        good = [g for g in claimed if any(matches(e, g) for e in want_refs)]
        r_prec = len(good) / len(claimed) if claimed else 1.0
        self.assertGreaterEqual(r_recall, th["calls"]["recall"],
                                "%s ref recall: missing %s" % (
                                    lang, [e for e in want_refs if e not in matched]))
        self.assertGreaterEqual(r_prec, th["calls"]["precision"],
                                "%s ref precision: extra %s" % (
                                    lang, [g for g in claimed if g not in good]))

    def test_python_gate(self):
        self._gate("python")

    def test_javascript_gate(self):
        self._gate("javascript")

    def test_go_gate(self):
        self._gate("go")

    def test_decay_contract_incremental_equals_full(self):
        # dec-016 gap 1 + review H1/H2: N incremental syncs must equal one fresh full
        # scan INCLUDING resolved bindings — dangling/mis-bound dst_symbol after an
        # in-place rename or a callee-file deletion must show up here.
        with tempfile.TemporaryDirectory() as proj:
            env = dict(os.environ, CLAUDE_PROJECT_DIR=proj, DEVANT_CODEGRAPH="off")

            def w(name, body):
                with open(os.path.join(proj, name), "w") as fh:
                    fh.write(body)

            def sync(idx):
                subprocess.run([sys.executable, BIN, "--index-db", idx, "graph", "sync"],
                               capture_output=True, env=env)

            def dump(idx):
                import sqlite3
                conn = sqlite3.connect(idx)
                conn.row_factory = sqlite3.Row
                qual = {s["id"]: (s["name"] if s["kind"] == "module" else s["qualname"])
                        for s in conn.execute("SELECT id,qualname,kind,name FROM symbol")}
                syms = {(r["qualname"], r["kind"]) for r in conn.execute(
                    "SELECT qualname,kind FROM symbol").fetchall()}
                refs = {(qual[r["src_symbol"]], r["dst_name"], r["kind"],
                         qual.get(r["dst_symbol"]))                    # resolved target or None
                        for r in conn.execute("SELECT * FROM ref").fetchall()}
                return syms, refs

            inc = os.path.join(proj, "inc.db")
            w("b.py", "def f():\n    return 1\n")
            w("a.py", "import b\n\ndef g():\n    return b.f()\n")
            sync(inc)
            w("b.py", "def f2():\n    return 2\n")                    # in-place RENAME (H1)
            sync(inc)
            w("c.py", "import b\n\ndef k():\n    return b.f2()\n")   # new caller
            sync(inc)
            os.remove(os.path.join(proj, "b.py"))                       # CALLEE deleted (H2)
            sync(inc)
            full = os.path.join(proj, "full.db")
            sync(full)
            self.assertEqual(dump(inc), dump(full))

    def test_hostile_file_degrades_to_per_file_error(self):
        # review H3: one broken notebook must not abort the sync or block the index.
        with tempfile.TemporaryDirectory() as proj:
            env = dict(os.environ, CLAUDE_PROJECT_DIR=proj, DEVANT_CODEGRAPH="off")
            with open(os.path.join(proj, "ok.py"), "w") as fh:
                fh.write("def fine():\n    return 1\n")
            with open(os.path.join(proj, "evil.ipynb"), "w") as fh:
                fh.write(json.dumps({"cells": [{"cell_type": "code", "source": 123}]}))
            idx = os.path.join(proj, "index.db")
            r = subprocess.run([sys.executable, BIN, "--index-db", idx, "graph", "sync", "-j"],
                               capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            import sqlite3
            conn = sqlite3.connect(idx)
            conn.row_factory = sqlite3.Row
            rows = {x["path"]: x["status"] for x in conn.execute("SELECT path,status FROM file")}
            self.assertEqual(rows.get("ok.py"), "ok")                   # the rest indexed fine
            self.assertIn(rows.get("evil.ipynb"), ("ok", "error"))      # never aborts

    def test_python_from_import_is_not_a_sql_table(self):
        # review M3: `from collections import x` must not fabricate resource coupling.
        with tempfile.TemporaryDirectory() as proj:
            env = dict(os.environ, CLAUDE_PROJECT_DIR=proj, DEVANT_CODEGRAPH="off")
            with open(os.path.join(proj, "m.py"), "w") as fh:
                fh.write("from collections import OrderedDict\n\ndef f():\n    return OrderedDict()\n")
            idx = os.path.join(proj, "index.db")
            subprocess.run([sys.executable, BIN, "--index-db", idx, "graph", "sync"],
                           capture_output=True, env=env)
            import sqlite3
            rows = sqlite3.connect(idx).execute(
                "SELECT name FROM resource WHERE kind='sql_table'").fetchall()
            self.assertEqual(rows, [])

    def test_prose_in_string_is_not_a_sql_table(self):
        # "update stats from cache" is English, not SQL — it must not fabricate table resources
        # (the false coupling that poisons `graph impact`).
        with tempfile.TemporaryDirectory() as proj:
            env = dict(os.environ, CLAUDE_PROJECT_DIR=proj, DEVANT_CODEGRAPH="off")
            with open(os.path.join(proj, "m.py"), "w") as fh:
                fh.write('import logging\nlog = logging.getLogger(__name__)\n\n'
                         'def f():\n    log.info("update stats from cache now")\n')
            idx = os.path.join(proj, "index.db")
            subprocess.run([sys.executable, BIN, "--index-db", idx, "graph", "sync"],
                           capture_output=True, env=env)
            import sqlite3
            rows = sqlite3.connect(idx).execute(
                "SELECT name FROM resource WHERE kind='sql_table'").fetchall()
            self.assertEqual(rows, [])

    def test_multiline_sql_string_yields_tables(self):
        # a real multi-line query must still resolve its tables (the false-negative the old
        # line-by-line scan produced).
        with tempfile.TemporaryDirectory() as proj:
            env = dict(os.environ, CLAUDE_PROJECT_DIR=proj, DEVANT_CODEGRAPH="off")
            with open(os.path.join(proj, "q.py"), "w") as fh:
                fh.write('def load():\n    return db.query(\n        """\n'
                         '        SELECT id\n        FROM orders\n'
                         '        JOIN users ON users.id = orders.user_id\n'
                         '        """\n    )\n')
            idx = os.path.join(proj, "index.db")
            subprocess.run([sys.executable, BIN, "--index-db", idx, "graph", "sync"],
                           capture_output=True, env=env)
            import sqlite3
            names = {n for (n,) in sqlite3.connect(idx).execute(
                "SELECT name FROM resource WHERE kind='sql_table'").fetchall()}
            self.assertIn("orders", names)
            self.assertIn("users", names)


class DeclTierExtraction(unittest.TestCase):
    """Regression guard for the shipped-but-hollow decl-tier bug: _extract_generic
    referenced an unbound `lineof`, so every non-py/js/go language raised NameError
    and was silently recorded as a 0-symbol parse error. Iterate EVERY declared
    language so no future addition can go hollow undetected."""
    SNIPPETS = {
        "java": "public class Foo {}\nimport java.util.List;\n",
        "kotlin": "class Foo\nfun bar() {}\n",
        "csharp": "public class Foo {}\nusing System.Text;\n",
        "ruby": "class Foo\n  def bar; end\nend\n",
        "rust": "pub struct Foo;\nfn bar() {}\n",
        "php": "<?php\nclass Foo {}\nfunction bar() {}\n",
        "c": "#include <stdio.h>\nint bar(void) { return 0; }\n",
        "cpp": "class Foo {};\n#include <vector>\n",
        "swift": "public class Foo {}\nfunc bar() {}\n",
        "shell": "bar() {\n  echo hi\n}\n",
    }

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(ROOT, "bin"))
        from devantlib import extract
        cls.extract = extract

    def test_every_decl_tier_language_extracts(self):
        for lang in self.extract._GENERIC_DECLS:
            with self.subTest(lang=lang):
                self.assertIn(lang, self.SNIPPETS,
                              "declared lang %s has no coverage snippet" % lang)
                out = self.extract._extract_generic(self.SNIPPETS[lang], lang)
                self.assertTrue(out["symbols"] or out["refs"],
                                "%s extracted nothing (hollow tier)" % lang)


class GraphSemantics(unittest.TestCase):
    """P2/P3 (dec-016): resource co-reference impact, container formats, hot ranking,
    concept traversal, and lint link-suggestions — the racing-wheel pair."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = self.tmp.name
        self.db = os.path.join(self.proj, ".devant", "intent.db")
        self.idx = os.path.join(self.proj, ".devant", "index.db")
        self.env = dict(os.environ, CLAUDE_PROJECT_DIR=self.proj)
        self.env.pop("DEVANT_CODEGRAPH", None)   # graph lifecycle ON for these tests

    def tearDown(self):
        self.tmp.cleanup()

    def dv(self, *args):
        return subprocess.run([sys.executable, BIN, "--db", self.db, "--index-db", self.idx, *args],
                              capture_output=True, text=True, env=self.env)

    def put(self, rel, content):
        p = os.path.join(self.proj, rel)
        d = os.path.dirname(p)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(p, "w") as fh:
            fh.write(content)

    def test_impact_crosses_shared_resources(self):
        self.put("a.py", 'import os\n\ndef f():\n    return os.environ["API_KEY"]\n')
        self.put("b.py", 'import os\n\ndef g():\n    return os.environ["API_KEY"]\n')
        self.dv("graph", "sync")
        r = json.loads(self.dv("graph", "impact", "f", "-j").stdout)
        hit = [s for s in r["symbols"] if s["qualname"] == "g"]
        self.assertTrue(hit and hit[0]["via"].startswith("resource:env:API_KEY"), r)

    def test_sync_records_size_and_stale_index_tracks_head(self):
        def git(*a):
            subprocess.run(["git", *a], cwd=self.proj, capture_output=True, text=True, env=self.env)
        git("init", "-q")
        git("config", "user.email", "t@t")
        git("config", "user.name", "t")
        git("config", "commit.gpgsign", "false")
        self.dv("add-node", "--kind", "note", "--title", "seed")   # so intent.db exists for dangling
        self.put("m.py", "def f():\n    return 1\n")
        git("add", "-A")
        git("commit", "-q", "-m", "seed")
        self.dv("graph", "sync")
        import sqlite3
        sizes = [s for (s,) in sqlite3.connect(self.idx).execute("SELECT size FROM file").fetchall()]
        self.assertTrue(sizes and all(s is not None for s in sizes))    # fast-path column populated
        self.assertFalse(json.loads(self.dv("dangling", "-j").stdout)["stale_index"])  # synced at HEAD
        self.put("n.py", "y = 2\n")
        git("add", "-A")
        git("commit", "-q", "-m", "more")                              # HEAD moves, no resync
        self.assertTrue(json.loads(self.dv("dangling", "-j").stdout)["stale_index"])   # STALE now
        self.dv("graph", "sync")
        self.assertFalse(json.loads(self.dv("dangling", "-j").stdout)["stale_index"])  # resync clears it

    def test_vue_script_block_is_extracted(self):
        self.put("w.vue", "<template><div/></template>\n<script>\nexport function hi() { return 1 }\n</script>\n")
        self.dv("graph", "sync")
        hits = json.loads(self.dv("graph", "search", "hi", "-j").stdout)
        self.assertTrue(any(h.get("kind") == "symbol" and h["qualname"] == "hi" for h in hits), hits)

    def test_hot_ranks_by_in_degree(self):
        self.put("lib.py", "def core():\n    return 1\n")
        self.put("u1.py", "import lib\n\ndef a():\n    return lib.core()\n")
        self.put("u2.py", "import lib\n\ndef b():\n    return lib.core()\n")
        self.dv("graph", "sync")
        top = json.loads(self.dv("graph", "hot", "-j").stdout)[0]
        self.assertEqual((top["qualname"], top["in_degree"]), ("core", 2))

    def test_semantic_impact_via_shared_concept(self):
        self.put("a.py", "def f():\n    return 1\n")
        self.put("b.py", "def g():\n    return 2\n")
        self.dv("graph", "sync")
        keys = {d["qualname"]: d["key"] for d in json.loads(self.dv("graph", "hot", "-j").stdout)}
        self.dv("graph", "annotate", "--key", keys["f"], "--type", "symbol",
                "--summary", "auth entry", "--concepts", "auth")
        self.dv("graph", "annotate", "--key", keys["g"], "--type", "symbol",
                "--summary", "auth helper", "--concepts", "auth")
        r = json.loads(self.dv("graph", "impact", "f", "--semantic", "-j").stdout)
        self.assertTrue(any(s["via"] == "concept:auth" for s in r["symbols"]), r)
        r0 = json.loads(self.dv("graph", "impact", "f", "-j").stdout)
        self.assertFalse(any(s["via"].startswith("concept:") for s in r0["symbols"]))  # opt-in only

    def test_lint_suggests_missing_code_links(self):
        self.put("mod.py", "def evaluate_thing():\n    return 1\n")
        self.dv("graph", "sync")
        self.dv("decide", "--id", "dec-x", "--title", "Harden evaluate_thing",
                "--body", "evaluate_thing must stay pure")
        rep = json.loads(self.dv("lint", "-j").stdout)
        self.assertIn({"node": "dec-x", "symbol": "evaluate_thing"}, rep["link_suggestions"])
        self.dv("link", "dec-x", "evaluate_thing", "--relation", "governs")   # resolves via graph
        rep = json.loads(self.dv("lint", "-j").stdout)
        self.assertNotIn({"node": "dec-x", "symbol": "evaluate_thing"}, rep["link_suggestions"])

    def test_status_surfaces_parse_errors(self):
        # dec-028: a file the extractor failed on (status='error', 0 symbols) must not hide
        # behind the totals — `graph status` surfaces the count, the paths, and a text warning.
        self.put("ok.py", "def f():\n    return 1\n")
        self.dv("graph", "sync")
        import sqlite3
        conn = sqlite3.connect(self.idx)
        conn.execute("UPDATE file SET status='error', error='boom' WHERE path='ok.py'")
        conn.commit()
        conn.close()
        rep = json.loads(self.dv("graph", "status", "-j").stdout)
        self.assertEqual(rep["parse_errors"], 1)
        self.assertEqual(rep["error_files"], ["ok.py"])
        txt = self.dv("graph", "status").stdout
        self.assertIn("failed to extract", txt)
        self.assertIn("ok.py", txt)


class PhaseAndCompactGate(unittest.TestCase):
    """Smart compaction scheduler (dec-018): `devant phase`, the PreCompact gate, and the
    context monitor's math."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = self.tmp.name
        self.state = os.path.join(self.proj, ".devant", "state")
        os.makedirs(self.state, exist_ok=True)
        self.env = dict(os.environ, CLAUDE_PLUGIN_ROOT=ROOT,
                        CLAUDE_PROJECT_DIR=self.proj, DEVANT_CODEGRAPH="off",
                        CLAUDE_CODE_SESSION_ID="pc")

    def tearDown(self):
        self.tmp.cleanup()

    def dv(self, *args):
        return subprocess.run([sys.executable, BIN, *args],
                              capture_output=True, text=True, env=self.env)

    def set_state(self, gate=None, pct=None, pct_age_min=0):
        if gate is not None:
            with open(os.path.join(self.state, "phase"), "w") as fh:
                json.dump({"text": "building the sync engine", "gate": gate, "ts": "t"}, fh)
        if pct is not None:
            p = os.path.join(self.state, "context.pct")
            with open(p, "w") as fh:
                fh.write(str(pct))
            if pct_age_min:
                import time
                old = time.time() - pct_age_min * 60
                os.utime(p, (old, old))

    def gate(self, trigger):
        r = subprocess.run(["bash", os.path.join(ROOT, "hooks", "lib", "pre-compact.sh")],
                           input=json.dumps({"cwd": self.proj, "session_id": "pc",
                                             "trigger": trigger}),
                           capture_output=True, text=True, env=self.env)
        out = r.stdout.strip()
        return json.loads(out)["decision"] if out else "allow"

    def test_phase_set_get_roundtrip(self):
        self.assertEqual(self.dv("phase", "--set", "designing", "--hold").stdout.strip(), "hold")
        d = json.loads(self.dv("phase", "-j").stdout)
        self.assertEqual((d["text"], d["gate"]), ("designing", "hold"))
        self.assertEqual(self.dv("phase", "--set", "design-locked").stdout.strip(), "open")
        self.assertEqual(json.loads(self.dv("phase", "-j").stdout)["gate"], "open")

    def test_goal_set_get_clear_roundtrip(self):
        self.assertEqual(self.dv("goal", "--set", "repro passes; suite green").stdout.strip(), "set")
        self.assertEqual(self.dv("goal").stdout.strip(), "repro passes; suite green")
        self.assertEqual(json.loads(self.dv("goal", "-j").stdout)["text"], "repro passes; suite green")
        self.dv("goal", "--clear")
        self.assertEqual(self.dv("goal").stdout.strip(), "no goal recorded.")

    def test_gate_defers_auto_compact_mid_phase(self):
        self.set_state(gate="hold", pct=60)
        self.assertEqual(self.gate("auto"), "block")

    def test_gate_never_blocks_manual_or_boundary_or_high(self):
        self.set_state(gate="hold", pct=60)
        self.assertEqual(self.gate("manual"), "allow")     # user /compact always passes
        self.set_state(gate="open", pct=60)
        self.assertEqual(self.gate("auto"), "allow")       # phase boundary -> land it
        self.set_state(gate="hold", pct=90)
        self.assertEqual(self.gate("auto"), "allow")       # >=85: never veto near the limit

    def test_gate_fails_open_without_fresh_signal(self):
        self.set_state(gate="hold")                        # no pct file at all
        self.assertEqual(self.gate("auto"), "allow")
        self.set_state(gate="hold", pct=60, pct_age_min=10)  # stale signal
        self.assertEqual(self.gate("auto"), "allow")

    def test_gate_clears_primed_marker_on_both_paths(self):
        primed = os.path.join(self.state, "pc.primed")
        open(primed, "w").close()
        self.gate("manual")
        self.assertFalse(os.path.exists(primed))

    def test_monitor_math(self):
        from importlib.machinery import SourceFileLoader as SFL
        from importlib.util import module_from_spec as MFS, spec_from_loader as SFLo
        spec = SFLo("ctxmon", SFL("ctxmon", os.path.join(ROOT, "hooks", "lib", "context_monitor.py")))
        mon = MFS(spec)
        spec.loader.exec_module(mon)
        self.assertEqual(mon.pct(300000, 500000), 60)
        self.assertEqual(mon.pct(999999, 500000), 100)     # capped
        t = os.path.join(self.proj, "t.jsonl")
        with open(t, "w") as fh:
            fh.write(json.dumps({"type": "user", "message": {"role": "user"}}) + "\n")
            fh.write(json.dumps({"type": "assistant", "message": {"usage": {
                "input_tokens": 1000, "cache_read_input_tokens": 2000,
                "cache_creation_input_tokens": 500, "output_tokens": 50}}}) + "\n")
            fh.write("not json\n")
        self.assertEqual(mon.last_usage_tokens(t), 3500)
        self.assertEqual(mon.zone(60, 50, "hold"), "pending")
        self.assertEqual(mon.zone(60, 50, "open"), "low")
        self.assertEqual(mon.zone(40, 50, "hold"), "low")
        self.assertEqual(mon.zone(90, 50, "open"), "high")

    def test_monitor_ignores_transcript_untouched_since_start(self):
        # Startup race repro: at session start the newest transcript by mtime (and even a
        # stale transcript.path) is the PREVIOUS session's, ending near the window limit —
        # trusting it fired a false "compaction imminent" on the first poll.
        from importlib.machinery import SourceFileLoader as SFL
        from importlib.util import module_from_spec as MFS, spec_from_loader as SFLo
        spec = SFLo("ctxmon2", SFL("ctxmon2", os.path.join(ROOT, "hooks", "lib", "context_monitor.py")))
        mon = MFS(spec)
        spec.loader.exec_module(mon)
        import time
        tdir = os.path.join(self.proj, "transcripts")
        os.makedirs(tdir)
        prev = os.path.join(tdir, "prev.jsonl")
        with open(prev, "w") as fh:
            fh.write(json.dumps({"message": {"usage": {"input_tokens": 490000}}}) + "\n")
        old = time.time() - 60
        os.utime(prev, (old, old))
        start = time.time()
        self.assertIsNone(mon.usable_transcript(self.state, tdir, start))
        cur = os.path.join(tdir, "cur.jsonl")
        with open(cur, "w") as fh:
            fh.write(json.dumps({"message": {"usage": {"input_tokens": 1000}}}) + "\n")
        os.utime(cur, (start + 1, start + 1))   # mtime granularity can lag time.time()
        self.assertEqual(mon.usable_transcript(self.state, tdir, start), cur)


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

    def lint(self, path, fix=False, score=False):
        args = ([sys.executable, BIN, "drawio-lint", path]
                + (["--fix"] if fix else []) + (["--score"] if score else []))
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

    def test_fix_recentres_off_centre_final_node_core(self):
        # the real defect: a final-node core left 5px off-centre inside its ring (from grid-snapping
        # the ring alone) reads as a crooked bullseye. --fix must snap the core exactly concentric.
        ring = self.vertex("ring", 140, 1200, 30, 30, "ellipse;")   # centre 155,1215
        core = self.vertex("core", 142, 1207, 16, 16, "ellipse;")   # centre 150,1215 — 5px off
        p = self.write(self._model(ring + core))
        self.assertIn("off-centre", self.lint(p).stdout)            # reported, not silently "clean"
        r = self.lint(p, fix=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("re-centred", r.stdout)
        import xml.etree.ElementTree as ET
        g = {c.get("id"): c.find("mxGeometry")
             for c in ET.parse(p).getroot().findall(".//mxCell[@vertex='1']")}
        rx, ry = float(g["ring"].get("x")), float(g["ring"].get("y"))
        cx, cy = float(g["core"].get("x")), float(g["core"].get("y"))
        self.assertEqual((rx + 30 / 2, ry + 30 / 2), (cx + 16 / 2, cy + 16 / 2))  # concentric now
        self.assertEqual(self.lint(p).returncode, 0)               # idempotent, stays clean

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

    def test_fontsize_scales_vertex_label_estimate(self):
        # The gate must measure a label at its declared fontSize, not a hardcoded 12px. This label
        # fits inside its 200px node at 12px but at 15px is 25% wider — it spills and lands on
        # sibling b. 30 same-width glyphs keep the width estimate exact.
        def deck(px):
            a = ('<mxCell id="a" value="%s" style="rounded=1;fontSize=%d;" vertex="1" parent="1">'
                 '<mxGeometry x="100" y="100" width="200" height="70" as="geometry" /></mxCell>'
                 % ("n" * 30, px))
            return self._model(a + self.vertex("b", 310, 100, 160, 70))
        self.assertEqual(self.lint(self.write(deck(12))).returncode, 0)       # fits at 12px
        r = self.lint(self.write(deck(15)))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)                # spills at 15px
        self.assertIn("labels colliding", r.stdout)
        self.assertIn("a->b", r.stdout)

    def test_fontsize_scales_edge_label_estimate(self):
        # Same fix, the separate edge-label path: this edge label clears bystander c at 12px but
        # overruns it at 15px.
        def deck(px):
            edge = ('<mxCell id="e" value="%s" style="edgeStyle=orthogonalEdgeStyle;rounded=0;'
                    'fontSize=%d;" edge="1" parent="1" source="a" target="b">'
                    '<mxGeometry relative="1" as="geometry" /></mxCell>' % ("n" * 30, px))
            cells = (self.vertex("a", 100, 100, 160, 70) + self.vertex("b", 100, 300, 160, 70)
                     + self.vertex("c", 290, 210, 100, 70) + edge)
            return self._model(cells)
        self.assertEqual(self.lint(self.write(deck(12))).returncode, 0)       # clears c at 12px
        r = self.lint(self.write(deck(15)))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)                # overruns c at 15px
        self.assertIn("labels colliding", r.stdout)
        self.assertIn("e->c", r.stdout)

    def wp_edge(self, i, src, tgt, points):
        pts = "".join('<mxPoint x="%s" y="%s" />' % p for p in points)
        return ('<mxCell id="%s" style="edgeStyle=orthogonalEdgeStyle;rounded=0;" edge="1" '
                'parent="1" source="%s" target="%s"><mxGeometry relative="1" as="geometry">'
                '<Array as="points">%s</Array></mxGeometry></mxCell>' % (i, src, tgt, pts))

    def test_waypointed_edge_through_bystander_warns_not_blocks(self):
        # a->b hand-routed straight through bystander c: a warning, never a gate failure
        cells = (self.vertex("a", 100, 100) + self.vertex("b", 100, 500)
                 + self.vertex("c", 100, 300) + self.wp_edge("e", "a", "b", [(180, 335)]))
        r = self.lint(self.write(self._model(cells)))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("routes through", r.stdout)
        self.assertIn("e->c", r.stdout)

    def test_crossing_waypointed_edges_warn_and_score(self):
        # two hand-routed edges form an X between four corner nodes
        cells = (self.vertex("n1", 100, 100) + self.vertex("n2", 500, 100)
                 + self.vertex("n3", 100, 300) + self.vertex("n4", 500, 300)
                 + self.wp_edge("e1", "n1", "n4", [(340, 200)])
                 + self.wp_edge("e2", "n3", "n2", [(340, 270)]))
        r = self.lint(self.write(self._model(cells)), score=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("edges cross", r.stdout)
        self.assertIn("e1<->e2", r.stdout)
        self.assertIn("score: 10", r.stdout)                              # one crossing = 10

    def test_edge_under_text_label_is_not_a_bystander_warning(self):
        # the common "edge label as its own text cell" pattern: a standalone text element sits on
        # the edge path. It draws no box, so the edge meeting its own label must not warn (dec-021).
        cells = (self.vertex("a", 100, 100) + self.vertex("b", 100, 500)
                 + self.vertex("c", 100, 300, style="text;html=1;align=center;")
                 + self.wp_edge("e", "a", "b", [(180, 335)]))
        r = self.lint(self.write(self._model(cells)))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("routes through", r.stdout)

    def test_autorouted_edge_never_gets_routing_warnings(self):
        # same a-over-c-to-b geometry but NO waypoints: the path isn't stored, so no guessing
        edge = ('<mxCell id="e" style="edgeStyle=orthogonalEdgeStyle;rounded=0;" edge="1" '
                'parent="1" source="a" target="b"><mxGeometry relative="1" as="geometry" /></mxCell>')
        cells = (self.vertex("a", 100, 100) + self.vertex("b", 100, 500)
                 + self.vertex("c", 100, 300) + edge)
        r = self.lint(self.write(self._model(cells)), score=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("routes through", r.stdout)
        self.assertIn("score: 0", r.stdout)


class DiagramBuild(unittest.TestCase):
    """dec-041: compact spec -> styled graph -> hardened ELK. Validation fails loud with named
    errors (no node/elkjs needed); the golden fixture is the real branchy 2-loop debate flow —
    lint exit 0 IS the geometry assertion, plus narrative-order checks (no XML snapshots)."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, spec, out=None):
        p = os.path.join(self.tmp.name, "spec.json")
        with open(p, "w") as fh:
            json.dump(spec, fh)
        args = [sys.executable, BIN, "diagram-build", p]
        if out:
            args += ["-o", out]
        return subprocess.run(args, capture_output=True, text=True)

    def spine(self):
        return {"kind": "activity", "title": "t",
                "nodes": [{"id": "start", "type": "start"},
                          {"id": "a", "type": "action", "label": "Do a"},
                          {"id": "end", "type": "end"}],
                "edges": [{"from": "start", "to": "a"}, {"from": "a", "to": "end"}]}

    def test_unknown_kind_fails_loud(self):
        r = self.build({"kind": "sequence", "title": "t", "nodes": [{"id": "a", "type": "action",
                                                                     "label": "x"}]})
        self.assertEqual(r.returncode, 1)
        self.assertIn("unknown kind 'sequence'", r.stderr)

    def test_missing_label_names_the_node_and_field(self):
        s = self.spine()
        del s["nodes"][1]["label"]
        r = self.build(s)
        self.assertEqual(r.returncode, 1)
        self.assertIn("node 'a'", r.stderr)
        self.assertIn("'label'", r.stderr)

    def test_type_invalid_for_kind_lists_allowed(self):
        s = self.spine()
        s["nodes"][1]["type"] = "container"  # a c4 type in an activity diagram
        r = self.build(s)
        self.assertEqual(r.returncode, 1)
        self.assertIn("not valid for kind 'activity'", r.stderr)
        self.assertIn("decision", r.stderr)

    def test_decision_branch_without_guard_fails(self):
        s = self.spine()
        s["nodes"].insert(2, {"id": "d", "type": "decision", "label": "OK?"})
        s["edges"] = [{"from": "start", "to": "a"}, {"from": "a", "to": "d"},
                      {"from": "d", "to": "end"}]
        r = self.build(s)
        self.assertEqual(r.returncode, 1)
        self.assertIn("leaving a decision needs its guard", r.stderr)

    def test_loop_edge_without_label_fails(self):
        s = self.spine()
        s["edges"].append({"from": "a", "to": "a", "loop": True})
        r = self.build(s)
        self.assertEqual(r.returncode, 1)
        self.assertIn("loop edge needs its repeat guard", r.stderr)

    def test_undeclared_cycle_names_it_and_hints_loop(self):
        s = self.spine()
        s["nodes"].insert(2, {"id": "b", "type": "action", "label": "Do b"})
        s["edges"] = [{"from": "start", "to": "a"}, {"from": "a", "to": "b"},
                      {"from": "b", "to": "a"}, {"from": "b", "to": "end"}]
        r = self.build(s)
        self.assertEqual(r.returncode, 1)
        self.assertIn("cycle among non-loop edges", r.stderr)
        self.assertIn("a -> b -> a", r.stderr)
        self.assertIn("loop:true", r.stderr)

    DEBATE_SPEC = {
        "kind": "activity", "title": "Design debate flow",
        "nodes": [
            {"id": "start", "type": "start"},
            {"id": "route", "type": "action", "label": "Route request",
             "note": "router: ground + push back"},
            {"id": "design", "type": "action", "label": "Draft design",
             "note": "architect: current vs proposed"},
            {"id": "debate", "type": "action", "label": "Re-ground independently",
             "note": "debate: fork, read-only"},
            {"id": "web", "type": "decision", "label": "Web reachable?"},
            {"id": "hypo", "type": "external", "label": "Tag unverified claims",
             "note": "hypothesis label, no block"},
            {"id": "chal", "type": "action", "label": "Emit challenges",
             "note": "lens + question + evidence"},
            {"id": "subst", "type": "decision", "label": "Substantive challenges?"},
            {"id": "answer", "type": "action", "label": "Answer with evidence",
             "note": "architect: concede or defend"},
            {"id": "accept", "type": "decision", "label": "Both sides accept?"},
            {"id": "rounds", "type": "decision", "label": "Round below 3?"},
            {"id": "open", "type": "action", "label": "Crystallize open items",
             "note": "for user decision"},
            {"id": "gate", "type": "action", "label": "Present approval gate",
             "note": "conceded / defended / open"},
            {"id": "appr", "type": "decision", "label": "User approves?"},
            {"id": "impl", "type": "success", "label": "Implement",
             "note": "diagram + devant:code"},
            {"id": "end", "type": "end"},
        ],
        "edges": [
            {"from": "start", "to": "route"}, {"from": "route", "to": "design"},
            {"from": "design", "to": "debate", "label": "always, no size gate"},
            {"from": "debate", "to": "web"},
            {"from": "web", "to": "hypo", "label": "[offline]"},
            {"from": "web", "to": "chal", "label": "[online]"},
            {"from": "hypo", "to": "chal"}, {"from": "chal", "to": "subst"},
            {"from": "subst", "to": "answer", "label": "[yes]"},
            {"from": "subst", "to": "gate", "label": "[none]"},
            {"from": "answer", "to": "accept"},
            {"from": "accept", "to": "gate", "label": "[yes]"},
            {"from": "accept", "to": "rounds", "label": "[no]"},
            {"from": "rounds", "to": "chal", "label": "[next round]", "loop": True},
            {"from": "rounds", "to": "open", "label": "[cap hit]"},
            {"from": "open", "to": "gate"}, {"from": "gate", "to": "appr"},
            {"from": "appr", "to": "impl", "label": "[yes]"},
            {"from": "appr", "to": "design", "label": "[rework]", "loop": True},
            {"from": "impl", "to": "end"},
        ],
    }

    def test_golden_two_loop_flow_builds_lint_clean_in_narrative_order(self):
        out = os.path.join(self.tmp.name, "flow.drawio")
        r = self.build(self.DEBATE_SPEC, out=out)
        if r.returncode == 1 and ("node not found" in r.stderr or "elkjs not found" in r.stderr):
            self.skipTest("node/elkjs unavailable")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("clean.", r.stdout)                          # the built-in lint gate passed
        import xml.etree.ElementTree as ET
        root = ET.parse(out).getroot()
        y = {c.get("id"): float(c.find("mxGeometry").get("y"))
             for c in root.iter("mxCell")
             if c.get("vertex") == "1" and c.find("mxGeometry") is not None
             and c.find("mxGeometry").get("y")}
        spine = ["start", "route", "design", "debate", "web", "chal", "subst", "answer",
                 "accept", "rounds", "gate", "appr", "impl", "end"]
        for above, below in zip(spine, spine[1:]):                 # narrative order held, not
            self.assertLess(y[above], y[below],                    # scrambled by cycle breaking
                            "%s (y=%s) should sit above %s (y=%s)"
                            % (above, y[above], below, y[below]))
        edges = {c.get("id"): c for c in root.iter("mxCell") if c.get("edge") == "1"}
        loops = [c for c in edges.values() if "jumpStyle=arc" in (c.get("style") or "")]
        self.assertEqual({(c.get("source"), c.get("target")) for c in loops},
                         {("rounds", "chal"), ("appr", "design")})  # drawn in true direction
        self.assertEqual(self.lint(out).returncode, 0)              # independent lint agrees
        lx = float(next(c for c in root.iter("mxCell") if c.get("id") == "legend")
                   .find("mxGeometry").get("x"))
        flow_right = max(float(c.find("mxGeometry").get("x", "0"))
                         + float(c.find("mxGeometry").get("width", "0"))
                         for c in root.iter("mxCell")
                         if c.get("vertex") == "1" and c.get("id") != "legend"
                         and c.find("mxGeometry") is not None and c.find("mxGeometry").get("x"))
        self.assertGreaterEqual(lx, flow_right)                     # legend outside the flow bbox

    def lint(self, path):
        return subprocess.run([sys.executable, BIN, "drawio-lint", path],
                              capture_output=True, text=True)

    def test_layout_leaves_edgeless_legend_in_place(self):
        # dec-041: a legend fed to ELK gets dragged into a layer; layout must exclude it
        xml = ('<mxfile host="devant"><diagram name="t" id="t"><mxGraphModel gridSize="10">'
               '<root><mxCell id="0" /><mxCell id="1" parent="0" />'
               '<mxCell id="a" value="a" style="rounded=1;" vertex="1" parent="1">'
               '<mxGeometry x="100" y="100" width="160" height="70" as="geometry" /></mxCell>'
               '<mxCell id="b" value="b" style="rounded=1;" vertex="1" parent="1">'
               '<mxGeometry x="100" y="300" width="160" height="70" as="geometry" /></mxCell>'
               '<mxCell id="legend" value="Legend" style="rounded=0;" vertex="1" parent="1">'
               '<mxGeometry x="700" y="40" width="200" height="100" as="geometry" /></mxCell>'
               '<mxCell id="e" style="edgeStyle=orthogonalEdgeStyle;rounded=0;" edge="1" '
               'parent="1" source="a" target="b">'
               '<mxGeometry relative="1" as="geometry" /></mxCell>'
               '</root></mxGraphModel></diagram></mxfile>')
        p = os.path.join(self.tmp.name, "d.drawio")
        with open(p, "w") as fh:
            fh.write(xml)
        r = subprocess.run([sys.executable, BIN, "layout", p, "--preset", "verticalFlow"],
                           capture_output=True, text=True)
        if r.returncode == 1 and ("node not found" in r.stderr or "elkjs not found" in r.stderr):
            self.skipTest("node/elkjs unavailable")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        import xml.etree.ElementTree as ET
        geo = {c.get("id"): c.find("mxGeometry")
               for c in ET.parse(p).getroot().iter("mxCell") if c.get("vertex") == "1"}
        self.assertEqual((geo["legend"].get("x"), geo["legend"].get("y")), ("700", "40"))


class DrawioPreview(unittest.TestCase):
    """dec-022 pure parts: the viewer-URL encoder must round-trip exactly (the viewer raw-inflates
    then decodeURIComponents), and browser resolution prefers the onboard-installed shell."""
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(ROOT, "bin"))
        from devantlib import drawio
        cls.drawio = drawio

    def test_viewer_url_roundtrips_percent_and_unicode(self):
        import base64
        import urllib.parse
        import zlib
        xml = '<mxfile><diagram name="t" id="t">giá 100% &amp; ổn</diagram></mxfile>'
        url = self.drawio._viewer_url(xml)
        self.assertTrue(url.startswith("https://viewer.diagrams.net/"))
        payload = urllib.parse.unquote(url.split("#R", 1)[1])
        inflated = zlib.decompress(base64.b64decode(payload), -zlib.MAX_WBITS).decode("utf-8")
        self.assertEqual(urllib.parse.unquote(inflated), xml)

    def _with_plugin_data(self, td):
        prev = os.environ.get("CLAUDE_PLUGIN_DATA")
        os.environ["CLAUDE_PLUGIN_DATA"] = td
        try:
            return self.drawio._find_browser()
        finally:
            if prev is None:
                del os.environ["CLAUDE_PLUGIN_DATA"]
            else:
                os.environ["CLAUDE_PLUGIN_DATA"] = prev

    def test_find_browser_resolves_plugin_shell(self):
        with tempfile.TemporaryDirectory() as td:
            shell = os.path.join(td, "browsers", "chrome-headless-shell", "linux-1.0",
                                 "chrome-headless-shell-linux64", "chrome-headless-shell")
            os.makedirs(os.path.dirname(shell))
            with open(shell, "w") as fh:
                fh.write("#!/bin/sh\n")
            os.chmod(shell, 0o755)
            self.assertEqual(self._with_plugin_data(td), shell)

    def test_find_browser_never_falls_back_to_system_or_exe(self):
        # dec-023: empty plugin data => None, even on a box where system Chrome or the WSL
        # Windows chrome.exe/msedge.exe exist — those are never consulted.
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(self._with_plugin_data(td))

    def test_preview_without_shell_points_at_onboard(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = os.path.join(td, "d.drawio")
            with open(fixture, "w") as fh:
                fh.write("<mxfile />")
            env = dict(os.environ, CLAUDE_PLUGIN_DATA=td)
            r = subprocess.run([sys.executable, BIN, "drawio-preview", fixture],
                               capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 1)
            self.assertIn("onboard", r.stderr)

    def test_preview_missing_file_fails_honestly(self):
        r = subprocess.run([sys.executable, BIN, "drawio-preview", "/nonexistent/x.drawio"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("cannot read", r.stderr)


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


class SlideSkill(unittest.TestCase):
    """dec-036 redesign: brand.json tokens -> `slide-styles` block (drift-proof against the shipped
    sample), and `slide-lint` catches the anti-slop tells geometry can check (off-brand colour,
    fabricated hero stat, decorative chart)."""
    REF = os.path.join(ROOT, "skills", "slide", "references")
    SAMPLE = os.path.join(REF, "brand-sample.fodp")

    def dv(self, *args):
        return subprocess.run([sys.executable, BIN, *args], capture_output=True, text=True)

    def _read_sample(self):
        with open(self.SAMPLE) as fh:
            return fh.read()

    def _variant(self, tmp, replace=None, extra_page=""):
        src = self._read_sample()
        if replace:
            src = src.replace(*replace)
        if extra_page:
            src = src.replace("</office:presentation>", extra_page + "\n  </office:presentation>")
        p = os.path.join(tmp, "deck.fodp")
        with open(p, "w") as fh:
            fh.write(src)
        return p

    def test_sample_lints_clean(self):
        r = self.dv("slide-lint", self.SAMPLE)                       # the repo self-test
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_generator_equals_sample_block(self):
        gen = self.dv("slide-styles").stdout                         # drift-proof invariant
        block = re.search(r"<office:automatic-styles>.*?</office:automatic-styles>",
                          self._read_sample(), re.S).group(0)
        norm = lambda s: re.sub(r"\s+", " ", s).strip()
        self.assertEqual(norm(gen), norm(block))

    def test_styles_rebrand_from_a_fed_token_file(self):
        with tempfile.TemporaryDirectory() as d:
            bp = os.path.join(d, "brand.json")
            with open(bp, "w") as fh:
                json.dump({"palette": {"accent": "#0B5FFF"}}, fh)   # feed just one token
            out = self.dv("slide-styles", "--brand", bp).stdout
            self.assertIn("#0B5FFF", out)                            # fed accent flows through
            self.assertNotIn("#C4351F", out)                         # default accent fully replaced

    def test_lint_flags_off_brand_colour(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._variant(d, replace=('fo:color="#1B1A17"', 'fo:color="#0AC5FF"'))
            r = self.dv("slide-lint", p)
            self.assertEqual(r.returncode, 1)
            self.assertIn("#0AC5FF", r.stderr)

    def test_lint_flags_fabricated_hero_stat(self):
        stat = ('<draw:page draw:name="Stat" draw:style-name="dpDark" draw:master-page-name="Master">'
                '<draw:frame draw:style-name="gText" svg:width="16cm" svg:height="4cm" svg:x="1.6cm" svg:y="2.8cm">'
                '<draw:text-box><text:p text:style-name="pFig">3.2x</text:p></draw:text-box></draw:frame></draw:page>')
        with tempfile.TemporaryDirectory() as d:
            r = self.dv("slide-lint", self._variant(d, extra_page=stat))
            self.assertEqual(r.returncode, 1)
            self.assertIn("hero figure", r.stderr)
            # a same-page source marker clears it
            sourced = stat.replace("</draw:page>",
                '<draw:frame draw:style-name="gText" svg:width="10cm" svg:height="1cm" svg:x="1.6cm" svg:y="12cm">'
                '<draw:text-box><text:p text:style-name="pBodyS">src: 2024 pilot</text:p></draw:text-box></draw:frame></draw:page>')
            r2 = self.dv("slide-lint", self._variant(d, extra_page=sourced))
            self.assertEqual(r2.returncode, 0, r2.stderr)

    def test_lint_flags_decorative_chart(self):
        bars = ('<draw:page draw:name="Bars" draw:style-name="dpDark" draw:master-page-name="Master">'
                '<draw:rect draw:style-name="gGrey" svg:width="1.4cm" svg:height="2cm" svg:x="20.5cm" svg:y="10.6cm"/>'
                '<draw:rect draw:style-name="gGrey" svg:width="1.4cm" svg:height="3cm" svg:x="22.3cm" svg:y="9.6cm"/>'
                '<draw:rect draw:style-name="gAccent" svg:width="1.4cm" svg:height="4.4cm" svg:x="24.1cm" svg:y="8.2cm"/></draw:page>')
        with tempfile.TemporaryDirectory() as d:
            r = self.dv("slide-lint", self._variant(d, extra_page=bars))
            self.assertEqual(r.returncode, 1)
            self.assertIn("decorative chart", r.stderr)
            r2 = self.dv("slide-lint", self._variant(d, extra_page=bars), "--allow-chart")
            self.assertEqual(r2.returncode, 0, r2.stderr)

    # ---- slide-build: deterministic geometry generator (dec-040) ----
    # Correctness anchor is these geometry assertions (equal widths/gutters + margin-safe on all 7
    # archetypes), NOT equality to slide-build's own output.
    EPS = 0.02
    _DECK = [
        {"archetype": "title", "title": "Ship it", "subtitle": "A short view"},
        {"archetype": "section-divider", "kicker": "PART ONE", "title": "Where time goes"},
        {"archetype": "milestone-flow", "kicker": "HOW IT WORKS", "heading": "Four phases",
         "cards": [{"title": "Ground", "desc": "Read graph"}, {"title": "Design", "desc": "Vet"},
                   {"title": "Build", "desc": "Edit"}, {"title": "Verify", "desc": "Prove"}]},
        {"archetype": "metric", "stat": "5 min", "label": "target", "src": "dec-040"},
        {"archetype": "two-column-compare", "heading": "Before and after",
         "left": {"title": "Today", "points": ["Hand XML", "Uneven", "3 rounds"]},
         "right": {"title": "Now", "points": ["Spec", "Aligned", "1 pass"]}},
        {"archetype": "three-point", "heading": "Why faster",
         "points": [{"title": "Less", "desc": "Spec"}, {"title": "Aligned", "desc": "Math"},
                    {"title": "Trusted", "desc": "Gate"}]},
        {"archetype": "process-flow", "heading": "Render path",
         "steps": ["Author", "build", "soffice", "deliver"]},
        {"archetype": "metric", "title": "One line to a deck", "body": "More story."},
    ]

    def _build(self, tmp, spec, *extra):
        sp = os.path.join(tmp, "spec.json")
        with open(sp, "w") as fh:
            json.dump(spec, fh)
        out = os.path.join(tmp, "deck.fodp")
        return self.dv("slide-build", sp, "-o", out, *extra), out

    def _pages(self, path):
        from xml.dom import minidom
        return minidom.parse(path).getElementsByTagName("draw:page")

    def _boxes(self, page, tag=None, h=None):
        out = []
        for t in ((tag,) if tag else ("draw:rect", "draw:frame")):
            for el in page.getElementsByTagName(t):
                b = tuple(float(el.getAttribute(a)[:-2])
                          for a in ("svg:x", "svg:y", "svg:width", "svg:height"))
                if h is None or abs(b[3] - h) < 0.001:
                    out.append(b)
        return out

    def test_build_all_archetypes_margin_safe(self):
        with tempfile.TemporaryDirectory() as d:
            r, out = self._build(d, self._DECK)
            self.assertEqual(r.returncode, 0, r.stderr)
            for pi, page in enumerate(self._pages(out), 1):
                for (x, y, w, h) in self._boxes(page):
                    self.assertGreaterEqual(x, 1.6 - self.EPS, "page %d left" % pi)
                    self.assertGreaterEqual(y, 1.6 - self.EPS, "page %d top" % pi)
                    self.assertLessEqual(x + w, 26.4 + self.EPS, "page %d right" % pi)
                    self.assertLessEqual(y + h, 14.15 + self.EPS, "page %d bottom" % pi)

    def test_build_milestone_cards_equal_width_and_gutter(self):
        with tempfile.TemporaryDirectory() as d:
            _, out = self._build(d, [self._DECK[2]])
            cards = sorted(self._boxes(self._pages(out)[0], tag="draw:rect", h=4.6))
            self.assertEqual(len(cards), 4)
            self.assertEqual(len({round(w, 3) for (_, _, w, _) in cards}), 1, "card widths differ")
            gaps = [round(cards[i + 1][0] - cards[i][0], 3) for i in range(3)]
            self.assertEqual(len(set(gaps)), 1, "card pitch differs: %s" % gaps)

    def test_build_compare_panels_equal_width(self):
        with tempfile.TemporaryDirectory() as d:
            _, out = self._build(d, [self._DECK[4]])
            panels = self._boxes(self._pages(out)[0], tag="draw:rect", h=8.8)
            self.assertEqual(len(panels), 2)
            self.assertAlmostEqual(panels[0][2], panels[1][2], places=3)

    def test_build_threepoint_columns_equal(self):
        with tempfile.TemporaryDirectory() as d:
            _, out = self._build(d, [self._DECK[5]])
            titles = sorted(self._boxes(self._pages(out)[0], tag="draw:frame", h=1.0))
            self.assertEqual(len(titles), 3)
            self.assertEqual(len({round(w, 3) for (_, _, w, _) in titles}), 1, "column widths differ")
            gaps = [round(titles[i + 1][0] - titles[i][0], 3) for i in range(2)]
            self.assertEqual(len(set(gaps)), 1, "column pitch differs: %s" % gaps)

    def test_build_deck_lints_clean(self):
        with tempfile.TemporaryDirectory() as d:
            _, out = self._build(d, self._DECK)
            r = self.dv("slide-lint", out)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_build_unknown_archetype_errors(self):
        with tempfile.TemporaryDirectory() as d:
            r, _ = self._build(d, [{"archetype": "pie-chart", "title": "x"}])
            self.assertEqual(r.returncode, 1)
            self.assertIn("unknown archetype", r.stderr)

    def test_build_missing_field_errors(self):
        with tempfile.TemporaryDirectory() as d:
            r, _ = self._build(d, [{"archetype": "milestone-flow", "heading": "x"}])
            self.assertEqual(r.returncode, 1)
            self.assertIn("cards", r.stderr)

    def test_build_raw_passthrough(self):
        frag = '<draw:page draw:name="Raw" draw:style-name="dpDark" draw:master-page-name="Master"/>'
        with tempfile.TemporaryDirectory() as d:
            _, out = self._build(d, [{"archetype": "raw", "fodp": frag}])
            with open(out) as fh:
                self.assertIn(frag, fh.read())

    def test_build_numeric_title_lints_clean(self):
        # a headline with a year is not a fabricated hero stat (dec-040 review #1)
        with tempfile.TemporaryDirectory() as d:
            _, out = self._build(d, [{"archetype": "title", "title": "2026 Strategy"},
                                     {"archetype": "section-divider", "title": "Top 5 Bets"}])
            r = self.dv("slide-lint", out)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_build_malformed_items_fail_clean(self):
        # bare-string card, labelless step, over-long compare column -> clean exit 1, no traceback
        bad = [
            [{"archetype": "milestone-flow", "heading": "h", "cards": ["a", "b"]}],
            [{"archetype": "process-flow", "heading": "h", "steps": [{"n": 1}, {"n": 2}]}],
            [{"archetype": "two-column-compare", "heading": "h",
              "left": {"title": "L", "points": ["1", "2", "3", "4", "5", "6", "7"]},
              "right": {"title": "R", "points": ["x"]}}],
        ]
        with tempfile.TemporaryDirectory() as d:
            for spec in bad:
                r, _ = self._build(d, spec)
                self.assertEqual(r.returncode, 1, spec)
                self.assertNotIn("Traceback", r.stderr)
                self.assertTrue(r.stderr.startswith("devant:"), r.stderr)

    def test_build_name_with_quote_stays_wellformed(self):
        # a page name is an XML attribute; a quote in it must not break the document (review #3)
        from xml.dom import minidom
        with tempfile.TemporaryDirectory() as d:
            _, out = self._build(d, [{"archetype": "title", "title": "x", "name": 'a" onload="y'}])
            minidom.parse(out)   # raises if the attribute injection broke well-formedness


if __name__ == "__main__":
    unittest.main(verbosity=2)
