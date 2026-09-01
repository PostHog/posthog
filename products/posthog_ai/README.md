# PostHog AI

PostHog AI is the agent that works alongside the user inside PostHog. This README is for **engineers on other product teams**: read it to make your product work with the agent.

> Building the agent surface itself? That's [`frontend/AGENTS.md`](./frontend/AGENTS.md). Consuming the run UI in detail? [`frontend/README.md`](./frontend/README.md). This file is the integration entry point.

## Where PostHog AI renders

Your integration can show up in any of these:

| Surface            | Where                                                                                                                                              |
| ------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| **The side panel** | Anywhere in the app, beside the page the user is on. This is what makes reactivity useful — the agent works while the user watches their own form. |
| `/ai`              | The full-page scene (`frontend/src/scenes/max/`). `/max` redirects here; `/ai/history` is the thread list.                                         |
| `/home`            | The AI-first homepage variant embeds an instance (`frontend/src/scenes/project-homepage/ai-first/AiFirstHomepage.tsx`).                            |
| `/tasks`           | The standalone runner scene (`frontend/scenes/TaskTracker/`).                                                                                      |
| Signals inbox      | Read-only embeds of a finished run.                                                                                                                |

There are two runtimes, picked per conversation by `conversation.agent_runtime`. **`sandbox` is where all new work goes.** `langgraph` is the legacy runtime and is frozen — do not extend it.

## There is no backend integration API

Nothing you build here talks to a PostHog AI backend. An integration has two halves:

1. **Give the agent the capability** — ship **MCP tools** for your product. That is how the agent reads and writes your entities. See [`/implementing-mcp-tools`](../../.agents/skills/implementing-mcp-tools/SKILL.md) and `products/<name>/mcp/tools.yaml`.
2. **Make your UI cooperate** — the frontend seams below.

Seam 1 depends on step 1: injected context is a set of _references_, and a reference the agent has no tool to resolve is a dead end.

## The import rule

Import from a domain-scoped `api/<module>` entry. Never reach into `components/...` or `logics/...`, and note there is deliberately no root barrel:

```ts
import { useAttachedContext, useToolStreamListener } from 'products/posthog_ai/frontend/api/logics'
import { registerToolRenderers } from 'products/posthog_ai/frontend/api/tools'
```

Pick the narrowest module that does the job — the split preserves code-splitting, and a fat import drags the markdown/virtualization thread or the side-effectful tool registry into your chunk. The full tier table lives in [`frontend/README.md`](./frontend/README.md#2-which-surface-do-i-use).

## Seam 1 — inject context

Register what the user is looking at. While registered, every message sent from the surface is silently prefixed with a context block describing it; the user only ever sees their own text.

```tsx
import { useAttachedContext } from 'products/posthog_ai/frontend/api/logics'

useAttachedContext(dashboard ? [{ type: 'dashboard', key: dashboard.id, label: dashboard.name ?? undefined }] : null)
```

Items are abstract: `type` is any string you like (`'insight'`, `'trace'`, `'text'`, `'hog_flow_editor_state'` — never an enum), plus optional `key`, `label`, `value`, `hidden`, and `dismissGroup`. JSX-only call sites can render `<AttachedContextProvider items={...} />` from `api/primitives`. From a kea logic, `connect` to `attachedContextLogic` and register through a disposable with `pauseOnPageHidden: false` — a hide-paused registration would drop context from a send that happens while the tab is hidden.

Three rules:

- **Inject identifiers, not object shapes.** The agent fetches details itself through your MCP tools. A full serialized entity costs tokens on every single message in the conversation, and large payloads risk being rejected or truncated on the way up. The one exception is **unsaved progress the agent cannot fetch** — live form state. Budget it: `products/workflows/frontend/Workflows/workflowAgentContext.ts` caps its editor state at `EDITOR_STATE_MAX_CHARS = 64_000` and _elides_ oversized parts rather than truncating, so the JSON stays parseable.
- **This context is untrusted.** It lands in `<posthog_untrusted_context>`, behind hardening prose. That is what makes it safe to inject whatever the user typed — which you should, since their unsaved work is the most useful thing you have.
- **Strip secrets before you serialize.** Saved secrets never reach the frontend, but a secret typed into a form and not yet saved sits in cleartext in your form state. `redactWorkflowSecretInputs` in the same file fails closed while the schemas that identify secret fields are still loading.

Deduping is automatic and task-scoped: an item already sent anywhere in the task's resume chain is pruned. `text` items are the exception and always resend.

## Seam 2 — inject custom instructions

The reserved `type: 'instructions'` routes the value into `<posthog_trusted_context>` instead — guidance the agent is told to follow. Use it to tell the agent what the user has open and which tools to reach for:

```ts
const ISSUES_QUERY_TOOL_CONTEXT_ITEM: AttachedContextItem = {
  type: 'instructions',
  hidden: true,
  value:
    'The user has the error tracking issue list open. When you call query-error-tracking-issues-list, the filters ' +
    'from your query (filter group, status, date range, search, ordering, assignee) are also applied to the open ' +
    'page, so the user sees matching issues both in this chat and on screen.',
}
```

**Trusted means static.** Instructions must only ever carry your own build-time strings — never user-entered or ingested data, and never a value interpolated from one. A crafted entity name in trusted context is a prompt injection against the next reader. If a pointer must vary (which id is open, which step is selected), put it on a normal untrusted item and have the instruction refer to it by field name.

`workflowAgentContext.ts` is the full example: it embeds the building-workflows skill markdown and the workflows MCP tool catalog (both build-time constants from a generated module), gates any interpolated id behind an allowlist regex, and pairs each visible chip with the hidden payload it stands for via `dismissGroup` so closing the chip actually detaches the payload.

## Seam 3 — react to what the agent does

`toolStreamEventsLogic` is a global bus that publishes tool-call lifecycle events with **resolved** tool names. Two consumer APIs, both from `api/logics`.

**Reload after the agent changes something** — `useToolStreamListener`:

```ts
useToolStreamListener({
  tools: ['cdp-functions-partial-update'],
  onEvent: (event) => {
    if (event.phase === 'completed') {
      loadHogFunction()
    }
  },
})
```

**Apply an agent edit back into an open form** — `useMcpToolApplyBack`. This is the one to reach for when the side panel is open next to your editor: the user asks PostHog AI to change a feature flag, and the open form updates instead of going stale.

```tsx
useMcpToolApplyBack({
  tools: ['insight-create', 'insight-update'],
  targetKey: `dashboard:${dashboard?.id ?? 'unloaded'}`,
  active: !!dashboard && canEditDashboard,
  onApply: (_event, { innerInput }) => {
    if (dashboard && insightIsAddedToDashboard(innerInput, dashboard.id)) {
      loadDashboard({ action: DashboardLoadAction.Update })
    }
  },
})
```

Apply-back is gated to the run the user is actually watching, excludes replay, and fails closed when two targets claim the same tool — so navigating between editors cannot hand an in-flight response to the wrong one. `applyOn` defaults to `'tool_call_completed'`; `'turn_end'` applies only the last matching completion, once, when the turn finishes.

Two caveats for both hooks:

- **Replay events are suppressed by default.** A page reload replays the run's history; without suppression your handler would re-fire on every reload. Opt in with `includeReplay` only if you want that.
- **`toolName` is unreliable at `phase: 'started'`** for exec-wrapped PostHog tools — the command streams in via updates, so it can still be `__posthog_exec_unknown__`. Match on `'completed'` when you need certainty.

From a kea logic, either listen to `toolStreamEventsLogic.actionTypes.emitToolEvent` and filter `event.source` yourself, or register via `registerToolListener` / `deregisterToolListener` in a disposable — again with `pauseOnPageHidden: false`, since missed live events are not redelivered.

## Seam 4 — render your own tool cards

Register a renderer so your product's tool calls display as a real card in the thread instead of the generic MCP fallback. Call it once at module load from your scene's entrypoint:

```tsx
import { registerToolRenderers } from 'products/posthog_ai/frontend/api/tools'

registerToolRenderers([
  {
    key: 'cdp-functions-partial-update',
    displayName: 'Update function',
    icon: <IconBolt />,
    renderPermissionPreview: renderPartialUpdatePreview,
    requiresPostHogOrigin: true,
  },
])
```

`key` is the inner exec tool name. A `Renderer` draws the result card; `renderPermissionPreview` draws the approval prompt shown _before_ a write runs. Set `requiresPostHogOrigin: true` so the entry only matches calls that came through the trusted PostHog server. Wrap a heavy renderer in `lazyWithRetry`.

**A tool card is two header lines plus an accordion.** `ToolActivity` gives you a `title` and one `subtitle` — the single most salient input. Everything else your tool produces goes in the collapsible `body`, never in always-visible `children`, so a thread with twenty tool calls stays scannable. Reserve `children` for payloads the user must act on.

The built-in PostHog widgets (insights, dashboards, recordings, error tracking, notebooks, query results) live in `frontend/components/tool/widgets/` and self-register the same way — that's the reference implementation.

> **MCP UI apps are a different mechanism.** The `@posthog/mcp-ui` components under `products/*/mcp/apps/` render tool results in _external_ clients like Claude Desktop, served through `services/mcp/`. They do not render inside PostHog AI threads. See [`/implementing-mcp-ui-apps`](../../.agents/skills/implementing-mcp-ui-apps/SKILL.md).

## Seam 5 (advanced) — build a custom UI on the run primitives

The same facade exposes the machinery for rendering and driving an agent run yourself: `ReadonlyRunSurface` (lazy read-only embed), the `RunSurface` compound (`Root` plus `.Thread` / `.Composer` / `.Resources` / `.ContextUsage` slots), `EmbeddedRunner` (the whole `/tasks` product inline), and the Tier 2 primitives — `Thread` atoms, `Composer.*`, permission and question surfaces — over `runStreamLogic` and `runInteractionLogic`.

**Avoid this unless you know exactly what you're doing.** Seams 1–4 are what a product integration needs. This one means owning stream binding, composer and queue state, permission routing, and the eager-vs-lazy choice that decides whether your surface doubles someone's bundle. There is no default layout, so you compose one.

If you genuinely need it, read [`frontend/README.md`](./frontend/README.md#3-recipes) for the recipes (read-only embed, live embed with composer, optimistically opening a run before it exists) and [`frontend/AGENTS.md`](./frontend/AGENTS.md) for the conventions first. The reference implementations are the signals inbox detail views and `frontend/scenes/TaskTracker/components/TaskRunChat.tsx`.

## Shortcut for a whole scene

`useSceneAgentPanel` does context, welcome headlines, and gated auto-open of the side panel in one call:

```ts
useSceneAgentPanel({
  sceneKey: 'workflow',
  contextItems: agentContextItems,
  headlines: editingEmail ? EMAIL_EDITOR_AGENT_HEADLINES : WORKFLOW_AGENT_HEADLINES,
  active: !!originalWorkflow || workflowSceneProps.id === 'new',
})
```

It lives in `frontend/src/scenes/max/useSceneAgentPanel.ts` rather than in this product's `api/`, because the Max scene is a consumer of the surface, not part of it. The whole integration rides a rollout flag, so nothing attaches or auto-opens for users it hasn't reached. Exemplar caller: `products/workflows/frontend/Workflows/WorkflowScene.tsx`.

## Do not use

- **`useMaxTool`** (`frontend/src/scenes/max/useMaxTool.ts`) and the `<MaxTool>` wrapper. Its callback fires on the LangGraph runtime only. New integrations use seams 1–4.
- **`MaxUIContext` / `maxContextLogic`** and the `maxContext` selector on scene logics. This is the legacy context store; add `AttachedContextItem`s instead.

## Directory map

```text
frontend/      # the agent-run surface + the api/ facade you import (see frontend/README.md)
backend/       # the run API that serves the surface — not an integration point for other products
mcp/           # this product's own MCP tools
skills/        # agent skills owned by PostHog AI, plus the repo-wide skills build (see skills/README.md)
evals/         # eval suites (see evals/AGENTS.md)
eval_harness/  # the harness those suites run on
dags/          # Dagster assets
```

## Where to read next

- [`frontend/README.md`](./frontend/README.md) — the full tier table, every export, and copy-paste recipes.
- [`frontend/AGENTS.md`](./frontend/AGENTS.md) — contributor guide for the surface itself: streaming architecture, the coupling boundary, conventions.
- [`skills/README.md`](./skills/README.md) — the skills this product owns and the build pipeline.
- [`/implementing-mcp-tools`](../../.agents/skills/implementing-mcp-tools/SKILL.md) — how to give the agent a new capability.
