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
- **Update, don't duplicate** — edit the existing doc (README, the relevant `.md`, docstrings).
  Do not create a parallel plan/spec/report/notes file — the edit guard blocks those anyway.
- Keep it lean: the minimum that makes the thing usable. No narration, no filler.
- Keep private intent (rejected paths, internal strategy) out of public docs unless asked.
