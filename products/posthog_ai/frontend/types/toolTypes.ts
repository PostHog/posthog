/**
 * The shape `toolRegistry` renderers receive — raw `ToolInvocation` stream state plus
 * renderer-facing fields resolved at render time.
 */
export interface ToolCallMessage {
    /** Stable id — the tool call id. */
    id: string
    /** Registry lookup key — the inner tool name for single-exec calls, otherwise the wire tool name. */
    resolvedKey: string
    rawServerName: string
    rawToolName: string
    innerToolName?: string
    /** Stable SDK tool name from `_meta.claudeCode.toolName` — set for Claude built-ins. */
    claudeToolName?: string
    /** rawInput at `tool_call` (for `exec`, includes the wrapper `{ command }`). */
    rawInput: Record<string, unknown>
    /** JSON-parsed inner args when `innerToolName` is set. */
    innerInput?: Record<string, unknown>
    rawOutput?: unknown
    /** Accumulated ACP `content[]`. */
    content: unknown[]
    status: 'pending' | 'in_progress' | 'completed' | 'failed'
    title?: string
    kind?: string
    /** ACP `toolCall.locations` — file paths (with optional line) the tool touched. */
    locations?: { path: string; line?: number }[]
    error?: { message?: string } | null
}
