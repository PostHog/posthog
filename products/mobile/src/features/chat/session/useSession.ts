import { randomUUID } from 'expo-crypto'
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'

import { ApiError } from '@/api/client'
import { readSse } from '@/api/sse'
import {
    type ArtifactUploadTarget,
    createTask,
    deleteTask,
    getTask,
    getTaskRun,
    getTaskRunLogs,
    openTaskRunStream,
    type PermissionModeApi,
    type SetConfigOptionParams,
    sendTaskRunCommand,
    startTaskRun,
    type TaskRunApi,
    type TaskRunCreateRequestApi,
} from '@/api/tasks'
import { useAuthStore } from '@/auth/authStore'
import { sessionGeneration } from '@/auth/tokens'
import { useDemoMode } from '@/demo/demoMode'
import { DEMO_ANSWER_REPLY, DEMO_REPLY, demoSessionLog, demoSessionRunId } from '@/demo/sessionThreads'
import { useAiApproval } from '@/features/ai/aiApproval'
import {
    CommandFailedError,
    deliverPermissionResponse,
    type RunRef,
    sendUserMessage,
} from '@/features/handoff/commands'
import { answerErrorMessage } from '@/features/handoff/hooks'
import { RunNotStartedError, withWarmRetry } from '@/features/handoff/kickoff'
import { pullRequestFromUrl } from '@/features/handoff/liveReport'
import { decisionQuestionFor, planAnswer, requestKind } from '@/features/handoff/permissionRequest'
import { HYDRATION_QUIET_MS } from '@/features/handoff/runHydration'
import {
    applyRunSnapshot,
    displayStage,
    type FrameContext,
    initialRunState,
    isTerminalRunStatus,
    markRequestHandled,
    type RunEffect,
    RunStreamCursor,
    reconnectDelayMs,
    reduceFrame,
    type StreamControl,
    shouldReconnect,
} from '@/features/handoff/runStream'
import type { PermissionRecord, RunStreamState } from '@/features/handoff/types'
import { IDLE_TIMEOUT_MS, isAbort, isFatal, useAppActive } from '@/features/handoff/useTaskRun'
import { abortError } from '@/lib/abort'
import { track } from '@/lib/analytics'
import { asRecord } from '@/lib/records'
import { sleep } from '@/lib/sleep'
import type { DecisionAnswerInput } from '@/model/types'
import type { PendingAttachment } from '../attachments/types'
import { AttachmentUploadError, uploadAttachments } from '../attachments/uploadAttachments'
import { toChatError } from '../chatErrors'
import { type ChatRunOptions, DEFAULT_CHAT_RUN_OPTIONS } from '../chatRunOptions'
import { bareQuestion, chatPrompt } from '../contextPrompt'
import type { ChatContext, ChatError } from '../types'
import { historyFrames, initialSessionThread, type SessionFrame, sessionThreadReducer } from './sessionReducer'
import {
    applyConfigChange,
    chatRunFields,
    chatStartRequests,
    configSyncPlan,
    currentPermissionMode,
    harnessMismatchMessage,
    type RunSourceFieldsApi,
    runConfigAfterStart,
    runConfigFromRun,
    runSourceFields,
    sentOptionProperties,
    type TrackedRunConfig,
    withPendingArtifacts,
    withStreamModeReport,
} from './sessionRun'
import { SessionTurnTracker } from './sessionTurn'
import type { SendOptions, Session, SessionAttachment, SessionDecision, SessionHistory, SessionPhase } from './types'

// Drives a sandbox task run in the chat sheet through the tasks API. Stream handling follows `docs/HANDOFF.md`.

export interface SessionOptions {
    taskId?: string
    /** Follows this run instead of the task's latest one. */
    runId?: string
}

const STOP_TIMEOUT_MS = 10_000
const CONFIG_STARTUP_WAIT_MS = 10_000
const CONFIG_RETRY_DELAY_MS = 500

const NOT_STARTED = "The agent hasn't started yet."
const STOP_FAILED = "Couldn't stop this run. Try again."
const ANSWERED_ELSEWHERE = 'Someone else answered this already.'
const ANSWER_RUN_ENDED = "Your answer wasn't sent. The run ended."
const CONNECTION_LOST = 'The connection to the agent dropped. Close this chat and open it again.'
const CONFIG_NOT_APPLIED = "Your model or mode change didn't reach the agent. Try again."
const UPLOAD_FAILED = "Your files didn't upload. Try again."

const LOADING: SessionHistory = { status: 'loading', error: null }
const IDLE: SessionHistory = { status: 'idle', error: null }

const UNKNOWN_RUN_CONFIG: TrackedRunConfig = {
    runtimeAdapter: null,
    model: null,
    reasoningEffort: null,
    permissionMode: null,
    modeSetHere: false,
}

/** A `set_config_option` the agent did not apply. The send stops before its `user_message`. */
class ConfigSyncError extends Error {
    constructor(message: string) {
        super(message)
        this.name = 'ConfigSyncError'
    }
}

/** The run ended before its config changed, so the message starts a resume run that carries the options instead. */
class RunEndedError extends Error {
    constructor() {
        super('The run ended.')
        this.name = 'RunEndedError'
    }
}

interface PartialAnswer {
    requestId: string
    labels: string[]
}

interface Follow {
    runId: string
    key: number
    fresh?: boolean
}

interface CursorEntry {
    cursor: RunStreamCursor
    /** A later connection with no cursor replays the log again, so the thread rebuilds from it. */
    followed: boolean
    hydrate: boolean
    pendingFrames: SessionFrame[]
}

function wait(ms: number, signal: AbortSignal): Promise<void> {
    return sleep(ms, signal).catch(() => undefined)
}

function isResumeRun(run: TaskRunApi): boolean {
    const resumeFrom = run.state?.resume_from_run_id
    return typeof resumeFrom === 'string' && resumeFrom !== ''
}

function sessionUpdate(frame: unknown): Record<string, unknown> | undefined {
    const record = asRecord(frame)
    const notification = asRecord(record?.notification)
    if (record?.type !== 'notification' || notification?.method !== 'session/update') {
        return undefined
    }
    return asRecord(asRecord(notification.params)?.update) ?? {}
}

function sendErrorMessage(error: unknown): string {
    if (error instanceof ConfigSyncError) {
        return error.message
    }
    if (error instanceof AttachmentUploadError) {
        return UPLOAD_FAILED
    }
    if (error instanceof CommandFailedError) {
        return "The agent didn't take your message. Try again."
    }
    if (error instanceof RunNotStartedError) {
        return "PostHog couldn't start the agent. Try again."
    }
    if (error instanceof ApiError) {
        if (error.code === 'warm_run_activation_unavailable') {
            return "PostHog couldn't start the agent in time. Try again."
        }
        if (error.status === 402 && error.detail) {
            return error.detail
        }
    }
    return toChatError(error).message
}

type SendErrorCode =
    | 'upload_failed'
    | 'config_rejected'
    | 'command_failed'
    | 'run_not_started'
    | 'warm_run_unavailable'
    | ChatError['kind']

/** The `code` of `mobile_session_send_failed`, which follows the cases of `sendErrorMessage`. */
function sendErrorCode(error: unknown): SendErrorCode {
    if (error instanceof AttachmentUploadError) {
        return 'upload_failed'
    }
    if (error instanceof ConfigSyncError) {
        return 'config_rejected'
    }
    if (error instanceof CommandFailedError) {
        return 'command_failed'
    }
    if (error instanceof RunNotStartedError) {
        return 'run_not_started'
    }
    if (error instanceof ApiError && error.code === 'warm_run_activation_unavailable') {
        return 'warm_run_unavailable'
    }
    return toChatError(error).kind
}

/**
 * A run the server definitely did not start, so the task a new chat just created can go. A 5xx other than 503, or
 * a lost connection, may still have started one, and deleting the task would hide a run that keeps going.
 */
function isRunRefused(error: unknown): boolean {
    return error instanceof ApiError && ((error.status >= 400 && error.status < 500) || error.status === 503)
}

function localAttachments(files: readonly PendingAttachment[]): SessionAttachment[] {
    return files.map((file) => ({ name: file.name, isImage: file.isImage, localUri: file.uri }))
}

/**
 * Uploads a send's files and reports a failure. Every failure here becomes an `AttachmentUploadError`, so the person
 * sees the upload copy instead of a server's copy for prepare or finalize. A send without files makes no request.
 */
async function uploadSendFiles(
    target: ArtifactUploadTarget,
    files: readonly PendingAttachment[],
    signal: AbortSignal,
    newTask: boolean
): Promise<string[]> {
    if (files.length === 0) {
        return []
    }
    try {
        return await uploadAttachments(target, files, signal)
    } catch (error) {
        if (isAbort(error, signal)) {
            throw error
        }
        const failure =
            error instanceof AttachmentUploadError
                ? error
                : new AttachmentUploadError(
                      error instanceof Error ? error.message : 'Upload failed',
                      error instanceof ApiError ? error.status : undefined
                  )
        track('mobile_chat_file_upload_failed', { status: failure.status, new_task: newTask })
        throw failure
    }
}

/** Retries while the sandbox's command channel comes up, as `deliverPermissionResponse` does. */
async function sendConfigOption(run: RunRef, params: SetConfigOptionParams, signal: AbortSignal): Promise<void> {
    const deadline = Date.now() + CONFIG_STARTUP_WAIT_MS
    for (;;) {
        try {
            const response = await sendTaskRunCommand(
                run.taskId,
                run.runId,
                { method: 'set_config_option', params },
                { id: `config-${randomUUID()}`, signal }
            )
            if (response.error) {
                throw new ConfigSyncError(CONFIG_NOT_APPLIED)
            }
            return
        } catch (error) {
            if (!(error instanceof ApiError)) {
                throw error
            }
            if (error.status === 409) {
                throw new RunEndedError()
            }
            if (
                error.status === 503 &&
                error.code === 'sandbox_not_ready' &&
                !signal.aborted &&
                Date.now() < deadline
            ) {
                await sleep((error.retryAfterSeconds ?? 0) * 1000 || CONFIG_RETRY_DELAY_MS, signal)
                continue
            }
            if (error.status === 400) {
                // Such as a model outside the run's gateway pin. The server copy says which.
                throw new ConfigSyncError(error.detail ?? CONFIG_NOT_APPLIED)
            }
            if (error.status === 502) {
                throw new ConfigSyncError(CONFIG_NOT_APPLIED)
            }
            throw error
        }
    }
}

type SendDelivery = 'steer' | 'queue' | 'direct'

/** The `delivery` and `queued_count` of `mobile_session_sent`. */
function deliveryProperties(
    steered: boolean,
    sendOptions: SendOptions
): { delivery: SendDelivery; queued_count: number } {
    const queuedCount = sendOptions.queuedCount ?? 0
    return {
        delivery: steered ? 'steer' : queuedCount > 0 ? 'queue' : 'direct',
        queued_count: queuedCount,
    }
}

function demoFrame(update: Record<string, unknown>): Record<string, unknown> {
    return {
        type: 'notification',
        notification: { jsonrpc: '2.0', method: 'session/update', params: { sessionId: 'demo-session', update } },
    }
}

const DEMO_TURN_COMPLETE = {
    type: 'notification',
    notification: { jsonrpc: '2.0', method: '_posthog/turn_complete', params: {} },
}

/** The demo reply as the wire streams it: a few words per chunk, then the finished message. */
function demoReplyFrames(reply: string): unknown[] {
    const messageId = `demo-${randomUUID()}`
    const words = reply.split(/(\s+)/)
    const frames: unknown[] = []
    for (let start = 0; start < words.length; start += 4) {
        const text = words.slice(start, start + 4).join('')
        frames.push(demoFrame({ sessionUpdate: 'agent_message_chunk', messageId, content: { type: 'text', text } }))
    }
    frames.push(demoFrame({ sessionUpdate: 'agent_message', messageId, content: { type: 'text', text: reply } }))
    frames.push(DEMO_TURN_COMPLETE)
    return frames
}

interface FollowHandlers {
    onOpen: () => void
    onHistory: (frames: SessionFrame[]) => void
    onFrame: (data: unknown, context: FrameContext) => void
    onResync: () => void
    onReconnecting: (reconnecting: boolean) => void
    onSnapshot: (run: TaskRunApi) => RunStreamState
    getState: () => RunStreamState
}

type FollowOutcome = 'ended' | 'gave_up' | 'aborted' | { fatal: unknown }

interface ConnectionResult {
    control?: StreamControl
    progressed: boolean
}

async function readConnection(
    taskId: string,
    runId: string,
    entry: CursorEntry,
    outer: AbortSignal,
    handlers: FollowHandlers
): Promise<ConnectionResult> {
    const connection = new AbortController()
    const abort = (): void => connection.abort()
    outer.addEventListener('abort', abort, { once: true })
    const cursor = entry.cursor.fork()
    let hydrating = entry.hydrate
    let quietTimer: ReturnType<typeof setTimeout> | undefined
    const cancelQuiet = (): void => {
        if (quietTimer) {
            clearTimeout(quietTimer)
            quietTimer = undefined
        }
    }
    const publishHistory = (): void => {
        cancelQuiet()
        if (!hydrating || outer.aborted) {
            return
        }
        hydrating = false
        entry.hydrate = false
        handlers.onHistory(entry.pendingFrames)
        entry.pendingFrames = []
        entry.cursor = cursor
    }
    let idleTimer: ReturnType<typeof setTimeout> | undefined
    const resetIdle = (): void => {
        if (idleTimer) {
            clearTimeout(idleTimer)
        }
        idleTimer = setTimeout(abort, IDLE_TIMEOUT_MS)
    }
    const result: ConnectionResult = { progressed: false }
    try {
        resetIdle()
        const response = await openTaskRunStream(taskId, runId, {
            lastEventId: cursor.cursor,
            signal: connection.signal,
        })
        if (outer.aborted) {
            return result
        }
        handlers.onOpen()
        await readSse(
            response,
            (event) => {
                if (outer.aborted) {
                    return
                }
                resetIdle()
                const outcome = cursor.accept(event)
                entry.cursor = cursor
                if (outcome.frame) {
                    result.progressed = true
                    if (hydrating) {
                        // Redis frames can also be backlog, so catch-up must not trigger live effects.
                        entry.pendingFrames.push({
                            frame: outcome.frame.data,
                            context: { ...outcome.frame.context, source: 'replay' },
                        })
                    } else {
                        handlers.onFrame(outcome.frame.data, outcome.frame.context)
                    }
                }
                if (hydrating) {
                    if (event.event === 'keepalive' || outcome.control?.type === 'ended') {
                        publishHistory()
                    } else if (event.event === 'message') {
                        cancelQuiet()
                        if (!event.id?.startsWith('log-')) {
                            // The protocol has no catch-up marker. Only the Redis tail can settle on silence.
                            quietTimer = setTimeout(publishHistory, HYDRATION_QUIET_MS)
                        }
                    }
                }
                if (outcome.control) {
                    cancelQuiet()
                    if (outcome.control.type === 'resync') {
                        entry.cursor = new RunStreamCursor(runId)
                        entry.pendingFrames = []
                        entry.hydrate = true
                    }
                    result.control = outcome.control
                    // The server closes after every control event; stop reading now.
                    connection.abort()
                }
            },
            connection.signal
        )
        return result
    } catch (error) {
        if (result.control || (connection.signal.aborted && !outer.aborted)) {
            return result
        }
        throw error
    } finally {
        cancelQuiet()
        entry.hydrate = true
        if (idleTimer) {
            clearTimeout(idleTimer)
        }
        outer.removeEventListener('abort', abort)
    }
}

/** The connection loop of `useTaskRun`'s `followRun`, reporting to the session instead of the hand-off store. */
async function followSessionRun(
    taskId: string,
    runId: string,
    entry: CursorEntry,
    signal: AbortSignal,
    handlers: FollowHandlers
): Promise<FollowOutcome> {
    let perDrop = 0
    let total = 0
    while (!signal.aborted) {
        let control: StreamControl | undefined
        let retryAfterMs: number | undefined
        try {
            const result = await readConnection(taskId, runId, entry, signal, handlers)
            control = result.control
            if (result.progressed) {
                perDrop = 0
            }
        } catch (error) {
            if (isAbort(error, signal)) {
                return 'aborted'
            }
            if (isFatal(error)) {
                return { fatal: error }
            }
            if (error instanceof ApiError && error.status === 503 && error.retryAfterSeconds) {
                retryAfterMs = error.retryAfterSeconds * 1000
            }
        }
        if (signal.aborted) {
            return 'aborted'
        }
        if (control?.type === 'resync') {
            handlers.onResync()
            continue
        }
        if (control?.type === 'rotated') {
            continue
        }
        let state = handlers.getState()
        try {
            const run = await getTaskRun(taskId, runId, signal)
            if (isTerminalRunStatus(run.status) && control?.type !== 'ended') {
                // A dropped connection can hide the last frames and its completion marker.
                const entries = await getTaskRunLogs(taskId, runId, signal)
                if (signal.aborted) {
                    return 'aborted'
                }
                handlers.onResync()
                handlers.onHistory(historyFrames(entries, runId, isResumeRun(run)))
            }
            state = handlers.onSnapshot(run)
        } catch (error) {
            if (isAbort(error, signal)) {
                return 'aborted'
            }
            if (isFatal(error)) {
                return { fatal: error }
            }
        }
        if (control?.type === 'ended') {
            return 'ended'
        }
        if (!shouldReconnect(state, { perDrop, total })) {
            return isTerminalRunStatus(state.status) ? 'ended' : 'gave_up'
        }
        handlers.onReconnecting(true)
        try {
            await sleep(retryAfterMs ?? reconnectDelayMs(perDrop), signal)
        } catch {
            return 'aborted'
        }
        perDrop += 1
        total += 1
    }
    return 'aborted'
}

function sessionScope(): string {
    const { host, projectId, user } = useAuthStore.getState()
    return JSON.stringify([host, projectId, user?.uuid, sessionGeneration()])
}

export function useSession(options: SessionOptions): Session {
    const { taskId, runId: requestedRunId } = options
    const approval = useAiApproval('chat', taskId ?? 'new')
    const scope = useAuthStore((state) =>
        JSON.stringify([state.host, state.projectId, state.user?.uuid, sessionGeneration()])
    )
    const openedScope = useRef(scope)
    const scopeIsCurrent = useCallback((): boolean => sessionScope() === openedScope.current, [])
    const demo = useDemoMode((state) => state.enabled)
    const active = useAppActive()
    const [thread, dispatchThread] = useReducer(sessionThreadReducer, false, initialSessionThread)
    const [live, setLiveState] = useState<RunStreamState | null>(null)
    const [title, setTitle] = useState<string | null>(null)
    const [history, setHistory] = useState<SessionHistory>(taskId ? LOADING : IDLE)
    const [notice, setNotice] = useState<string | undefined>(undefined)
    const [isSending, setSending] = useState(false)
    const [isStopping, setStopping] = useState(false)
    const [reconnecting, setReconnecting] = useState(false)
    const [partial, setPartialState] = useState<PartialAnswer | null>(null)
    const [follow, setFollow] = useState<Follow | null>(null)
    const [followEnded, setFollowEnded] = useState(false)
    const [demoPlaying, setDemoPlaying] = useState(false)
    const [createdTaskId, setCreatedTaskId] = useState<string | null>(null)
    const [unsentText, setUnsentText] = useState<string | undefined>(undefined)
    const activeTaskId = scope === openedScope.current ? (taskId ?? createdTaskId) : null

    const taskIdRef = useRef<string | null>(activeTaskId)
    taskIdRef.current = activeTaskId
    const liveRef = useRef<RunStreamState | null>(null)
    const partialRef = useRef<PartialAnswer | null>(null)
    /** The latest run detail, whose model a follow-up run keeps. */
    const runDetail = useRef<TaskRunApi | null>(null)
    /** Increments per bootstrap and on unmount, so work that a reload abandoned cannot touch newer state. */
    const epoch = useRef(0)
    const bootController = useRef<AbortController | null>(null)
    const actionController = useRef<AbortController | null>(null)
    const cursors = useRef(new Map<string, CursorEntry>())
    /** Runs the stream showed generating. Cancelling before that would drop the run's first message. */
    const generating = useRef(new Set<string>())
    const canSteerRef = useRef(false)
    const sendingRef = useRef(false)
    const stoppingRef = useRef(false)
    const stopTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
    const runConfigs = useRef(new Map<string, TrackedRunConfig>())
    const runSource = useRef<RunSourceFieldsApi>({})
    const [turnTracker] = useState(() => new SessionTurnTracker())
    const shownDecisions = useRef(new Set<string>())

    const setLive = useCallback((next: RunStreamState | null): void => {
        liveRef.current = next
        setLiveState(next)
    }, [])

    const updateLive = useCallback(
        (runId: string, change: (state: RunStreamState) => RunStreamState): void => {
            const current = liveRef.current
            if (!current || current.runId !== runId) {
                return
            }
            const next = change(current)
            if (next !== current) {
                setLive(next)
            }
        },
        [setLive]
    )

    const setPartial = useCallback((next: PartialAnswer | null): void => {
        partialRef.current = next
        setPartialState(next)
    }, [])

    const endStopping = useCallback((): void => {
        if (stopTimer.current) {
            clearTimeout(stopTimer.current)
            stopTimer.current = null
        }
        stoppingRef.current = false
        setStopping(false)
    }, [])

    const applySnapshot = useCallback(
        (run: TaskRunApi): RunStreamState => {
            const current = liveRef.current
            const base =
                current && current.runId === run.id
                    ? current
                    : initialRunState(taskIdRef.current ?? run.task, run.id, run.status)
            const next = applyRunSnapshot(base, run)
            if (!current || current.runId === run.id) {
                runDetail.current = run
                setLive(next)
                if (isTerminalRunStatus(next.status)) {
                    dispatchThread({ type: 'settle' })
                }
            }
            return next
        },
        [setLive]
    )

    const refreshRun = useCallback(
        async (runId: string): Promise<void> => {
            const id = taskIdRef.current
            const mine = epoch.current
            if (!id) {
                return
            }
            try {
                const run = await getTaskRun(id, runId)
                if (epoch.current === mine && scopeIsCurrent()) {
                    applySnapshot(run)
                }
            } catch {
                // The stream still reports the run's state; this fetch only makes it arrive sooner.
            }
        },
        [applySnapshot, scopeIsCurrent]
    )

    const surfaceRequest = useCallback(
        (runId: string, record: PermissionRecord): void =>
            updateLive(runId, (state) => ({
                ...state,
                handledRequestIds: state.handledRequestIds.filter((id) => id !== record.requestId),
                pending: { record, kind: requestKind(record), replayed: false },
            })),
        [updateLive]
    )

    const runEffects = useCallback(
        async (run: RunRef, effects: RunEffect[], signal: AbortSignal): Promise<void> => {
            for (const effect of effects) {
                if (signal.aborted || !scopeIsCurrent()) {
                    return
                }
                try {
                    const outcome = await deliverPermissionResponse(
                        run,
                        { requestId: effect.requestId, optionId: effect.optionId },
                        { signal }
                    )
                    if (outcome === 'ended') {
                        void refreshRun(run.runId)
                    }
                } catch (error) {
                    if (isAbort(error, signal)) {
                        return
                    }
                    // Allowing on the user's behalf failed, so ask them instead of leaving the agent waiting.
                    surfaceRequest(run.runId, effect.record)
                }
            }
        },
        [refreshRun, scopeIsCurrent, surfaceRequest]
    )

    const applyFrame = useCallback(
        (data: unknown, context: FrameContext, runId: string, signal: AbortSignal): void => {
            if (!scopeIsCurrent()) {
                return
            }
            dispatchThread({ type: 'frame', frame: data, context })
            const current = liveRef.current
            if (!current || current.runId !== runId) {
                return
            }
            if (context.source === 'replay' && context.sourceRunId !== runId) {
                // An earlier run in the resume chain: its turn ends and requests say nothing about this run.
                return
            }
            const update = sessionUpdate(data)
            const tracked = runConfigs.current.get(runId)
            if (tracked && context.source === 'live' && update?.sessionUpdate === 'current_mode_update') {
                runConfigs.current.set(runId, withStreamModeReport(tracked))
            }
            const result = reduceFrame(current, data, context)
            if (context.source === 'live' && result.state.phase === 'working') {
                generating.current.add(runId)
            } else if (result.state.phase !== 'working' || result.state.turnEnded) {
                generating.current.delete(runId)
            }
            if (result.state !== current) {
                setLive(result.state)
                if (!isTerminalRunStatus(current.status) && isTerminalRunStatus(result.state.status)) {
                    dispatchThread({ type: 'settle' })
                }
            }
            const id = taskIdRef.current
            if (result.effects.length > 0 && id) {
                void runEffects({ taskId: id, runId }, result.effects, signal)
            }
        },
        [runEffects, scopeIsCurrent, setLive]
    )

    const resetState = useCallback((): void => {
        turnTracker.finish('abandoned')
        actionController.current?.abort()
        actionController.current = null
        bootController.current?.abort()
        bootController.current = null
        cursors.current.clear()
        generating.current.clear()
        runConfigs.current.clear()
        runDetail.current = null
        sendingRef.current = false
        endStopping()
        setFollow(null)
        setFollowEnded(false)
        setReconnecting(false)
        setDemoPlaying(false)
        setSending(false)
        setNotice(undefined)
        setUnsentText(undefined)
        setPartial(null)
        setLive(null)
        dispatchThread({ type: 'reset' })
    }, [endStopping, setLive, setPartial, turnTracker])

    const reloadHistory = useCallback(async (): Promise<void> => {
        epoch.current += 1
        const mine = epoch.current
        resetState()
        setCreatedTaskId(null)
        runSource.current = {}
        if (!taskId || scope !== openedScope.current) {
            taskIdRef.current = null
            setTitle(null)
            setHistory(IDLE)
            return
        }
        setHistory(LOADING)
        if (demo) {
            const log = demoSessionLog(taskId)
            if (!log) {
                setHistory({ status: 'error', error: toChatError(new ApiError(404, undefined)) })
                return
            }
            const runId = demoSessionRunId(taskId)
            const frames = historyFrames(log.entries, runId, false)
            let state = initialRunState(taskId, runId, log.status)
            for (const { frame, context } of frames) {
                state = reduceFrame(state, frame, context).state
            }
            setTitle(log.title)
            dispatchThread({ type: 'frames', frames })
            if (isTerminalRunStatus(state.status)) {
                dispatchThread({ type: 'settle' })
            }
            setLive(state)
            setHistory(IDLE)
            track('mobile_session_resumed', { status: log.status })
            return
        }
        const controller = new AbortController()
        bootController.current = controller
        const { signal } = controller
        try {
            const task = await getTask(taskId, signal)
            if (epoch.current !== mine || !scopeIsCurrent()) {
                return
            }
            setTitle(task.title || null)
            runSource.current = runSourceFields(task.signal_report)
            const run =
                requestedRunId && requestedRunId !== task.latest_run?.id
                    ? await getTaskRun(taskId, requestedRunId, signal)
                    : task.latest_run
            if (epoch.current !== mine || !scopeIsCurrent()) {
                return
            }
            if (!run) {
                setHistory(IDLE)
                track('mobile_session_resumed', { status: 'none' })
                return
            }
            runDetail.current = run
            const resumed = isResumeRun(run)
            dispatchThread({ type: 'reset', resumeRun: resumed })
            let state = applyRunSnapshot(initialRunState(taskId, run.id, run.status), run)
            if (isTerminalRunStatus(run.status)) {
                const entries = await getTaskRunLogs(taskId, run.id, signal)
                if (epoch.current !== mine || !scopeIsCurrent()) {
                    return
                }
                const frames = historyFrames(entries, run.id, resumed)
                for (const { frame, context } of frames) {
                    state = reduceFrame(state, frame, context).state
                }
                dispatchThread({ type: 'frames', frames })
                dispatchThread({ type: 'settle' })
                // The run detail is newer than any state frame in the log.
                setLive(applyRunSnapshot(state, run))
                setHistory(IDLE)
            } else {
                // Without a cursor the stream replays the stored log first, which builds the thread.
                setLive(state)
                setFollow({ runId: run.id, key: 0 })
            }
            track('mobile_session_resumed', { status: run.status })
        } catch (error) {
            if (epoch.current !== mine || !scopeIsCurrent() || isAbort(error, signal)) {
                return
            }
            setHistory({ status: 'error', error: toChatError(error) })
        } finally {
            if (bootController.current === controller) {
                bootController.current = null
            }
        }
    }, [demo, requestedRunId, resetState, setLive, taskId, scope, scopeIsCurrent])

    useEffect(() => {
        reloadHistory().catch(() => undefined)
    }, [reloadHistory])

    useEffect(
        () => () => {
            turnTracker.finish('abandoned')
            epoch.current += 1
            bootController.current?.abort()
            actionController.current?.abort()
            if (stopTimer.current) {
                clearTimeout(stopTimer.current)
            }
        },
        [turnTracker]
    )

    useEffect(() => {
        turnTracker.observe(live)
    }, [turnTracker, live])

    const pendingRequestId = live?.pending?.record.requestId
    const pendingKind = live?.pending?.kind
    const pendingReplayed = live?.pending?.replayed ?? false
    useEffect(() => {
        if (!pendingRequestId || !pendingKind || shownDecisions.current.has(pendingRequestId)) {
            return
        }
        shownDecisions.current.add(pendingRequestId)
        track('mobile_decision_shown', { kind: pendingKind, surface: 'chat', replayed: pendingReplayed })
    }, [pendingRequestId, pendingKind, pendingReplayed])

    useEffect(() => {
        if (!follow || !activeTaskId || !active || demo) {
            return
        }
        const controller = new AbortController()
        const { signal } = controller
        const { runId } = follow
        let entry = cursors.current.get(runId)
        if (!entry) {
            entry = { cursor: new RunStreamCursor(runId), followed: false, hydrate: !follow.fresh, pendingFrames: [] }
            cursors.current.set(runId, entry)
        }
        if (entry.followed && entry.cursor.cursor === undefined) {
            dispatchThread({ type: 'resuming' })
        }
        entry.followed = true
        setFollowEnded(false)
        const handlers: FollowHandlers = {
            onOpen: () => {
                setReconnecting(false)
            },
            onHistory: (frames) => {
                dispatchThread({ type: 'frames', frames })
                const current = liveRef.current
                if (current?.runId === runId) {
                    let state: RunStreamState = { ...current, liveActivitySeen: false }
                    for (const { frame, context } of frames) {
                        if (context.sourceRunId === runId) {
                            state = reduceFrame(state, frame, context).state
                        }
                    }
                    setLive(state)
                    if (isTerminalRunStatus(state.status)) {
                        dispatchThread({ type: 'settle' })
                    }
                }
                setHistory(IDLE)
            },
            onFrame: (data, context) => applyFrame(data, context, runId, signal),
            onResync: () => dispatchThread({ type: 'resuming' }),
            onReconnecting: setReconnecting,
            onSnapshot: applySnapshot,
            getState: () => liveRef.current ?? initialRunState(activeTaskId, runId),
        }
        void followSessionRun(activeTaskId, runId, entry, signal, handlers).then((outcome) => {
            if (outcome === 'aborted' || signal.aborted) {
                return
            }
            setReconnecting(false)
            setFollowEnded(true)
            if (outcome === 'gave_up') {
                setHistory((current) =>
                    current.status === 'loading'
                        ? { status: 'error', error: { kind: 'network', message: CONNECTION_LOST } }
                        : current
                )
                setNotice(CONNECTION_LOST)
            } else if (typeof outcome === 'object') {
                const error = toChatError(outcome.fatal)
                setHistory((current) => (current.status === 'loading' ? { status: 'error', error } : current))
                setNotice((current) => current ?? error.message)
            }
        })
        return () => controller.abort()
    }, [active, activeTaskId, applyFrame, applySnapshot, demo, follow, setLive])

    const liveStatus = live?.status
    const liveTurnEnded = live?.turnEnded
    useEffect(() => {
        if (isStopping && (liveTurnEnded || (liveStatus && isTerminalRunStatus(liveStatus)))) {
            endStopping()
        }
    }, [endStopping, isStopping, liveStatus, liveTurnEnded])

    const playDemoFrames = useCallback(
        async (frames: unknown[], signal: AbortSignal): Promise<void> => {
            const runId = liveRef.current?.runId
            if (!runId) {
                return
            }
            const context: FrameContext = { source: 'live', sourceRunId: runId }
            setDemoPlaying(true)
            await wait(300, signal)
            for (const frame of frames) {
                if (signal.aborted) {
                    break
                }
                applyFrame(frame, context, runId, signal)
                await wait(45, signal)
            }
            if (actionController.current?.signal === signal) {
                actionController.current = null
                setDemoPlaying(false)
            }
        },
        [applyFrame]
    )

    const configFor = useCallback((runId: string): TrackedRunConfig => {
        const tracked = runConfigs.current.get(runId)
        if (tracked) {
            return tracked
        }
        const detail = runDetail.current
        return detail?.id === runId ? runConfigFromRun(detail) : UNKNOWN_RUN_CONFIG
    }, [])

    const startRun = useCallback(
        async (
            content: string,
            previousRunId: string | undefined,
            options: ChatRunOptions,
            signal: AbortSignal,
            mine: number,
            artifactIds: readonly string[]
        ): Promise<PermissionModeApi> => {
            const id = taskIdRef.current
            if (!id) {
                throw new RunNotStartedError()
            }
            const fields = chatRunFields(options, previousRunId ? configFor(previousRunId) : null)
            const body: TaskRunCreateRequestApi = withPendingArtifacts(
                {
                    mode: 'interactive',
                    pending_user_message: content,
                    ...(previousRunId ? { resume_from_run_id: previousRunId } : runSource.current),
                    ...fields,
                },
                artifactIds
            )
            const response = await withWarmRetry(
                (headers) => {
                    if (!scopeIsCurrent()) {
                        throw abortError()
                    }
                    return startTaskRun(id, body, { headers, signal })
                },
                { signal }
            )
            const run = response.run ?? response.latest_run ?? null
            if (!run) {
                throw new RunNotStartedError()
            }
            if (epoch.current !== mine || !scopeIsCurrent()) {
                return fields.initial_permission_mode
            }
            runDetail.current = run
            runConfigs.current.set(run.id, runConfigAfterStart(run, fields))
            if (previousRunId) {
                // A thin-tail run's first replay is the whole resume chain, which then draws the thread again.
                dispatchThread({ type: 'resuming', resumeRun: true })
            }
            setPartial(null)
            setLive(applyRunSnapshot(initialRunState(id, run.id, run.status), run))
            setFollow({ runId: run.id, key: 0, fresh: !previousRunId })
            return fields.initial_permission_mode
        },
        [configFor, scopeIsCurrent, setLive, setPartial]
    )

    const syncConfig = useCallback(
        async (run: RunRef, options: ChatRunOptions, signal: AbortSignal, mine: number): Promise<PermissionModeApi> => {
            const live = liveRef.current
            const plan = configSyncPlan(
                options,
                configFor(run.runId),
                live?.runId === run.runId ? live.mode : undefined
            )
            if (plan.type === 'harness_mismatch') {
                throw new ConfigSyncError(harnessMismatchMessage(plan.runtimeAdapter))
            }
            for (const change of plan.changes) {
                await sendConfigOption(run, change, signal)
                if (epoch.current !== mine || !scopeIsCurrent()) {
                    break
                }
                // Recorded per change, so a later failure resends only what did not go out.
                runConfigs.current.set(run.runId, applyConfigChange(configFor(run.runId), change))
            }
            return plan.permissionMode
        },
        [configFor, scopeIsCurrent]
    )

    /**
     * The task's latest run, followed when it is live. A first run that failed with a 5xx or a lost connection may
     * still have started, and a fresh run beside it would make two agents answer.
     */
    const adoptLatestRun = useCallback(
        async (id: string, signal: AbortSignal, mine: number): Promise<RunStreamState | null> => {
            const task = await getTask(id, signal)
            const run = task.latest_run
            if (!run || epoch.current !== mine || !scopeIsCurrent()) {
                return null
            }
            runDetail.current = run
            const state = applyRunSnapshot(initialRunState(id, run.id, run.status), run)
            setLive(state)
            if (!isTerminalRunStatus(run.status)) {
                setFollow({ runId: run.id, key: 0 })
            }
            return state
        },
        [scopeIsCurrent, setLive]
    )

    const followUp = useCallback(
        async (
            text: string,
            context: ChatContext,
            options: ChatRunOptions,
            sendOptions: SendOptions
        ): Promise<boolean> => {
            const taskId = taskIdRef.current
            const trimmed = text.trim()
            if (!scopeIsCurrent() || !taskId || !trimmed || sendingRef.current) {
                return false
            }
            const steer = sendOptions.steer === true && canSteerRef.current
            const attachments = sendOptions.attachments ?? []
            const content = chatPrompt(trimmed, context)
            const reportCount = context.kind === 'reports' ? context.reports.length : 0
            const localId = `local-${randomUUID()}`
            const mine = epoch.current
            const controller = new AbortController()
            actionController.current?.abort()
            actionController.current = controller
            setNotice(undefined)
            setUnsentText(undefined)
            dispatchThread({
                type: 'local_user',
                id: localId,
                text: bareQuestion(trimmed),
                attachments: localAttachments(attachments),
            })
            if (demo) {
                const runId = liveRef.current?.runId
                if (runId) {
                    const echo = demoFrame({
                        sessionUpdate: 'user_message_chunk',
                        content: { type: 'text', text: content },
                    })
                    applyFrame(echo, { source: 'live', sourceRunId: runId }, runId, controller.signal)
                }
                track('mobile_session_sent', {
                    new_task: false,
                    resumed_run: false,
                    report_count: reportCount,
                    attachment_count: attachments.length,
                    ...sentOptionProperties(options, options.permissionMode),
                    ...deliveryProperties(steer, sendOptions),
                })
                if (steer) {
                    turnTracker.join(liveRef.current)
                } else {
                    turnTracker.begin(liveRef.current)
                }
                await playDemoFrames(demoReplyFrames(DEMO_REPLY), controller.signal)
                return true
            }
            sendingRef.current = true
            setSending(true)
            let resumed = false
            let steered = false
            try {
                const current = liveRef.current ?? (await adoptLatestRun(taskId, controller.signal, mine))
                if (epoch.current !== mine || !scopeIsCurrent()) {
                    return false
                }
                let delivered = false
                let permissionMode: PermissionModeApi = options.permissionMode
                if (current && !isTerminalRunStatus(current.status)) {
                    const run = { taskId, runId: current.runId }
                    let ended = false
                    try {
                        permissionMode = await syncConfig(run, options, controller.signal, mine)
                    } catch (error) {
                        if (!(error instanceof RunEndedError)) {
                            throw error
                        }
                        ended = true
                    }
                    if (!ended) {
                        // `ended` (a 409) falls through to a resume run, which has no live turn to steer.
                        // Run-scoped ids belong to this run only, so a resume below uploads the files again.
                        const artifactIds = await uploadSendFiles(
                            { kind: 'run', ...run },
                            attachments,
                            controller.signal,
                            false
                        )
                        if (!scopeIsCurrent() || controller.signal.aborted) {
                            return false
                        }
                        const outcome = await sendUserMessage(run, content, {
                            id: randomUUID(),
                            signal: controller.signal,
                            steer,
                            artifactIds,
                        })
                        delivered = outcome === 'queued'
                        steered = delivered && steer
                        if (delivered && epoch.current === mine) {
                            // The agent works on the message now; the stream confirms it when the turn starts.
                            updateLive(current.runId, (state) => ({ ...state, turnEnded: false }))
                        }
                    }
                }
                if (!delivered) {
                    resumed = current !== null
                    const stagedIds = await uploadSendFiles(
                        { kind: 'staged', taskId },
                        attachments,
                        controller.signal,
                        false
                    )
                    if (!scopeIsCurrent() || controller.signal.aborted) {
                        return false
                    }
                    permissionMode = await startRun(
                        content,
                        current?.runId,
                        options,
                        controller.signal,
                        mine,
                        stagedIds
                    )
                }
                if (epoch.current === mine) {
                    track('mobile_session_sent', {
                        new_task: false,
                        resumed_run: resumed,
                        report_count: reportCount,
                        attachment_count: attachments.length,
                        ...sentOptionProperties(options, permissionMode),
                        ...deliveryProperties(steered, sendOptions),
                    })
                    if (steered) {
                        turnTracker.join(liveRef.current)
                    } else {
                        turnTracker.begin(liveRef.current)
                    }
                }
            } catch (error) {
                if (epoch.current !== mine || !scopeIsCurrent() || controller.signal.aborted) {
                    return false
                }
                dispatchThread({ type: 'withdraw', id: localId })
                setNotice(sendErrorMessage(error))
                setUnsentText(trimmed)
                track('mobile_session_send_failed', { code: sendErrorCode(error), new_task: false })
                return false
            } finally {
                if (epoch.current === mine) {
                    sendingRef.current = false
                    setSending(false)
                }
            }
            return true
        },
        [
            adoptLatestRun,
            applyFrame,
            demo,
            playDemoFrames,
            scopeIsCurrent,
            startRun,
            syncConfig,
            turnTracker,
            updateLive,
        ]
    )

    const startNew = useCallback(
        async (
            text: string,
            context: ChatContext,
            options: ChatRunOptions,
            sendOptions: SendOptions
        ): Promise<boolean> => {
            const trimmed = text.trim()
            if (!scopeIsCurrent() || taskIdRef.current || !trimmed || sendingRef.current) {
                return false
            }
            const attachments = sendOptions.attachments ?? []
            const requests = chatStartRequests(trimmed, context, options)
            const sentProperties = {
                new_task: true,
                resumed_run: false,
                report_count: context.kind === 'reports' ? context.reports.length : 0,
                attachment_count: attachments.length,
                ...sentOptionProperties(options, requests.fields.initial_permission_mode),
                ...deliveryProperties(false, sendOptions),
            }
            const localId = `local-${randomUUID()}`
            const mine = epoch.current
            const controller = new AbortController()
            actionController.current?.abort()
            actionController.current = controller
            const { signal } = controller
            setNotice(undefined)
            setUnsentText(undefined)
            dispatchThread({
                type: 'local_user',
                id: localId,
                text: bareQuestion(trimmed),
                attachments: localAttachments(attachments),
            })
            if (demo) {
                const demoTaskId = `demo-new-${randomUUID()}`
                const runId = `demo-run-${randomUUID()}`
                taskIdRef.current = demoTaskId
                setCreatedTaskId(demoTaskId)
                setLive(initialRunState(demoTaskId, runId, 'in_progress'))
                const echo = demoFrame({
                    sessionUpdate: 'user_message_chunk',
                    content: { type: 'text', text: requests.run.pending_user_message },
                })
                applyFrame(echo, { source: 'live', sourceRunId: runId }, runId, signal)
                track('mobile_session_sent', sentProperties)
                turnTracker.begin(liveRef.current)
                await playDemoFrames(demoReplyFrames(DEMO_REPLY), signal)
                return true
            }
            sendingRef.current = true
            setSending(true)
            try {
                // No abort signal, so the app always learns the task id and whether its run started.
                const task = await withWarmRetry((headers) => {
                    if (!scopeIsCurrent()) {
                        throw abortError()
                    }
                    return createTask(requests.task, { headers })
                })
                if (epoch.current !== mine || !scopeIsCurrent()) {
                    // An empty task cannot start a run after its composer has gone.
                    if (!task.latest_run && scopeIsCurrent()) {
                        await deleteTask(task.id).catch(() => undefined)
                    }
                    return task.latest_run != null
                }
                taskIdRef.current = task.id
                runSource.current = requests.runSource
                setCreatedTaskId(task.id)
                setTitle(task.title || null)
                // The create sends no `branch`, so it never claims a warm run, and the files stage on the task for `run/`.
                if (task.latest_run && attachments.length > 0) {
                    // A run from the create would never get the files, so the send fails rather than drop them.
                    deleteTask(task.id).catch(() => undefined)
                    taskIdRef.current = null
                    runSource.current = {}
                    setCreatedTaskId(null)
                    setTitle(null)
                    throw new AttachmentUploadError('The create started a run before the files uploaded')
                }
                let run = task.latest_run ?? null
                if (!run) {
                    let runRequested = false
                    try {
                        const artifactIds = await uploadSendFiles(
                            { kind: 'staged', taskId: task.id },
                            attachments,
                            signal,
                            true
                        )
                        if (!scopeIsCurrent() || signal.aborted) {
                            throw abortError()
                        }
                        runRequested = true
                        const response = await withWarmRetry((headers) => {
                            if (!scopeIsCurrent()) {
                                throw abortError()
                            }
                            return startTaskRun(task.id, withPendingArtifacts(requests.run, artifactIds), { headers })
                        })
                        run = response.run ?? response.latest_run ?? null
                    } catch (error) {
                        if (scopeIsCurrent() && (!runRequested || isRunRefused(error))) {
                            // No run started, so the task would only sit empty in the Chats list.
                            deleteTask(task.id).catch(() => undefined)
                            if (epoch.current === mine) {
                                taskIdRef.current = null
                                runSource.current = {}
                                setCreatedTaskId(null)
                                setTitle(null)
                            }
                        }
                        throw error
                    }
                }
                if (!run) {
                    throw new RunNotStartedError()
                }
                if (epoch.current !== mine || !scopeIsCurrent()) {
                    return true
                }
                runDetail.current = run
                runConfigs.current.set(run.id, runConfigAfterStart(run, requests.fields))
                setLive(applyRunSnapshot(initialRunState(task.id, run.id, run.status), run))
                setFollow({ runId: run.id, key: 0, fresh: true })
                track('mobile_session_sent', sentProperties)
                turnTracker.begin(liveRef.current)
            } catch (error) {
                if (epoch.current !== mine || !scopeIsCurrent() || signal.aborted) {
                    return false
                }
                dispatchThread({ type: 'withdraw', id: localId })
                setNotice(sendErrorMessage(error))
                setUnsentText(trimmed)
                track('mobile_session_send_failed', { code: sendErrorCode(error), new_task: true })
                return false
            } finally {
                if (epoch.current === mine) {
                    sendingRef.current = false
                    setSending(false)
                }
            }
            return true
        },
        [applyFrame, demo, playDemoFrames, scopeIsCurrent, setLive, turnTracker]
    )

    const submit = useCallback(
        async (
            text: string,
            context: ChatContext,
            options: ChatRunOptions = DEFAULT_CHAT_RUN_OPTIONS,
            sendOptions: SendOptions = {}
        ): Promise<boolean> => {
            const mine = epoch.current
            if (!scopeIsCurrent() || !text.trim() || sendingRef.current || !(await approval.request())) {
                return false
            }
            if (!scopeIsCurrent() || epoch.current !== mine) {
                return false
            }
            return taskIdRef.current
                ? followUp(text, context, options, sendOptions)
                : startNew(text, context, options, sendOptions)
        },
        [followUp, startNew, approval.request, scopeIsCurrent]
    )

    const answer = useCallback(
        async (input: DecisionAnswerInput): Promise<void> => {
            const taskId = taskIdRef.current
            const current = liveRef.current
            if (!scopeIsCurrent() || !taskId || !current || sendingRef.current) {
                return
            }
            const pending = current.pending
            if (!pending) {
                void refreshRun(current.runId)
                return
            }
            const requestId = pending.record.requestId
            const answered = partialRef.current?.requestId === requestId ? partialRef.current.labels : []
            const question = decisionQuestionFor(pending, answered)
            if (question.id !== input.questionId) {
                // The card the user answered is gone; fetch the run so the sheet catches up.
                void refreshRun(current.runId)
                return
            }
            const plan = planAnswer(pending, answered, input)
            const picked = question.options.find((option) => option.id === input.optionId)?.title ?? input.text
            if (plan.type === 'next_question') {
                setPartial({ requestId, labels: [...answered, plan.label] })
                return
            }
            const echo = [...answered, picked].join('\n')
            const trackAnswer = (): void =>
                track('mobile_decision_answered', {
                    task_id: taskId,
                    kind: pending.kind,
                    picked_option: Boolean(input.optionId),
                    surface: 'chat',
                })
            const mine = epoch.current
            const controller = new AbortController()
            actionController.current?.abort()
            actionController.current = controller
            setNotice(undefined)
            if (demo) {
                updateLive(current.runId, (state) => markRequestHandled(state, requestId))
                setPartial(null)
                dispatchThread({ type: 'local_user', id: `answer-${requestId}`, text: echo, echo: false })
                trackAnswer()
                await playDemoFrames(demoReplyFrames(DEMO_ANSWER_REPLY), controller.signal)
                return
            }
            sendingRef.current = true
            setSending(true)
            try {
                if (!(await approval.request()) || epoch.current !== mine || !scopeIsCurrent()) {
                    return
                }
                const outcome = await deliverPermissionResponse({ taskId, runId: current.runId }, plan.params, {
                    signal: controller.signal,
                })
                if (epoch.current !== mine || !scopeIsCurrent()) {
                    return
                }
                updateLive(current.runId, (state) => markRequestHandled(state, requestId))
                setPartial(null)
                if (outcome === 'resolved') {
                    dispatchThread({ type: 'local_user', id: `answer-${requestId}`, text: echo, echo: false })
                    trackAnswer()
                } else if (outcome === 'gone') {
                    setNotice(ANSWERED_ELSEWHERE)
                } else {
                    setNotice(ANSWER_RUN_ENDED)
                    void refreshRun(current.runId)
                }
            } catch (error) {
                if (epoch.current !== mine || !scopeIsCurrent() || controller.signal.aborted) {
                    return
                }
                setNotice(answerErrorMessage(error))
            } finally {
                if (epoch.current === mine) {
                    sendingRef.current = false
                    setSending(false)
                }
            }
        },
        [demo, playDemoFrames, refreshRun, scopeIsCurrent, setPartial, updateLive, approval.request]
    )

    const stop = useCallback((): void => {
        if (demo) {
            if (actionController.current) {
                actionController.current.abort()
                actionController.current = null
                setDemoPlaying(false)
                dispatchThread({ type: 'settle' })
                track('mobile_session_stopped')
                turnTracker.finish('stopped')
            }
            return
        }
        const taskId = taskIdRef.current
        const current = liveRef.current
        if (!scopeIsCurrent() || !taskId || !current || stoppingRef.current) {
            return
        }
        if (
            !active ||
            reconnecting ||
            current.status !== 'in_progress' ||
            current.phase !== 'working' ||
            current.turnEnded ||
            !generating.current.has(current.runId)
        ) {
            setNotice(NOT_STARTED)
            return
        }
        stoppingRef.current = true
        setStopping(true)
        track('mobile_session_stopped')
        turnTracker.markStopped(true)
        stopTimer.current = setTimeout(endStopping, STOP_TIMEOUT_MS)
        const mine = epoch.current
        sendTaskRunCommand(taskId, current.runId, { method: 'cancel' }, { id: `cancel-${randomUUID()}` })
            .then((response) => {
                if (response.error) {
                    throw new CommandFailedError(response.error.message ?? 'The agent did not stop.')
                }
            })
            .catch(() => {
                if (epoch.current === mine) {
                    endStopping()
                    setNotice(STOP_FAILED)
                    turnTracker.markStopped(false)
                }
            })
    }, [active, demo, endStopping, reconnecting, scopeIsCurrent, turnTracker])

    const dismissNotice = useCallback((): void => setNotice(undefined), [])

    const reset = useCallback((): void => {
        reloadHistory().catch(() => undefined)
    }, [reloadHistory])

    const decision = useMemo((): SessionDecision | undefined => {
        const pending = live?.pending
        if (!pending) {
            return undefined
        }
        const labels = partial?.requestId === pending.record.requestId ? partial.labels : []
        return {
            question: decisionQuestionFor(pending, labels),
            kind: pending.kind,
            toolCallId: pending.record.toolCallId,
        }
    }, [live?.pending, partial])

    const terminal = live ? isTerminalRunStatus(live.status) : true
    const following = follow !== null && !followEnded
    let phase: SessionPhase = 'idle'
    if (reconnecting) {
        phase = 'reconnecting'
    } else if (demoPlaying || (active && live?.phase === 'working' && !terminal && !live.turnEnded && following)) {
        phase = 'working'
    }

    // `phase` is `working` only after a live frame showed the agent generating, which is the guard `stop` keeps in
    // `generating`. A replayed backlog leaves `phase` idle, because the agent may not have taken its first message yet.
    const canSteer = demo
        ? demoPlaying && !decision
        : phase === 'working' && live?.status === 'in_progress' && !decision && !isSending && !isStopping
    canSteerRef.current = canSteer

    const stage = live ? displayStage(live) : undefined
    const config = live ? configFor(live.runId) : undefined
    return {
        taskId: activeTaskId,
        runId: live?.runId ?? null,
        title,
        runStatus: live?.status ?? null,
        items: thread.items,
        invocations: thread.invocations,
        phase,
        ...(stage ? { stage } : {}),
        history,
        ...(decision ? { decision } : {}),
        ...(live?.prUrl ? { pullRequest: pullRequestFromUrl(live.prUrl) } : {}),
        pullRequests: [...new Set([...(live?.prUrls ?? []), ...(live?.prUrl ? [live.prUrl] : [])])].map(
            pullRequestFromUrl
        ),
        ...(live?.errorMessage ? { runError: live.errorMessage } : {}),
        isSending: isSending || approval.pending,
        isStopping,
        ...(notice ? { notice } : {}),
        ...(unsentText ? { unsentText } : {}),
        ...(config && live
            ? {
                  runConfig: {
                      runtimeAdapter: config.runtimeAdapter,
                      model: config.model,
                      reasoningEffort: config.reasoningEffort,
                      permissionMode: currentPermissionMode(config, live.mode),
                  },
              }
            : {}),
        start: submit,
        send: submit,
        canSteer,
        answer,
        stop,
        reloadHistory,
        reset,
        dismissNotice,
    }
}
