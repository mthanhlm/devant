---
name: document
user-invocable: false
description: devant specialist (router-invoked) to write or update documentation grounded in the code (codegraph) and the project's vision/audience (intent graph). Updates existing docs in place; never spawns stray plan/spec/report files.
---

# devant: document

Produce docs that match the code and the project's intent. The intent CLI is
`python3 "${CLAUDE_PLUGIN_ROOT}/bin/devant"`.

- **Ground in reality** — describe what the code actually does (`codegraph_explore`/`search`),
  not what you assume. Frame it for the audience and vision (`devant direction`,
  `devant query <topic>`).
- **Update, don't duplicate** — edit the existing doc (README, the relevant `.md`, docstrings).
  Do not create a parallel plan/spec/report/notes file — the edit guard blocks those anyway.
- Keep it lean: the minimum that makes the thing usable. No narration, no filler.
- Keep private intent (rejected paths, internal strategy) out of public docs unless asked.
