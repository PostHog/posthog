/**
 * Thread shapes for the sandbox agent runtime (`agent_runtime === 'sandbox'`).
 *
 * The sandbox path consumes the products/tasks SSE endpoint directly (the same endpoint
 * PostHog Code uses). `runStreamLogic` folds the raw wire frames (typed in
 * `./wireTypes`) into `ToolInvocation` / `ThreadItem` stream state.
 */

import type { AgentQuestion } from '../policy/questionUtils'
import type { PermissionOption } from './wireTypes'

export type ToolInvocationStatus = 'pending' | 'in_progress' | 'completed' | 'failed'
export type ProgressStatus = 'pending' | 'in_progress' | 'completed' | 'failed'

export interface ProgressStep {
    key: string
    label: string
    status: ProgressStatus
    detail?: string
}

/**
 * The kinds of alert the `RunAlertActivity` card renders. `reconnecting` is the live-connection retry
 * banner (attempt counter + backoff); `connection_failed` is its terminal state (retries exhausted or a
 * non-retryable open); `agent_error` / `agent_crash` are genuine agent-emitted failures rendered inline.
 */
export type RunAlertKind = 'reconnecting' | 'connection_failed' | 'agent_error' | 'agent_crash'

/**
 * View-model for the live connection banner, derived by `runStreamLogic.runConnectionState` and consumed
 * by `RunAlertActivity`. Kept a pure type here (Tier 3) so the headless selector never imports the
 * component. `null` from the selector means "connection healthy — render nothing".
 */
export interface RunConnectionState {
    kind: RunAlertKind
    /** `reconnecting`: current 1-based reconnect attempt. */
    attempt?: number
    /** `reconnecting`: max attempts before the connection is given up. */
    maxAttempts?: number
    /** The failed kinds: the error/crash detail to surface. */
    message?: string
}

/**
 * One merged tool call: a `tool_call` creation plus N × `tool_call_update`s folded into a
 * single raw stream record keyed on `toolCallId`. Renderer-specific parsing, such as resolving
 * the inner tool name for PostHog's single-exec MCP server, happens outside this stream state.
 */
export interface ToolInvocation {
    toolCallId: string
    /** ACP-reported MCP server, e.g. 'posthog' or '<user-installed>'. */
    rawServerName: string
    /** ACP-reported tool, e.g. 'exec', 'TodoWrite', '<user-tool>'. */
    rawToolName: string
    /** rawInput at `tool_call` time (for `exec`, includes the wrapper `{ command }`). */
    input: Record<string, unknown>
    /** rawOutput on the final `tool_call_update`. */
    output?: unknown
    /** Error carried by a failed `tool_call_update` (from the update or its notification envelope). */
    error?: { message?: string } | null
    /** Partial result from intermediate updates. */
    progress?: unknown
    status: ToolInvocationStatus
    title?: string
    /** ACP `toolCall.kind`. */
    kind?: string
    locations?: { path: string; line?: number }[]
    /** Accumulated ACP `content[]` from updates. */
    contentBlocks: unknown[]
    /** Raw ACP `_meta` from the latest tool frame. */
    meta?: unknown
}

/**
 * A tool-call lifecycle event published on the global `toolStreamEventsLogic` bus so a consumer can
 * react to the agent invoking a specific (resolved) tool — e.g. a scene that refreshes when the agent
 * creates a dashboard. Carries plain data only; the resolved name is computed in `runStreamLogic`.
 */
export type ToolStreamPhase = 'started' | 'updated' | 'completed' | 'failed'

export interface ToolStreamEvent {
    /** The `runStreamLogic` key the event was emitted from (conversation id or run/task id). */
    streamKey: string
    toolCallId: string
    /** Resolved registry key (inner PostHog MCP tool, e.g. 'create_dashboard') via `resolveToolCall`. */
    toolName: string
    /** The raw ACP tool name before resolution. */
    rawToolName: string
    phase: ToolStreamPhase
    invocation: ToolInvocation
    source: 'live' | 'replay' | 'client'
}

export type ThreadItemType =
    | 'human_message'
    | 'assistant_message'
    | 'assistant_thought'
    | 'tool_invocation'
    | 'turn_separator'
    | 'error'
    | 'status'
    | 'compact_boundary'
    | 'task_notification'
    | 'progress'
    | 'debug'

/**
 * An ordered, append-only entry the renderer consumes. Human messages, text chunks, streamed
 * reasoning ("thoughts"), tool-invocation references, run-lifecycle markers, inline errors, and
 * inline `_posthog/*` notifications (status / compaction / task milestones) all flow through this
 * list.
 */
export interface ThreadItem {
    /** Stable id — message buffer id, tool call id, or a generated separator/error id. */
    id: string
    type: ThreadItemType
    /** For `human_message`, `assistant_message`, and `assistant_thought` items. */
    text?: string
    /** Whether the assistant message buffer is finalized. */
    complete?: boolean
    /** For `tool_invocation` items — the keyed tool call id (look up in `toolInvocations`). */
    toolCallId?: string
    /** For `error` items. */
    errorMessage?: string
    /**
     * For `error` items — distinguishes a friendlier agent-crash affordance (`crash`) from a
     * raw error line (`error`, the default). Drives the copy/styling branch in the renderer.
     */
    variant?: 'error' | 'crash'
    /** For `status` and `task_notification` items — the wire `status` string. */
    status?: string
    /** For `status` items — whether the status phase has completed. */
    isComplete?: boolean
    /** For `compact_boundary` items — what triggered the compaction (e.g. 'auto'). */
    trigger?: string
    /** For `compact_boundary` items — token count before compaction. */
    preTokens?: number
    /** For `compact_boundary` items — post-compaction context size. */
    contextSize?: number
    /** For `task_notification` items — the milestone summary. */
    summary?: string
    /** For `progress` items — backend-supplied group id, scoped to the task run. */
    progressGroup?: string
    /** For `progress` items — ordered setup/runtime progress rows. */
    progressSteps?: ProgressStep[]
    /** For `debug` items — the `_posthog/console` level (debug/info/warn/error). */
    debugLevel?: string
}

/** One PostHog product the agent grounded an answer in, accumulated across the whole session. */
export interface ResourceProduct {
    /** Wire product id, e.g. 'product_analytics'. The local taxonomy maps it to an icon + label. */
    id: string
    /** Wire-supplied label; falls back to the local taxonomy label when absent. */
    label?: string
}

/**
 * Latest-wins context-usage snapshot for the footer ring. `used`/`size` (numeric token counts)
 * drive the percentage and arrive on the `session/update` aggregate; `tokens`/`cost`/`breakdown`
 * arrive on the `_posthog/usage_update` ext-notification.
 */
export interface ContextUsage {
    /** Numeric used-token count from the session/update aggregate (drives the ring). */
    used?: number
    /** Numeric context-window size from the session/update aggregate (drives the ring). */
    size?: number
    /** Cumulative token breakdown from the ext-notification. */
    tokens?: {
        inputTokens?: number
        outputTokens?: number
        cachedReadTokens?: number
        cachedWriteTokens?: number
    }
    /** Cost in USD (normalized to a number from either wire cost shape). */
    cost?: number
    /** Context-window composition breakdown from the ext-notification. */
    breakdown?: {
        systemPrompt?: number
        tools?: number
        rules?: number
        skills?: number
        mcp?: number
        subagents?: number
        conversation?: number
    }
}

/** Diagnostic resume plumbing — `taskRunId → sessionId / adapter`. No UI; kept for telemetry. */
export interface SdkSession {
    sessionId?: string
    adapter?: string
}

/**
 * Git artifacts a coding run exposes — surfaced pre-turn (working/base branch) and post-turn
 * (the opened PR). Accumulated latest-wins from the bootstrap run fetch (`state.pr_base_branch`,
 * top-level `branch`, `output.pr_url`) and live `task_run_state` frames. Stays empty for a pure
 * analytics conversation, so the coding UI it feeds self-hides.
 */
export interface RunArtifacts {
    /** `output.pr_url` — the opened pull request, when the run created one. */
    prUrl?: string
    /** The run's working branch (top-level `branch`). */
    branch?: string
    /** `state.pr_base_branch` — the branch the PR targets. */
    baseBranch?: string
    /** `owner/name` when present; generally unset on the run wire shape. */
    repo?: string
}

/**
 * A pending ACP `permission_request` surfaced by the products/tasks stream, rendered by
 * `PermissionInput` in the input area.
 */
export interface PermissionRequestRecord {
    requestId: string
    toolCallId: string
    /** Canonical ACP tool name (`mcp__posthog__exec`, or a built-in like `Bash`) — drives the default permission policy. */
    toolName: string
    options: PermissionOption[]
    title?: string
    description?: string
    rawToolCall: ToolInvocation
    /**
     * Present when this request is an `AskUserQuestion` — Twig routes questions through the permission
     * framework (`toolCall._meta.codeToolKind === 'question'`, `_meta.questions`). Drives the
     * interactive question overlay instead of the approve/decline card, and blocks auto-approval.
     */
    questions?: AgentQuestion[]
}
