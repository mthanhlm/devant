# devant

A **single-command, intent-aware coding companion** for Claude Code. It works like a teammate who
knows the project — what it's for, where it's going, and **what NOT to do** — so you ship lean,
correct changes instead of debt you get blamed for later.

It pairs two knowledge graphs:
- **codegraph** — the structure of your code (reused; not bundled).
- a **local intent graph you own** — the project's vision, direction, decisions, constraints, and
  non-goals, linked to code symbols.

## Use it

```
/devant:onboard        # one time per repo: scans with codegraph, interviews you, seeds the intent graph
/devant:run <whatever> # everything else — devant auto-routes (answer · code · document · recall direction)
```

That's the whole surface. No menu of commands to learn.

## What makes it different

- **Fast by default.** No fixed pipeline. A typo is one pass; only genuinely wide changes get the
  elaborate path. Steps scale with codegraph blast radius, never line count.
- **Knows what NOT to do.** Recorded constraints are enforced on edits: a Write/Edit that breaks a
  block rule (e.g. a planner reaching into the DB instead of reporting back) is **denied before it
  lands**, naming the sanctioned path and the decision behind it. A separate Bash guard **denies**
  `git commit`, `git push`, `git add`, and destructive git (history rewrite, `reset --hard`,
  forced `clean`, branch/tag delete, `stash drop`/`clear`, discard `checkout`) — devant never
  commits, pushes, or rewrites git state on your behalf; you do that manually. Both are cooperative
  guards, not a sandbox — they raise the floor, they don't claim to stop a determined bypass
  (`DEVANT=off` disables them).
- **Pushes back.** Debt-prone or already-rejected requests get challenged before a line is written.
- **Pushes you to verify.** Bugs want a failing repro test first; the Stop hook surfaces the
  impacted tests (`codegraph affected`) to run. devant *reminds and grounds* verification — it does
  not gate "done" for you; running the tests is still your call.
- **Stays out of your repo.** Everything devant stores lives under `.devant/` and is kept out of
  git via `.git/info/exclude` — never committed, never pushed. Only your project code is shared.

## Requirements

- The **codegraph** CLI on `PATH` (`codegraph`). Without it, structural features degrade to plain
  Read/Grep and devant still works.
- **python3** (stdlib only — no third-party packages).

## Notes

- `.devant/` (the intent graph + local state) and `.codegraph/` are added to `.git/info/exclude`
  automatically on session start; the shared `.gitignore` is never touched.
- The intent graph is local to your clone. On a fresh clone, run `/devant:onboard` again.
- Hooks never abort a session: any failure degrades gracefully and exits 0.
- `DEVANT=off` disables devant's hook behavior for a session.
- `python3 "$CLAUDE_PLUGIN_ROOT/bin/devant" doctor` self-tests the guard engine (a canary against a
  silently-broken guard) and reports codegraph/index/intent health and specialist usage.
- The plugin is covered by an end-to-end test suite (`python3 tests/test_devant.py`) that exercises
  the CLI **and** the bash hooks (the edit guard, the git guard, and the session/prompt/stop hooks),
  so the guards are verified to actually deny under bash.
