import { type EventSourceMessage, createParser } from 'eventsource-parser'
import { type BreakPointFunction, actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { projectLogic } from 'scenes/projectLogic'
import { userLogic } from 'scenes/userLogic'

import { tasksRunsCommandCreate, tasksRunsStreamTokenRetrieve } from 'products/tasks/frontend/generated/api'
import type { TaskRunBootstrapCreateRequestInitialPermissionModeEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import { getClaudeCodeMeta, resolveToolCall } from '../components/tool/toolResolver'
import { parseSandboxQuestions } from '../policy/questionUtils'
import { defaultPermissionDecision, findAllowOptionId } from '../policy/toolPolicy'
import type {
    ContextUsage,
    PermissionRequestRecord,
    ResourceProduct,
    RunArtifacts,
    ProgressStatus,
    ProgressStep,
    RunConnectionState,
    SdkSession,
    ThreadItem,
    ThreadItemType,
    ToolInvocation,
    ToolInvocationStatus,
} from '../types/streamTypes'
import {
    type PermissionOption,
    type PermissionRequestFrame,
    type PosthogPermissionRequestParams,
    type PosthogProgressParams,
    type PosthogUsageUpdateParams,
    type SessionUpdateUsage,
    type SseErrorFrameData,
    type StoredLogEntry,
    isKnownSessionUpdate,
    isNotificationFrame,
    isPermissionRequestFrame,
    isPosthogNotification,
    isSessionUpdateNotification,
    isSessionUpdateUsage,
    isSessionUpdateUserMessage,
    isTaskRunStateFrame,
} from '../types/wireTypes'
import type { runStreamLogicType } from './runStreamLogicType'

export type RunSseStatus = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed' | 'error'
export type RunStatus = 'queued' | 'in_progress' | 'completed' | 'failed' | 'cancelled'

export interface RunStreamLogicProps {
    /**
     * Stable logic key. PostHog AI passes the conversation id; a generic task viewer (no conversation)
     * passes the task id. The logic operates on `(taskId, runId)` internally, so it never needs the
     * conversation beyond this key and the optional telemetry tag below.
     */
    streamKey: string
    /** Optional telemetry tag — present for PostHog AI conversations, absent for a generic task viewer. */
    conversationId?: string
    /**
     * Read-only/replay mode for a generic run viewer: bootstrap replays the persisted `logs/` snapshot
     * once and never opens SSE — even for an in-progress run. Folded into the logic key so a read-only
     * instance can never share state with a live streaming instance, even for the same `streamKey`.
     */
    replayOnly?: boolean
}

/** Reconnect/backoff constants for the SSE drop-recovery loop. */
export const MAX_SSE_RECONNECT_ATTEMPTS = 10
export const SSE_RECONNECT_BASE_DELAY_MS = 2_000
export const SSE_RECONNECT_MAX_DELAY_MS = 30_000
/**
 * Retries for the one-shot `logs/` history snapshot fetch. A transient blip here must not tear down an
 * otherwise-healthy live SSE (which is connected first); only exhausting these attempts does.
 */
export const MAX_HISTORY_FETCH_ATTEMPTS = 3
/**
 * Re-mint budget for the proxy read token on a 401 handshake — kept separate from the reconnect budget so
 * bumping reconnects to 10 doesn't balloon the number of token re-mints per open.
 */
export const MAX_STREAM_TOKEN_REMINTS = 5
/**
 * Cumulative cap across all drops in a run — bounds runaway clean-EOF loops that keep dodging the
 * per-drop counter (a connection that opens, immediately drops, and reopens resets `reconnectAttempt`
 * to 0 every cycle, so only this counter catches the loop).
 */
export const MAX_CUMULATIVE_RECONNECT_ATTEMPTS = 30
/** A connection open at least this long before dropping is healthy — its drop is forgiven. */
export const SSE_HEALTHY_CONNECTION_MS = 60_000
export const INITIAL_PERMISSION_MODE: TaskRunBootstrapCreateRequestInitialPermissionModeEnumApi = 'auto'

/** The crash-error string the in-sandbox agent server writes on a fatal exception. */
const AGENT_CRASH_PREFIX = 'Agent server crashed'

/**
 * In-band durable end-of-run sentinel emitted by both the Django stream view and the agent-proxy
 * (`event: stream-end`, `data: {"status":"complete"}`). Distinct from the rotation `end` event (a
 * 15-min connection recycle that means "reconnect"): the sentinel means the run is finished, so the
 * client stops reconnecting and drops its resume cursor instead of resuming.
 */
const STREAM_END_EVENT = 'stream-end'

/**
 * Per-run resume cursor persisted to sessionStorage. The sandbox's primary reload-resume is the S3
 * history replay (see `bootstrapRun`); this cursor is the secondary hint the live reconnect path
 * falls back to when the in-memory cursor is gone (a keyed-logic remount). Keyed by run id so two
 * runs never collide. Cleared when the run's stream completes or reaches a terminal status.
 */
function streamResumeKey(runId: string): string {
    return `posthog-ai:stream-resume:${runId}`
}
function readStreamResumeId(runId: string): string | null {
    try {
        return window.sessionStorage.getItem(streamResumeKey(runId))
    } catch {
        return null
    }
}
function writeStreamResumeId(runId: string, eventId: string): void {
    try {
        window.sessionStorage.setItem(streamResumeKey(runId), eventId)
    } catch {
        // sessionStorage may be unavailable (private mode / quota) — resume from in-memory state only.
    }
}
function clearStreamResumeId(runId: string): void {
    try {
        window.sessionStorage.removeItem(streamResumeKey(runId))
    } catch {
        // ignore
    }
}

/** Resolved live-stream destination: the agent-proxy origin plus the run-scoped read token. */
export interface StreamProxyTarget {
    baseUrl: string
    token: string
}

/**
 * Resolve the proxy target for a run, or null to stream from Django. Purely additive: with the
 * rollout flag off we skip the token mint entirely (pre-proxy behavior); with it on but the server
 * resolves no base URL — or the mint throws — we fall back to Django so streaming never breaks.
 */
export async function resolveStreamTarget(
    projectId: string,
    taskId: string,
    runId: string,
    viaProxy: boolean
): Promise<StreamProxyTarget | null> {
    if (!viaProxy) {
        return null
    }
    try {
        const { token, stream_base_url } = await tasksRunsStreamTokenRetrieve(projectId, taskId, runId)
        if (!stream_base_url) {
            return null
        }
        return { baseUrl: stream_base_url, token }
    } catch {
        return null
    }
}

const TERMINAL_RUN_STATUSES: ReadonlySet<string> = new Set(['completed', 'failed', 'cancelled'])

export function isTerminalRunStatus(status: string | null | undefined): boolean {
    return status != null && TERMINAL_RUN_STATUSES.has(status)
}

/** Capped exponential backoff: 2s / 4s / 8s / 16s / 30s. `attempt` is 1-based. */
export function reconnectDelayMs(attempt: number): number {
    const delay = SSE_RECONNECT_BASE_DELAY_MS * 2 ** (attempt - 1)
    return Math.min(delay, SSE_RECONNECT_MAX_DELAY_MS)
}

export interface StreamErrorEnvelope {
    errorTitle: string
    errorMessage?: string
    retryable: boolean
    status?: number
}

function streamError(errorTitle: string, retryable: boolean, status: number | undefined): StreamErrorEnvelope {
    return status === undefined ? { errorTitle, retryable } : { errorTitle, retryable, status }
}

/**
 * HTTP status → user-visible error envelope for refetch/open failures. Cloud-agent also emits
 * some of these as `event: error` frames; those carry their own envelope and bypass this table.
 */
export function mapHttpStatusToStreamError(status: number | undefined): StreamErrorEnvelope {
    switch (status) {
        case 401:
            return streamError('Cloud authentication expired', true, status)
        case 403:
            return streamError('Cloud access denied', true, status)
        case 404:
            return streamError('Conversation backing run not found', false, status)
        case 406:
            return streamError('Cloud stream unavailable', true, status)
        default:
            return streamError('Cloud stream failed', true, status)
    }
}

/**
 * Recovers the raw text the user typed from a persisted `_posthog/user_message`. The backend
 * prepends a `<posthog_context>…</posthog_context>` block when attachments are present
 * (`context_wrapper.wrap_user_message`); stripping it keeps a replayed prompt identical to the one
 * the live send path echoed via `pushHumanMessage`.
 */
function unwrapUserMessageContent(content: string): string {
    const closeTag = '</posthog_context>'
    if (content.startsWith('<posthog_context>')) {
        const closeIdx = content.indexOf(closeTag)
        if (closeIdx !== -1) {
            return content.slice(closeIdx + closeTag.length).replace(/^\n+/, '')
        }
    }
    return content
}

/**
 * Pull rendered text out of a `_posthog/user_message` frame's `content`. The seeder writes a plain
 * string; the live wire may instead carry ACP content blocks (`[{ type: 'text', text }]`). Returns
 * the concatenated text, or '' when there's nothing renderable.
 */
function extractUserMessageText(content: string | unknown[] | undefined): string {
    if (typeof content === 'string') {
        return content
    }
    if (Array.isArray(content)) {
        return content
            .map((block) =>
                block && typeof block === 'object' && typeof (block as { text?: unknown }).text === 'string'
                    ? (block as { text: string }).text
                    : ''
            )
            .join('')
    }
    return ''
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function normalizeNotificationEntry(entry: unknown): StoredLogEntry | null {
    if (isNotificationFrame(entry)) {
        return entry
    }

    // Older append_log callers wrote `{ notification }` directly, without the stream envelope.
    if (!isRecord(entry) || !isRecord(entry.notification)) {
        return null
    }

    return {
        type: 'notification',
        ...(typeof entry.timestamp === 'string' ? { timestamp: entry.timestamp } : {}),
        notification: entry.notification,
    } as StoredLogEntry
}

function isResumeRun(run: { state?: unknown }): boolean {
    const state = run.state
    return isRecord(state) && typeof state.resume_from_run_id === 'string' && state.resume_from_run_id !== ''
}

/**
 * Union incoming resource products into the accumulated list by `id`, preserving first-seen order.
 * Pure — mirrors the reference `accumulateSessionResources`. Products without an `id` are skipped.
 */
export function mergeResourceProducts(
    existing: ResourceProduct[],
    incoming: { id?: string; label?: string }[]
): ResourceProduct[] {
    const seen = new Set(existing.map((p) => p.id))
    const next = [...existing]
    for (const product of incoming) {
        if (typeof product.id !== 'string' || product.id === '' || seen.has(product.id)) {
            continue
        }
        seen.add(product.id)
        next.push({ id: product.id, label: product.label })
    }
    return next
}

const RUN_ARTIFACT_KEYS = ['prUrl', 'branch', 'baseBranch', 'repo'] as const

/**
 * Latest-wins fold of git artifacts onto the accumulated snapshot — a non-empty string overwrites,
 * undefined/empty values are ignored (so a later frame that omits a field never clears it). Mirrors
 * the `mergeResourceProducts` accumulation pattern.
 */
export function mergeRunArtifacts(existing: RunArtifacts, partial: Partial<RunArtifacts>): RunArtifacts {
    const next: RunArtifacts = { ...existing }
    for (const key of RUN_ARTIFACT_KEYS) {
        const value = partial[key]
        if (typeof value === 'string' && value !== '') {
            next[key] = value
        }
    }
    return next
}

/**
 * Pull the git artifacts a run-shaped payload exposes. The bootstrap `run` carries
 * `state.pr_base_branch`, a top-level `branch`, and `output.pr_url`; a live `task_run_state` frame
 * carries only the top-level `branch` and `output` (no `state`). Both feed through here. The wire is
 * loosely typed, so `state`/`output` are guarded with `isRecord` before any field read.
 */
export function extractRunArtifacts(run: {
    state?: unknown
    output?: unknown
    branch?: string | null
}): Partial<RunArtifacts> {
    const partial: Partial<RunArtifacts> = {}
    const state = isRecord(run.state) ? run.state : undefined
    const output = isRecord(run.output) ? run.output : undefined
    if (typeof run.branch === 'string') {
        partial.branch = run.branch
    }
    if (typeof state?.pr_base_branch === 'string') {
        partial.baseBranch = state.pr_base_branch
    }
    if (typeof state?.repository === 'string') {
        partial.repo = state.repository
    }
    if (typeof output?.pr_url === 'string') {
        partial.prUrl = output.pr_url
    }
    return partial
}

/** Normalize either wire cost shape (a bare number, or `{amount, currency}`) to a number | undefined. */
function normalizeUsageCost(
    cost: number | { amount?: number; currency?: string } | null | undefined
): number | undefined {
    if (cost == null) {
        return undefined
    }
    if (typeof cost === 'number') {
        return cost
    }
    return typeof cost.amount === 'number' ? cost.amount : undefined
}

/** Latest-wins fold of an `_posthog/usage_update` ext-notification onto the context-usage snapshot. */
export function foldUsageNotification(existing: ContextUsage | null, params: PosthogUsageUpdateParams): ContextUsage {
    const next: ContextUsage = { ...existing }
    if (params.used != null) {
        next.tokens = params.used
    }
    if (params.breakdown != null) {
        next.breakdown = params.breakdown
    }
    const cost = normalizeUsageCost(params.cost)
    if (cost !== undefined) {
        next.cost = cost
    }
    return next
}

/** Latest-wins fold of the numeric `session/update` usage aggregate (drives the percentage ring). */
export function foldUsageAggregate(existing: ContextUsage | null, update: SessionUpdateUsage): ContextUsage {
    const next: ContextUsage = { ...existing }
    if (typeof update.used === 'number') {
        next.used = update.used
    }
    if (typeof update.size === 'number') {
        next.size = update.size
    }
    const cost = normalizeUsageCost(update.cost)
    if (cost !== undefined) {
        next.cost = cost
    }
    return next
}

/**
 * Fetch the run's `logs/` snapshot, retrying transient failures with capped backoff (§case 5). Returns the
 * raw entries on success, or `{ historyError }` once the attempts are exhausted — a sentinel object, not a
 * throw, so the caller's teardown branch is driven by an ordinary check and a kea `breakpoint(ms)` delay
 * (which throws to cancel a superseded bootstrap) propagates through untouched.
 */
async function fetchLogEntriesWithRetry(
    taskId: string,
    runId: string,
    breakpoint: BreakPointFunction
): Promise<unknown[] | { historyError: unknown }> {
    for (let attempt = 1; ; attempt++) {
        try {
            return await api.tasks.runs.getLogEntries(taskId, runId)
        } catch (error) {
            if (attempt >= MAX_HISTORY_FETCH_ATTEMPTS) {
                return { historyError: error }
            }
        }
        // Outside the try so a supersession cancel (breakpoint throw) is never mistaken for a fetch failure.
        await breakpoint(reconnectDelayMs(attempt))
    }
}

/** Refetch the run's status (plus any git artifacts it now exposes); on failure return the mapped error envelope. */
async function fetchRunStatus(
    taskId: string,
    runId: string
): Promise<{ status: string | null; artifacts: Partial<RunArtifacts> } | { error: StreamErrorEnvelope }> {
    try {
        const run: { status?: string; state?: unknown; output?: unknown; branch?: string | null } =
            await api.tasks.runs.get(taskId, runId)
        return { status: run.status ?? null, artifacts: extractRunArtifacts(run) }
    } catch (error) {
        return { error: mapHttpStatusToStreamError((error as { status?: number })?.status) }
    }
}

/**
 * The id of the parent Task tool call when this frame belongs to a subagent's inner work
 * (`_meta.claudeCode.parentToolCallId`), else undefined. Inner calls are rolled into their parent
 * Task card rather than surfaced as top-level thread items.
 */
export function subagentParentToolCallId(meta: unknown): string | undefined {
    const parent = getClaudeCodeMeta(meta)?.parentToolCallId
    return typeof parent === 'string' && parent ? parent : undefined
}

/**
 * Permission-denial reason from `_meta.claudeCode.toolResponse`, preferring `decisionReason` over
 * the generic `message`. Returns undefined when no `_meta` is present (the inline `canUseTool` path),
 * so the caller can fall back to the content text / existing error.
 */
export function extractDenialReason(meta: unknown): string | undefined {
    const claudeCode = getClaudeCodeMeta(meta)
    const toolResponse = claudeCode?.toolResponse
    if (typeof toolResponse !== 'object' || toolResponse === null) {
        return undefined
    }
    const r = toolResponse as { decisionReason?: unknown; message?: unknown }
    if (typeof r.decisionReason === 'string' && r.decisionReason) {
        return r.decisionReason
    }
    if (typeof r.message === 'string' && r.message) {
        return r.message
    }
    return undefined
}

/**
 * Finds the last buffer of `type` for a wire message id, also matching the derived `${id}@<n>` ids
 * minted when the wire omits `messageId` and every chunk shares the fallback id. Shared by the
 * assistant-message and agent-thought streams, which both buffer incremental chunks this way.
 */
function findLastBufferIndex(state: ThreadItem[], id: string, type: ThreadItemType, incompleteOnly: boolean): number {
    for (let i = state.length - 1; i >= 0; i--) {
        const item = state[i]
        if (
            item.type === type &&
            (item.id === id || item.id.startsWith(`${id}@`)) &&
            (!incompleteOnly || !item.complete)
        ) {
            return i
        }
    }
    return -1
}

/** The in-progress compaction spinner item — cleared when compaction completes or a boundary lands. */
function isPendingCompactingStatus(item: ThreadItem): boolean {
    return item.type === 'status' && item.status === 'compacting' && item.isComplete !== true
}

function insertHumanMessageAtTurnStart(state: ThreadItem[], item: ThreadItem): ThreadItem[] {
    const lastTurnSeparatorIndex = state.findLastIndex((threadItem) => threadItem.type === 'turn_separator')
    const turnStartIndex = lastTurnSeparatorIndex + 1
    const currentTurn = state.slice(turnStartIndex)

    if (currentTurn.some((threadItem) => threadItem.type === 'human_message')) {
        return [...state, item]
    }

    return [...state.slice(0, turnStartIndex), item, ...currentTurn]
}

/**
 * Is this human message already shown in the current turn (since the last separator)? Used to drop a
 * live wire user echo that's already on screen — the optimistic `_client/human_message` of an idle
 * send, or the first wire form of a queue-drained send (which can echo in two forms).
 */
function currentTurnHasHumanText(state: ThreadItem[], text: string): boolean {
    for (let i = state.length - 1; i >= 0; i--) {
        const item = state[i]
        if (item.type === 'turn_separator') {
            return false
        }
        if (item.type === 'human_message' && item.text === text) {
            return true
        }
    }
    return false
}

function mapAcpStatus(status: unknown): ToolInvocationStatus {
    switch (status) {
        case 'in_progress':
            return 'in_progress'
        case 'completed':
            return 'completed'
        case 'failed':
            return 'failed'
        default:
            return 'pending'
    }
}

function normalizeProgressStatus(status: unknown): ProgressStatus {
    switch (status) {
        case 'pending':
        case 'in_progress':
        case 'completed':
            return status
        case 'failed':
        case 'cancelled':
            return 'failed'
        default:
            return 'in_progress'
    }
}

function stringifyOptional(value: unknown): string | undefined {
    return typeof value === 'string' ? value : undefined
}

function parsePermissionOption(raw: unknown): PermissionOption | null {
    if (typeof raw !== 'object' || raw === null) {
        return null
    }
    const r = raw as Record<string, unknown>
    const optionId = r.optionId
    const kind = String(r.kind ?? '')
    // Require only the two fields the card acts on: the `optionId` forwarded on the reply and a
    // non-empty `kind` to classify. The kind vocabulary tracks the agent adapter (`reject` became
    // `reject_once`, etc.), so accept any non-empty kind and let the prefix-based mapper resolve the
    // affordance — an exact-match allowlist silently dropped unknown kinds and blanked the prompt
    // whenever none survived.
    if (typeof optionId !== 'string' || !kind) {
        return null
    }
    const meta = r._meta
    const customInput =
        typeof meta === 'object' && meta !== null && (meta as Record<string, unknown>).customInput === true
    return {
        optionId,
        name: String(r.name ?? ''),
        kind,
        customInput,
    }
}

/**
 * Parses a permission request into a `PermissionRequestRecord` — either the live
 * `data.type === 'permission_request'` SSE envelope or the `_posthog/permission_request`
 * notification params the agent-server persists to the run log (both carry the same fields).
 * The toolCall payload mirrors the ACP `tool_call` shape. Returns null when the frame is malformed
 * or carries no usable options. The wire payload is typed, not validated, so every field read keeps
 * its runtime check.
 */
export function parsePermissionRequestFrame(
    frame: PermissionRequestFrame | PosthogPermissionRequestParams
): PermissionRequestRecord | null {
    const requestId = frame.requestId
    if (typeof requestId !== 'string') {
        return null
    }
    const toolCall = (frame.toolCall ?? {}) as Record<string, unknown>
    const toolCallId = String(toolCall.toolCallId ?? frame.toolCallId ?? '')
    if (!toolCallId) {
        return null
    }
    const options = Array.isArray(frame.options)
        ? frame.options.map(parsePermissionOption).filter((o): o is PermissionOption => o !== null)
        : []
    if (options.length === 0) {
        return null
    }

    const rawServerName = String(toolCall.serverName ?? 'posthog')
    const rawToolName = String(toolCall.toolName ?? '')
    const input = (toolCall.rawInput ?? toolCall.input ?? {}) as Record<string, unknown>

    // Canonical ACP tool name (e.g. `mcp__posthog__exec`, or a built-in like `Bash`). The wire puts
    // it on `_meta.claudeCode.toolName`; the bare fields are the fallback. The default permission
    // policy classifies off this — `mcp__`-prefixed vs built-in, plus the exec sub-tool.
    const meta = toolCall._meta
    const metaRecord = typeof meta === 'object' && meta !== null ? (meta as Record<string, unknown>) : {}
    const claudeCode = getClaudeCodeMeta(meta) ?? {}
    const toolName = String(claudeCode.toolName ?? toolCall.toolName ?? rawToolName)

    // `AskUserQuestion` is routed through the permission framework by the agent (Twig): the question
    // payload rides `_meta.codeToolKind === 'question'` + `_meta.questions`. When present, this renders
    // the interactive question overlay (not the approve/decline card) and is never auto-approved.
    const questions = metaRecord.codeToolKind === 'question' ? parseSandboxQuestions(metaRecord) : []

    return {
        requestId,
        toolCallId,
        toolName,
        options,
        title: toolCall.title as string | undefined,
        description: toolCall.description as string | undefined,
        ...(questions.length > 0 ? { questions } : {}),
        rawToolCall: {
            toolCallId,
            rawServerName,
            rawToolName,
            input,
            status: mapAcpStatus(toolCall.status),
            title: toolCall.title as string | undefined,
            kind: toolCall.kind as string | undefined,
            locations: toolCall.locations as { path: string; line?: number }[] | undefined,
            contentBlocks: Array.isArray(toolCall.content) ? toolCall.content : [],
            meta,
        },
    }
}

/** Who ingested a frame: the `logs/` bootstrap, the live SSE, or a client-injected synthetic entry. */
export type FrameSource = 'replay' | 'live' | 'client'

/** One frame in the ordered log, tagged with its source so the projection can branch on it (§6 resume filter). */
export interface StoredEntry {
    entry: StoredLogEntry
    source: FrameSource
}

/**
 * Ordered raw-frame log, in render order — the single source of truth. `threadItems` and
 * `toolInvocations` are pure projections of it (see `foldLogToThread`). Frames are appended,
 * never keyed or per-entry deduped: the only place two independently-identified sources overlap is
 * the bootstrap seam (the S3 history vs. the live SSE, which is connected *before* the history loads
 * so no frame is gapped), and that one overlap is reconciled once by `dedupeBufferedAgainstHistory`
 * before the live tail is appended. Steady-state live frames resume exactly after the last-seen
 * Redis id (exclusive), so they never re-deliver — a plain append therefore cannot double the thread.
 *
 * One principled exception to append-only: `tool_call_update` frames. The agent re-sends the full
 * accumulated `rawOutput`/`content` snapshot on every update (a long-running tool call can emit
 * thousands, each hundreds of KB), and neither the S3 log nor the live stream trims them — retaining
 * every superseded snapshot balloons renderer memory by orders of magnitude while the fold only ever
 * renders the merged latest. `appendToRunLog` therefore keeps a single field-wise-merged update entry
 * per `toolCallId` (see `mergeToolCallUpdateEntries`); `toolUpdateIndex` locates it in O(1).
 */
export interface RunLog {
    entries: StoredEntry[]
    /** Index into `entries` of the retained (merged) `tool_call_update` entry per toolCallId. */
    toolUpdateIndex: Record<string, number>
}

export function emptyRunLog(): RunLog {
    return { entries: [], toolUpdateIndex: {} }
}

/** The non-empty toolCallId of a `tool_call_update` frame, or null for every other frame. */
function toolCallUpdateKey(stored: StoredEntry): string | null {
    const notification = stored.entry.notification
    if (notification.method !== 'session/update') {
        return null
    }
    const update = notification.params?.update
    if (!isRecord(update) || update.sessionUpdate !== 'tool_call_update') {
        return null
    }
    return typeof update.toolCallId === 'string' && update.toolCallId ? update.toolCallId : null
}

/**
 * Field-wise merge of a superseded `tool_call_update` entry into its successor for the same tool
 * call — the log-level twin of `handleToolCallUpdate`'s fold precedence, so folding the one merged
 * entry yields the same invocation as folding both in sequence. Newer fields win when present;
 * absent fields fall back to the older update. Verbatim keep-latest would lose data: the wire sends
 * *partial* updates (e.g. `rawInput` streams in on an early update and the terminal update omits it).
 */
function mergeToolCallUpdateEntries(older: StoredEntry, newer: StoredEntry): StoredEntry {
    const olderNotification = older.entry.notification
    const newerNotification = newer.entry.notification
    const olderUpdateRaw = olderNotification.params?.update
    const newerUpdateRaw = newerNotification.params?.update
    const olderUpdate = isRecord(olderUpdateRaw) ? olderUpdateRaw : {}
    const newerUpdate = isRecord(newerUpdateRaw) ? newerUpdateRaw : {}

    const base = { ...olderUpdate }
    // `rawInput`/`input` are one logical field in the fold (`rawInput ?? input`) — a newer value for
    // either supersedes both, so a stale older `rawInput` can't shadow a newer `input`.
    if ((newerUpdate.rawInput && typeof newerUpdate.rawInput === 'object') || isRecord(newerUpdate.input)) {
        delete base.rawInput
        delete base.input
    }
    const mergedUpdate: Record<string, unknown> = { ...base, ...newerUpdate }
    // Content replaces only when the newer update actually carries blocks — the fold ignores an
    // empty list, so an explicitly-empty newer `content` must not erase the older blocks.
    const olderContent = Array.isArray(olderUpdate.content) ? olderUpdate.content : []
    const newerContent = Array.isArray(newerUpdate.content) ? newerUpdate.content : []
    if (olderContent.length > 0 && newerContent.length === 0) {
        mergedUpdate.content = olderContent
    }

    return {
        source: newer.source,
        entry: {
            ...newer.entry,
            notification: {
                ...newerNotification,
                // The fold reads the envelope-level error for failed updates — carry the older one
                // forward when the newer frame doesn't restate it.
                ...(newerNotification.error == null && olderNotification.error != null
                    ? { error: olderNotification.error }
                    : {}),
                params: { ...newerNotification.params, update: mergedUpdate },
            },
        },
    }
}

/**
 * Append frames to the log, collapsing superseded `tool_call_update` snapshots per toolCallId (see
 * the `RunLog` doc). The merged entry moves to the tail — where the latest update would sit — which
 * never reorders thread items: a tool card's position comes from its creating `tool_call` frame,
 * not from updates. Every ingest source (`live`, `replay`, `client`) funnels through here, so the
 * collapse covers both the live stream and the bootstrap history replay.
 */
export function appendToRunLog(state: RunLog, incoming: StoredEntry[]): RunLog {
    if (incoming.length === 0) {
        return state
    }
    const entries = [...state.entries]
    const toolUpdateIndex = { ...state.toolUpdateIndex }
    for (const stored of incoming) {
        const toolCallId = toolCallUpdateKey(stored)
        const priorIdx = toolCallId !== null ? toolUpdateIndex[toolCallId] : undefined
        if (toolCallId === null || priorIdx === undefined) {
            if (toolCallId !== null) {
                toolUpdateIndex[toolCallId] = entries.length
            }
            entries.push(stored)
            continue
        }
        const merged = mergeToolCallUpdateEntries(entries[priorIdx], stored)
        entries.splice(priorIdx, 1)
        for (const [id, idx] of Object.entries(toolUpdateIndex)) {
            if (idx > priorIdx) {
                toolUpdateIndex[id] = idx - 1
            }
        }
        toolUpdateIndex[toolCallId] = entries.length
        entries.push(merged)
    }
    return { entries, toolUpdateIndex }
}

/**
 * The fixed prefix the agent-server's resume builder prepends to the synthetic "resume context"
 * prompt it injects between run start and the genuine human turn on a resume run. That prompt is
 * persisted to the S3 log (it never arrives live), so on bootstrap replay it would otherwise render
 * as a human bubble. The projection drops it when the bootstrapped run is a resume run (§6).
 */
const RESUME_CONTEXT_PREFIX = 'You are resuming a previous conversation.'
function isResumeContextPrompt(text: string): boolean {
    return text.startsWith(RESUME_CONTEXT_PREFIX)
}

/**
 * One-shot multiset reconciliation of the bootstrap seam (port of the reference client's
 * `drainBufferedLogBatches`). While the S3 history loads we connect the live SSE first and buffer
 * its frames; some buffered frames are the same logical entries the history already contains (the
 * live stream and the S3 log overlap around the connect cutoff). This drops each buffered frame a
 * historical frame accounts for, keyed on the ACP `notification` payload — the only field identical
 * across both copies. The SSE `id` is the Redis stream id (absent from S3), and the envelope
 * `timestamp` is stamped independently on the persist and the live-publish paths, so neither can be
 * part of the key. A *multiset* (counts, not a set) so N genuine repeats of an identical payload
 * survive: each historical copy absorbs exactly one buffered copy, and any buffered surplus passes
 * through. Steady-state live frames after the drain are appended directly and never deduped.
 */
function dedupeBufferedAgainstHistory(buffered: StoredLogEntry[], history: StoredLogEntry[]): StoredLogEntry[] {
    const seamKey = (entry: StoredLogEntry): string => JSON.stringify(entry.notification)
    const historicalCounts = new Map<string, number>()
    for (const entry of history) {
        const key = seamKey(entry)
        historicalCounts.set(key, (historicalCounts.get(key) ?? 0) + 1)
    }
    const survivors: StoredLogEntry[] = []
    for (const entry of buffered) {
        const key = seamKey(entry)
        const remaining = historicalCounts.get(key) ?? 0
        if (remaining > 0) {
            historicalCounts.set(key, remaining - 1)
            continue
        }
        survivors.push(entry)
    }
    return survivors
}

export interface FoldedThread {
    threadItems: ThreadItem[]
    toolInvocations: Map<string, ToolInvocation>
}

/**
 * Pure projection: fold the ordered log into the rendered thread (and the tool-invocation map the
 * renderer looks up). The fold rules (chunk buffering with the tail rule, tool-update merge,
 * human-turn hoisting) are computed deterministically from the ordered log so item ids are stable
 * across re-folds. `isResumeRun` drives the §6 resume-context filter; per-entry `source` decides
 * whether a wire user turn renders (replay) or is left to the live echo (live).
 */
export function foldLogToThread(entries: StoredEntry[], options: { isResumeRun: boolean }): FoldedThread {
    let items: ThreadItem[] = []
    const invocations = new Map<string, ToolInvocation>()
    // Texts already rendered by a `_posthog/user_message`, so a later identical `user_message_chunk`
    // (resume chains persist the same turn in both forms) is consumed once rather than doubled.
    const rememberedHumanTexts = new Map<string, number>()
    let humanCount = 0
    let bubbleSeq = 0
    let separatorSeq = 0
    let errorSeq = 0
    let statusSeq = 0
    let compactSeq = 0
    let taskSeq = 0
    let consoleSeq = 0

    const pushHuman = (text: string): void => {
        items = insertHumanMessageAtTurnStart(items, {
            id: `human-${humanCount++}`,
            type: 'human_message',
            text,
            complete: true,
        })
    }

    const appendChunk = (id: string, type: ThreadItemType, delta: string): void => {
        const idx = findLastBufferIndex(items, id, type, false)
        // Continue the matched buffer only while it's still the tail and incomplete; otherwise (no
        // buffer, a finalized one, or one interrupted by a tool call/separator) start a fresh bubble
        // so text resuming after an interruption renders in chronological order. Every fresh bubble
        // gets a unique `${id}@<seq>` id — the wire often omits `messageId` (and the S3 replay always
        // does, since the backend drops chunks), so the bare fallback id would collide as a React key
        // across messages. The continuation lookup matches the `${id}@` prefix, so it still works.
        if (idx === -1 || items[idx].complete || idx !== items.length - 1) {
            items.push({ id: `${id}@${bubbleSeq++}`, type, text: delta, complete: false })
            return
        }
        items[idx] = { ...items[idx], text: (items[idx].text ?? '') + delta }
    }

    const finalizeMessage = (id: string, text: string): void => {
        let idx = findLastBufferIndex(items, id, 'assistant_message', true)
        if (idx === -1) {
            // The wire isn't consistent about carrying `messageId` across a message's chunks and its
            // closing `agent_message` (the chunks often have one, the finalize doesn't, or vice
            // versa), so an id-keyed lookup can miss the buffer the chunks opened. Fall back to the
            // message still being streamed — the last open assistant buffer in the current turn —
            // and close that, rather than appending a second bubble with the same text. Bounded at
            // the turn separator so a finalize never reaches back into a prior turn.
            for (let i = items.length - 1; i >= 0; i--) {
                if (items[i].type === 'turn_separator') {
                    break
                }
                if (items[i].type === 'assistant_message' && !items[i].complete) {
                    idx = i
                    break
                }
            }
        }
        if (idx === -1) {
            // No buffer to close (the common replay case: S3 drops chunks, so a finalized message
            // arrives alone). Push a fresh bubble with a unique id — a bare fallback id would collide
            // as a React key with every other no-`messageId` message in the thread.
            items.push({ id: `${id}@${bubbleSeq++}`, type: 'assistant_message', text, complete: true })
            return
        }
        items[idx] = { ...items[idx], text, complete: true }
    }

    const upsertInvocationItem = (toolCallId: string): void => {
        if (!items.some((item) => item.type === 'tool_invocation' && item.toolCallId === toolCallId)) {
            items.push({ id: toolCallId, type: 'tool_invocation', toolCallId })
        }
    }

    const renderReplayHuman = (rawText: string, remember: boolean): void => {
        const text = unwrapUserMessageContent(rawText)
        if (!text) {
            return
        }
        if (options.isResumeRun && isResumeContextPrompt(text)) {
            return
        }
        if (!remember) {
            const seen = rememberedHumanTexts.get(text) ?? 0
            if (seen > 0) {
                rememberedHumanTexts.set(text, seen - 1)
                return
            }
        }
        pushHuman(text)
        if (remember) {
            rememberedHumanTexts.set(text, (rememberedHumanTexts.get(text) ?? 0) + 1)
        }
    }

    const renderLiveHuman = (rawText: string): void => {
        const text = unwrapUserMessageContent(rawText)
        if (!text) {
            return
        }
        // The server echoes every user send live. An idle send already rendered it optimistically via
        // `_client/human_message`; a queue-drained send (dispatched with `addToThread: false`) did not,
        // so its echo is what surfaces it. Render unless the current turn already shows this message —
        // which both drops the optimistic-paired echo and dedupes a send echoed in two wire forms.
        if (currentTurnHasHumanText(items, text)) {
            return
        }
        pushHuman(text)
    }

    const handleToolCallUpdate = (
        update: Record<string, unknown>,
        notification: StoredLogEntry['notification']
    ): void => {
        const toolCallId = String(update.toolCallId ?? '')
        if (!toolCallId) {
            return
        }
        const existing = invocations.get(toolCallId)
        const status = mapAcpStatus(update.status ?? existing?.status)
        const rawInput =
            update.rawInput && typeof update.rawInput === 'object'
                ? (update.rawInput as Record<string, unknown>)
                : update.input && typeof update.input === 'object'
                  ? (update.input as Record<string, unknown>)
                  : undefined
        const denialReason = status === 'failed' ? extractDenialReason(update._meta) : undefined
        const errorMessage =
            (update.error as { message?: string } | null)?.message ??
            denialReason ??
            (status === 'failed' ? notification.error?.message : undefined)
        const updateContent = Array.isArray(update.content) ? update.content : []

        if (!existing) {
            // A reconnect can deliver a terminal update whose creating `tool_call` was lost — upsert a
            // minimal invocation so the card still renders instead of vanishing.
            invocations.set(toolCallId, {
                toolCallId,
                rawServerName: 'posthog',
                rawToolName: '',
                input: rawInput ?? {},
                status,
                title: update.title as string | undefined,
                locations: update.locations as { path: string; line?: number }[] | undefined,
                contentBlocks: updateContent,
                meta: update._meta,
                ...(errorMessage !== undefined ? { error: { message: errorMessage } } : {}),
            })
            if (!subagentParentToolCallId(update._meta)) {
                upsertInvocationItem(toolCallId)
            }
            return
        }

        invocations.set(toolCallId, {
            ...existing,
            status,
            title: (update.title as string | undefined) ?? existing.title,
            progress: update.progress ?? existing.progress,
            output: update.rawOutput ?? existing.output,
            locations: (update.locations as { path: string; line?: number }[] | undefined) ?? existing.locations,
            // ACP update semantics: a present `content` replaces the collection (the agent re-sends
            // the full accumulated blocks) — appending would duplicate every prior snapshot.
            contentBlocks: updateContent.length > 0 ? updateContent : existing.contentBlocks,
            error: errorMessage !== undefined ? { message: errorMessage } : existing.error,
            ...(rawInput ? { input: rawInput } : {}),
            ...(update._meta ? { meta: update._meta } : {}),
        })
    }

    for (const { entry, source } of entries) {
        const notification = entry.notification
        const method = notification.method
        const params = (notification.params ?? {}) as Record<string, unknown>

        if (method === '_client/human_message') {
            pushHuman(String(params.content ?? ''))
            continue
        }
        if (method === '_client/error') {
            items.push({
                id: `error-${errorSeq++}`,
                type: 'error',
                errorMessage: String(params.message ?? ''),
                variant: params.variant === 'crash' ? 'crash' : 'error',
            })
            continue
        }
        if (method === '_posthog/error') {
            items.push({
                id: `error-${errorSeq++}`,
                type: 'error',
                errorMessage: String(params.message ?? notification.error?.message ?? 'Agent error'),
                variant: 'error',
            })
            continue
        }
        if (method === '_posthog/turn_complete') {
            items.push({ id: `turn-${separatorSeq++}`, type: 'turn_separator' })
            continue
        }
        if (method === '_posthog/progress') {
            const group = stringifyOptional(params.group)
            const step = stringifyOptional(params.step)
            const label = stringifyOptional(params.label)
            if (group && step && label) {
                const detail = stringifyOptional(params.detail)
                const nextStep: ProgressStep = {
                    key: step,
                    status: normalizeProgressStatus(params.status),
                    label,
                    ...(detail !== undefined ? { detail } : {}),
                }
                const idx = items.findIndex((item) => item.type === 'progress' && item.progressGroup === group)
                if (idx === -1) {
                    items.push({
                        id: `progress-${group}`,
                        type: 'progress',
                        progressGroup: group,
                        progressSteps: [nextStep],
                    })
                } else {
                    const existingSteps = items[idx].progressSteps ?? []
                    const stepIdx = existingSteps.findIndex((s) => s.key === step)
                    items[idx] = {
                        ...items[idx],
                        progressSteps:
                            stepIdx === -1
                                ? [...existingSteps, nextStep]
                                : existingSteps.map((s, i) => (i === stepIdx ? nextStep : s)),
                    }
                }
            }
            continue
        }
        if (method === '_posthog/status') {
            const status = String(params.status ?? '')
            const isComplete = params.isComplete === true
            if (status === 'compacting' && isComplete) {
                items = items.filter((item) => !isPendingCompactingStatus(item))
            } else {
                items.push({ id: `status-${statusSeq++}`, type: 'status', status, isComplete })
            }
            continue
        }
        if (method === '_posthog/compact_boundary') {
            items = items.filter((item) => !isPendingCompactingStatus(item))
            items.push({
                id: `compact-${compactSeq++}`,
                type: 'compact_boundary',
                trigger: stringifyOptional(params.trigger),
                preTokens: typeof params.preTokens === 'number' ? params.preTokens : undefined,
                contextSize: typeof params.contextSize === 'number' ? params.contextSize : undefined,
            })
            continue
        }
        if (method === '_posthog/task_notification') {
            items.push({
                id: `task-${taskSeq++}`,
                type: 'task_notification',
                status: stringifyOptional(params.status),
                summary: stringifyOptional(params.summary),
            })
            continue
        }
        if (method === '_posthog/user_message') {
            const userText = extractUserMessageText(params.content as string | unknown[] | undefined)
            if (source === 'replay') {
                renderReplayHuman(userText, true)
            } else {
                renderLiveHuman(userText)
            }
            continue
        }
        if (method === '_posthog/console') {
            const message = typeof params.message === 'string' ? params.message : ''
            const level = typeof params.level === 'string' ? params.level : 'info'
            if (message) {
                items.push({
                    id: `console-${consoleSeq++}`,
                    type: 'debug',
                    text: message,
                    debugLevel: level,
                })
            }
            continue
        }
        if (method?.startsWith('_posthog/')) {
            // run_started, usage_update, resources_used, sdk_session, sandbox_output, … — no thread item.
            continue
        }
        if (method !== 'session/update') {
            // session/prompt and everything else never produces a thread item.
            continue
        }
        const update = params.update
        if (!isRecord(update)) {
            continue
        }
        const sessionUpdate = update.sessionUpdate
        if (sessionUpdate === 'user_message_chunk' || sessionUpdate === 'user_message') {
            const content = update.content as { text?: string } | undefined
            const userText = String(content?.text ?? update.text ?? '')
            if (source === 'replay') {
                renderReplayHuman(userText, false)
            } else {
                renderLiveHuman(userText)
            }
            continue
        }
        const content = update.content as { text?: string } | undefined
        switch (sessionUpdate) {
            case 'agent_message_chunk':
                appendChunk(
                    String(update.messageId ?? 'current'),
                    'assistant_message',
                    String(content?.text ?? update.text ?? '')
                )
                break
            case 'agent_message':
                finalizeMessage(String(update.messageId ?? 'current'), String(content?.text ?? update.text ?? ''))
                break
            case 'agent_thought_chunk':
                appendChunk(
                    String(update.messageId ?? 'current-thought'),
                    'assistant_thought',
                    String(content?.text ?? update.text ?? '')
                )
                break
            case 'tool_call': {
                const toolCallId = String(update.toolCallId ?? '')
                if (!toolCallId) {
                    break
                }
                invocations.set(toolCallId, {
                    toolCallId,
                    rawServerName: String(update.serverName ?? 'posthog'),
                    rawToolName: String(update.toolName ?? ''),
                    input: (update.rawInput ?? update.input ?? {}) as Record<string, unknown>,
                    status: mapAcpStatus(update.status),
                    title: update.title as string | undefined,
                    kind: update.kind as string | undefined,
                    locations: update.locations as { path: string; line?: number }[] | undefined,
                    contentBlocks: Array.isArray(update.content) ? update.content : [],
                    meta: update._meta,
                })
                // A subagent's inner tool calls carry the parent Task's id; they belong inside that
                // card, not as top-level siblings, so keep them out of the thread.
                if (!subagentParentToolCallId(update._meta)) {
                    upsertInvocationItem(toolCallId)
                }
                break
            }
            case 'tool_call_update':
                handleToolCallUpdate(update, notification)
                break
        }
    }

    return { threadItems: items, toolInvocations: invocations }
}

/**
 * Whether a folded item renders any content. Empty priming thoughts and step-less progress rows fold
 * into the thread but render nothing; drop them here so a virtualized consumer never reserves an empty,
 * gap-padded row. Tool items are always paired with an invocation (see `upsertInvocationItem`), and
 * `debug` rows are gated separately by `showDebugItems`, so neither needs a content check here.
 */
function rendersThreadItemContent(item: ThreadItem): boolean {
    switch (item.type) {
        case 'assistant_thought':
            return !!item.text?.trim()
        case 'progress':
            return (item.progressSteps?.length ?? 0) > 0
        default:
            return true
    }
}

/**
 * Owns the SSE connection to the products/tasks stream endpoint (a `fetch` reader driven by
 * `eventsource-parser`, so a reconnect can resume via a Last-Event-ID header), parses the ACP wire
 * format, and produces thread-shaped state the renderer consumes. Coexistence sibling to
 * `maxThreadLogic`'s streaming loop — the sandbox path never enters the LangGraph stream loop.
 *
 * Covers open/close, `data.type === 'notification'` → `ingestAcpFrame` dispatch, terminal status,
 * and stream-error capture, plus the reconnect/backoff loop on SSE drops, the ordered append-only
 * log the projection folds, HTTP-status error mapping, and the `bootstrapRun`
 * connect-first/buffer/snapshot/drain helper.
 *
 * Keyed by `streamKey` (the conversation id for PostHog AI, the task id for a generic task viewer)
 * so concurrent streams keep independent stream state and connections.
 */
export const runStreamLogic = kea<runStreamLogicType>([
    // `replayOnly` needs a default so selectors can depend on it as a prop (kea throws on a missing prop).
    props({ replayOnly: false } as RunStreamLogicProps),
    // A read-only viewer keys under a `replay:` namespace so it never shares an instance with a live
    // stream of the same run — streaming can't bleed into a read-only thread.
    key((props) => (props.replayOnly ? `replay:${props.streamKey}` : props.streamKey)),
    path((key) => ['products', 'posthog_ai', 'frontend', 'logics', 'runStreamLogic', key]),
    connect(() => ({
        values: [
            projectLogic,
            ['currentProjectId'],
            featureFlagLogic,
            ['featureFlags'],
            preflightLogic,
            ['isDev'],
            userLogic,
            ['user'],
        ],
    })),
    actions({
        /**
         * Bootstrap an existing run on conversation open. Terminal run: replay the `logs/` history
         * and stay read-only (no SSE). In-progress run: connect the SSE *first* (buffering live
         * frames), then read the `logs/` snapshot, then drain the buffered tail against it
         * (`dedupeBufferedAgainstHistory`) so the seam neither duplicates nor gaps. `justCreatedRun`
         * skips the `logs/` round-trip (fresh-run fast path — nothing historical to assemble).
         */
        bootstrapRun: (payload: { taskId: string; runId: string; justCreatedRun?: boolean; traceId?: string }) =>
            payload,
        openSseForRun: (payload: { taskId: string; runId: string; startLatest?: boolean; traceId?: string }) => payload,
        /** Internal: the read-only replay snapshot finished loading — clears the bootstrap spinner. */
        bootstrapReplayComplete: true,
        /** Internal: the live run history snapshot finished loading or was intentionally skipped. */
        bootstrapLogReady: true,
        closeSse: true,
        /**
         * The conversations/open POST is in flight — drives the optimistic "spinning up" indicator
         * before any SSE state exists. The caller (maxThreadLogic) flips it on before the POST and off
         * on the no-handle/failure paths; the success path lets `openSseForRun` clear it via the reducer.
         */
        setRunOpening: (opening: boolean) => ({ opening }),
        sseConnecting: true,
        sseOpened: true,
        sseReconnecting: (attempt: number) => ({ attempt }),
        /** Internal: an SSE drop initiates the refetch + backoff loop. */
        sseDropped: true,
        /**
         * Internal: the in-band `stream-end` sentinel landed — the run's event stream is finished.
         * Tears the connection down without reconnecting and finalizes the run status (a safety net
         * for a stream that ended without a preceding terminal `task_run_state` frame).
         */
        streamEnded: true,
        /**
         * Frame ingestion — appends one frame to the log and runs its one-shot side effects
         * (telemetry, permission routing, value folds). Called by the live SSE listener
         * (`source: 'live'`), the products/tasks `logs/` replay (`source: 'replay'`), and the
         * bootstrap drain (the deduped live tail). Telemetry is suppressed for replay; the
         * permission/run-started/tool-completion guards keep the side effects fired-once without a
         * per-frame key. The resume cursor (`cache.lastEventId`) is stamped by the SSE reader, not here.
         */
        ingestAcpFrame: (entry: StoredLogEntry, source: FrameSource = 'live') => ({ entry, source }),
        /** Append frames to the ordered log (the single source of truth). */
        appendEntries: (entries: StoredEntry[]) => ({ entries }),
        /** Records whether the bootstrapped run is a resume run, so the projection can drop its synthetic resume prompt. */
        markBootstrapResumeRun: (value: boolean) => ({ value }),
        /**
         * Surface a permission request. `replayedFromHistory` marks requests re-derived from the
         * `logs/` bootstrap — they restore card state but don't re-fire telemetry (the event
         * already fired when the request was live).
         */
        ingestPermissionRequest: (record: PermissionRequestRecord, replayedFromHistory: boolean = false) => ({
            record,
            replayedFromHistory,
        }),
        /**
         * Entry point for every parsed permission request. Applies the default tool policy
         * (`toolPolicy`): auto-approve built-in tools + non-destructive PostHog exec, prompt
         * for update/delete exec (and other MCP). Replayed-from-history requests are never
         * auto-approved — they're a read-only restore and the run may already be terminal.
         */
        routePermissionRequest: (record: PermissionRequestRecord, replayedFromHistory: boolean = false) => ({
            record,
            replayedFromHistory,
        }),
        /** Silently POST `allow` for a request the default policy auto-approves (no card shown). */
        autoApprovePermissionRequest: (record: PermissionRequestRecord, optionId: string) => ({ record, optionId }),
        /** Pin a requestId as seen without surfacing a card, so a reconnect replay can't re-process it. */
        markPermissionRequestSeen: (requestId: string) => ({ requestId }),
        /**
         * The request was answered — by this client (successful POST), another tab/client, or a
         * `_posthog/permission_resolved` log entry. Clears the matching card and pins the id so
         * reconnect/bootstrap replays cannot re-surface it.
         */
        markPermissionRequestResolved: (requestId: string) => ({ requestId }),
        /**
         * User picked an option on the approval card. POSTs the reply to the sandbox `permission/`
         * endpoint (which routes to the products/tasks `permission_response` command); the pending
         * request clears only once the POST succeeds, so a failure keeps the card for retry.
         * `customInput` carries `reject_with_feedback` text. `answers` carries `AskUserQuestion`
         * selections (keyed by question text) — the agent reads `_meta.answers` to resolve the question.
         */
        respondToPermission: (payload: {
            requestId: string
            optionId: string
            customInput?: string
            answers?: Record<string, string>
        }) => payload,
        clearPermissionRequest: true,
        /**
         * Cancel a run via the generic tasks relay. With no argument, cancels the streamed run
         * (`cache.activeRun`); pass an explicit run to cancel a warm Run the renderer isn't streaming.
         */
        cancelRun: (run?: { taskId: string; runId: string }) => ({ run }),
        /**
         * Internal: the reply POST failed. Resets the in-flight flag (so the surviving card's
         * buttons re-enable for retry) without coupling that reset to unrelated stream errors.
         */
        permissionResponseFailed: true,
        handleTerminalStatus: (status: {
            status: RunStatus
            errorMessage?: string | null
            replayedFromHistory?: boolean
        }) => status,
        handleStreamError: (envelope: StreamErrorEnvelope) => envelope,
        // Value-fold side effects emitted by ingestAcpFrame (thread items are derived in the projection).
        setCurrentMode: (mode: string) => ({ mode }),
        setCurrentProgress: (progress: string) => ({ progress }),
        /** Optional `task_run_state.stage` — wired for a future richer status surface (G6). */
        setCurrentStage: (stage: string | null) => ({ stage }),
        markRunStarted: true,
        markTurnComplete: true,
        /** Echoes the user's own message into the thread as a `client`-sourced log entry (the wire never replays a live turn). */
        pushHumanMessage: (content: string) => ({ content }),
        /**
         * Open a run optimistically before its real id exists: flips the thread to the provisioning
         * indicator and, when a first message is given, renders it immediately as the human bubble. The
         * composable seam for an optimistic-create UI — mount a surface keyed by a client `streamKey`,
         * call this on send, then attach the real run (`bootstrapRun({ justCreatedRun: true })`) once
         * created; the live SSE echo dedups the seeded message. Pure composition of `setRunOpening` +
         * `pushHumanMessage`.
         */
        startOptimisticRun: (message?: string) => ({ message }),
        /** Injects a client-side error (terminal failure / stream disconnect) into the log as a `client`-sourced entry. */
        pushErrorItem: (errorMessage: string, variant: 'error' | 'crash' = 'error') => ({ errorMessage, variant }),
        /** Union the products an answer was grounded in — accumulates across the whole session. */
        mergeResourcesUsed: (products: { id?: string; label?: string }[]) => ({ products }),
        /** Latest-wins merge of git artifacts (PR url / branch / base / repo) a run exposes. */
        mergeRunArtifacts: (partial: Partial<RunArtifacts>) => ({ partial }),
        /** Latest-wins context-usage snapshot fold (token/cost/breakdown or numeric aggregate). */
        setContextUsage: (usage: ContextUsage) => ({ usage }),
        /** Diagnostic `_posthog/sdk_session` plumbing — no UI. */
        setSdkSession: (session: SdkSession) => ({ session }),
        reset: true,
    }),
    reducers({
        // True while the conversations/open POST is in flight, before any SSE state exists. Folds into
        // `streamPhase` as provisioning so the thread shows the optimistic "spinning up" indicator
        // immediately on send. Cleared once a real stream lifecycle takes over (or ends/errors).
        runOpening: [
            false,
            {
                setRunOpening: (_, { opening }) => opening,
                openSseForRun: () => false,
                sseOpened: () => false,
                handleStreamError: () => false,
                handleTerminalStatus: () => false,
                pushErrorItem: () => false,
                reset: () => false,
            },
        ],
        sseStatus: [
            'idle' as RunSseStatus,
            {
                sseConnecting: () => 'connecting',
                sseOpened: () => 'open',
                sseReconnecting: () => 'reconnecting',
                closeSse: () => 'closed',
                handleStreamError: () => 'error',
                reset: () => 'idle',
            },
        ],
        reconnectAttempt: [
            0,
            {
                sseReconnecting: (_, { attempt }) => attempt,
                // A successful (re)connection clears the counter; bootstrapping a run starts fresh.
                sseOpened: () => 0,
                bootstrapRun: () => 0,
                reset: () => 0,
            },
        ],
        // Counts every drop in the run regardless of the per-drop counter (healthy-connection drops
        // don't bump `reconnectAttempt`, and a clean-EOF reopen loop keeps resetting it). Bounds
        // runaway loops via MAX_CUMULATIVE_RECONNECT_ATTEMPTS. Cleared only on a fresh bootstrap.
        cumulativeReconnectAttempt: [
            0,
            {
                sseReconnecting: (state) => state + 1,
                bootstrapRun: () => 0,
                reset: () => 0,
            },
        ],
        currentRunStatus: [
            null as RunStatus | null,
            {
                // A reconnect reopens the same in-flight run — keep its known status rather than
                // flickering back to queued; only a fresh open (no/terminal status) resets.
                openSseForRun: (state) => (state && !isTerminalRunStatus(state) ? state : 'queued'),
                handleTerminalStatus: (_, { status }) => status,
                reset: () => null,
            },
        ],
        // Trace correlation for the telemetry inventory. The SSE bypasses Django, so the frontend
        // supplies the trace_id it minted for POST /sandbox/ when it opened the run; conversation_id
        // is this keyed logic's own props.conversationId. Undefined for history-loaded runs — a
        // reload can't recover the trace_id the original run was sent under.
        traceId: [
            null as string | null,
            {
                bootstrapRun: (state, { traceId }) => traceId ?? state,
                openSseForRun: (state, { traceId }) => traceId ?? state,
                reset: () => null,
            },
        ],
        // The single source of truth: an ordered log of every ingested frame (plus client-injected
        // synthetic entries). `threadItems` and `toolInvocations` are pure projections of it (see
        // the selectors). The bootstrap seam is reconciled once before its live tail is appended
        // (see `bootstrapRun` / `dedupeBufferedAgainstHistory`), and steady-state live frames
        // resume exclusively after the last-seen Redis id, so a plain append never doubles the
        // thread. Superseded `tool_call_update` snapshots are the one exception to append-only —
        // `appendToRunLog` merges them per toolCallId (see the `RunLog` doc for why).
        log: [
            emptyRunLog(),
            {
                appendEntries: (state, { entries }) => appendToRunLog(state, entries),
                reset: () => emptyRunLog(),
            },
        ],
        // True while a bootstrap is in flight before the thread has anything to show. Cleared once the
        // live stream opens, the read-only replay snapshot finishes, or an error surfaces. Drives the
        // read-only viewer's initial spinner.
        bootstrapLoading: [
            false,
            {
                bootstrapRun: () => true,
                sseOpened: () => false,
                bootstrapReplayComplete: () => false,
                handleStreamError: () => false,
                reset: () => false,
            },
        ],
        // The run id this instance last bootstrapped, so the surface can adopt an already-bootstrapped
        // instance (the optimistic-create handoff) instead of resetting and re-bootstrapping it. Logic-
        // resident (not a per-component ref) so the decision survives the create-thread → detail swap.
        bootstrappedRunId: [
            null as string | null,
            {
                bootstrapRun: (_, { runId }) => runId,
                reset: () => null,
            },
        ],
        // True between an optimistic seed (`startOptimisticRun`) and its attach (`bootstrapRun`): the
        // surface uses it to take the seed-preserving fast path when the real run id arrives.
        awaitingOptimisticAttach: [
            false,
            {
                startOptimisticRun: () => true,
                bootstrapRun: () => false,
                reset: () => false,
            },
        ],
        // Live-mode bootstrapping remains true after the SSE opens and only clears once the
        // historical log snapshot has been replayed. Fresh runs explicitly skip history.
        logBootstrapLoading: [
            false,
            {
                bootstrapRun: () => true,
                bootstrapLogReady: () => false,
                bootstrapReplayComplete: () => false,
                handleStreamError: () => false,
                reset: () => false,
            },
        ],
        bootstrapError: [
            null as StreamErrorEnvelope | null,
            {
                bootstrapRun: () => null,
                bootstrapLogReady: () => null,
                bootstrapReplayComplete: () => null,
                handleStreamError: (_, envelope) => envelope,
                reset: () => null,
            },
        ],
        // Whether the bootstrapped run is a resume run — drives the §6 resume-prompt filter in the
        // projection. Set from `run.state.resume_from_run_id` when bootstrap fetches the run.
        isBootstrapResumeRun: [
            false,
            {
                markBootstrapResumeRun: (_, { value }) => value,
                reset: () => false,
            },
        ],
        pendingPermissionRequest: [
            null as PermissionRequestRecord | null,
            {
                ingestPermissionRequest: (_, { record }) => record,
                // Cleared on resolution (successful POST or a permission_resolved entry), NOT on
                // respondToPermission dispatch — a failed POST keeps the card so the user can retry.
                markPermissionRequestResolved: (state, { requestId }) =>
                    state?.requestId === requestId ? null : state,
                clearPermissionRequest: () => null,
                // A terminal run can't accept approvals — drop a card re-derived from its history.
                handleTerminalStatus: (state, { status }) => (isTerminalRunStatus(status) ? null : state),
                reset: () => null,
            },
        ],
        // requestIds ever surfaced, so a reconnect's full replay can't double-fire telemetry or
        // re-ingest a request this client already knows about.
        seenPermissionRequestIds: [
            new Set<string>(),
            {
                ingestPermissionRequest: (state, { record }) => {
                    const next = new Set(state)
                    next.add(record.requestId)
                    return next
                },
                markPermissionRequestSeen: (state, { requestId }) => {
                    const next = new Set(state)
                    next.add(requestId)
                    return next
                },
                reset: () => new Set<string>(),
            },
        ],
        // requestIds answered (locally or observed via permission_resolved) — replayed requests
        // with these ids must never re-surface as pending.
        resolvedPermissionRequestIds: [
            new Set<string>(),
            {
                markPermissionRequestResolved: (state, { requestId }) => {
                    const next = new Set(state)
                    next.add(requestId)
                    return next
                },
                reset: () => new Set<string>(),
            },
        ],
        // In-flight state for the approval reply POST — drives the input card's loading/disabled
        // props. Cleared on resolution (success) and on the POST's own failure (the card stays
        // pending, so the buttons must re-enable for retry).
        respondingToPermission: [
            false,
            {
                respondToPermission: () => true,
                markPermissionRequestResolved: () => false,
                clearPermissionRequest: () => false,
                permissionResponseFailed: () => false,
                reset: () => false,
            },
        ],
        currentMode: [
            null as string | null,
            {
                setCurrentMode: (_, { mode }) => mode,
                reset: () => null,
            },
        ],
        currentProgress: [
            null as string | null,
            {
                setCurrentProgress: (_, { progress }) => progress,
                markTurnComplete: () => null,
                reset: () => null,
            },
        ],
        // Optional `task_run_state.stage` — generally unset for PHAI runs, but cheap to track so a
        // future richer status surface (G6) can render "research / plan / build" without re-touching
        // this logic. No render consumes it yet.
        currentStage: [
            null as string | null,
            {
                setCurrentStage: (_, { stage }) => stage,
                reset: () => null,
            },
        ],
        runStarted: [
            false,
            {
                markRunStarted: () => true,
                reset: () => false,
            },
        ],
        turnComplete: [
            false,
            {
                markTurnComplete: () => true,
                // A run emits `_posthog/run_started` once; a follow-up message on the same run starts
                // a fresh turn with no new run_started frame, so a human message also reopens the
                // turn — otherwise the thinking indicator would stay off for the whole follow-up.
                markRunStarted: () => false,
                pushHumanMessage: () => false,
                reset: () => false,
            },
        ],
        // Products the agent grounded answers in, unioned by id (first-seen order) across the whole
        // session. NOT cleared on markTurnComplete — the bar accumulates; only a reset clears it.
        resourcesUsed: [
            [] as ResourceProduct[],
            {
                mergeResourcesUsed: (state, { products }) => mergeResourceProducts(state, products),
                reset: () => [],
            },
        ],
        // Git artifacts a coding run exposes (PR url, working branch, base branch, repo), accumulated
        // latest-wins from the bootstrap run fetch and live task_run_state frames. The pre/post-turn
        // coding UI reads this and self-hides while empty, so a pure-analytics conversation shows
        // nothing. NOT cleared on markTurnComplete — only a reset clears it.
        runArtifacts: [
            {} as RunArtifacts,
            {
                mergeRunArtifacts: (state, { partial }) => mergeRunArtifacts(state, partial),
                reset: () => ({}),
            },
        ],
        // Latest-wins context-usage snapshot for the footer ring. The setContextUsage payload is the
        // already-folded snapshot (the listener merges onto the prior value).
        contextUsage: [
            null as ContextUsage | null,
            {
                setContextUsage: (_, { usage }) => usage,
                reset: () => null,
            },
        ],
        // Diagnostic resume plumbing — adapter/session identity for telemetry. No UI.
        sdkSession: [
            null as SdkSession | null,
            {
                setSdkSession: (_, { session }) => session,
                reset: () => null,
            },
        ],
    }),
    selectors({
        /**
         * Pure projection of the ordered log into the rendered thread plus the tool-invocation map.
         * Memoized on `log` identity, so it recomputes only when a frame is actually appended.
         */
        foldedThread: [
            (s) => [s.log, s.isBootstrapResumeRun],
            (log, isResumeRun): FoldedThread => foldLogToThread(log.entries, { isResumeRun }),
        ],
        /**
         * Whether `_posthog/console` debug rows should surface in the thread. Derived from the current
         * user's staff/impersonation flag and dev environment, so debug items are filtered out of
         * `threadItems` for non-privileged users — never reaching the virtualizer.
         */
        showDebugItems: [
            (s) => [s.user, s.isDev],
            (user, isDev): boolean => !!user?.is_staff || !!user?.is_impersonated || !!isDev,
        ],
        threadItems: [
            (s) => [s.foldedThread, s.showDebugItems],
            (foldedThread, showDebugItems): ThreadItem[] =>
                // Filtering lives here, not in the renderer: a row the renderer would return `null` for
                // (a content-less item, or a debug row a non-privileged user can't see) still reserves an
                // empty, gap-padded slot in the virtualized thread. Drop them before they become rows.
                foldedThread.threadItems.filter(
                    (item: ThreadItem) => (item.type !== 'debug' || showDebugItems) && rendersThreadItemContent(item)
                ),
        ],
        toolInvocations: [
            (s) => [s.foldedThread],
            (foldedThread): Map<string, ToolInvocation> => foldedThread.toolInvocations,
        ],
        /**
         * Whether the agent is actively working a turn — drives the thread's thinking indicator.
         * Off once the turn completes, the run reaches a terminal status (a failed or cancelled
         * run may never emit `_posthog/turn_complete`), or the stream errors out.
         *
         * A run is "in flight" from the moment it is `queued` — keying off `currentRunStatus` as
         * well as `runStarted` lights the indicator during the multi-second cold-boot window before
         * the first `_posthog/run_started` frame, which `runStarted` alone misses.
         */
        isThinking: [
            // `replayOnly` always resolves (default in `props`); `!` drops the optional-prop `undefined`.
            (s, p) => [s.runStarted, s.turnComplete, s.currentRunStatus, s.sseStatus, p.replayOnly!],
            (runStarted, turnComplete, currentRunStatus, sseStatus, replayOnly): boolean => {
                // A read-only snapshot is never "thinking" — it's a static replay, so the indicator
                // must never spin (an in-progress run replayed read-only has no live turn to await).
                if (replayOnly) {
                    return false
                }
                if (sseStatus === 'error' || isTerminalRunStatus(currentRunStatus)) {
                    return false
                }
                const runInFlight = runStarted || currentRunStatus === 'queued' || currentRunStatus === 'in_progress'
                return runInFlight && !turnComplete
            },
        ],
        /**
         * Stream lifecycle phase gating the bottom-of-thread thinking indicator. `provisioning` = the
         * cold-boot window — the conversations/open POST is in flight (`runOpening`), or the stream is
         * opening/open but the agent hasn't started yet (the workflow is still setting up the sandbox).
         * `ThreadView` shows a fixed "spinning up" indicator here until a real `_posthog/progress`
         * boot step lands (which then takes over) or `run_started` flips the phase to `thinking`. The
         * playful gerund loader is held off until `thinking` so it never shows before a turn begins.
         * `thinking` = the agent is working a turn (mirrors `isThinking`), and is
         * what `ThreadView` gates the gerund loader on; `idle` otherwise (terminal, errored, or
         * not yet connecting). A read-only viewer is always `idle` — it never streams.
         */
        streamPhase: [
            (s, p) => [s.runStarted, s.isThinking, s.currentRunStatus, s.sseStatus, s.runOpening, p.replayOnly!],
            (
                runStarted,
                isThinking,
                currentRunStatus,
                sseStatus,
                runOpening,
                replayOnly
            ): 'provisioning' | 'thinking' | 'idle' => {
                // A read-only snapshot never provisions or thinks — there is no live stream behind it.
                if (replayOnly) {
                    return 'idle'
                }
                const connecting = sseStatus === 'connecting' || sseStatus === 'open' || sseStatus === 'reconnecting'
                // `runOpening` covers the conversations/open POST window, before any SSE state exists.
                if ((connecting || runOpening) && !runStarted && !isTerminalRunStatus(currentRunStatus)) {
                    return 'provisioning'
                }
                if (isThinking) {
                    return 'thinking'
                }
                return 'idle'
            },
        ],
        /**
         * Whether the bottom-of-thread gerund loader ("Thinking…", "Pondering…") should show. The
         * loader is a *gap filler*: it stands in only while the agent is working a turn but nothing
         * visible is streaming at the tail — i.e. it is genuinely "thinking". It hides the moment the
         * tail produces visible output: a streaming assistant message, an in-flight tool call, or a
         * running structured-progress activity (each already conveys "the agent is busy"). Reasoning is
         * deliberately NOT a hide condition — the gerund is what fills the thinking/reasoning period
         * (and the explicit `agent_thought_chunk` thinking signal arrives during exactly these gaps).
         */
        showThinkingIndicator: [
            (s) => [s.streamPhase, s.threadItems, s.toolInvocations],
            (streamPhase, threadItems, toolInvocations): boolean => {
                if (streamPhase !== 'thinking') {
                    return false
                }
                // Scan the current turn only (items after the last separator).
                const turnStart = threadItems.findLastIndex((item) => item.type === 'turn_separator') + 1
                for (let i = turnStart; i < threadItems.length; i++) {
                    const item = threadItems[i]
                    // A running structured-progress activity owns the "busy" line.
                    if (item.type === 'progress' && item.progressSteps?.some((step) => step.status === 'in_progress')) {
                        return false
                    }
                    // A tool actively running already shows its own spinner.
                    if (
                        item.type === 'tool_invocation' &&
                        item.toolCallId &&
                        ['pending', 'in_progress'].includes(toolInvocations.get(item.toolCallId)?.status ?? '')
                    ) {
                        return false
                    }
                }
                // The visible tail is streaming answer text — that's writing, not thinking.
                const tail = threadItems[threadItems.length - 1]
                if (tail?.type === 'assistant_message' && tail.complete !== true) {
                    return false
                }
                return true
            },
        ],
        /** Whether the run exposes any git artifact worth surfacing — gates the pre/post-turn coding UI. */
        hasGitArtifacts: [
            (s) => [s.runArtifacts],
            (runArtifacts): boolean => !!runArtifacts.prUrl || !!runArtifacts.branch,
        ],
        /**
         * Gates routing the live stream through the standalone agent-proxy (the durable-streaming
         * rollout). Purely flag-driven: off ⇒ stream directly from Django and never mint a
         * `stream_token`; on ⇒ resolve a proxy target. The server still owns the final
         * proxy-vs-Django decision via `stream_token` (no base URL ⇒ Django), so a flag-on client
         * where the proxy isn't deployed falls back safely. Frontend flags evaluate in local dev, so
         * a dev exercises the proxy by enabling `tasks-stream-via-proxy` for their user.
         */
        streamViaProxyEnabled: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => !!featureFlags[FEATURE_FLAGS.TASKS_STREAM_VIA_PROXY],
        ],
        /**
         * The live connection banner view-model (footer `RunAlertActivity`), or null when the connection is
         * healthy. `reconnecting` drives the attempt-counter card during the backoff loop; `connection_failed`
         * is its terminal state (retries/cumulative exhausted, a non-retryable open, or a bootstrap-fetch
         * failure — including read-only replay, which surfaces via `sseStatus='error'`). A terminal run's own
         * failure/crash is an inline `error` item, not a banner, so it's excluded here.
         */
        runConnectionState: [
            (s, p) => [s.sseStatus, s.reconnectAttempt, s.bootstrapError, s.currentRunStatus, p.replayOnly!],
            (sseStatus, reconnectAttempt, bootstrapError, currentRunStatus, replayOnly): RunConnectionState | null => {
                if (isTerminalRunStatus(currentRunStatus)) {
                    return null
                }
                if (!replayOnly && sseStatus === 'reconnecting') {
                    return {
                        kind: 'reconnecting',
                        attempt: reconnectAttempt,
                        maxAttempts: MAX_SSE_RECONNECT_ATTEMPTS,
                    }
                }
                if (sseStatus === 'error') {
                    const detail = bootstrapError
                        ? [bootstrapError.errorTitle, bootstrapError.errorMessage].filter(Boolean).join(' — ')
                        : undefined
                    return { kind: 'connection_failed', message: detail || undefined }
                }
                return null
            },
        ],
    }),
    listeners(({ values, actions, cache, props }) => ({
        bootstrapRun: async ({ taskId, runId, justCreatedRun }, breakpoint) => {
            const projectId = values.currentProjectId
            if (projectId === null) {
                actions.handleStreamError({ errorTitle: 'No current project', retryable: false })
                return
            }

            // Read-only viewer: replay the `logs/` snapshot once and never open SSE, regardless of run
            // status. `breakpoint()` cancels a superseded in-flight bootstrap (a remount / StrictMode
            // double-invoke), and the log-empty guard before folding keeps a re-bootstrap of a shared
            // keyed instance (a second mounted viewer of the same run) from doubling the thread.
            if (props.replayOnly) {
                let replayRun: { status?: string; state?: unknown; output?: unknown; branch?: string | null }
                try {
                    replayRun = await api.tasks.runs.get(taskId, runId)
                } catch (error) {
                    actions.handleStreamError(mapHttpStatusToStreamError((error as { status?: number })?.status))
                    return
                }
                breakpoint()
                actions.markBootstrapResumeRun(isResumeRun(replayRun))
                actions.mergeRunArtifacts(extractRunArtifacts(replayRun))

                const replayResult = await fetchLogEntriesWithRetry(taskId, runId, breakpoint)
                if (!Array.isArray(replayResult)) {
                    actions.handleStreamError(
                        mapHttpStatusToStreamError((replayResult.historyError as { status?: number })?.status)
                    )
                    return
                }
                const replayEntries = replayResult
                breakpoint()
                if (values.log.entries.length === 0) {
                    replayEntries
                        .map(normalizeNotificationEntry)
                        .filter((entry): entry is StoredLogEntry => entry !== null)
                        .forEach((entry) => actions.ingestAcpFrame(entry, 'replay'))
                }

                if (isTerminalRunStatus(replayRun.status ?? null)) {
                    // Record the terminal status read-only — no SSE to close, no termination telemetry.
                    actions.handleTerminalStatus({
                        status: replayRun.status as RunStatus,
                        replayedFromHistory: true,
                    })
                }
                actions.bootstrapReplayComplete()
                return
            }

            // Persistent provisioning flag for disconnect telemetry: stays true across the async
            // gap between bootstrap and the first connection/run_started. Cleared on the first
            // `sseOpened`/`_posthog/run_started`.
            cache.isBootstrapping = true
            // Fresh run: clear the durable-stream end sentinel and the proxy re-mint budget so a
            // reopened conversation starts clean.
            cache.streamEnded = false
            cache.streamTokenRefreshes = 0

            // Fresh-run fast path: nothing historical to assemble — stream from the top, with nothing
            // to buffer or drain.
            if (justCreatedRun) {
                actions.openSseForRun({ taskId, runId, startLatest: false })
                actions.bootstrapLogReady()
                return
            }

            // Existing run: read the status first to branch terminal (read-only history) vs.
            // in-progress (connect-first, then reconcile the seam).
            let run: { status?: string; state?: unknown; output?: unknown; branch?: string | null }
            try {
                run = await api.tasks.runs.get(taskId, runId)
            } catch (error) {
                actions.handleStreamError(mapHttpStatusToStreamError((error as { status?: number })?.status))
                return
            }
            breakpoint()
            // Flag the run's resume-ness so the projection can drop the synthetic resume-context
            // prompt (§6) before any history frame folds.
            actions.markBootstrapResumeRun(isResumeRun(run))
            // Surface any git artifacts the run already carries (working/base branch, an opened PR)
            // so the pre-turn header and post-turn PR card render immediately on reopen.
            actions.mergeRunArtifacts(extractRunArtifacts(run))
            const terminal = isTerminalRunStatus(run.status ?? null)

            // Connect the live SSE *before* reading the S3 snapshot for an in-progress run. Frames the
            // agent emits while the history loads are then captured by the live stream and buffered
            // (see `handleSseEvent`), not gapped between the snapshot read and the connect cutoff. The
            // buffered tail is reconciled against the history once the snapshot lands (the drain below).
            if (!terminal) {
                cache.bufferingLiveFrames = true
                cache.bufferedLiveFrames = []
                actions.openSseForRun({ taskId, runId, startLatest: true })
            }

            // Retry the snapshot before giving up (§case 5) — a transient blip shouldn't kill the live SSE.
            const historyResult = await fetchLogEntriesWithRetry(taskId, runId, breakpoint)
            if (!Array.isArray(historyResult)) {
                // Retries exhausted; for an in-progress run the SSE is already open, so tear it down too —
                // a thread of live-only frames with no history is more confusing than a clean, retryable error.
                cache.bufferingLiveFrames = false
                cache.bufferedLiveFrames = undefined
                cache.disposables.dispose('reconnect-backoff')
                cache.disposables.dispose('event-source')
                actions.handleStreamError(
                    mapHttpStatusToStreamError((historyResult.historyError as { status?: number })?.status)
                )
                return
            }
            const entries = historyResult
            breakpoint()

            // The full resume-chain S3 snapshot — replayed as `replay`, so the projection renders
            // persisted human turns and side-effect telemetry stays suppressed for history.
            const history = entries
                .map(normalizeNotificationEntry)
                .filter((entry): entry is StoredLogEntry => entry !== null)
            history.forEach((entry) => actions.ingestAcpFrame(entry, 'replay'))

            if (terminal) {
                // Read-only history — surface the terminal status, do not open SSE. Flag the replay
                // so the listener records the status without re-emitting termination telemetry.
                actions.handleTerminalStatus({ status: run.status as RunStatus, replayedFromHistory: true })
                actions.bootstrapLogReady()
                return
            }

            // Drain the seam: drop buffered-live frames the snapshot already accounts for (content
            // multiset), then append the surviving tail as live. Stop buffering first so any frame
            // arriving during the drain appends directly rather than landing in a buffer we've moved past.
            const buffered = (cache.bufferedLiveFrames as StoredLogEntry[] | undefined) ?? []
            cache.bufferingLiveFrames = false
            cache.bufferedLiveFrames = undefined
            dedupeBufferedAgainstHistory(buffered, history).forEach((entry) => actions.ingestAcpFrame(entry, 'live'))
            actions.bootstrapLogReady()
        },
        openSseForRun: ({ taskId, runId, startLatest }) => {
            // A read-only instance must never stream — guard here too, so even a stray or connected
            // dispatch can't open SSE into a read-only thread.
            if (props.replayOnly) {
                return
            }
            const projectId = values.currentProjectId
            if (projectId === null) {
                actions.handleStreamError({ errorTitle: 'No current project', retryable: false })
                return
            }

            // Track the active run so the reconnect loop can refetch it on a drop.
            cache.activeRun = { taskId, runId }

            actions.sseConnecting()
            cache.disposables.dispose('reconnect-backoff')

            // Route one parsed SSE event. `eventsource-parser` unifies the old `onmessage` (default
            // data channel — `event` undefined) and `addEventListener('error')` (named `error`
            // envelope) split into one callback keyed off the `event` field.
            const handleSseEvent = ({ id, event, data }: EventSourceMessage): void => {
                if (id) {
                    // The Redis stream id. Stamped (even for a buffered frame) so a reconnect resumes
                    // exactly after it via the Last-Event-ID header — an exclusive resume, so the
                    // steady-state stream never re-delivers a frame we've already appended. Mirrored to
                    // sessionStorage so a live reconnect that lost the in-memory cursor can recover it.
                    cache.lastEventId = id
                    writeStreamResumeId(runId, id)
                }
                if (event === STREAM_END_EVENT) {
                    // Durable end-of-run sentinel — the run's event stream is finished, so stop here
                    // rather than treating the imminent connection close as a drop to reconnect. Drop
                    // the persisted cursor (a completed run must never be resumed) and finalize via
                    // the listener. `streamEnded` (read by the reader loop) suppresses the clean-EOF
                    // drop that follows.
                    cache.streamEnded = true
                    clearStreamResumeId(runId)
                    actions.streamEnded()
                    return
                }
                if (event === 'error') {
                    // Named error envelope — surface verbatim. Real backend frames carry only `error`,
                    // so the title/retryable fall back to the generic stream-failure defaults.
                    try {
                        const envelope: SseErrorFrameData = JSON.parse(data)
                        actions.handleStreamError({
                            errorTitle: envelope.errorTitle ?? 'Cloud stream failed',
                            errorMessage: envelope.errorMessage,
                            retryable: envelope.retryable ?? true,
                        })
                    } catch {
                        actions.handleStreamError({ errorTitle: 'Cloud stream failed', retryable: true })
                    }
                    return
                }
                // keepalive (and any other named, non-data event) carries nothing to fold.
                if (event && event !== 'message') {
                    return
                }
                let parsed: unknown
                try {
                    parsed = JSON.parse(data)
                } catch {
                    return
                }
                if (isNotificationFrame(parsed)) {
                    // During the bootstrap window the SSE is connected before the S3 snapshot lands,
                    // so buffer live notification frames instead of appending them; the drain
                    // reconciles them against the snapshot once it loads (see `bootstrapRun`). Steady
                    // state (and every send/reconnect open, which never buffers) appends directly.
                    if (cache.bufferingLiveFrames) {
                        ;(cache.bufferedLiveFrames as StoredLogEntry[]).push(parsed)
                    } else {
                        actions.ingestAcpFrame(parsed, 'live')
                    }
                } else if (isPermissionRequestFrame(parsed)) {
                    // requestId-keyed dedup: this top-level envelope isn't a notification, so a
                    // reconnect's resume could re-deliver it verbatim.
                    const record = parsePermissionRequestFrame(parsed)
                    if (
                        record &&
                        !values.seenPermissionRequestIds.has(record.requestId) &&
                        !values.resolvedPermissionRequestIds.has(record.requestId)
                    ) {
                        actions.routePermissionRequest(record)
                    }
                } else if (isTaskRunStateFrame(parsed)) {
                    // `stage` is dropped by handleTerminalStatus's status-only path; track it
                    // separately for a future richer status surface. Generally unset for PHAI.
                    if (parsed.stage !== undefined) {
                        actions.setCurrentStage(parsed.stage ?? null)
                    }
                    // The frame carries the working `branch` and an `output.pr_url` once the run opens
                    // a PR — fold them in so the post-turn PR card appears the moment it lands.
                    actions.mergeRunArtifacts(extractRunArtifacts(parsed))
                    actions.handleTerminalStatus({
                        status: parsed.status as RunStatus,
                        errorMessage: parsed.error_message ?? null,
                    })
                }
                // unknown frame types are ignored.
            }

            // Open the stream as a fetch response and pump its body through the parser. A native
            // `EventSource` can't set request headers; a fetch can, so a reconnect resumes exactly
            // after `cache.lastEventId` via the Last-Event-ID header instead of re-broadcasting the
            // whole stream. A clean EOF or read error (not an abort) is a drop → run the recovery
            // loop; an aborted signal (teardown) is silent.
            const streamRun = async (signal: AbortSignal): Promise<void> => {
                // Resolve the destination fresh on every (re)connect: with the rollout flag on this
                // mints a short-lived proxy read token (so a reconnect after a long stream always
                // carries a valid one); with it off, or on the fallback, it's a no-op and we hit
                // Django. A failed mint falls back to Django — streaming never breaks on the proxy.
                const proxyTarget = values.streamViaProxyEnabled
                    ? await resolveStreamTarget(String(projectId), taskId, runId, true)
                    : null
                if (signal.aborted) {
                    return
                }
                // Resume cursor: prefer the in-memory id stamped by the reader; fall back to the
                // persisted sessionStorage cursor only outside the bootstrap seam window
                // (`bufferingLiveFrames`). The connect-first bootstrap deliberately streams
                // `start=latest` and reconciles the S3 history seam, so a persisted cursor must never
                // pre-empt it — only a live reconnect that lost its in-memory cursor honors it.
                const lastEventId =
                    (cache.lastEventId as string | undefined) ??
                    (cache.bufferingLiveFrames ? undefined : (readStreamResumeId(runId) ?? undefined))

                let response: Response
                try {
                    response = await api.tasks.runs.openStream(taskId, runId, {
                        signal,
                        lastEventId,
                        startLatest,
                        ...(proxyTarget ? { proxyTarget } : {}),
                    })
                } catch (error) {
                    if (signal.aborted) {
                        return
                    }
                    // A fetch (unlike a native EventSource) exposes the HTTP status. Surface a
                    // permanently-failed open (e.g. 404 — the backing run is gone) as a terminal
                    // stream error instead of looping the reconnect logic forever; treat a transient
                    // status or a network-level reject as a drop and let the recovery loop retry.
                    const status = (error as { status?: number })?.status
                    // A 401 on the proxy leg means the short-lived read token expired between mint and
                    // handshake — re-mint and retry once (free, off the reconnect budget) rather than
                    // surfacing an auth error. Bounded so a genuinely revoked user can't loop; on
                    // exhaustion it falls through to the normal drop handling (whose Django fallback
                    // surfaces a real 401 as a retryable error).
                    if (status === 401 && proxyTarget && (cache.streamTokenRefreshes ?? 0) < MAX_STREAM_TOKEN_REMINTS) {
                        cache.streamTokenRefreshes = ((cache.streamTokenRefreshes as number | undefined) ?? 0) + 1
                        return streamRun(signal)
                    }
                    const mapped = status !== undefined ? mapHttpStatusToStreamError(status) : undefined
                    if (mapped && !mapped.retryable) {
                        actions.handleStreamError(mapped)
                    } else {
                        actions.sseDropped()
                    }
                    return
                }
                if (signal.aborted) {
                    return
                }
                const reader = response.body?.getReader()
                if (!reader) {
                    actions.sseDropped()
                    return
                }
                // Headers received and a body to read → the connection is open.
                actions.sseOpened()
                const decoder = new TextDecoder()
                const parser = createParser({ onEvent: handleSseEvent })
                try {
                    for (;;) {
                        const { done, value } = await reader.read()
                        if (value) {
                            parser.feed(decoder.decode(value, { stream: true }))
                        }
                        if (done) {
                            break
                        }
                    }
                } catch {
                    if (!signal.aborted && !cache.streamEnded) {
                        actions.sseDropped()
                    }
                    return
                }
                // Clean EOF: the server closed the stream. A terminal frame or the `stream-end`
                // sentinel would already have torn us down (dispose → abort / `streamEnded`);
                // otherwise this is a drop, so refetch status and decide.
                if (!signal.aborted && !cache.streamEnded) {
                    actions.sseDropped()
                }
            }

            // Replace any prior connection. A hot reload can orphan the previous build's reader (its
            // `cache`, and thus this disposable, is discarded before teardown runs), but the keyed
            // log store makes duplicate ingestion idempotent — a lingering orphan can no longer
            // double the thread, so the old `EventSource` registry is gone.
            cache.disposables.dispose('event-source')
            // pauseOnPageHidden: false — a live stream must survive tab hides; re-running setup on
            // show would reopen the stream and re-fold thread state.
            cache.disposables.add(
                (): (() => void) => {
                    const controller = new AbortController()
                    void streamRun(controller.signal)
                    return () => controller.abort()
                },
                'event-source',
                { pauseOnPageHidden: false }
            )
        },
        sseOpened: () => {
            // Stamp the connection time for the healthy-connection rule in sseDropped. The
            // provisioning flag (`isBootstrapping`, read by the disconnect telemetry) is NOT cleared
            // here: connect-first opens the SSE before the history snapshot loads, so the bootstrap
            // window (connect → snapshot → drain → first `run_started`) outlives the first connect.
            // It clears when the agent actually starts (`_posthog/run_started`) or on reset.
            cache.sseConnectedAtMs = Date.now()
            // A successful handshake means the proxy token worked — reset the re-mint budget so a
            // later expiry on this long-lived connection re-mints from a clean slate.
            cache.streamTokenRefreshes = 0
        },
        sseDropped: async (_, breakpoint) => {
            const activeRun = cache.activeRun as { taskId: string; runId: string } | undefined
            if (!activeRun) {
                return
            }
            // Abort the in-flight reader so its clean-EOF/error handler can't also schedule a
            // reconnect while this loop owns recovery.
            cache.disposables.dispose('event-source')

            // First refetch the run to detect terminal state.
            const result = await fetchRunStatus(activeRun.taskId, activeRun.runId)
            breakpoint()
            // The stream was closed or replaced while the refetch was in flight — drop this loop.
            if (cache.activeRun !== activeRun) {
                return
            }
            if ('error' in result) {
                actions.handleStreamError(result.error)
                return
            }

            // A reconnect refetch can be the first place a freshly-opened PR (or branch) shows up —
            // fold it in even if the run has since terminated.
            actions.mergeRunArtifacts(result.artifacts)

            // Terminal → final terminal-status action + close.
            if (isTerminalRunStatus(result.status)) {
                actions.handleTerminalStatus({ status: result.status as RunStatus })
                return
            }

            // Cumulative cap — bounds runaway clean-EOF reopen loops that keep resetting the per-drop
            // counter. The about-to-be-scheduled reconnect is the (cumulative + 1)th.
            if (values.cumulativeReconnectAttempt + 1 > MAX_CUMULATIVE_RECONNECT_ATTEMPTS) {
                actions.handleStreamError({ errorTitle: 'Cloud stream failed', retryable: true })
                return
            }

            // Healthy-connection rule — a connection that stayed open ≥60s before dropping is not a
            // flaky transport, so its drop is forgiven: schedule a reconnect but don't grow the
            // per-drop budget. The cumulative counter still increments (via sseReconnecting) to
            // bound pathological reopen loops.
            const connectedAtMs = cache.sseConnectedAtMs as number | undefined
            const wasHealthy = connectedAtMs !== undefined && Date.now() - connectedAtMs >= SSE_HEALTHY_CONNECTION_MS

            // Non-terminal → capped exponential backoff; attempts exhausted surface a retryable error.
            const attempt = wasHealthy ? values.reconnectAttempt : values.reconnectAttempt + 1
            if (attempt > MAX_SSE_RECONNECT_ATTEMPTS) {
                actions.handleStreamError({ errorTitle: 'Cloud stream failed', retryable: true })
                return
            }
            // Backoff off the per-drop budget; a forgiven healthy drop (attempt 0) reconnects fast.
            const delayMs = reconnectDelayMs(Math.max(attempt, 1))
            actions.sseReconnecting(attempt)
            // pauseOnPageHidden: false — the SSE connection survives tab hides, so a drop in a
            // hidden tab must also reconnect there; a paused timer would stall until refocus.
            cache.disposables.add(
                (): (() => void) => {
                    const timer = window.setTimeout(() => {
                        // Resume from `cache.lastEventId` via the Last-Event-ID header (set inside
                        // openSseForRun) — the backend replays exactly the frames after it, filling
                        // the gap with no re-broadcast. `startLatest: true` only matters if no frame
                        // was ever seen (dropped before the first one): then resume from the head
                        // rather than re-streaming from `0`.
                        actions.openSseForRun({ taskId: activeRun.taskId, runId: activeRun.runId, startLatest: true })
                    }, delayMs)
                    return () => clearTimeout(timer)
                },
                'reconnect-backoff',
                { pauseOnPageHidden: false }
            )
        },
        streamEnded: async (_, breakpoint) => {
            // The durable `stream-end` sentinel landed: tear down without reconnecting.
            cache.disposables.dispose('reconnect-backoff')
            cache.disposables.dispose('event-source')
            const activeRun = cache.activeRun as { taskId: string; runId: string } | undefined
            // The terminal `task_run_state` frame ahead of the sentinel usually already finalized the
            // run (and fired its telemetry); short-circuit so we don't refetch or double-count. Only
            // when the stream ended without one do we refetch to resolve the authoritative status.
            if (!activeRun || isTerminalRunStatus(values.currentRunStatus)) {
                return
            }
            const result = await fetchRunStatus(activeRun.taskId, activeRun.runId)
            breakpoint()
            // The stream was closed or replaced while the refetch was in flight — drop this loop.
            if (cache.activeRun !== activeRun) {
                return
            }
            if ('error' in result) {
                // Stream said done but the status is unreadable — leave the thread as-is and never
                // reconnect; the durable stream is authoritatively finished.
                return
            }
            // A reconnect/end refetch can be the first place a freshly-opened PR (or branch) shows up.
            actions.mergeRunArtifacts(result.artifacts)
            if (isTerminalRunStatus(result.status)) {
                actions.handleTerminalStatus({ status: result.status as RunStatus })
            }
        },
        routePermissionRequest: ({ record, replayedFromHistory }) => {
            // Replayed history is a read-only restore — never auto-approve (the run may be terminal).
            if (!replayedFromHistory && defaultPermissionDecision(record) === 'auto_allow') {
                const optionId = findAllowOptionId(record)
                if (optionId) {
                    actions.autoApprovePermissionRequest(record, optionId)
                    return
                }
            }
            actions.ingestPermissionRequest(record, replayedFromHistory)
        },
        autoApprovePermissionRequest: async ({ record, optionId }) => {
            // Pin it seen up front so a reconnect replay can't re-process the same request mid-POST.
            actions.markPermissionRequestSeen(record.requestId)
            const activeRun = cache.activeRun as { taskId: string; runId: string } | undefined
            const resolvedToolCall = resolveToolCall(record.rawToolCall)
            posthog.capture('permission_auto_approved', {
                conversation_id: props.conversationId,
                trace_id: values.traceId,
                request_id: record.requestId,
                tool_call_name: resolvedToolCall.resolvedKey,
                tool_call_id: record.toolCallId,
                run_id: activeRun?.runId,
                task_id: activeRun?.taskId,
                execution_type: 'sandbox',
            })
            if (!activeRun || values.currentProjectId == null) {
                // No active run to command yet — fall back to the manual card so the user can respond.
                actions.ingestPermissionRequest(record)
                return
            }
            try {
                await tasksRunsCommandCreate(String(values.currentProjectId), activeRun.taskId, activeRun.runId, {
                    jsonrpc: '2.0',
                    method: 'permission_response',
                    params: { requestId: record.requestId, optionId },
                })
                actions.markPermissionRequestResolved(record.requestId)
            } catch (error) {
                // The auto-approve command failed — don't leave the agent silently blocked. Fall back to
                // the manual card so the user can respond.
                posthog.captureException(error)
                actions.ingestPermissionRequest(record)
            }
        },
        ingestPermissionRequest: ({ record, replayedFromHistory }) => {
            if (replayedFromHistory) {
                return
            }
            // conversation_id / trace_id are correlated by the caller (the SSE bypasses Django);
            // emit what this logic knows.
            const activeRun = cache.activeRun as { taskId: string; runId: string } | undefined
            const resolvedToolCall = resolveToolCall(record.rawToolCall)
            posthog.capture('permission_requested', {
                conversation_id: props.conversationId,
                trace_id: values.traceId,
                request_id: record.requestId,
                tool_call_name: resolvedToolCall.resolvedKey,
                tool_call_id: record.toolCallId,
                run_id: activeRun?.runId,
                task_id: activeRun?.taskId,
                execution_type: 'sandbox',
            })
        },
        respondToPermission: async ({ requestId, optionId, customInput, answers }) => {
            const activeRun = cache.activeRun as { taskId: string; runId: string } | undefined
            if (!activeRun || values.currentProjectId == null) {
                // No live run to command — keep the card so the user can retry once the stream resolves.
                actions.permissionResponseFailed()
                lemonToast.error('Failed to send approval. Please try again.')
                return
            }
            try {
                // PERMISSION_RESPONDED telemetry is emitted server-side by the tasks relay. The renderer
                // commands the run it is streaming (`cache.activeRun`); on a persistent sandbox the run
                // only advances when the old one dies and the successor takes over — which is exactly the
                // run the renderer has re-resolved, so the reply lands where it belongs.
                await tasksRunsCommandCreate(String(values.currentProjectId), activeRun.taskId, activeRun.runId, {
                    jsonrpc: '2.0',
                    method: 'permission_response',
                    params: { requestId, optionId, customInput, answers },
                })
                actions.markPermissionRequestResolved(requestId)
            } catch (error) {
                // A failed reply POST does not mean the run died — the agent is still alive and
                // blocked on this same approval. Keep the failure local to the card (re-enable its
                // buttons for a retry) instead of tearing down the stream, which would release the
                // chat lock and hide the still-pending request behind the normal input.
                posthog.captureException(error)
                actions.permissionResponseFailed()
                lemonToast.error('Failed to send approval. Please try again.')
            }
        },
        cancelRun: async ({ run }) => {
            // Cancel a run through the generic tasks relay — the same command PostHog Code issues. The
            // SSE then receives a terminal task_run_state; cancellation telemetry is emitted server-side
            // by the relay. `run` defaults to the streamed run; a warm Run (not streamed) is passed in.
            // Fire-and-forget: a failure leaves the run alive for a retry.
            const target = run ?? (cache.activeRun as { taskId: string; runId: string } | undefined)
            if (!target || values.currentProjectId == null) {
                return
            }
            try {
                await tasksRunsCommandCreate(String(values.currentProjectId), target.taskId, target.runId, {
                    jsonrpc: '2.0',
                    method: 'cancel',
                })
            } catch (error) {
                posthog.captureException(error)
            }
        },
        handleTerminalStatus: ({ status, errorMessage, replayedFromHistory }) => {
            // The wire emits task_run_state for non-terminal transitions too (e.g. queued →
            // in_progress) — only an actually-terminal run has no more frames to stream.
            if (!isTerminalRunStatus(status)) {
                return
            }
            cache.disposables.dispose('reconnect-backoff')
            cache.disposables.dispose('event-source')

            // The run is done — drop its persisted resume cursor so a later reopen can't try to
            // resume a finished stream (the S3 history replay is the reopen path).
            const terminalRun = cache.activeRun as { taskId: string; runId: string } | undefined
            if (terminalRun) {
                clearStreamResumeId(terminalRun.runId)
            }

            // A run that already terminated in a prior session is surfaced read-only on reopen —
            // the reducers still record the terminal status, but re-emitting telemetry on every
            // page load would inflate termination counts.
            if (replayedFromHistory) {
                return
            }

            // Crash/failure affordance: a failed run carrying an error_message otherwise just blanks
            // the thinking indicator. Push a visible error item so the user sees why it stopped. The
            // in-sandbox agent server writes "Agent server crashed: …" on a fatal exception — render
            // that as a friendlier, retry-oriented `crash` variant; other failures show the raw line.
            if (status === 'failed' && errorMessage) {
                actions.pushErrorItem(errorMessage, errorMessage.startsWith(AGENT_CRASH_PREFIX) ? 'crash' : 'error')
            }

            // TASK_RUN_TERMINATED telemetry. `duration_ms` is measured from the current turn's start
            // (run start for the first turn, the latest human message for a follow-up); absent if the
            // run terminated before either was seen.
            const activeRun = cache.activeRun as { taskId: string; runId: string } | undefined
            const startedAt = cache.turnStartedAtMs as number | undefined
            posthog.capture('task_run_terminated', {
                conversation_id: props.conversationId,
                trace_id: values.traceId,
                run_id: activeRun?.runId,
                task_id: activeRun?.taskId,
                status,
                error_message: errorMessage ?? undefined,
                execution_type: 'sandbox',
                duration_ms: startedAt !== undefined ? Date.now() - startedAt : undefined,
            })
        },
        handleStreamError: ({ errorTitle, retryable }) => {
            // A stream/connection failure no longer appends an inline error item (which stacked up as
            // spam on a flapping stream). It sets `sseStatus='error'` + the error envelope via the reducers,
            // which the `runConnectionState` selector projects into the single footer `RunAlertActivity`
            // card. Here we only capture the disconnect telemetry that mirrors the cloud client's
            // CLOUD_STREAM_DISCONNECTED (the relay can't see a client-side reconnect-budget exhaustion).
            const activeRun = cache.activeRun as { taskId: string; runId: string } | undefined
            posthog.capture('sandbox_stream_disconnected', {
                conversation_id: props.conversationId,
                trace_id: values.traceId,
                run_id: activeRun?.runId,
                task_id: activeRun?.taskId,
                error_title: errorTitle,
                retryable,
                reconnect_attempts: values.reconnectAttempt,
                stream_error_attempts: 0,
                cumulative_reconnect_attempts: values.cumulativeReconnectAttempt,
                was_bootstrapping: cache.isBootstrapping === true,
                execution_type: 'sandbox',
            })
        },
        closeSse: () => {
            cache.activeRun = undefined
            cache.lastEventId = undefined
            cache.disposables.dispose('reconnect-backoff')
            // Aborts the in-flight fetch reader (its signal); the reader loop sees `aborted` and
            // exits without scheduling a reconnect.
            cache.disposables.dispose('event-source')
        },
        reset: () => {
            // `log` clears via its own reducer on `reset`, so the projection empties with it.
            cache.activeRun = undefined
            cache.turnStartedAtMs = undefined
            cache.isBootstrapping = false
            cache.bufferingLiveFrames = false
            cache.bufferedLiveFrames = undefined
            cache.sseConnectedAtMs = undefined
            cache.streamEnded = false
            cache.streamTokenRefreshes = 0
            // Drop the resume cursor so the next bootstrap opens fresh (start=latest) instead of
            // resuming a prior run's stream.
            cache.lastEventId = undefined
            cache.disposables.dispose('reconnect-backoff')
            cache.disposables.dispose('event-source')
        },
        startOptimisticRun: ({ message }) => {
            actions.setRunOpening(true)
            if (message) {
                actions.pushHumanMessage(message)
            }
        },
        pushHumanMessage: ({ content }) => {
            // The echo is always a live turn (replayed human turns render straight from the log), so
            // stamp the turn start for per-turn duration metrics and append it as a `client`-sourced
            // log entry the projection renders in order.
            cache.turnStartedAtMs = Date.now()
            actions.appendEntries([
                {
                    entry: {
                        type: 'notification',
                        notification: { method: '_client/human_message', params: { content } },
                    },
                    source: 'client',
                },
            ])
        },
        pushErrorItem: ({ errorMessage, variant }) => {
            // Client-side errors (terminal failure, stream disconnect) aren't wire frames — append
            // them as `client`-sourced log entries so the projection renders them in thread order.
            actions.appendEntries([
                {
                    entry: {
                        type: 'notification',
                        notification: { method: '_client/error', params: { message: errorMessage, variant } },
                    },
                    source: 'client',
                },
            ])
        },
        ingestAcpFrame: ({ entry, source }) => {
            const notification = entry?.notification
            if (!notification) {
                return
            }
            const method = notification.method
            const isReplay = source === 'replay'

            // Pre-update tool status for the once-per-transition `tool_call_completed` telemetry,
            // read from the projection BEFORE the append folds this update in. Live only — replay
            // suppresses the telemetry, so the lookup (and its O(N) re-fold) is skipped for history.
            let preToolStatus: ToolInvocationStatus | undefined
            if (!isReplay && method === 'session/update') {
                const u = notification.params?.update
                if (isRecord(u) && u.sessionUpdate === 'tool_call_update') {
                    preToolStatus = values.toolInvocations.get(String(u.toolCallId ?? ''))?.status
                }
            }

            // Append to the ordered log — the single source of truth. The bootstrap seam was already
            // deduped (see `bootstrapRun`) and steady-state live frames resume exclusively, so the
            // side effects below run exactly once per frame without a per-frame key; the
            // run-started/permission/tool-completion guards enforce fire-once on their own.
            actions.appendEntries([{ entry, source }])

            // Custom `_posthog/*` notification namespace emitted by the agent-server. Thread items
            // (errors, status, compaction, task notifications, progress, human turns) are derived by
            // the projection straight from the log — handled here only for their value-fold side
            // effects (telemetry, usage/resources/mode folds, permission routing).
            if (method === '_posthog/run_started') {
                // TASK_RUN_STARTED telemetry — emit once per run on the first `_posthog/run_started`
                // frame. Suppressed while replaying history (the run started in a prior session);
                // `markRunStarted` still runs so started/thinking state stays correct.
                if (!values.runStarted && !isReplay) {
                    const activeRun = cache.activeRun as { taskId: string; runId: string } | undefined
                    cache.turnStartedAtMs = Date.now()
                    posthog.capture('task_run_started', {
                        conversation_id: props.conversationId,
                        trace_id: values.traceId,
                        run_id: activeRun?.runId,
                        task_id: activeRun?.taskId,
                        execution_type: 'sandbox',
                        // The run-started frame carries no warmth signal and pre-warming isn't wired
                        // yet, so every run is a cold start. A later pre-warm hook flips this.
                        cold_start: true,
                    })
                }
                cache.isBootstrapping = false
                actions.markRunStarted()
                return
            }
            if (method === '_posthog/turn_complete') {
                actions.markTurnComplete()
                return
            }
            if (method === '_posthog/progress') {
                const progress = (notification.params ?? {}) as PosthogProgressParams
                actions.setCurrentProgress(
                    stringifyOptional(progress.label) ?? stringifyOptional(progress.detail) ?? ''
                )
                return
            }
            // The agent-server persists the permission lifecycle to the run log — pending approvals
            // are re-derived on bootstrap (a reload mid-approval would otherwise lose the card while
            // the agent stays blocked), and a resolution observed here clears the local card.
            if (isPosthogNotification(notification, '_posthog/permission_request')) {
                const record = parsePermissionRequestFrame(notification.params ?? {})
                if (
                    record &&
                    !values.seenPermissionRequestIds.has(record.requestId) &&
                    !values.resolvedPermissionRequestIds.has(record.requestId)
                ) {
                    actions.routePermissionRequest(record, isReplay)
                }
                return
            }
            if (isPosthogNotification(notification, '_posthog/permission_resolved')) {
                const requestId = notification.params?.requestId
                if (typeof requestId === 'string' && requestId) {
                    actions.markPermissionRequestResolved(requestId)
                }
                return
            }
            // The agent reports, per turn, which PostHog products an answer was grounded in.
            if (isPosthogNotification(notification, '_posthog/resources_used')) {
                actions.mergeResourcesUsed(notification.params?.products ?? [])
                return
            }
            // Token usage + cost + context-window breakdown. The numeric used/size aggregate that
            // drives the percentage ring arrives separately on a session/update (handled below).
            if (isPosthogNotification(notification, '_posthog/usage_update')) {
                actions.setContextUsage(foldUsageNotification(values.contextUsage, notification.params ?? {}))
                return
            }
            // Diagnostic only — no UI; kept for resume telemetry / crash-affordance work.
            if (isPosthogNotification(notification, '_posthog/sdk_session')) {
                const params = notification.params
                actions.setSdkSession({ sessionId: params?.sessionId, adapter: params?.adapter })
                return
            }
            if (method?.startsWith('_posthog/')) {
                // _posthog/error, _posthog/status, _posthog/compact_boundary, _posthog/task_notification,
                // _posthog/user_message → rendered by the projection. _posthog/console, _posthog/
                // sandbox_output, _posthog/git_checkpoint, … → no UI. No side effect either way.
                return
            }
            // session/prompt never renders and the resume-context filter is handled in the projection.
            if (method === 'session/prompt') {
                return
            }
            if (!isSessionUpdateNotification(notification)) {
                return
            }
            const update = notification.params?.update
            // The numeric used/size usage aggregate is session/update-framed — fold it into the ring.
            if (isSessionUpdateUsage(update)) {
                actions.setContextUsage(foldUsageAggregate(values.contextUsage, update))
                return
            }
            // Wire user turns render only on replay (the projection branches on source) — no side effect.
            if (isSessionUpdateUserMessage(update)) {
                return
            }
            if (!isKnownSessionUpdate(update)) {
                return
            }
            if (update.sessionUpdate === 'current_mode_update') {
                actions.setCurrentMode(String(update.currentModeId ?? update.mode ?? ''))
                return
            }
            if (update.sessionUpdate === 'tool_call_update') {
                // TOOL_CALL_COMPLETED telemetry — emit once when a tool call first transitions to a
                // terminal status. `preToolStatus` (read before the upsert) gates the once-only fire;
                // the resolved key comes from the merged invocation in the projection. Suppressed on
                // replay, and skipped when the creating `tool_call` was lost (no pre-status).
                const toolCallId = String(update.toolCallId ?? '')
                if (!toolCallId) {
                    return
                }
                const status = mapAcpStatus(update.status ?? preToolStatus)
                if (
                    !isReplay &&
                    preToolStatus !== undefined &&
                    preToolStatus !== 'completed' &&
                    preToolStatus !== 'failed' &&
                    (status === 'completed' || status === 'failed')
                ) {
                    const invocation = values.toolInvocations.get(toolCallId)
                    const startedAt = cache.turnStartedAtMs as number | undefined
                    posthog.capture('tool_call_completed', {
                        conversation_id: props.conversationId,
                        trace_id: values.traceId,
                        tool_call_id: toolCallId,
                        tool_qualified_name: invocation ? resolveToolCall(invocation).resolvedKey : undefined,
                        status,
                        duration_ms: startedAt !== undefined ? Date.now() - startedAt : undefined,
                        execution_type: 'sandbox',
                    })
                }
                return
            }
            // agent_message_chunk / agent_message / agent_thought_chunk / tool_call → projection only.
        },
    })),
])
