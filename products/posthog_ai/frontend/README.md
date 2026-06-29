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
import { RunViewer } from 'products/posthog_ai/frontend/api/run'
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

| Tier                           | Module                     | What's in it                                                                                                                                                                                                                  | Use when                                                                                    |
| ------------------------------ | -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| **1 — Prepackaged surfaces**   | `api/run`                  | `RunViewer` (lazy, code-split embeddable → default layout), `RunComposer`                                                                                                                                                     | "Just show/drive a run." Inbox read-only embed, tasks embed.                                |
| **2 — Compound primitives**    | `api/primitives`           | `Thread` + atoms (`.Message/.Markdown/.Reasoning/.Failure/.Activity/.ToolCall`), `ThreadView`, `Composer.*`, `RunLogSkeleton`, activity primitives + `RunActivity`, message presenters, permission/question/resource surfaces | Custom layout, or a bespoke/compact thread.                                                 |
| **3 — Headless logic + types** | `api/logics` + `api/types` | `runStreamLogic`, `runInteractionLogic`, status helpers (`isTerminalRunStatus`, `INITIAL_PERMISSION_MODE`), thinking-message helpers; folded-thread + tool types                                                              | Status badge or automation — no React, no registry.                                         |
| **4 — Extension seam**         | `api/tools`                | `toolRegistry`, `registerToolRenderers`, `lookupToolRenderer`, `GenericMcpToolRenderer`, `DataToolRow`, `ToolActivity`, `FilePath`, diff helpers                                                                              | Your product renders tool cards (insights, dashboards…). Register them from your own scene. |

`api/run` (Tier 1) is built on `api/primitives` (Tier 2); `api/primitives` consumes the headless
`api/logics`/`api/types` (Tier 3). Going down a tier trades convenience for control and a smaller chunk.

`RunViewer` is **lazy by default** — code-split behind a `RunLogSkeleton` Suspense fallback — because the
embeds that use it (the inbox detail views) show it as a secondary panel. A surface where the run viewer is
the _primary_ content of an already-code-split route (the `/tasks` runner scene) is the exception: it renders
the eager implementation directly so it doesn't pay a second chunk fetch + Suspense flash for the one thing
the route exists to show.

## 3. Recipes

Each recipe shows the granular import to copy.

### Read-only embed (inbox-style)

```tsx
import { RunViewer } from 'products/posthog_ai/frontend/api/run'
;<RunViewer taskId={task.id} runId={run.id} interaction="read-only" />
```

### Live embed with composer + queue (tasks-style; caller owns draft/queue)

```tsx
import { RunViewer } from 'products/posthog_ai/frontend/api/run'
import { runInteractionLogic, type RunInteractionLogicProps } from 'products/posthog_ai/frontend/api/logics'

// Bind runInteractionLogic for the follow-up/queue facade, then render the viewer with a composer slot.
const { queuedMessages } = useValues(runInteractionLogic(props))
<RunViewer taskId={task.id} runId={run.id} />
```

### Custom layout via `Thread.*` + the run primitives

`RunViewer` (Tier 1) is a single lazy embeddable — it renders the default layout and intentionally does
not surface slot atoms (no consumer composed them, and lazy-wrapping each would only add Suspense
boundaries that never fire). For a custom layout, bind `runStreamLogic` yourself and compose the Tier 2
primitives (`ThreadView`, `ResourcesBar`, `PermissionInput`, `Composer.*`, `ContextUsageBar`) — use
`RunLogSkeleton` for the loading state so the surface keeps its shape.

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
