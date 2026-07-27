/**
 * Wire shapes for the sandbox agent stream (products/tasks SSE frames + persisted log entries).
 *
 * Two trust levels, matching who owns each shape: the `type`-discriminated envelope frames are
 * emitted by products/tasks (or follow JSON-RPC framing) and are guarded at the parse boundary;
 * everything inside `notification.params` is owned by the external agent adapters and evolves
 * independently — those shapes are typed but only discriminant-checked, never validated, so an
 * unknown or extended payload degrades to a no-op instead of an error. Old S3 log entries replay
 * forever; the parse path must accept the union of all historical formats.
 *
 * This file is the authoritative typed view of the contract — the frontend is the only consumer
 * of live SSE frames. The Python backend types just the slice it reads (persisted log entries)
 * at `products/posthog_ai/backend/wire_types.py`; keep that slice in sync when it grows.
 */

/** ACP notification body — the JSON-RPC payload carried inside a `StoredLogEntry`. */
export interface AcpNotification {
    jsonrpc?: string
    method?: string
    params?: Record<string, unknown>
    result?: unknown
    error?: { message?: string; code?: number } | null
}

/**
 * Wire envelope around a single ACP notification. The products/tasks stream emits these as
 * the bulk of `data.type === 'notification'` traffic; the `logs/` endpoint replays them.
 */
export interface StoredLogEntry {
    type: 'notification'
    timestamp?: string
    notification: AcpNotification
}

/**
 * Run-state frame from `TaskRun.build_stream_state_event` (products/tasks/backend/models.py).
 * Emitted for non-terminal transitions too (queued → in_progress) — never treat every frame
 * as terminal. Field names are snake_case on the wire.
 */
export interface TaskRunStateFrame {
    type: 'task_run_state'
    run_id?: string
    task_id?: string
    status?: string
    stage?: string | null
    output?: unknown
    branch?: string | null
    error_message?: string | null
    updated_at?: string | null
    completed_at?: string | null
}

export interface KeepaliveFrame {
    type: 'keepalive'
}

export interface PermissionOption {
    optionId: string
    name: string
    /**
     * ACP option kind. Known values: `allow_once`, `allow_always`, `reject_once`, plus the legacy
     * `reject` / `reject_with_feedback`. The vocabulary evolves with the agent adapter, so this stays
     * a `string` — the card resolves the affordance by prefix (`allow*` approve, everything else
     * decline), never by exact match. An exact-match allowlist silently dropped `reject_once`.
     */
    kind: string
    /** `_meta.customInput === true` — the option accepts optional free-text feedback. */
    customInput?: boolean
}

/** Top-level permission frame hoisted onto the stream by the relay. */
export interface PermissionRequestFrame {
    type: 'permission_request'
    requestId?: string
    toolCallId?: string
    options?: PermissionOption[]
    toolCall?: Record<string, unknown>
}

export type WireFrame = StoredLogEntry | TaskRunStateFrame | KeepaliveFrame | PermissionRequestFrame

/**
 * `event: error` payload. The products/tasks relay emits `{error}`; cloud-agent envelopes carry
 * `{errorTitle, errorMessage, retryable}` — consumers must tolerate either.
 */
export interface SseErrorFrameData {
    error?: string
    errorTitle?: string
    errorMessage?: string
    retryable?: boolean
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function isNotificationFrame(value: unknown): value is StoredLogEntry {
    return isRecord(value) && value.type === 'notification' && isRecord(value.notification)
}

export function isTaskRunStateFrame(value: unknown): value is TaskRunStateFrame {
    return isRecord(value) && value.type === 'task_run_state'
}

export function isKeepaliveFrame(value: unknown): value is KeepaliveFrame {
    return isRecord(value) && value.type === 'keepalive'
}

export function isPermissionRequestFrame(value: unknown): value is PermissionRequestFrame {
    return isRecord(value) && value.type === 'permission_request'
}

// --- session/update bodies ---

export interface SessionUpdateText {
    type?: string
    text?: string
}

export interface SessionUpdateAgentMessageChunk {
    sessionUpdate: 'agent_message_chunk'
    messageId?: string
    content?: SessionUpdateText
    text?: string
}

export interface SessionUpdateAgentMessage {
    sessionUpdate: 'agent_message'
    messageId?: string
    content?: SessionUpdateText
    text?: string
}

/**
 * Streamed agent reasoning. Mirrors `agent_message_chunk` on the wire (a text `content` block,
 * usually no `messageId`) but renders as a collapsible "Thought" rather than chat text. ACP emits
 * no finalize counterpart — a thought is done once a later block (message or tool call) starts.
 */
export interface SessionUpdateAgentThoughtChunk {
    sessionUpdate: 'agent_thought_chunk'
    messageId?: string
    content?: SessionUpdateText
    text?: string
}

export interface SessionUpdateToolCall {
    sessionUpdate: 'tool_call'
    toolCallId?: string
    serverName?: string
    toolName?: string
    title?: string
    kind?: string
    status?: string
    rawInput?: Record<string, unknown>
    input?: Record<string, unknown>
    locations?: { path: string; line?: number }[]
    content?: unknown[]
    _meta?: SessionUpdateToolCallMeta
}

/**
 * Claude adapter metadata stamped under `_meta.claudeCode` on every Claude tool frame. `toolName`
 * is the stable SDK tool name (e.g. "Edit", "TodoWrite") — built-ins carry no top-level `toolName`,
 * so this is the only place the real name is reachable. `toolResponse` is present on a permission
 * denial and free-form otherwise. Mirrors Twig's `ToolUpdateMeta`.
 */
export interface SessionUpdateClaudeCodeMeta {
    toolName?: string
    /** Present on a permission denial; free-form on other frames. */
    toolResponse?: { decisionReason?: string; decisionReasonType?: string; message?: string } | unknown
    parentToolCallId?: string
    bashCommand?: string
}

export interface SessionUpdateToolCallMeta {
    claudeCode?: SessionUpdateClaudeCodeMeta
}

export interface SessionUpdateToolCallUpdate {
    sessionUpdate: 'tool_call_update'
    toolCallId?: string
    status?: string
    title?: string
    rawInput?: Record<string, unknown>
    input?: Record<string, unknown>
    rawOutput?: unknown
    progress?: unknown
    error?: { message?: string } | null
    locations?: { path: string; line?: number }[]
    content?: unknown[]
    _meta?: SessionUpdateToolCallMeta
}

export interface SessionUpdateCurrentMode {
    sessionUpdate: 'current_mode_update'
    currentModeId?: string
    mode?: string
}

export type SessionUpdateBody =
    | SessionUpdateAgentMessageChunk
    | SessionUpdateAgentMessage
    | SessionUpdateAgentThoughtChunk
    | SessionUpdateToolCall
    | SessionUpdateToolCallUpdate
    | SessionUpdateCurrentMode

export interface SessionUpdateParams {
    sessionId?: string
    update?: SessionUpdateBody | Record<string, unknown>
}

export function isSessionUpdateNotification(
    notification: AcpNotification
): notification is AcpNotification & { method: 'session/update'; params?: SessionUpdateParams } {
    return notification.method === 'session/update'
}

const KNOWN_SESSION_UPDATES: ReadonlySet<string> = new Set([
    'agent_message_chunk',
    'agent_message',
    'agent_thought_chunk',
    'tool_call',
    'tool_call_update',
    'current_mode_update',
])

export function isKnownSessionUpdate(update: unknown): update is SessionUpdateBody {
    return (
        isRecord(update) && typeof update.sessionUpdate === 'string' && KNOWN_SESSION_UPDATES.has(update.sessionUpdate)
    )
}

// --- `_posthog/*` notification params (adapter-owned; keys are camelCase as on the wire) ---

export interface PosthogConsoleParams {
    sessionId?: string
    level?: string
    message?: string
}

export interface PosthogProgressParams {
    sessionId?: string
    step?: string
    status?: string
    label?: string
    group?: string
    detail?: string
}

export interface PosthogSandboxOutputParams {
    sessionId?: string
    stdout?: string
    stderr?: string
    exitCode?: number
}

export interface PosthogUserMessageParams {
    content?: string | unknown[]
}

export interface PosthogUsageTokens {
    inputTokens?: number
    outputTokens?: number
    cachedReadTokens?: number
    cachedWriteTokens?: number
}

export interface PosthogUsageBreakdown {
    systemPrompt?: number
    tools?: number
    rules?: number
    skills?: number
    mcp?: number
    subagents?: number
    conversation?: number
}

/**
 * The `_posthog/usage_update` ext-notification. Permissive on purpose: the Codex adapter emits two
 * separate frames (one carrying `used`+`cost: null`, one carrying `breakdown`), while the Claude
 * adapter emits a single combined frame carrying `used`, `cost` (a bare number), AND `breakdown`
 * together. `cost` therefore tolerates either the `{amount, currency}` object (Codex / the
 * session/update aggregate) or a raw number (Claude). All fields optional so any adapter's framing
 * folds in without dropping data.
 */
export interface PosthogUsageUpdateParams {
    sessionId?: string
    used?: PosthogUsageTokens
    cost?: number | { amount?: number; currency?: string } | null
    breakdown?: PosthogUsageBreakdown
}

/**
 * The numeric `used`/`size` aggregate that drives the context-usage percentage ring. It does NOT
 * arrive on the `_posthog/usage_update` ext-notification — it is a `session/update`-framed update
 * (`sessionUpdate: 'usage_update'`) carrying flat numeric token counts plus cost.
 */
export interface SessionUpdateUsage {
    sessionUpdate: 'usage_update'
    used?: number
    size?: number
    cost?: { amount?: number; currency?: string } | null
}

export function isSessionUpdateUsage(update: unknown): update is SessionUpdateUsage {
    return isRecord(update) && update.sessionUpdate === 'usage_update'
}

/**
 * The user's own turn, echoed back by the agent adapter and persisted to the run log as a
 * `session/update` (not a `_posthog/*` ext-notification). Carries the full prompt text in a single
 * frame — it is not token-streamed like the agent's. Rendered only on `logs/` bootstrap replay: a
 * live turn is already echoed into the thread by maxThreadLogic the moment it's sent, so rendering
 * the wire echo too would duplicate it. This is the path that restores human turns on thread load.
 */
export interface SessionUpdateUserMessage {
    sessionUpdate: 'user_message_chunk' | 'user_message'
    messageId?: string
    content?: SessionUpdateText
    text?: string
}

export function isSessionUpdateUserMessage(update: unknown): update is SessionUpdateUserMessage {
    return (
        isRecord(update) && (update.sessionUpdate === 'user_message_chunk' || update.sessionUpdate === 'user_message')
    )
}

export interface PosthogStatusParams {
    sessionId?: string
    status?: string
    isComplete?: boolean
}

export interface PosthogCompactBoundaryParams {
    sessionId?: string
    trigger?: string
    preTokens?: number
    contextSize?: number
}

export interface PosthogTaskNotificationParams {
    sessionId?: string
    taskId?: string
    status?: string
    summary?: string
    outputFile?: string
}

export interface PosthogErrorParams {
    message?: string
    classification?: string
}

export interface PosthogSdkSessionParams {
    taskRunId?: string
    sessionId?: string
    adapter?: string
}

export interface PosthogResourcesUsedParams {
    sessionId?: string
    products?: { id?: string; label?: string }[]
}

/** Permission lifecycle persisted to the run log — pending approvals are re-derived from these on bootstrap. */
export interface PosthogPermissionRequestParams {
    requestId?: string
    toolCallId?: string
    options?: PermissionOption[]
    toolCall?: Record<string, unknown>
}

export interface PosthogPermissionResolvedParams {
    requestId?: string
    toolCallId?: string
    optionId?: string
}

export interface PosthogRunStartedParams {
    sessionId?: string
    runId?: string
    taskId?: string
    agentVersion?: string
}

export interface PosthogTurnCompleteParams {
    sessionId?: string
    stopReason?: string
}

export interface PosthogNotificationParamsByMethod {
    '_posthog/console': PosthogConsoleParams
    '_posthog/progress': PosthogProgressParams
    '_posthog/sandbox_output': PosthogSandboxOutputParams
    '_posthog/user_message': PosthogUserMessageParams
    '_posthog/usage_update': PosthogUsageUpdateParams
    '_posthog/status': PosthogStatusParams
    '_posthog/compact_boundary': PosthogCompactBoundaryParams
    '_posthog/task_notification': PosthogTaskNotificationParams
    '_posthog/error': PosthogErrorParams
    '_posthog/sdk_session': PosthogSdkSessionParams
    '_posthog/resources_used': PosthogResourcesUsedParams
    '_posthog/permission_request': PosthogPermissionRequestParams
    '_posthog/permission_resolved': PosthogPermissionResolvedParams
    '_posthog/run_started': PosthogRunStartedParams
    '_posthog/turn_complete': PosthogTurnCompleteParams
}

/**
 * Narrows a notification to a known `_posthog/*` method and its params shape. Discriminant-only:
 * the params contents stay trusted per the module contract.
 */
export function isPosthogNotification<M extends keyof PosthogNotificationParamsByMethod>(
    notification: AcpNotification,
    method: M
): notification is AcpNotification & { method: M; params?: PosthogNotificationParamsByMethod[M] } {
    return notification.method === method
}

/** "Has field" checks rather than mutually exclusive — the Claude combined frame carries both. */
export function hasUsageUsed(params: PosthogUsageUpdateParams | undefined): boolean {
    return !!params && params.used != null
}

export function hasUsageBreakdown(params: PosthogUsageUpdateParams | undefined): boolean {
    return !!params && params.breakdown != null
}
