---
name: document
user-invocable: false
effort: medium
allowed-tools: Bash(devant *)
description: devant specialist (router-invoked): write or update docs grounded in the devant graph (code + intent)'s vision/audience. Updates in place; no stray files.
---

# devant: document

Produce docs that match the code and the project's intent. The intent CLI is `devant`.

- **Ground in reality** — describe what the code actually does (`devant graph explore`/`search`),
  not what you assume. Frame it for the audience and vision (`devant direction`,
  `devant query <topic>`).
- **Match the artifact's shape** — a README leads with what/why + the fastest path to running it;
  a guide is task-ordered (goal → steps → the gotcha); a docstring states the contract (args,
  returns, the non-obvious constraint), never a restatement of the body. Give the reader the
  shortest path to doing the thing — nothing they'd skip.
- **Verify every claim before you ship it** — run or cross-check each command, code example, and
  signature against the graph/the real code; flag anything you couldn't verify as an assumption
  rather than asserting it (the `ask` rule). A stale or wrong example is worse than none.
- **Update, don't duplicate** — edit the existing doc (README, the relevant `.md`, docstrings).
  Do not create a parallel plan/spec/report/notes file — the edit guard blocks those anyway.
- Keep it lean: the minimum that makes the thing usable. No narration, no filler.
- Keep private intent (rejected paths, internal strategy) out of public docs unless asked.
