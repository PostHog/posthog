# PostHog AI agent-run surface — frontend guide

This directory is the **composable PostHog AI agent-run UI**: a conversation-agnostic library of surfaces
that render and drive an agent run (the streamed thread, tool cards, approvals, the composer). It is
consumed by the Max scene (`frontend/src/scenes/max`) and the signals inbox — and is meant to be
embeddable anywhere an agent run needs to be shown or interacted with. The standalone runner scene
(`TaskTracker`, the `/tasks` route) lives here too, under `scenes/`.

> This used to live under a `sandbox/` subfolder behind a `Sandbox*` codename prefix; it's now laid out
> conventionally directly under `frontend/` with the prefix dropped. The word "sandbox" that remains is the
> agent _runtime_ (`agent_runtime === 'sandbox'`), a real domain term — not the old codename.

## 1. The public API is the barrel (`index.ts`)

Every external consumer imports from `products/posthog_ai/frontend` (the barrel) — **never** from deep
paths. The barrel is the contract; internal files can move freely behind it. The headline exports:

- **`RunViewer`** — Radix-style compound for an embeddable run. `RunViewer.Root` binds the stream logic and
  bootstraps the run; slots `RunViewer.Thread / .Prompt / .Composer / .Resources / .ContextUsage` compose a
  custom layout. Calling `RunViewer` directly (`<RunViewer .../>`) renders the prepackaged default layout —
  use that for the common embed.
- **`Thread`** — Radix-style compound for the run thread. `Thread.Root` is the virtualized presenter; the
  atoms `Thread.Message / .Markdown / .Reasoning / .Failure / .Activity / .ToolCall` are the same
  presentational building blocks, exposed for bespoke threads.
- **`Composer`** — logic-free compound input (`Composer.Root/Frame/Field/Placeholder/Textarea/Footer/Submit/
Banner`). The caller owns `value`/`onChange`/`onSubmit`; every part is a styled slot.
- **`runStreamLogic`** — the SSE stream + thread projection (see §3). **`runInteractionLogic`** — the
  Max-agnostic follow-up/queue interaction facade.
- Tool rendering: **`toolRegistry`**, `lookupToolRenderer`, `GenericMcpToolRenderer`,
  `ToolActivity`, `DataToolRow`, `EditDiffRenderer`, and the diff/exec helpers.
- Permission/question/resource surfaces, message presenters, and the folded-thread types.

## 2. Coupling boundary — couples to tasks runs, never to Max

This surface **couples to the tasks run API by design** (`products/tasks/frontend/generated/api`): a task +
its run + the SSE stream together _are_ the agent-run surface. Importing the tasks run/stream/command API
from the stream and interaction logics is expected.

It must stay **free of the Max scene and conversation orchestration**. Do not import `scenes/max/*`,
`maxThreadLogic`, `maxContextLogic`, `MaxUIContext`, or the conversations API from anywhere under
`products/posthog_ai/frontend`. Max is a _consumer_ of this surface, not a dependency of it.

- `runStreamLogic` keys on a generic `streamKey` (conversation id for Max, run/task id for a task
  viewer). Keep it generic — no Max-specific branching.
- **Product-specific tool renderers live in Max, not here.** Renderers that display PostHog product entities
  (insights, dashboards, recordings, error-tracking issues, notebooks, query results) live in
  `scenes/max/messages/adapters` and register themselves into `toolRegistry` via
  `registerMaxToolRenderers` (imported once by the Max scene). The shared registry only knows the built-ins,
  the exec verbs, the question card, the generic MCP card, and the generic `EditDiffRenderer`. Surfaces that
  never load Max (tasks, signals inbox) fall through to the generic card for those product keys — by design.
- If Max needs something the surface doesn't express generically, **lift it to a generic prop/selector here
  and have Max adapt** — never special-case Max in this directory. Enforced by a grep gate:
  `grep -rE "scenes/max|maxThreadLogic|MaxUIContext" products/posthog_ai/frontend` must be empty.

## 3. Streaming architecture (`logics/runStreamLogic.ts`)

The heart of the surface:

- **SSE connection** — a `fetch` body reader pumped through `eventsource-parser`; a reconnect resumes after
  the last Redis stream id via `Last-Event-ID` (capped exponential backoff + cumulative cap).
- **Ordered, append-only `log` is the single source of truth** — every wire frame (plus a few synthetic
  client entries) is appended, never keyed or per-entry deduped.
- **Pure projection** `foldLogToThread(entries) → { threadItems, toolInvocations }`, memoized on `log`
  identity, derives the rendered thread.
- **Keyed by `streamKey`** so concurrent streams stay independent.

**Permissions:** parse (`parsePermissionRequestFrame`) → route (`policy/toolPolicy` auto-approves
built-ins + read-only PostHog `exec`, else surfaces a card) → answer (`respondToPermission`) → resolve (pins
the id so a reconnect replay can't re-surface it).

Supporting modules live in `policy/` (tool policy + permission/question utils) and `types/`
(`streamTypes` = folded thread shapes; `wireTypes` = ACP wire shapes + guards). Wire types are
loosely typed — guard at the parse boundary with runtime checks; never assume a field is present.

## 4. Conventions

- **Logic in the logic, never in a component.** Wire parsing, log folding, SSE handling, telemetry, and
  permission routing belong in `runStreamLogic` (or a `policy/` sibling). Components consume selectors
  and dispatch actions.
- **Keep UI runtime-agnostic.** Render components take plain props (`ThreadItem`, `ToolInvocation`,
  `PermissionRequestRecord`); they know nothing about langgraph vs sandbox or the conversation.
- **Atomic components.** One responsibility per component — small memoized leaf presenters keyed by the
  stable item `id`, not a giant inline switch.
- **Memoize — `threadItems` re-projects on every appended frame.** Wrap leaves in `React.memo`, derive with
  `useMemo`, wrap child callbacks in `useCallback`, and subscribe narrowly (select only what you render).
- **Keep the projection pure.** `foldLogToThread` is pure and deterministic; item ids stay stable across
  re-folds. Listeners fire only side effects, each with a fire-once guard, suppressed on `source: 'replay'`.

## 5. Layout

```text
index.ts            # public API barrel (the contract)
components/         # RunViewer, Thread, Composer, permission/question/resource surfaces, activity, tool/
  composer/         #   the Composer compound
  tool/             #   tool registry + renderers (built-ins, generic MCP, EditDiffRenderer, diff/exec utils)
logics/             # runStreamLogic, runInteractionLogic; tasksLogic/taskLogic data logics (+ *LogicType.ts)
policy/             # tool policy + permission/question utils
types/              # streamTypes (folded thread), wireTypes (ACP), toolTypes, taskTypes (task/run domain)
messages/           # MessageTemplate, MarkdownMessage, ReasoningAnswer, AssistantFailureMessage
utils/              # thinkingMessages
lib/                # task/run helpers (parse-logs, task-status, repository, ph-debug, util-functions)
scenes/             # standalone scenes registered via ../manifest.tsx
  TaskTracker/      #   the runner scene (component, stories, scene logics, scene-specific components/)
generated/          # auto-generated API types (mcp_tools / docs_search) — do not edit by hand
```
