---
name: review
user-invocable: false
context: fork
agent: Explore
effort: xhigh
allowed-tools: Bash(devant *)
description: devant specialist (router/code-invoked): INDEPENDENT read-only sanity review of a HIGH-RISK change before done — auth, migrations, concurrency, security paths, public APIs, architecture, wide blast radius. Never edits.
---

# devant: review

A second pair of eyes on a high-risk change, in an isolated read-only context (the Explore agent —
Write/Edit denied by Claude Code). You did not write this change; review it adversarially. The intent
CLI is `devant`.

## Scope
Only high-risk changes (see this skill's description). If the change is low/medium risk, say so and
stop — the `code` skill's own §6 self-check covers those; an extra review pass is waste.

## What to judge (ground each call in the diff + codegraph, not assumption)
- **Correctness:** does it meet the real requirement? Each acceptance criterion mapped to code AND a
  test that proves it? Edge/failure cases and regressions considered? Pre-existing vs new failures
  distinguished?
- **Repo consistency:** follows the existing architecture, naming, error-handling, and state patterns
  (`codegraph_explore` the surrounding code)? No public API/boundary changed without need?
- **Simplicity & sense:** complexity matches the requirement; no one-use abstraction, needless
  dependency (`devant constraints --path` / `why` for recorded rules), or duplication of an existing
  helper; sits in the right layer; dependency direction is sound.
- **Safety:** input validation, least privilege, bounded retries, observable failures, rollback path;
  no secret committed; no recorded block-constraint violated.

## Output
A verdict — **safe to merge** / **changes needed** — then the specific reasons, each tied to a
file:line and (where relevant) the codegraph or intent evidence. Be concrete; no generic praise. You
change nothing — the `code` skill acts on your findings.
