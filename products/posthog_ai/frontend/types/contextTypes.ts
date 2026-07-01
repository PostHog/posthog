/**
 * Frontend context injection for the agent-run surface.
 *
 * A consumer attaches typed references (a dashboard, an insight, free text…) to a run; the backend
 * `ContextService.wrap_user_message` renders them into the `<posthog_context>` block prepended to the
 * user message. This shape mirrors the backend `AttachedContext` TypedDict
 * (`products/posthog_ai/backend/context_wrapper.py`) — the shared wire contract. The frontend only
 * ever sends these typed references; it never builds the wrapper block itself.
 */

export type AgentContextItemType =
    | 'dashboard'
    | 'insight'
    | 'event'
    | 'action'
    | 'error_tracking_issue'
    | 'evaluation'
    | 'notebook'
    | 'text'

/** One typed attachment. Entity types carry `id` (+ optional human `name`); `text` carries `value`. */
export interface AgentContextItem {
    type: AgentContextItemType
    id?: string | number
    name?: string
    value?: string
}

/** Stable dedupe + chip key: `${type}:${id ?? value}`. `text` items intentionally never dedupe. */
export function agentContextKey(item: AgentContextItem): string {
    return `${item.type}:${item.id ?? item.value ?? ''}`
}

/** Instance-agnostic chip data for a composer attachment row. Consumers map `type` → icon in React. */
export interface AgentContextChip {
    key: string
    label: string
    type: AgentContextItemType
}
