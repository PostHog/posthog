import type { SseEvent } from '@/api/sse'
import type { TaskRunApi } from '@/api/tasks'
import { asRecord } from '@/lib/records'
import type { TaskRunStatus } from '@/model/types'

import { parsePermissionRequest, requestKind } from './permissionRequest'
import { routePermissionRequest } from './toolPolicy'
import { describeToolCall, mergeToolCallSource, toolCallSource } from './toolTitle'
import type { PermissionRecord, RunStreamState } from './types'

// Frame formats are in `docs/HANDOFF.md`. Web reference: `products/posthog_ai/frontend/logics/runStreamLogic.ts`.

const RUN_STATUSES: ReadonlySet<string> = new Set([
    'not_started',
    'queued',
    'in_progress',
    'completed',
    'failed',
    'cancelled',
])
const TERMINAL_STATUSES: ReadonlySet<TaskRunStatus> = new Set(['completed', 'failed', 'cancelled'])

/** Session updates that mean the agent is working again, so an ended turn is over. */
const AGENT_GENERATING_UPDATES: ReadonlySet<string> = new Set([
    'agent_message',
    'agent_message_chunk',
    'agent_thought_chunk',
    'tool_call',
    'plan',
])

const HANDLED_REQUEST_LIMIT = 200

export function isTerminalRunStatus(status: TaskRunStatus): boolean {
    return TERMINAL_STATUSES.has(status)
}

export function initialRunState(taskId: string, runId: string, status: TaskRunStatus = 'queued'): RunStreamState {
    return {
        taskId,
        runId,
        status,
        phase: 'unknown',
        prUrls: [],
        handledRequestIds: [],
        turnEnded: false,
        messageOpen: false,
        activity: 0,
    }
}

function asString(value: unknown): string | undefined {
    return typeof value === 'string' && value ? value : undefined
}

function addHandled(ids: readonly string[], requestId: string): string[] {
    if (ids.includes(requestId)) {
        return [...ids]
    }
    return [...ids, requestId].slice(-HANDLED_REQUEST_LIMIT)
}

export function markRequestHandled(state: RunStreamState, requestId: string): RunStreamState {
    return {
        ...state,
        handledRequestIds: addHandled(state.handledRequestIds, requestId),
        pending: state.pending?.record.requestId === requestId ? undefined : state.pending,
    }
}

/** A terminal run cannot take an answer, so its pending request and ended turn go away. */
function settle(state: RunStreamState): RunStreamState {
    return isTerminalRunStatus(state.status)
        ? {
              ...state,
              phase: 'idle',
              pending: undefined,
              turnEnded: false,
              messageOpen: false,
              toolTitle: undefined,
              latestToolCallId: undefined,
              latestToolCall: undefined,
              progressLabel: undefined,
              serverStage: undefined,
          }
        : state
}

function applyRunFields(state: RunStreamState, run: Record<string, unknown>): RunStreamState {
    const next: RunStreamState = { ...state }
    if (!isTerminalRunStatus(state.status) && typeof run.status === 'string' && RUN_STATUSES.has(run.status)) {
        next.status = run.status as TaskRunStatus
    }
    if ('stage' in run) {
        next.serverStage = asString(run.stage)
    }
    if ('error_message' in run) {
        next.errorMessage = asString(run.error_message)
    }
    const output = asRecord(run.output)
    if (output) {
        const urls = Array.isArray(output.pr_urls)
            ? output.pr_urls.filter((url): url is string => typeof url === 'string' && url.length > 0)
            : []
        const prUrl = asString(output.pr_url) ?? urls[0]
        if (prUrl) {
            next.prUrl = prUrl
            next.prUrls = [...new Set([...next.prUrls, prUrl, ...urls])]
        }
    }
    return settle(next)
}

export function applyRunSnapshot(state: RunStreamState, run: TaskRunApi): RunStreamState {
    return run.id === state.runId && run.task === state.taskId
        ? applyRunFields(state, run as unknown as Record<string, unknown>)
        : state
}

export function displayStage(state: RunStreamState): string | undefined {
    return state.turnEnded || state.phase === 'idle' || isTerminalRunStatus(state.status)
        ? undefined
        : (state.progressLabel ?? state.toolTitle ?? state.serverStage)
}

export type RunEffect = { type: 'auto_allow'; requestId: string; optionId: string; record: PermissionRecord }

export interface FrameContext {
    /** `replay` for durable-log frames (`log-<n>` ids), `live` otherwise. */
    source: 'replay' | 'live'
    /** The run a replayed frame belongs to. A resumed run's log starts with its predecessors. */
    sourceRunId: string
}

export interface ReduceResult {
    state: RunStreamState
    effects: RunEffect[]
}

function unchanged(state: RunStreamState): ReduceResult {
    return { state, effects: [] }
}

function reducePermissionRequest(state: RunStreamState, params: unknown, context: FrameContext): ReduceResult {
    const record = parsePermissionRequest(params)
    if (
        !record ||
        context.sourceRunId !== state.runId ||
        isTerminalRunStatus(state.status) ||
        state.handledRequestIds.includes(record.requestId) ||
        state.pending?.record.requestId === record.requestId
    ) {
        return unchanged(state)
    }
    const replayed = context.source === 'replay'
    const route = routePermissionRequest(record, { mode: state.mode, replayed })
    const active: RunStreamState = { ...state, turnEnded: false, messageOpen: false, activity: state.activity + 1 }
    if (route.action === 'auto_allow') {
        return {
            state: { ...active, handledRequestIds: addHandled(state.handledRequestIds, record.requestId) },
            effects: [{ type: 'auto_allow', requestId: record.requestId, optionId: route.optionId, record }],
        }
    }
    return { state: { ...active, pending: { record, kind: requestKind(record), replayed } }, effects: [] }
}

function messageText(update: Record<string, unknown>): string {
    const content = asRecord(update.content)
    if (content && typeof content.text === 'string') {
        return content.text
    }
    return typeof update.text === 'string' ? update.text : ''
}

function reduceSessionUpdate(
    state: RunStreamState,
    update: Record<string, unknown>,
    context: FrameContext
): RunStreamState {
    const kind = update.sessionUpdate
    if (typeof kind !== 'string') {
        return state
    }
    let next = AGENT_GENERATING_UPDATES.has(kind)
        ? { ...state, turnEnded: false, phase: context.source === 'live' ? ('working' as const) : ('unknown' as const) }
        : state
    switch (kind) {
        case 'agent_message_chunk': {
            const text = messageText(update)
            if (!text) {
                return next
            }
            return {
                ...next,
                messageOpen: true,
                activity: next.messageOpen ? next.activity : next.activity + 1,
            }
        }
        case 'agent_message': {
            const text = messageText(update)
            return text ? { ...next, messageOpen: false, activity: next.activity + 1 } : next
        }
        case 'agent_thought_chunk':
        case 'plan':
            return { ...next, messageOpen: false, activity: next.activity + 1 }
        case 'tool_call': {
            const toolCallId = asString(update.toolCallId)
            const source = toolCallSource(update)
            const { title } = describeToolCall(source, asString(update.title))
            next = { ...next, messageOpen: false, activity: next.activity + 1 }
            if (toolCallId) {
                next.latestToolCallId = toolCallId
                next.latestToolCall = source
            }
            if (title) {
                next.toolTitle = title
            }
            return next
        }
        case 'tool_call_update': {
            const toolCallId = asString(update.toolCallId)
            if (toolCallId && toolCallId === next.latestToolCallId) {
                const source = mergeToolCallSource(next.latestToolCall, toolCallSource(update))
                const { title } = describeToolCall(source, asString(update.title))
                next = { ...next, latestToolCall: source, ...(title ? { toolTitle: title } : {}) }
            }
            // Another client answered: the tool the agent asked about has finished. Resolution
            // frames only arrive in the durable-log replay, never live.
            const status = update.status
            if (
                next.pending &&
                toolCallId === next.pending.record.toolCallId &&
                (status === 'completed' || status === 'failed')
            ) {
                next = markRequestHandled(next, next.pending.record.requestId)
            }
            return next
        }
        case 'current_mode_update': {
            const mode = asString(update.currentModeId) ?? asString(update.mode)
            return mode ? { ...next, mode } : next
        }
        default:
            return next
    }
}

function reduceNotification(
    state: RunStreamState,
    notification: Record<string, unknown>,
    context: FrameContext
): ReduceResult {
    const method = notification.method
    const params = asRecord(notification.params) ?? {}
    switch (method) {
        case 'session/update': {
            const update = asRecord(params.update)
            return unchanged(update ? reduceSessionUpdate(state, update, context) : state)
        }
        case 'session/new': {
            // The starting permission mode rides here; the adapter only sends `current_mode_update` on changes.
            const mode = asString(asRecord(params._meta)?.permissionMode)
            return unchanged(mode ? { ...state, mode } : state)
        }
        case '_posthog/progress': {
            if (params.step === 'pr' && params.status === 'completed' && typeof params.detail === 'string') {
                try {
                    const url = new URL(params.detail)
                    if (url.protocol === 'https:' && /\/(?:pull|merge_requests)\/\d+\/?$/.test(url.pathname)) {
                        return unchanged({
                            ...state,
                            prUrl: params.detail,
                            prUrls: [...new Set([...state.prUrls, params.detail])],
                        })
                    }
                } catch {
                    return unchanged(state)
                }
            }
            const status = params.status
            const done = status === 'completed' || status === 'failed' || status === 'cancelled'
            const label = done ? undefined : (asString(params.label) ?? asString(params.detail))
            if (label === state.progressLabel) {
                return unchanged(state)
            }
            return unchanged({
                ...state,
                progressLabel: label,
                turnEnded: label ? false : state.turnEnded,
                activity: state.activity + 1,
            })
        }
        case '_posthog/turn_complete':
            return unchanged({
                ...(state.pending ? markRequestHandled(state, state.pending.record.requestId) : state),
                turnEnded: true,
                phase: 'idle',
                toolTitle: undefined,
                latestToolCallId: undefined,
                latestToolCall: undefined,
                serverStage: undefined,
                messageOpen: false,
                progressLabel: undefined,
                pending: undefined,
            })
        case '_posthog/error': {
            const message = asString(params.message) ?? asString(params.error)
            return unchanged(message ? { ...state, errorMessage: message } : state)
        }
        case '_posthog/permission_request':
            return reducePermissionRequest(state, params, context)
        case '_posthog/permission_resolved': {
            const requestId = asString(params.requestId)
            if (!requestId || context.sourceRunId !== state.runId) {
                return unchanged(state)
            }
            return unchanged(markRequestHandled(state, requestId))
        }
        default:
            return unchanged(state)
    }
}

export function reduceFrame(state: RunStreamState, frame: unknown, context: FrameContext): ReduceResult {
    const record = asRecord(frame)
    if (!record || context.sourceRunId !== state.runId) {
        return unchanged(state)
    }
    if (context.source === 'replay' && state.liveActivitySeen && record.type !== 'task_run_state') {
        const notification = asRecord(record.notification)
        const method = notification?.method
        const update = asRecord(asRecord(notification?.params)?.update)
        if (
            method === 'session/update' &&
            update?.sessionUpdate === 'tool_call_update' &&
            update.toolCallId === state.pending?.record.toolCallId &&
            (update.status === 'completed' || update.status === 'failed') &&
            state.pending
        ) {
            return unchanged(markRequestHandled(state, state.pending.record.requestId))
        }
        if (method === 'session/new' || method === '_posthog/error') {
            return unchanged(state)
        }
        if (method === '_posthog/turn_complete') {
            return unchanged(
                state.pending?.replayed ? markRequestHandled(state, state.pending.record.requestId) : state
            )
        }
        if (method === 'session/update' && update?.sessionUpdate !== 'current_mode_update') {
            return unchanged(state)
        }
        if (method === '_posthog/progress') {
            const params = asRecord(notification?.params)
            if (params?.step !== 'pr' || params.status !== 'completed') {
                return unchanged(state)
            }
        }
    }
    if (isTerminalRunStatus(state.status) && record.type !== 'task_run_state') {
        return unchanged(state)
    }
    const notification = asRecord(record.notification)
    const method = notification?.method
    const update = asRecord(asRecord(notification?.params)?.update)
    const isLiveActivity =
        record.type === 'permission_request' ||
        method === '_posthog/permission_request' ||
        method === '_posthog/turn_complete' ||
        (method === 'session/update' &&
            typeof update?.sessionUpdate === 'string' &&
            AGENT_GENERATING_UPDATES.has(update.sessionUpdate))
    if (context.source === 'live' && isLiveActivity) {
        state = { ...state, liveActivitySeen: true }
    }
    switch (record.type) {
        case 'task_run_state': {
            if (asString(record.run_id) && record.run_id !== state.runId) {
                return unchanged(state)
            }
            const terminal =
                record.run_id === state.runId &&
                typeof record.status === 'string' &&
                TERMINAL_STATUSES.has(record.status as TaskRunStatus)
            return unchanged(
                applyRunFields(state, context.source === 'replay' && !terminal ? { output: record.output } : record)
            )
        }
        case 'permission_request':
            return reducePermissionRequest(state, record, context)
        case 'notification': {
            const notification = asRecord(record.notification)
            return notification ? reduceNotification(state, notification, context) : unchanged(state)
        }
        default:
            return unchanged(state)
    }
}

export type StreamControl =
    /** `end` rotated: the connection hit its time cap. Reconnect at once with the cursor. */
    | { type: 'rotated' }
    /** `end` resync: the cursor is no longer valid. Reconnect without it. */
    | { type: 'resync' }
    | { type: 'ended' }
    /** `error`: the server closes after this. Reconnect with backoff. */
    | { type: 'error'; message: string }

export interface StreamEventResult {
    frame?: { data: unknown; context: FrameContext }
    control?: StreamControl
}

/** Event ids kept for dedupe. Delivery is at-least-once around a reconnect, so recent ids suffice. */
const SEEN_EVENT_LIMIT = 2000

export class RunStreamCursor {
    cursor: string | undefined
    private readonly runId: string
    private readonly seen = new Set<string>()
    private readonly seenOrder: string[] = []
    private backlogRunId: string

    constructor(runId: string) {
        this.runId = runId
        this.backlogRunId = runId
    }

    fork(): RunStreamCursor {
        const fork = new RunStreamCursor(this.runId)
        fork.cursor = this.cursor
        fork.backlogRunId = this.backlogRunId
        for (const eventId of this.seenOrder) {
            fork.seen.add(eventId)
            fork.seenOrder.push(eventId)
        }
        return fork
    }

    resetCursor(): void {
        this.cursor = undefined
        this.backlogRunId = this.runId
    }

    private remember(eventId: string): boolean {
        if (this.seen.has(eventId)) {
            return false
        }
        this.seen.add(eventId)
        this.seenOrder.push(eventId)
        if (this.seenOrder.length > SEEN_EVENT_LIMIT) {
            const oldest = this.seenOrder.shift()
            if (oldest !== undefined) {
                this.seen.delete(oldest)
            }
        }
        return true
    }

    accept(event: SseEvent): StreamEventResult {
        switch (event.event) {
            case 'keepalive':
                return {}
            case 'stream-end':
                this.resetCursor()
                return { control: { type: 'ended' } }
            case 'end': {
                const control = asRecord(safeParse(event.data))
                if (control?.type === 'resync') {
                    this.resetCursor()
                    return { control: { type: 'resync' } }
                }
                return { control: { type: 'rotated' } }
            }
            case 'error': {
                const body = asRecord(safeParse(event.data))
                return { control: { type: 'error', message: asString(body?.error) ?? 'Stream failed' } }
            }
            case 'message':
                break
            default:
                return {}
        }
        const data = safeParse(event.data)
        const replay = event.id?.startsWith('log-') ?? false
        if (event.id) {
            this.cursor = event.id
        }
        const record = asRecord(data)
        if (!record) {
            return {}
        }
        if (replay && record.type === 'notification') {
            const notification = asRecord(record.notification)
            const params = asRecord(notification?.params)
            const marker =
                notification?.method === '_posthog/run_started'
                    ? asString(params?.runId)
                    : notification?.method === '_posthog/sdk_session'
                      ? asString(params?.taskRunId)
                      : undefined
            if (marker) {
                this.backlogRunId = marker
            }
        }
        const eventId = asString(record.event_id)
        if (eventId && !this.remember(eventId)) {
            return {}
        }
        const sourceRunId = asString(record.source_run_id) ?? (replay ? this.backlogRunId : this.runId)
        return { frame: { data, context: { source: replay ? 'replay' : 'live', sourceRunId } } }
    }
}

function safeParse(data: string): unknown {
    try {
        return JSON.parse(data) as unknown
    } catch {
        return undefined
    }
}

export const RECONNECT_ATTEMPTS_PER_DROP = 10
export const RECONNECT_ATTEMPTS_TOTAL = 30

export function reconnectDelayMs(attempt: number): number {
    return Math.min(2000 * 2 ** attempt, 30_000)
}

export function shouldReconnect(state: RunStreamState, attempts: { perDrop: number; total: number }): boolean {
    return (
        !isTerminalRunStatus(state.status) &&
        attempts.perDrop < RECONNECT_ATTEMPTS_PER_DROP &&
        attempts.total < RECONNECT_ATTEMPTS_TOTAL
    )
}
