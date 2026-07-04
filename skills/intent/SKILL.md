---
name: intent
user-invocable: false
effort: low
allowed-tools: Bash(devant *)
disallowed-tools: Write, Edit, NotebookEdit
description: devant specialist (router-invoked): inspect or update project intent — vision, direction, decisions, constraints, non-goals — via the devant CLI. Record decisions, add/retire rules, answer "why are we allowed to X".
---

# devant: intent

The voice of the project's direction and rules. The intent CLI is `devant` (on the Bash PATH while this plugin is enabled).

## Read
- `devant summary` — vision + active block rules + direction.
- `devant direction` — vision → milestones → goals.
- `devant why <symbol>` — the intent behind a piece of code.
- `devant constraints --path <p>` / `devant query <text>` — rules and nodes for an area/topic.

## Write (every decision/constraint needs a rationale `--body`)
- Record a decision: `devant decide --title "…" --body "<why>" [--rejected "…" --why-rejected "…"]
  [--realizes <goal>] [--establishes <constraint>] [--supersedes <old> --exempt <path>]`.
- Add a rule: `devant add-node --kind constraint --id <slug> --title "…" --body "<why>"
  --applies "<glob>" --forbid "<substr>" [--expected "<sanctioned path>"] --severity block|warn`.
- Add/retire vision, direction, goal, non-goal with `add-node`, re-using the stable id to update.
  (Updates MERGE into existing meta, so re-titling a constraint keeps its forbid/applies/severity;
  to actually relax a rule, pass the new `--severity`/`--exempt` explicitly, or use `decide`.)
- Link intent to code: `devant link <id> <qualifiedName> --relation implemented_by|governs|constrains`.
- Keep the graph honest: `devant lint` (broken edges, rules with no teeth/scope), `devant dangling`.

## When to capture
When a real choice is made or ruled out, record it so it isn't re-litigated later. Don't record
trivia. The store is local and never committed — it's the user's working model of the project.
