/**
 * Trimmed, self-contained ACP / JSON-RPC / session types.
 *
 * Vendored from `@agentclientprotocol/sdk` and the Electron app's
 * `shared/types/session-events.ts`. Only the subset referenced by the
 * conversation pipeline and renderers is copied here — this module has NO
 * external imports so the renderer can live entirely inside posthog/posthog.
 *
 * Source of truth in the reference app:
 * - @agentclientprotocol/sdk (schema/types.gen.d.ts)
 * - apps/code/src/shared/types/session-events.ts
 * - apps/code/src/renderer/features/sessions/types.ts
 */

// ---------------------------------------------------------------------------
// JSON-RPC message shapes
// ---------------------------------------------------------------------------

export interface JsonRpcNotification<T = unknown> {
    jsonrpc?: '2.0'
    method: string
    params?: T
}

export interface JsonRpcRequest<T = unknown> {
    jsonrpc?: '2.0'
    id: number
    method: string
    params?: T
}

export interface JsonRpcResponse<T = unknown> {
    jsonrpc?: '2.0'
    id: number
    result?: T
    error?: {
        code: number
        message: string
        data?: unknown
    }
}

export type JsonRpcMessage = JsonRpcNotification | JsonRpcRequest | JsonRpcResponse

/** Type guards for JSON-RPC messages. */
export function isJsonRpcNotification(msg: JsonRpcMessage): msg is JsonRpcNotification {
    return 'method' in msg && !('id' in msg)
}

export function isJsonRpcRequest(msg: JsonRpcMessage): msg is JsonRpcRequest {
    return 'method' in msg && 'id' in msg
}

export function isJsonRpcResponse(msg: JsonRpcMessage): msg is JsonRpcResponse {
    return !('method' in msg) && 'id' in msg
}

// ---------------------------------------------------------------------------
// ACP transport event
// ---------------------------------------------------------------------------

/**
 * Unified ACP message event. The source (client/agent) is inferred from the
 * ACP protocol method/sessionUpdate, not carried explicitly.
 */
export interface AcpMessage {
    type: 'acp_message'
    ts: number
    message: JsonRpcMessage
}

/**
 * S3 log entry format for stored session logs. Used when fetching historical
 * logs and appending new entries.
 */
export interface StoredLogEntry {
    type: string
    timestamp?: string
    notification?: {
        id?: number
        method?: string
        params?: unknown
        result?: unknown
        error?: unknown
    }
}

// ---------------------------------------------------------------------------
// Content blocks
// ---------------------------------------------------------------------------

export interface TextContent {
    type: 'text'
    text: string
    _meta?: { [key: string]: unknown } | null
}

export interface ImageContent {
    type: 'image'
    data?: string
    mimeType?: string
    uri?: string
    _meta?: { [key: string]: unknown } | null
}

export interface AudioContent {
    type: 'audio'
    data?: string
    mimeType?: string
    _meta?: { [key: string]: unknown } | null
}

export interface ResourceLink {
    type: 'resource_link'
    uri: string
    name?: string
    title?: string
    description?: string
    mimeType?: string
    _meta?: { [key: string]: unknown } | null
}

export interface EmbeddedResource {
    type: 'resource'
    resource: {
        uri?: string
        text?: string
        mimeType?: string
        [key: string]: unknown
    }
    _meta?: { [key: string]: unknown } | null
}

/** A single item of content. */
export type ContentBlock = TextContent | ImageContent | AudioContent | ResourceLink | EmbeddedResource

// ---------------------------------------------------------------------------
// Tool calls
// ---------------------------------------------------------------------------

export type ToolCallStatus = 'pending' | 'in_progress' | 'completed' | 'failed'

export type ToolKind =
    | 'read'
    | 'edit'
    | 'delete'
    | 'move'
    | 'search'
    | 'execute'
    | 'think'
    | 'fetch'
    | 'switch_mode'
    | 'other'

/** PostHog adds a synthetic `question` kind on top of the ACP kinds. */
export type CodeToolKind = ToolKind | 'question'

export interface ToolCallLocation {
    path: string
    line?: number | null
    _meta?: { [key: string]: unknown } | null
}

export interface DiffContent {
    type: 'diff'
    path: string
    oldText?: string | null
    newText: string
    _meta?: { [key: string]: unknown } | null
}

export interface PlainContent {
    type: 'content'
    content: ContentBlock
    _meta?: { [key: string]: unknown } | null
}

export interface TerminalContent {
    type: 'terminal'
    terminalId: string
    _meta?: { [key: string]: unknown } | null
}

/** Content produced by a tool call. */
export type ToolCallContent = PlainContent | DiffContent | TerminalContent

/**
 * A tool call as carried inside the renderer. Mirrors the ACP `ToolCall` but
 * widens `kind` to `CodeToolKind` and loosens nullability for the merge logic
 * (`Object.assign(existing, update)`).
 */
export interface ToolCall {
    _meta?: { [key: string]: unknown } | null
    content?: ToolCallContent[]
    kind?: CodeToolKind | null
    locations?: ToolCallLocation[]
    rawInput?: unknown
    rawOutput?: unknown
    status?: ToolCallStatus | null
    title: string
    toolCallId: string
}

export interface ToolCallUpdate {
    _meta?: { [key: string]: unknown } | null
    content?: ToolCallContent[] | null
    kind?: ToolKind | null
    locations?: ToolCallLocation[] | null
    rawInput?: unknown
    rawOutput?: unknown
    status?: ToolCallStatus | null
    title?: string | null
    toolCallId: string
}

// ---------------------------------------------------------------------------
// Session updates
// ---------------------------------------------------------------------------

interface ContentChunk {
    content: ContentBlock
    messageId?: string
    _meta?: { [key: string]: unknown } | null
}

export interface PlanEntry {
    content: string
    priority?: 'high' | 'medium' | 'low'
    status?: 'pending' | 'in_progress' | 'completed'
    _meta?: { [key: string]: unknown } | null
}

export interface Plan {
    entries: PlanEntry[]
    _meta?: { [key: string]: unknown } | null
}

export interface ConfigOptionUpdate {
    _meta?: { [key: string]: unknown } | null
    [key: string]: unknown
}

/**
 * Different types of updates streamed during session processing. Only the
 * variants the pipeline reads are spelled out; the long tail is folded into a
 * permissive fallback so unknown updates don't break the switch.
 */
export type SessionUpdate =
    | (ContentChunk & { sessionUpdate: 'user_message_chunk' })
    | (ContentChunk & { sessionUpdate: 'agent_message_chunk' })
    | (ContentChunk & { sessionUpdate: 'agent_thought_chunk' })
    | (ToolCall & { sessionUpdate: 'tool_call' })
    | (ToolCallUpdate & { sessionUpdate: 'tool_call_update' })
    | (Plan & { sessionUpdate: 'plan' })
    | { sessionUpdate: 'available_commands_update'; _meta?: { [key: string]: unknown } | null; [key: string]: unknown }
    | { sessionUpdate: 'current_mode_update'; _meta?: { [key: string]: unknown } | null; [key: string]: unknown }
    | (ConfigOptionUpdate & { sessionUpdate: 'config_option_update' })
    | { sessionUpdate: 'session_info_update'; _meta?: { [key: string]: unknown } | null; [key: string]: unknown }
    | { sessionUpdate: 'usage_update'; _meta?: { [key: string]: unknown } | null; [key: string]: unknown }

/** Notification containing a session update from the agent. */
export interface SessionNotification {
    _meta?: { [key: string]: unknown } | null
    sessionId: string
    update: SessionUpdate
}

/** Convenience extracts used by renderers. */
export type AgentThoughtChunk = Extract<SessionUpdate, { sessionUpdate: 'agent_thought_chunk' }>
export type AgentMessageChunk = Extract<SessionUpdate, { sessionUpdate: 'agent_message_chunk' }>
export type ToolCallSessionUpdate = Extract<SessionUpdate, { sessionUpdate: 'tool_call' }>

/**
 * `_meta.claudeCode` payload Claude-backed sessions attach to tool calls and
 * session updates. Used to recover the concrete tool name, the parent tool
 * call id (for subagent nesting) and the raw tool response.
 */
export interface ClaudeCodeMeta {
    claudeCode?: {
        toolName?: string
        parentToolCallId?: string
        toolResponse?: unknown
    }
}

// ---------------------------------------------------------------------------
// User shell execute (bash mode) ACP extension
// ---------------------------------------------------------------------------

export interface UserShellExecuteResult {
    stdout: string
    stderr: string
    exitCode: number
}

/**
 * Params for the `_array/user_shell_execute` ACP extension notification.
 * When `result` is undefined, the command is still in progress.
 */
export interface UserShellExecuteParams {
    id: string
    command: string
    cwd: string
    result?: UserShellExecuteResult
}

// ---------------------------------------------------------------------------
// Queued messages
// ---------------------------------------------------------------------------

export interface QueuedMessage {
    id: string
    content: string
    rawPrompt?: string | ContentBlock[]
    queuedAt: number
}
