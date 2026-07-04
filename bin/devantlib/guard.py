"""Edit + Bash guard engines. Hot path: hooks call these per Write/Edit/Bash, so this
module may import only devantlib.common and stdlib — never intent/graph/drawio."""
import json
import os
import re
import shlex
import sys

from .common import (DOC_TEST_CTX, _active, connect, first_forbid_hit, is_under, load_meta,
                     path_match, project_dir, rel_to_project, secret_like)


def evaluate_guard(rel, content, conn, file_exists=False):
    """Decide a proposed write of `content` to repo-relative `rel`. Returns (decision, reason).
    Pure (no stdin/print) so both the CLI and the PreToolUse hook helper share one implementation."""
    # .devant is CLI-managed; direct edits could weaken a guardrail (always wins).
    if rel and is_under(rel, ".devant"):
        return ("deny",
                "Don't edit .devant/ directly — devant manages it via the CLI "
                "(`devant decide` / `add-node` / `link`). Editing it by hand can silently weaken a guard.")

    # Collect all candidate findings, then return the STRONGEST (deny > ask > allow) — so an
    # ask-level secret can never mask a block-constraint deny.
    candidates = []  # (decision, reason)

    sec = secret_like(content)
    if sec:
        label, sev = sec
        ctx = DOC_TEST_CTX.search(rel or "")
        if not (sev == "ask" and ctx):                     # placeholders in fixtures -> ignore
            if sev == "deny" and ctx and label != "private key block":
                sev = "ask"                                 # flag in fixture context (never a private key)
            candidates.append((sev, "Possible %s in this write. Don't hard-code credentials — use env/secret config." % label))

    if rel and rel.lower().endswith((".md", ".markdown")) and not file_exists and not is_under(rel, ".devant") \
            and re.search(r"(^|[-_ ])(plan|spec|scratch|wip|draft)([-_ .]|$)", os.path.basename(rel).lower()):
        candidates.append(("ask",
                           "This looks like a stray plan/scratch file. devant keeps plans in chat and captures "
                           "durable intent with `devant decide`. Proceed only if it's a real, lasting project doc."))

    if conn is not None and rel:
        for c in _active(conn, "constraint"):
            m = load_meta(c)
            applies = m.get("applies_to_paths") or []
            link_paths = [lk["path"] for lk in conn.execute(
                "SELECT path FROM code_link WHERE node=? AND relation='constrains'", (c["id"],)
            ).fetchall() if lk["path"]]
            scope = applies + link_paths
            if not scope or not any(path_match(rel, g) for g in scope):
                continue
            if any(path_match(rel, g) for g in (m.get("exempt_paths") or [])):
                continue
            hit = first_forbid_hit(content, m.get("forbid") or [])
            if not hit:
                continue
            exp = m.get("expected")
            why = conn.execute(
                "SELECT n.body FROM edge e JOIN node n ON n.id=e.src "
                "WHERE e.kind='establishes' AND e.dst=? AND n.body IS NOT NULL LIMIT 1", (c["id"],)
            ).fetchone()
            r = "%s: %s. Forbidden here: '%s'.%s%s%s" % (
                c["id"], c["title"], hit,
                (" Sanctioned path: %s." % exp) if exp else "",
                (" Why: %s" % why["body"]) if why and why["body"] else "",
                (" To override one path, the user can run: devant decide --title '…' --body '…' --supersedes %s --exempt <glob>" % c["id"]),
            )
            # warn-severity rules inform without interrupting: surfaced as context by the
            # hook (dec-019), never as a modal ask — that's reserved for secrets/plan files.
            candidates.append(("deny" if m.get("severity") == "block" else "warn", r))

    for want in ("deny", "ask", "warn"):
        for d, r in candidates:
            if d == want:
                return (d, r)
    return ("allow", "")


# Bash git-guard: devant never commits/pushes/adds or rewrites/destroys git state on the user's
# behalf (nongoal-002). Cooperative — raises the floor, not a sandbox (nongoal-001); DEVANT=off
# disables it and it does not pretend to stop a determined bypass (e.g. value-taking wrapper opts).
_GIT_WRAPPERS = {"sudo", "doas", "nice", "time", "env", "command", "xargs", "nohup", "stdbuf", "setsid", "ionice"}
_GIT_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix", "--config-env"}
_GIT_DENY_ALWAYS = {"commit", "push", "add", "rm", "filter-branch", "filter-repo"}


def _git_subcommand(tokens):
    """The git subcommand a shell segment runs, else None. Sees through leading VAR=val
    assignments, command wrappers (sudo/env/…), and git's own global options."""
    i, n = 0, len(tokens)
    while i < n and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[i]):
        i += 1
    while i < n and os.path.basename(tokens[i].strip("()")) in _GIT_WRAPPERS:
        i += 1
        while i < n and tokens[i].startswith("-"):
            i += 1
    if i >= n or os.path.basename(tokens[i].strip("()")) != "git":
        return None
    i += 1
    while i < n and tokens[i].startswith("-"):  # git's global options (some consume a value)
        opt = tokens[i]
        i += 1
        if opt in _GIT_VALUE_OPTS and "=" not in opt:
            i += 1
    return tokens[i].strip("()") if i < n else None


def _git_deny_hit(sub, tokens):
    """The denied git operation a segment performs, else None."""
    if sub in _GIT_DENY_ALWAYS:
        return "git %s" % sub
    opts = set(t for t in tokens if t.startswith("-"))
    if sub == "reset" and "--hard" in opts:
        return "git reset --hard"
    if sub == "clean" and ("--force" in opts or any(re.match(r"^-[a-eg-z]*f", o) for o in opts)):
        return "git clean -f"
    if sub == "branch" and (opts & {"-d", "-D", "--delete"}):
        return "git branch -d/-D"
    if sub == "tag" and (opts & {"-d", "--delete"}):
        return "git tag -d"
    if sub == "checkout":
        if (opts & {"-f", "--force"}) or "--" in tokens:
            return "git checkout (discard)"
        # A pathspec (not a lone branch name) discards worktree changes: `git checkout .`,
        # `git checkout HEAD file.py`. Branch-creating opts consume their value.
        args, skip = [], False
        try:
            rest = tokens[tokens.index("checkout") + 1:]
        except ValueError:
            rest = []
        for t in rest:
            if skip:
                skip = False
            elif t in ("-b", "-B", "--orphan"):
                skip = True
            elif not t.startswith("-"):
                args.append(t)
        if len(args) > 1 or "." in args or "*" in args:
            return "git checkout (discard)"
    if sub == "restore":
        # Default target is the worktree (discard); only a pure --staged restore is safe.
        shorts = "".join(o[1:] for o in opts if not o.startswith("--"))
        if "--worktree" in opts or "W" in shorts or not ("--staged" in opts or "S" in shorts):
            return "git restore (discard)"
    if sub == "switch" and (opts & {"--discard-changes", "-f", "--force"}):
        return "git switch --discard-changes"
    if sub == "stash" and ("drop" in tokens or "clear" in tokens):
        return "git stash drop/clear"
    return None


def _shell_segments(command):
    """Split a shell command on unquoted ;, &, |, newline (so && and || fall out as empty
    segments). A naive re.split broke quoted patterns ('grep "a\\|b"') into unbalanced-quote
    fragments that the conservative fallback then mis-denied."""
    segs, buf, quote, esc = [], [], None, False
    for ch in command:
        if esc:
            buf.append(ch)
            esc = False
            continue
        if ch == "\\" and quote != "'":
            buf.append(ch)
            esc = True
            continue
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
            buf.append(ch)
            continue
        if ch in ";&|\n":
            segs.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    segs.append("".join(buf))
    return segs


def evaluate_bash(command):
    """Decide a proposed Bash command: deny git commit/push/add and destructive git, else allow.
    Pure (no I/O) so the CLI and the PreToolUse(Bash) helper share one implementation."""
    if not command or not command.strip():
        return ("allow", "")
    for seg in _shell_segments(command):
        seg = seg.strip()
        if not seg:
            continue
        try:
            tokens = shlex.split(seg)
        except ValueError:  # unbalanced quotes — fall back to a conservative literal check
            if re.search(r"\bgit\b[^\n]*\b(commit|push|add)\b", seg):
                return ("deny", _git_reason("git commit/push/add"))
            continue
        sub = _git_subcommand(tokens)
        if sub is None:
            continue
        hit = _git_deny_hit(sub, tokens)
        if hit:
            return ("deny", _git_reason(hit))
    return ("allow", "")


def _git_reason(hit):
    return ("[devant] Blocked: %s. devant never commits, pushes, adds, or rewrites/destroys git "
            "state on your behalf — do that manually. Cooperative guard, not a sandbox "
            "(DEVANT=off disables it)." % hit)


def cmd_guard(args):
    f = args.file or ""
    content = sys.stdin.read() if args.content == "-" else (args.content or "")
    rel = rel_to_project(f, project_dir())
    decision, reason = evaluate_guard(rel, content, connect(args), file_exists=bool(f and os.path.exists(f)))
    print(json.dumps({"decision": decision, "reason": reason}))
    return 0
