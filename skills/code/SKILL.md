---
name: code
user-invocable: false
description: devant specialist (router-invoked) to make a verified code change — implement, fix, refactor, debug-and-fix, or complete unfinished work — grounded in codegraph and the intent graph, sized by blast radius, surgical, and verified for logic (not just compilation). Used for substantial changes; the router does trivial edits inline.
---

# devant: code

Own the change end to end: ground, change surgically, verify, record if a real decision emerged.
The intent CLI is `python3 "${CLAUDE_PLUGIN_ROOT}/bin/devant"` (`devant` below).

## 1. Ground & necessity
Work the reuse ladder: does it need to exist? is it already here (`codegraph_search` — reuse,
don't rewrite)? stdlib / platform / existing dep / one line / only then minimal code. Check
`devant constraints --path <file>` before writing — if a **block** rule applies, take the
sanctioned path; the edit guard will deny a violation anyway, so resolve it up front.

## 2. Size, then act (no fixed pipeline)
`codegraph_impact`/`callers`. Bounded fan-out → implement directly. Wide/cross-module → a brief
visible outline first, then execute. Never quarter a small change.

## 3. Implement surgically
Every changed line traces to the request. Match surrounding style and idiom. No drive-by
refactors or reformatting. Remove only the orphans your change created.

## 4. Verify logic, not compilation — and actually RUN it
- Bug → write a **failing repro test first**, then make it pass (red proves the logic). A test
  that can't fail before the fix proves nothing.
- New behavior → asserting tests.
- Run the impacted subset: `git diff --name-only | codegraph affected --stdin -q`, then run those.
  **If that returns nothing, don't trust the silence** — codegraph may not resolve the dependents;
  fall back to the project's own test command (pytest/go test/npm test/…) for the touched area.
  No test infra at all → a runtime smoke, and say so (don't scaffold a framework).
- Lint/typecheck the changed files. Report honestly with real command output, including failures.
  Don't say "done" on a green compile alone or on an unrun test.

## 5. Record only a real decision
If the change settled a genuine choice (or ruled one out), capture it:
`devant decide --title "…" --body "<why>" [--rejected "…" --why-rejected "…"] [--realizes <goal>]`.
Keep it one node. Do not write plan/spec/report markdown. Do not edit `.devant/` by hand.
