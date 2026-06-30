#!/usr/bin/env python3
"""Tests for the devant intent CLI. Stdlib unittest, no third-party deps.

Run: python3 tests/test_devant.py   (or: python3 -m unittest -v tests/test_devant.py)

Pure functions (path_match, first_forbid_hit, _content_tokens, secret_like) are tested in-process;
guard/why/supersede/lint behavior is tested end-to-end through the CLI against a temp --db.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "bin", "devant")
dv = SourceFileLoader("devant_mod", BIN).load_module()


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
                  "git checkout -- file.py", "git filter-branch --all", "git filter-repo --invert"):
            self.assertEqual(dv.evaluate_bash(c)[0], "deny", c)

    def test_evaluate_bash_allows_readonly_and_nongit(self):
        for c in ("git status", "git diff", "git log --grep=push", "git branch",
                  "git checkout main", "git reset HEAD file.py", "git clean -n",
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
        self.env = dict(os.environ, CLAUDE_PLUGIN_ROOT=ROOT,
                        CLAUDE_PROJECT_DIR=self.proj, DEVANT_CODEGRAPH="off")
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

    def test_write_hook_allows_clean_and_records_touched(self):
        self.assertEqual(self.decision(self.w("src/util.py", "def add(a, b):\n    return a + b\n")), "allow")
        self.assertTrue(os.path.exists(os.path.join(self.proj, ".devant", "state", "h.touched")))

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

    def ctx(self, r):
        out = r.stdout.strip()
        return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else ""

    def test_session_start_emits_intent_brief(self):
        r = self.hook("session-start.sh", {"cwd": self.proj, "session_id": "ss"})
        self.assertIn("no sqlite in handlers", self.ctx(r))   # the block rule seeded in setUp

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
