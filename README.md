# devant

A **single-command, intent-aware coding companion** for Claude Code. It works like a teammate who
knows the project — what it's for, where it's going, and **what NOT to do** — so you ship lean,
correct changes instead of debt you get blamed for later.

It pairs two knowledge graphs:
- **the devant graph** — the structure of your code, indexed by devant itself (no external indexer).
- a **local intent graph you own** — the project's vision, direction, decisions, constraints, and
  non-goals, linked to code symbols.

## Use it

```
/devant:onboard        # one time per repo: builds the devant graph, interviews you, seeds the intent graph
/devant:run <whatever> # everything else — devant auto-routes (answer · code · document · recall direction)
```

That's the whole surface. No menu of commands to learn.

## What makes it different

- **Fast by default.** No fixed pipeline. A typo is one pass; only genuinely wide changes get the
  elaborate path. Steps scale with graph blast radius, never line count.
- **Knows what NOT to do.** Recorded constraints are enforced on edits: a Write/Edit that breaks a
  block rule (e.g. a planner reaching into the DB instead of reporting back) is **denied before it
  lands**, naming the sanctioned path and the decision behind it. A separate Bash guard **denies**
  `git commit`, `git push`, `git add`, and destructive git (history rewrite, `reset --hard`,
  forced `clean`, branch/tag delete, `stash drop`/`clear`, worktree-discarding
  `checkout`/`restore`/`switch`) — devant never commits, pushes, or rewrites git state on your
  behalf; you do that manually. Both are cooperative guards, not a sandbox — they raise the floor,
  they don't claim to stop a determined bypass (`DEVANT=off` disables them, and commands hidden
  inside `sh -c '…'` or `$(…)` aren't parsed).
- **Pushes back.** Debt-prone or already-rejected requests get challenged before a line is written.
- **Pushes you to verify.** Bugs want a failing repro test first; the Stop hook surfaces the
  impacted tests (`devant graph affected`) to run. devant *reminds and grounds* verification — it does
  not gate "done" for you; running the tests is still your call.
- **Stays out of your repo.** Everything devant stores lives under `.devant/` and is kept out of
  git via `.git/info/exclude` — never committed, never pushed. Only your project code is shared.

## Requirements

- **python3** (stdlib only — no third-party packages). This alone runs devant's core.
- **Node.js (optional)** — only for diagram auto-layout (elkjs, installed into the plugin's
  data dir by `/devant:onboard`). Code indexing needs nothing beyond python3: the devant graph
  is built in (dec-016).
- Iterate without reinstalling: `claude --plugin-dir ~/lam/devant` loads the working tree as the plugin for that session; `/reload-plugins --force` applies hook/manifest edits mid-session, `/reload-skills` re-scans skill edits.
- Smoke the SessionStart wiring headlessly: `claude --init-only --debug "hooks"`.
- Release gate: `claude plugin validate . --strict` must pass before every release.

Note: the context monitor (smart compaction, dec-018) is a plugin background monitor — it runs only in interactive CLI sessions, does not load for project-scope plugin installs, and is skipped when `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` is set. The PreCompact gate fails open without it. `DEVANT_CODEGRAPH=off` disables the graph *lifecycle* (hook syncs, intent bridge), not the `devant graph` CLI itself — a stale index still answers direct queries.

## Notes

- `.devant/` (the intent graph + local state) and `.codegraph/` are added to `.git/info/exclude`
  automatically on session start; the shared `.gitignore` is never touched.
- The intent graph is local to your clone. On a fresh clone, run `/devant:onboard` again.
- Hooks never abort a session: any failure degrades gracefully and exits 0.
- `DEVANT=off` disables devant's hook behavior for a session.
- `python3 "$CLAUDE_PLUGIN_ROOT/bin/devant" doctor` self-tests the guard engine (a canary against a
  silently-broken guard) and reports graph/intent health and specialist usage.
- The plugin is covered by an end-to-end test suite (`python3 tests/test_devant.py`) that exercises
  the CLI **and** the bash hooks (the edit guard, the git guard, and the session/prompt/stop hooks),
  so the guards are verified to actually deny under bash.
