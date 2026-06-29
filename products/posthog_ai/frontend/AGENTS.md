# PostHog AI agent-run surface — frontend guide

This directory is the **composable PostHog AI agent-run UI**: a conversation-agnostic library of surfaces
that render and drive an agent run (the streamed thread, tool cards, approvals, the composer). It is
consumed by the Max scene (`frontend/src/scenes/max`) and the signals inbox — and is meant to be
embeddable anywhere an agent run needs to be shown or interacted with. The standalone runner scene
(`TaskTracker`, the `/tasks` route) lives here too, under `scenes/`.

> This used to live under a `sandbox/` subfolder behind a `Sandbox*` codename prefix; it's now laid out
> conventionally directly under `frontend/` with the prefix dropped. The word "sandbox" that remains is the
> agent _runtime_ (`agent_runtime === 'sandbox'`), a real domain term — not the old codename.

## 1. The public API is the `api/<module>` facade

Every external consumer imports from a domain-scoped **`api/<module>`** entry — **never** from deep paths
(`components/...`, `logics/...`). The `api/` modules are the contract; internal files move freely behind
them. There are four tiers, split along dependency/side-effect boundaries (not cosmetics — that's what
preserves code-splitting). Consumers pick the **lowest tier** that does the job. The full decision table,
import rule, and copy-paste recipes live in the consumer-facing [`README.md`](./README.md); the summary:

| Tier                           | Module                     | What's in it                                                                                                                                                   |
| ------------------------------ | -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **1 — Prepackaged surfaces**   | `api/run`                  | `RunViewer` (lazy, code-split embeddable → default layout), `RunComposer`                                                                                      |
| **2 — Compound primitives**    | `api/primitives`           | `Thread` + atoms, `ThreadView`, `Composer.*`, `RunLogSkeleton`, activity primitives + `RunActivity`, message presenters, permission/question/resource surfaces |
| **3 — Headless logic + types** | `api/logics` + `api/types` | `runStreamLogic`, `runInteractionLogic`, status + thinking helpers; folded-thread + tool types                                                                 |
| **4 — Extension seam**         | `api/tools`                | `toolRegistry`, `registerToolRenderers`, `lookupToolRenderer`, `GenericMcpToolRenderer`, `DataToolRow`, `ToolActivity`, `FilePath`, diff helpers               |

**Why the split, not one flat barrel:** the tool registry registers built-ins at module load — a top-level
side effect that is _not_ tree-shaken. A single barrel statically re-exports it alongside the
markdown/virtualization-heavy thread and the headless logics, so a consumer wanting only
`isTerminalRunStatus` for a status badge would drag the registry + presenters into its chunk. Isolating the
side-effectful registry in `api/tools` and keeping the headless lane (`api/logics` + `api/types`) free of
React/registry imports is what keeps each consumer's bundle to its subtree.

There is deliberately **no root `index.ts` barrel**: a single aggregate that re-exports every tier would
re-fatten any consumer's chunk and undo the split. It also wouldn't match the repo norm — no other
`products/*/frontend` ships a barrel; consumers import the specific path they need. Every public symbol is
reached through an `api/<module>` entry; add new exports to the relevant tier module, not to a new barrel.

The headline exports per module:

- **`api/run`** — **`RunViewer`**, the lazy, code-split embeddable: calling `<RunViewer .../>` binds the
  stream logic and renders the default layout behind a `RunLogSkeleton` Suspense fallback (the heavy chunk —
  stream logic, virtualized thread, tool/diff renderers — loads on demand). This is the form every **embed**
  uses (the inbox detail views), where the viewer is a secondary panel worth splitting out. The one exception
  is the **runner scene** (`scenes/TaskTracker`), which renders `components/RunViewerImpl` **directly (eager,
  relative import)**: the `/tasks` route is already a code-split scene chunk and the viewer is its primary
  content, so a second `lazy()` would only add a redundant chunk fetch + Suspense flash. The compound
  (`Root` plus the `.Thread/.Prompt/.Composer/.Resources/.ContextUsage` slots) stays internal to
  `components/RunViewerImpl` backing the default layout, not surfaced (no consumer composes the slots, and
  lazy-wrapping each would only add Suspense boundaries that never fire). For a custom layout, bind
  `runStreamLogic` and compose the Tier 2 primitives. Also **`RunComposer`**.
- **`api/primitives`** — **`Thread`** (Radix-style compound: `Thread.Root` is the virtualized presenter, the
  atoms `Thread.Message/.Markdown/.Reasoning/.Failure/.Activity/.ToolCall` are the building blocks for
  bespoke threads), **`Composer`** (logic-free compound input — the caller owns
  `value`/`onChange`/`onSubmit`), **`RunLogSkeleton`** (the shared "run log is loading" loader — the
  `RunViewer` Suspense/bootstrap fallback, also used by the runner scene), activity primitives, message
  presenters, and the permission/question/resource surfaces.
- **`api/logics`** — **`runStreamLogic`** (SSE stream + thread projection, see §3),
  **`runInteractionLogic`** (Max-agnostic follow-up/queue facade), status helpers
  (`isTerminalRunStatus`, `INITIAL_PERMISSION_MODE`), and thinking-message helpers. Imports only
  `logics/*` + `utils/*` — never a component or the registry, so it's the clean headless lane.
- **`api/types`** — folded-thread + tool domain types (pure types).
- **`api/tools`** — **`toolRegistry`**, **`registerToolRenderers`** (the generic per-product seam, see §2),
  `lookupToolRenderer`, `GenericMcpToolRenderer`, `DataToolRow`, `ToolActivity`, `FilePath`, and the
  diff/exec helpers. Isolated here because importing it pulls the side-effectful registry chunk.

## 2. Coupling boundary — couples to tasks runs, never to Max

This surface **couples to the tasks run API by design** (`products/tasks/frontend/generated/api`): a task +
its run + the SSE stream together _are_ the agent-run surface. Importing the tasks run/stream/command API
from the stream and interaction logics is expected.

It must stay **free of the Max scene and conversation orchestration**. Do not import `scenes/max/*`,
`maxThreadLogic`, `maxContextLogic`, `MaxUIContext`, or the conversations API from anywhere under
`products/posthog_ai/frontend`. Max is a _consumer_ of this surface, not a dependency of it.

- `runStreamLogic` keys on a generic `streamKey` (conversation id for Max, run/task id for a task
  viewer). Keep it generic — no Max-specific branching.
- **Product-specific tool renderers live in the consuming product, not here — via the generic seam.**
  `api/tools` exposes `toolRegistry` and the convenience wrapper **`registerToolRenderers(entries)`**: the
  generic per-product mechanism for a product to plug in cards that display its own entities. A product
  registers from its own scene's entrypoint; the shared registry stays free of product imports. **Max is
  the first consumer of this pattern, not a special case** — its renderers (insights, dashboards,
  recordings, error-tracking issues, notebooks, query results) live in `scenes/max/messages/adapters` and
  call `registerToolRenderers` via `registerMaxToolRenderers` (imported once by the Max scene). The shared
  registry only knows the built-ins, the exec verbs, the question card, the generic MCP card, and the
  generic `EditDiffRenderer`. Surfaces without an adapter for a key (tasks, signals inbox) fall through to
  the generic card — by design.
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
api/                # public API facade — the contract (import api/<module>, never deep paths)
  run.ts            #   Tier 1: RunViewer, RunComposer
  primitives.ts     #   Tier 2: Composer, Thread + atoms, ThreadView, presenters, perm/question/resource
  logics.ts         #   Tier 3: runStreamLogic, runInteractionLogic, status + thinking helpers (headless)
  types.ts          #   Tier 3: folded-thread + tool domain types (pure types)
  tools.ts          #   Tier 4: toolRegistry + registerToolRenderers seam (side-effectful — isolated)
components/         # RunViewer (lazy wrapper) + RunViewerImpl (heavy chunk), RunLogSkeleton (shared loader),
                    #   Thread, Composer, permission/question/resource surfaces, activity, tool/
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

## 6. Replacement-readiness

This surface is the intended replacement for Max's **legacy LangGraph thread**. The design keeps the
eventual switch clean, so build with it in mind:

- **The new-vs-legacy switch is a consumer concern, not this surface's.** Max already routes
  `conversation.agent_runtime === 'sandbox'` through `runStreamLogic` (keyed by `conversationId`) and renders
  `threadItems` via this surface, while its LangGraph `EventSource` path renders Max's own thread. **This
  surface must never branch on Max/LangGraph/conversation** — enforced by the §2 grep gate.
- **For full replacement, what the LangGraph path owns that the surface doesn't express generically** —
  agent modes, billing context, scene attachments/context — **stays in Max as a consumer** and feeds the
  surface through generic props / the tool registry / `streamKey`. If the surface needs it, lift it to a
  generic seam here; never special-case Max. The setting flips the default implementation **in Max**; this
  surface's contract (the four tiers in §1) is unchanged whichever side of the switch is active.
