# Sharpen-the-ask guide — distilled Anthropic prompt engineering

The rules the router's step 1.5 applies when a request is vague or under-specified. Distilled
from Anthropic's prompting best practices and the Console prompt improver; stable principles
only — model-specific tips live at
https://platform.claude.com/docs/en/docs/build-with-claude/prompt-engineering/overview.

## Always — what the sharpened ask must contain

- **Done-condition first.** A prompt without success criteria can't be "the best": state what
  observable outcome makes this done (a passing test, a rendered file, an answered question).
- **Golden rule.** If a colleague with minimal context would be confused by the ask, so will the
  model. Sharpen until a first-time reader needs no follow-up question.
- **Clear and direct.** Name the concrete outcome, not the activity ("make the login error show
  the retry hint" beats "improve login").
- **Keep the motivation.** Carry the *why* behind a constraint into the restatement — the reason
  generalizes better than the bare rule.
- **Positive instructions.** Say what to do, not what to avoid ("write flowing prose" beats
  "don't use bullets").
- **Minimal.** The sharpened ask is **outcome + scope + done-condition in ≤3 lines** — sharpening
  is compression, not expansion.

## Only for complex or data-carrying asks

Anthropic's own prompt improver targets complex tasks, not every request — mirror that scoping;
never apply these to a simple ask.

- **XML tags** to separate instructions from data when the ask carries logs, code, or documents
  (`<instructions>`, `<input>`, `<context>`).
- **3–5 examples**, relevant and diverse, in `<example>` tags, when output format/tone matters
  more than the words can convey.
- **Role framing** (one sentence) when a perspective focuses the work ("as the release manager…").
