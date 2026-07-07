# PostHog AI agent-run surface — consumer guide

This directory is the **conversation-agnostic agent-run UI**: a library that renders and drives a streamed
agent run — the thread, tool cards, approvals, the composer. If you're embedding a run, showing a status
badge, or registering a product's tool cards, you consume it from here.

> Building _on_ the surface (adding a thread-item type, a permission rule, stream telemetry)? That's the
> contributor guide — [`AGENTS.md`](./AGENTS.md) — not this file.

## 1. How to import — the one rule

Import from a domain-scoped **`api/<module>`** entry. Never reach into deep internal paths
(`../components/...`, `../logics/...`); the `api/` modules are the contract and internal files move behind
them. The `products/*` path alias is configured in tsconfig, so the import is absolute:

```ts
import { ReadonlyRunSurface } from 'products/posthog_ai/frontend/api/readableRun'
import { isTerminalRunStatus } from 'products/posthog_ai/frontend/api/logics'
```

**Prefer the narrowest module that does the job.** The split exists to preserve code-splitting: the
side-effectful tool registry (`api/tools`) and the markdown/virtualization-heavy thread (`api/primitives`)
must not leak into a bundle that only needs a status helper from `api/logics`. A status badge that imports
a fat path drags presenters and the registry into its chunk; importing `api/logics` alone does not.

There is deliberately **no root `index.ts` barrel** — a barrel that re-exports every tier would
re-introduce the exact bundling problem the split solves. Always import an `api/<module>`.

## 2. Which surface do I use?

Pick the **lowest tier** that does the job.

| Tier                           | Module                                              | What's in it                                                                                                                                                                                                                                                                                                                                               | Use when                                                                                                                                                                    |
| ------------------------------ | --------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **1 — Prepackaged surfaces**   | `api/readableRun` + `api/runSurface` + `api/runner` | `ReadonlyRunSurface` (lazy, code-split read-only embed); the `RunSurface` compound (`Root` + slots, eager) for custom layouts; `EmbeddedRunner` (lazy TaskTracker product for inline hosts)                                                                                                                                                                | "Just show a run" → `ReadonlyRunSurface` (inbox embeds). "Drive a run / custom layout" → `RunSurface` (tasks). "Embed the whole `/tasks` product" → `EmbeddedRunner` (Max). |
| **2 — Compound primitives**    | `api/primitives`                                    | `Thread` + atoms (`.Message/.Markdown/.Reasoning/.Failure/.Activity/.ToolCall`), `ThreadView`, `Composer.*`, `QueuedMessageList`, `RunLogSkeleton`, activity primitives + `RunActivity`, message presenters, permission/question/resource surfaces                                                                                                         | Custom layout, or a bespoke/compact thread.                                                                                                                                 |
| **3 — Headless logic + types** | `api/logics` + `api/types`                          | `runStreamLogic`, `runInteractionLogic`, status helpers (`isTerminalRunStatus`, `INITIAL_PERMISSION_MODE`), thinking-message helpers, context injection (`attachedContextLogic`, `useAttachedContext`), tool-stream subscriptions (`toolStreamEventsLogic`, `useToolStreamListener`); folded-thread + tool types, `AttachedContextItem`, `ToolStreamEvent` | Status badge, automation, context injection, tool-event listeners — no presenters, no registry.                                                                             |
| **4 — Extension seam**         | `api/tools`                                         | `toolRegistry`, `registerToolRenderers`, `lookupToolRenderer`, `GenericMcpToolRenderer`, `DataToolRow`, `ToolActivity`, `FilePath`, diff helpers                                                                                                                                                                                                           | Your product renders tool cards (insights, dashboards…). Register them from your own scene.                                                                                 |

The Tier 1 surfaces are built on `api/primitives` (Tier 2), which consumes the headless
`api/logics`/`api/types` (Tier 3). Going down a tier trades convenience for control and a smaller chunk.

`ReadonlyRunSurface` is **lazy by default** — code-split behind a `RunLogSkeleton` Suspense fallback —
because the embeds that use it (the inbox detail views) show it as a secondary panel. The `RunSurface`
compound (`api/runSurface`) is **eager**: import it only where the surface is the _primary_ content of an
already-code-split route (the `/tasks` runner scene composes its own live-composer layout), so it doesn't pay
a second chunk fetch + Suspense flash for the one thing the route exists to show.

## 3. Recipes

Each recipe shows the granular import to copy.

### Read-only embed (inbox-style)

```tsx
import { ReadonlyRunSurface } from 'products/posthog_ai/frontend/api/readableRun'
;<ReadonlyRunSurface taskId={task.id} runId={run.id} interaction="read-only" />
```

The prepackaged, lazy read-only surface: thread (plus the meta bars for a live run), no composer and no
approval prompt. It streams fresh frames while running when `interaction='live'`, and replays the snapshot
once when `'read-only'`. This is what all three inbox embeds drop in.

### Live embed with composer (tasks-style; caller owns the composer + draft/queue)

Compose the `RunSurface` compound (`api/runSurface`, eager) and pass your composer UI as the
`RunSurface.Composer` children — the slot owns prompt-vs-composer precedence and the null-bootstrap gate; you
own the composer. See `scenes/TaskTracker/components/TaskRunChat.tsx` for the full wiring.

```tsx
import { RunSurface } from 'products/posthog_ai/frontend/api/runSurface'
import { Composer, QueuedMessageList } from 'products/posthog_ai/frontend/api/primitives'
import { runInteractionLogic } from 'products/posthog_ai/frontend/api/logics'

// Bind runInteractionLogic (the follow-up/queue facade) keyed by the same runId RunSurface.Root binds.
const { draft, isSubmitting, isBusy, queuedMessages } = useValues(runInteractionLogic(props))
const { cancelRun } = useActions(runInteractionLogic(props))
;<RunSurface.Root taskId={task.id} runId={run.id} interaction="live">
  <div className="@container/thread flex flex-col h-full overflow-hidden">
    <div className="flex-1 min-h-0">
      <RunSurface.Thread />
    </div>
    <RunSurface.Resources />
    <RunSurface.Composer>
      <Composer.Root
        value={draft}
        onChange={setDraft}
        onSubmit={submit}
        loading={isSubmitting}
        isTurnActive={isBusy}
        onStop={() => cancelRun()}
      >
        {/* …Composer.Frame / Field / Textarea / Submit… */}
      </Composer.Root>
    </RunSurface.Composer>
    <RunSurface.ContextUsage />
  </div>
</RunSurface.Root>
```

Pass `isTurnActive` + `onStop` to make the send button a **Stop** button while the agent is working a turn and
the input is empty (clicking cancels the run); with drafted text it stays **Send** and queues the follow-up.
Omit both for a send-only composer.

### Custom layout via the `RunSurface` compound

`RunSurface.Root` (Tier 1, `api/runSurface`) binds the stream logic and bootstraps the run; the slots
(`.Thread/.Composer/.Resources/.ContextUsage`) compose into any layout — there is no default. Omit
`RunSurface.Composer` for a no-input surface (that's exactly what `ReadonlyRunSurface` does); render it with
composer children for an interactive one. For something even more bespoke, drop to the Tier 2 primitives
(`ThreadView`, `ResourcesBar`, `Composer.*`, `ContextUsageBar`) and bind `runStreamLogic` yourself.

### Optimistically open a run before it exists

To show the thread the instant a user hits send — their message + a "spinning up" indicator — before the
create/run round-trips finish, mount `RunSurface.Root` in its **pending** state (a `null` `runId` keyed by a
client `streamKey`), seed it via `runStreamLogic.startOptimisticRun(message)`, then supply the real `runId`
once created; the surface attaches it (preserving the seed) and the live SSE echo dedups the message.

```tsx
import { runStreamLogic } from 'products/posthog_ai/frontend/api/logics'
import { RunSurface } from 'products/posthog_ai/frontend/api/runSurface'

const streamKey = `draft-${uuid()}`
const stream = runStreamLogic({ streamKey })
stream.mount() // hold it across the render swap; release when done
stream.actions.startOptimisticRun(message) // empty → "spinning up" + the typed message

// render the pending surface (no run yet):
;<RunSurface.Root taskId="" runId={null} streamKey={streamKey} interaction="live">
  <RunSurface.Thread />
</RunSurface.Root>

// …after api create/run resolve, set runId on the same surface to attach + stream it.
```

The attach is **idempotent and seed-preserving** via `runStreamLogic`'s `bootstrappedRunId` /
`awaitingOptimisticAttach` state — so the run can be adopted by a _different_ surface that mounts later, not
only by an in-place `runId` flip. A consumer that navigates (e.g. `/tasks/new → /tasks/:id`) keeps the seeded
instance alive (hold the manual `.mount()`), then has the destination surface bind the **same `streamKey`** plus
the real `runId`: `RunSurface.Root` sees the instance is already bootstrapped for that run and adopts it without
a `reset()` — no skeleton re-flash, the thread is continuous across the unmount/mount. If that destination also
drives `runInteractionLogic`, pass it the same `streamKey` (a `streamKey ?? runId` connect-key) so the composer
reads the exact stream the thread renders; `runInteractionLogic` still keys its own per-run state by `runId`.

The tasks runner composes exactly this (`scenes/TaskTracker/taskTrackerSceneLogic.ts` + `TaskCreateThread` for
the pending phase, then `TaskDetailPage → TaskRunLog → TaskRunChat` adopting the seeded stream after navigation).

### Bespoke / compact thread via `Thread.*` atoms

```tsx
import { Thread } from 'products/posthog_ai/frontend/api/primitives'

// Compose only the atoms you want — e.g. a compact inline preview that drops the activity/tool chrome.
;<Thread.Root items={items}>{(item) => <Thread.Message item={item} />}</Thread.Root>
```

### Register product tool renderers (Tier 4)

```tsx
import { registerToolRenderers, type ToolRegistryEntry } from 'products/posthog_ai/frontend/api/tools'

// Call once from your scene's entrypoint. Tools without an adapter fall through to the generic MCP card.
registerToolRenderers([
  { key: 'my-product-tool', displayName: 'My tool', icon: <IconWrench />, Renderer: MyToolRenderer },
])
```

This is the generic per-product mechanism. Max is its first consumer
(`scenes/max/messages/adapters/registerMaxToolRenderers`), not a special case.

### Headless status badge / automation

```ts
import { runStreamLogic, isTerminalRunStatus } from 'products/posthog_ai/frontend/api/logics'

const { currentRunStatus } = useValues(runStreamLogic({ streamKey }))
const done = isTerminalRunStatus(currentRunStatus)
```

No React presenters, no tool registry — this import lane stays out of those chunks.

### Inject context the agent should see

Register the resource(s) the user is looking at; while registered, every message sent from the surface is
prefixed with an invisible `<posthog_context>` block describing them (the user only ever sees their own
text). Items are abstract — `type` is any string (`'insight'`, `'trace'`, `'text'`…), plus
`key`/`label`/`value` — and are deduped across providers and across sends within a task (the whole
resume chain of runs, matching the backend's per-task semantics; except `text`, which always resends).

```tsx
import { useAttachedContext } from 'products/posthog_ai/frontend/api/logics'

// In your scene/component — registered while mounted, removed on unmount:
useAttachedContext([{ type: 'insight', key: insight.short_id, label: insight.name }])
```

JSX-only call sites can render `<AttachedContextProvider items={...} />` (`api/primitives`) instead.

From a kea logic, connect to `attachedContextLogic` and register through a disposable (the repo-preferred
teardown idiom — see `/using-kea-disposables`); the returned cleanup deregisters on unmount, no
`beforeUnmount` needed. Pass `pauseOnPageHidden: false`: the registration costs nothing while idle, and the
default hide-pause would silently drop context from a queued follow-up that flushes while the tab is hidden.

```ts
afterMount(({ actions, cache, values }) => {
  cache.disposables.add(
    () => {
      actions.registerContext('my-scene', [{ type: 'dashboard', key: values.dashboard.id }])
      return () => actions.deregisterContext('my-scene')
    },
    'attachedContext',
    { pauseOnPageHidden: false }
  )
})
```

Re-dispatching `registerContext` with the same provider id (e.g. from a `subscriptions` handler when the
resource changes) is an upsert — see `scenes/max/posthogAiContextBridgeLogic.ts` for the full shape.

### React to the agent invoking a tool

Subscribe to tool-call lifecycle events (resolved tool names) — e.g. refresh a list when the agent creates
a dashboard. Replay events are suppressed by default so a page reload never re-triggers your handler; opt
in with `includeReplay` if you need them.

```ts
import { useToolStreamListener } from 'products/posthog_ai/frontend/api/logics'

useToolStreamListener({
  tools: ['create_dashboard'],
  onEvent: (event) => {
    if (event.phase === 'completed') {
      loadDashboards()
    }
  },
})
```

From a kea logic, either connect to `toolStreamEventsLogic` and listen to its `emitToolEvent` action (you
filter everything yourself, including `event.source`), or register a subscription through a disposable —
same shape as the context recipe above, calling `registerToolListener(listenerId, { tools, onEvent })` in
setup and `deregisterToolListener(listenerId)` in cleanup, with `pauseOnPageHidden: false` (tool events fire
while the tab is hidden and missed live events are not redelivered).

Note: for exec-wrapped PostHog tools the resolved name can be unknown at `phase: 'started'` (the command
streams in later) — match on `completed` when you need certainty.

## 4. Coupling boundary

This surface **couples to the tasks run API by design** (`products/tasks/frontend/generated/api`) and
**never to Max or the conversations API** — Max is a consumer, not a dependency. The full rule (and the
grep gate that enforces it) is in [`AGENTS.md`](./AGENTS.md#2-coupling-boundary--couples-to-tasks-runs-never-to-max).

## 5. Replacement-ready by design

This surface is the intended replacement for Max's legacy LangGraph thread. The new-vs-legacy switch is a
**consumer concern** (Max routes `agent_runtime === 'sandbox'` conversations through `runStreamLogic` and
renders this surface; its LangGraph path renders its own thread). The surface never branches on
Max/LangGraph/conversation. Anything the LangGraph path owns that the surface doesn't express generically
(agent modes, billing context, scene attachments) stays in Max and feeds the surface through generic props
/ the tool registry / `streamKey` — lifted to a generic seam here, never special-cased. The four-tier
contract above is unchanged whichever side of the switch is active. See
[`AGENTS.md`](./AGENTS.md#6-replacement-readiness) for the contributor-side detail.
