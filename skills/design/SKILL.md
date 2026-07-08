---
name: design
user-invocable: false
effort: high
allowed-tools: Bash(devant *)
disallowed-tools: Write, Edit, NotebookEdit
description: devant specialist (work-invoked): design a change BEFORE building it — keep/bend/replace verdict on the current structure, current-vs-proposed in chat, inline evidence-cited red-team, one approval gate. Read-only, no plan/spec files.
---

# devant: design

Your value is **catching the critical problems the user is not aware of**, so approval happens
with eyes open. Read-only; the design lives in chat. The intent CLI is `devant`.

## 0. Verdict first: keep / bend / replace
Before proposing anything, judge whether the current structure deserves to survive this change:
**keep** (extend in place, fit the existing idioms), **bend** (reshape a boundary, preserve the
rest), or **replace** (the current shape IS the problem). Say which, with one reason. The user
calling the code a prototype / throwaway / known-bad — or asking for greenfield — forces
**replace mode**: the existing code is then a requirements-and-failure-mode inventory, NOT a
style standard to fit. Without that signal, default to fitting this codebase's idioms — but the
verdict is yours to argue either way; user statements about their own code are admissible evidence.

## 1. Ground in what exists — a gate, not a gesture
- `devant graph explore`/`search` the symbols, layers, and data the change touches; describe the
  CURRENT design from the graph. The Current section is invalid unless it cites real symbols/files
  you read AND the data model (persisted state → name the tables/shape; stateless → "N/A").
- `devant graph impact`/`callers` on every symbol the change reshapes — the affected sites anchor
  the risk section.
- Recorded intent arrived via the hook; pull bodies only as needed (`devant why <id>`).
- **A recorded decision colliding with the design is NOT dead on arrival:** evaluate its staleness
  (what changed since it was recorded?) and either design within it or offer
  "retire <dec-id> via `devant decide --supersedes`" as an explicit option at the gate.
  Block rules stay machine-enforced; retiring one is always the user's call.
- If the request admits materially different readings, settle WHICH ONE with the user before
  designing. Designing the wrong case fast is still wrong.

## 2. Triage the axes — name the 2–3 that bite
Menu: data model & ownership · failure modes & error handling · concurrency & consistency ·
migration & rollback · security & authz · scaling & performance · integration & coupling (blast
radius) · testing strategy. Pick the 2–3 that actually bite THIS change and state each decision
**with its consequence**, tied to the symbols you grounded; every open question ships with a
recommended default. Unpicked axes stay silent — no N/A litany. When failure-mode, data-model, or
blast-radius is in play, it must carry a concrete consequence, not a mention.

## 3. Present in chat — then ONE approval gate
1. **Goal** — the change restated as a verifiable outcome.
2. **Current** — grounded, with the keep/bend/replace verdict and its reason.
3. **Proposed** — components, data flow, the pattern and why it fits this stack (in replace mode:
   why the replacement is fit for purpose, not why it resembles what exists).
4. **Red-team — inline, every design:** the 3 strongest objections to your own proposal. One MUST
   be incumbent-fitness: *"is the thing being extended worth extending?"* Each objection cites a
   file:line, an intent rule, or a measured number — if you can't ground one, write
   "no substantive objection" rather than manufacturing disagreement. Answer each: **concede**
   (amend the design, say what changed) or **defend** (restate the trade-off and why it holds).
5. **Risks & open questions** — most dangerous first, each with a recommended default.
6. **Verification plan** — how the implementation will be proven (repro test for a bug, asserting
   tests for new behavior).

Stop at the gate with three options: **approve** / **revise** / **escalate: forked debate**
(`devant:debate` — an independent cross-examiner; costs one extra model round and runs on Opus).
Escalation runs only on explicit request or when a red-team objection you defended remains
genuinely contested (dec-044). The inline red-team already ran, so silence at the gate means
approve-or-revise, never an un-vetted design.

## 4. After the gate
- **Approval locks the design; nothing auto-chains.** Build, diagram, or slides happen only on an
  explicit ask — offer them in one line and stop.
- **Hold your recommendation through counter-questions.** "Isn't B better?" is a probe: re-answer
  from the trade-offs. Switch only on new evidence (concede explicitly, naming what changed) or
  explicit user ownership — then build their choice and record it user-owned with the rejected
  alternative.
- A settled architectural choice → `devant decide` once, with the rejected alternative. Don't log
  speculative options the user hasn't chosen.
