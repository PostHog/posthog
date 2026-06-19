# Instrumentation-gap detection rules

These are the heuristics the dreaming run applies to each merged PR's diff. They mirror the
implementation in `products/signals/backend/temporal/dreaming/instrumentation_gaps.py` — keep
the two in sync if either changes.

## Principle: precision over recall

The output feeds a single consolidated PR that humans review. A false positive there costs
reviewer trust and trains people to ignore the dreaming PR. A false negative is cheap — the
next nightly run catches a real gap you missed. So **when in doubt, leave it out.**

## Scope

Only added lines (`+` in the unified diff) are considered — we suggest instrumentation for
_new_ code, not pre-existing code the PR happened to touch.

Files that are never analyzed:

- non-source files (only `.py`, `.ts`, `.tsx`, `.js`, `.jsx`),
- generated code, migrations, vendored deps (`/generated/`, `/migrations/`, `/node_modules/`),
- snapshots and minified/declaration files (`/__snapshots__/`, `.min.js`, `.d.ts`),
- test files (`/test/`, `/tests/`, `/__tests__/`, `test_*`, `*_test.*`, `*.test.*`, `*.spec.*`).

## The three gap categories

### Product analytics

**Trigger:** an added line introduces user-facing surface — a `def`/handler whose name looks
like a view/handler/endpoint/action/submit/create/update/delete, a route decorator
(`@app.post(...)` etc.), a React `onClick`/`onSubmit`/`onChange` handler, or a button.

**Clear (no gap):** the same diff already contains a `capture(...)` / `ph_scoped_capture(...)`
call.

**Gap:** new surface, no capture. Suggest capturing the relevant user action.

### Error tracking

**Trigger:** an added `except ...:` (Python) or `} catch (...)` (JS/TS) block.

**Clear (no gap):** the diff re-raises (`raise` / `throw`) — the error propagates, so it isn't
swallowed — OR it already reports via `capture_exception(...)` / `captureException(...)`.

**Gap:** a new handler that neither re-raises nor reports. Suggest `capture_exception(...)`.

### LLM analytics / observability

**Trigger:** an added raw LLM provider call — `OpenAI(...)`, `Anthropic(...)`, their async
variants, `.chat.completions.create(...)`, `.messages.create(...)`, or the Vercel AI SDK
`generateText`/`streamText`.

**Clear (no gap):** the diff routes through PostHog LLM observability — `posthog.ai`,
`@observe`, `PostHogCallback`, `posthog/ai`, or `withTracing`.

**Gap:** a raw LLM call with no observability wrapper. Suggest wrapping it so traces, tokens,
and cost are captured.

## Output

At most one gap **per kind per file**, so a file with three swallowed excepts produces one
error-tracking suggestion, not three. Gaps are grouped by PR in the cleanup PR's checklist and
description.
