---
name: review
user-invocable: false
context: fork
agent: Explore
effort: xhigh
allowed-tools: Bash(devant *), Bash(git diff *)
description: devant specialist (router/code-invoked): INDEPENDENT read-only sanity review of a HIGH-RISK change before done — auth, migrations, concurrency, security paths, public APIs, architecture, wide blast radius. Never edits.
---

# devant: review

A second pair of eyes on a high-risk change, in an isolated read-only context (the Explore agent —
Write/Edit denied by Claude Code). You did not write this change; review it adversarially. The intent
CLI is `devant`.

## Scope
Only high-risk changes (see this skill's description). If the change is low/medium risk, say so and
stop — the `code` skill's own §6 self-check covers those; an extra review pass is waste. Designs
before approval are `devant:debate`'s job — this skill judges code diffs after implementation.

## What to judge (ground each call in the diff + the devant graph, not assumption)
Obtain the change yourself — `git diff` (or `git diff --stat` for scope) — and review from that, not
from the code skill's narration; seeing what actually changed (vs the post-edit file alone) is what
lets you meet the "pre-existing vs new" bar, and reading it first-hand is the whole point of an
independent pass.
- **Correctness:** does it meet the real requirement? Each acceptance criterion mapped to code AND a
  test that proves it? Edge/failure cases and regressions considered? Pre-existing vs new failures
  distinguished?
- **Repo consistency:** follows the existing architecture, naming, error-handling, and state patterns
  (`devant graph explore` the surrounding code)? No public API/boundary changed without need?
- **Solid & lean:** judge against the concrete bar in the `code` skill's `references/quality.md`
  (error handling, boundary validation, least privilege/idempotency, guard clauses, no one-use
  abstraction, dependency direction, YAGNI/rule-of-three, duplication of an existing helper).
- **Recorded rules & safety:** the rules for this path (`devant constraints --path` / `why`) — no
  block-constraint violated, no secret committed, a rollback path wherever state changes.

## Output
A verdict — **safe to merge** / **changes needed** — then the specific reasons, each tied to a
file:line and (where relevant) the graph or intent evidence. Be concrete; no generic praise. You
change nothing — the `code` skill acts on your findings.
