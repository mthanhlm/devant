---
name: code
user-invocable: false
effort: high
allowed-tools: Bash(devant *)
description: devant specialist (router-invoked): make a verified code change — implement, fix, refactor, debug — grounded in the devant graph (code + intent), sized by blast radius, surgical, verified for logic. For substantial changes.
---

# devant: code

Own the change end to end: ground, change surgically, verify, record if a real decision emerged.
The intent CLI is `devant` (on the Bash PATH while this plugin is enabled).

## 1. Ground & necessity
Work the reuse ladder: does it need to exist? is it already here (`devant graph search` — reuse,
don't rewrite)? stdlib / platform / existing dep / one line / only then minimal code. Check
`devant constraints --path <file>` before writing — if a **block** rule applies, take the
sanctioned path; the edit guard will deny a violation anyway, so resolve it up front.

## 2. Plan — think it through, then post it (visible, before touching code)
`devant graph impact`/`callers` to size it. Work out — not just report — what you're changing, why
(the requirement/bug it satisfies), and how (the approach, step by step through the logic), then
post that plan before writing any code. This is the thinking step, not a formality after you've
already decided: if you can't state the how in steps, you haven't planned it yet. Depth scales
with size (a few lines for a bounded change, a fuller outline for wide/cross-module) but it's
never skipped. Never quarter a small change. For substantial work, record the definition of done
so it can't drift: `devant goal --set "<acceptance criteria, one per line>"` — it's surfaced in the
Stop reminder and re-hydrated after compaction. It reminds; it never gates (you still verify below).

## 3. Implement surgically
Every changed line traces to the request. Match surrounding style and idiom. No drive-by
refactors or reformatting. Remove only the orphans your change created.

## 4. Verify logic, not compilation — evidence, not claims
"Done" requires the evidence below as real command output, never a green compile or an unrun test.
- **Requirement → evidence:** map each acceptance criterion to the code that satisfies it and the
  test that proves it. An unmapped criterion is unfinished.
- **Bug → failing repro FIRST:** write the test that fails for the stated bug (red proves the
  logic), then make it pass. A test that can't fail before the fix proves nothing.
- **New behavior → asserting tests**, including the edge/failure cases — not just the happy path.
- **Run the impacted subset:** `git diff --name-only | devant graph affected --stdin`, then run
  those. **If it returns nothing, don't trust the silence** — the graph may not resolve the
  dependents; fall back to the project's own test command (pytest/go test/npm test/…) for the
  touched area. No test infra at all → a runtime smoke, and say so (don't scaffold a framework).
- **Pre-existing vs new:** if the touched suite was already red, state which failures you introduced
  vs inherited — don't claim a regression you didn't cause or hide one you did.
- **Lint/typecheck the changed files.** Report honestly, including failures.
- **Green is the exit, not the checklist:** "done" means the verification above actually came back
  green; red you caused is *not* done — loop back and fix, then re-verify. (When retries stop
  teaching you anything new, §5 governs the stop.)

## 5. When stuck, stop — don't loop
"New evidence" is concrete: the failure signature **changed** (a different error/assert/stack), or an
attempt **eliminated** a hypothesis. Re-running the same code to see the same failure is not new
evidence. If a fix→test cycle fails ~2–3 times without new evidence, STOP — but stopping is **not
done**. Report state with the same real command output §4 demands (the current failing output,
verbatim), what you tried, which hypotheses are eliminated, and your best next one, tagged
explicitly **"BLOCKED — not done."** Never let this stop pose as completion: a hand-back with a
lower evidence bar than §4's "done" is the report-instead-of-work failure dec-009 forbids. A human
steer is cheaper than a tenth blind iteration.

## 6. Engineering-sense check (scale to risk)
Before "done", sanity-check the change *makes sense*, not just that it runs — against the concrete
solid + lean bar in `references/quality.md` (error handling, boundary validation, YAGNI, rule-of-
three, dependency direction, right layer, reads clearly), scaled to risk. For **high-risk** changes
— auth/authz, data migrations, concurrency, security-sensitive paths, public APIs, architecture
changes, or a wide graph blast radius — get an INDEPENDENT read-only review via the `devant:review`
skill before declaring done. Low-risk changes: the self-check above suffices.

## 7. Record only a real decision
If the change settled a genuine choice (or ruled one out), capture it:
`devant decide --title "…" --body "<why>" [--rejected "…" --why-rejected "…"] [--realizes <goal>]`.
Keep it one node. Do not write plan/spec/report markdown. Do not edit `.devant/` by hand.

Phase gate (dec-018): when starting substantial work, run
`devant phase --set "implementing: <what>" --hold` so auto-compact defers mid-flight;
at each completed milestone run `devant phase --set "<milestone> done; next: <next>" --open`
so the deferred compact lands at the boundary. When every acceptance criterion is met and
verified (§4), clear the definition of done: `devant goal --clear`.
