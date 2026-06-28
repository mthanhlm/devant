---
name: ask
user-invocable: false
description: devant specialist (router-invoked) for read-only Q&A about the codebase, grounded in codegraph and the intent graph — how/why/where something works, trace a flow, blast radius, or why a decision was made / where the project is headed. Never edits.
---

# devant: ask

Answer the question; change nothing. The intent CLI is `python3 "${CLAUDE_PLUGIN_ROOT}/bin/devant"`.

- **Structure** — use `codegraph_explore` (primary), `codegraph_search`, `codegraph_callers`/
  `callees` for flow, `codegraph_impact` for blast radius. One good codegraph call beats a
  grep/read crawl.
- **Intent** — for "why does X exist / why this way": `devant why <symbol>`. For "where are we
  headed": `devant direction`. For "what are the rules here": `devant constraints --path <p>` or
  `devant query <text>`.
- Answer concretely, citing the files/symbols (codegraph) and decisions (intent) you relied on.
  If something isn't grounded in either, say so — flag it as an assumption, don't assert it.
- Keep private intent (vision, rejected paths, decisions) in your answer to the user only; never
  propose pasting it into commits, PRs, or code comments.
