# Solid & lean code — the concrete bar

The checklist that `work` §7 and the `review` skill point at instead of restating. Apply it
**scaled to risk** — a throwaway script and an auth path do not earn the same bar. Grounded in
Anthropic's agent-engineering posture (favor simple, debuggable designs over clever ones) and
long-standing practice (The Pragmatic Programmer; Ousterhout, *A Philosophy of Software Design*;
Metz on the cost of the wrong abstraction) — not invented rules.

## Solid — it holds up when reality misbehaves

- **Handle the failures that can actually happen; ignore the ones that can't.** A dependency
  down/slow/returning garbage, a partial write, a race — each needs defined behavior. Don't invent
  handling for impossible states; that's noise wearing safety's clothes.
- **Fail loud or fail open — on purpose, per call site, visibly.** Never swallow an error to keep
  going quietly. This repo's own hooks fail *open* by deliberate choice, not accident.
- **Validate at the boundary.** Untrusted input is checked where it enters, not deep in the stack
  where the assumption is already load-bearing.
- **Least privilege, idempotent, no secrets in code or logs** for anything risky or retried — a
  retried non-idempotent write is a bug waiting for its trigger.
- **Guard clauses over deep nesting.** Return early on the exceptional case; keep the happy path
  flat enough to read in one pass.
- **Effects at the edges, logic in a pure core.** Pure functions are testable; a testability smell
  is a design smell.

## Lean — the cheapest code that is still solid

- **YAGNI.** Build for the requirement in front of you — no configurability or extension point
  nobody asked for. Speculative generality is debt you start paying interest on immediately.
- **Rule of three.** Don't abstract until the third real use; a wrong abstraction costs more than
  the duplication it removed ("duplication is far cheaper than the wrong abstraction").
- **Every dependency is a liability.** A new import is a permanent cost — supply chain, version
  drift, portability. This repo's stdlib-only core is that principle taken to its conclusion.
- **Delete first.** The best change is often less code; removing a special case beats adding a
  handler for it.
- **Reads clearly in six months.** Name for intent; comment only the non-obvious *why*. The next
  maintainer, not the compiler, is the audience.
