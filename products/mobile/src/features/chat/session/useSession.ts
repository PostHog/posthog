import { randomUUID } from 'expo-crypto'
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'

import { ApiError } from '@/api/client'
import { readSse } from '@/api/sse'
import {
    getTask,
    getTaskRun,
    getTaskRunLogs,
    openTaskRunStream,
    sendTaskRunCommand,
    startTaskRun,
    type TaskRunApi,
    type TaskRunCreateRequestApi,
} from '@/api/tasks'
import { useDemoMode } from '@/demo/demoMode'
import { DEMO_ANSWER_REPLY, demoSessionLog, demoSessionRunId } from '@/demo/sessionThreads'
import {
    CommandFailedError,
    deliverPermissionResponse,
    type RunRef,
    sendUserMessage,
} from '@/features/handoff/commands'
import { answerErrorMessage } from '@/features/handoff/hooks'
import { HANDOFF_RUNTIME, RunNotStartedError, withWarmRetry } from '@/features/handoff/kickoff'
import { pullRequestFromUrl } from '@/features/handoff/liveReport'
import { decisionQuestionFor, planAnswer, requestKind } from '@/features/handoff/permissionRequest'
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
import { track } from '@/lib/analytics'
import { asRecord } from '@/lib/records'
import { sleep } from '@/lib/sleep'
import type { DecisionAnswerInput } from '@/model/types'

import { toChatError } from '../chatErrors'
import { chatPrompt } from '../contextPrompt'
import { DEMO_REPLY } from '../hooks'
import type { ChatContext } from '../types'
import { historyFrames, initialSessionThread, sessionThreadReducer } from './sessionReducer'
import type { Session, SessionDecision, SessionHistory, SessionPhase } from './types'

// Drives a sandbox task run in the chat sheet through the tasks API. Stream handling follows `docs/HANDOFF.md`.

export interface SessionOptions {
    taskId?: string
    /** Follows this run instead of the task's latest one. */
    runId?: string
}

const STOP_TIMEOUT_MS = 10_000

const NOT_STARTED = "The agent hasn't started yet."
const STOP_FAILED = "Couldn't stop this run. Try again."
const ANSWERED_ELSEWHERE = 'Someone else answered this already.'
const ANSWER_RUN_ENDED = "Your answer wasn't sent. The run ended."
const CONNECTION_LOST = 'The connection to the agent dropped. Close this chat and open it again.'

const LOADING: SessionHistory = { status: 'loading', error: null }
const IDLE: SessionHistory = { status: 'idle', error: null }

interface PartialAnswer {
    requestId: string
    labels: string[]
}

interface Follow {
    runId: string
    key: number
}

interface CursorEntry {
    cursor: RunStreamCursor
    /** A later connection with no cursor replays the log again, so the thread rebuilds from it. */
    followed: boolean
}

function wait(ms: number, signal: AbortSignal): Promise<void> {
    return sleep(ms, signal).catch(() => undefined)
}

function isResumeRun(run: TaskRunApi): boolean {
    const resumeFrom = run.state?.resume_from_run_id
    return typeof resumeFrom === 'string' && resumeFrom !== ''
}

function isSessionUpdate(frame: unknown): boolean {
    const record = asRecord(frame)
    return record?.type === 'notification' && asRecord(record.notification)?.method === 'session/update'
}

function sendErrorMessage(error: unknown): string {
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

/** A follow-up keeps the ended run's model, so the conversation does not switch agents halfway. */
function successorRuntime(
    previous: TaskRunApi | null
): Pick<TaskRunCreateRequestApi, 'runtime_adapter' | 'model' | 'reasoning_effort'> {
    if (!previous?.model) {
        return { ...HANDOFF_RUNTIME }
    }
    return {
        model: previous.model,
        ...(previous.runtime_adapter ? { runtime_adapter: previous.runtime_adapter } : {}),
        ...(previous.reasoning_effort ? { reasoning_effort: previous.reasoning_effort } : {}),
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
    cursor: RunStreamCursor,
    outer: AbortSignal,
    handlers: FollowHandlers
): Promise<ConnectionResult> {
    const connection = new AbortController()
    const abort = (): void => connection.abort()
    outer.addEventListener('abort', abort, { once: true })
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
        handlers.onOpen()
        await readSse(
            response,
            (event) => {
                resetIdle()
                const outcome = cursor.accept(event)
                if (outcome.frame) {
                    result.progressed = true
                    handlers.onFrame(outcome.frame.data, outcome.frame.context)
                }
                if (outcome.control) {
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
    cursor: RunStreamCursor,
    signal: AbortSignal,
    handlers: FollowHandlers
): Promise<FollowOutcome> {
    let perDrop = 0
    let total = 0
    while (!signal.aborted) {
        let control: StreamControl | undefined
        let retryAfterMs: number | undefined
        try {
            const result = await readConnection(taskId, runId, cursor, signal, handlers)
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
            state = handlers.onSnapshot(await getTaskRun(taskId, runId, signal))
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

export function useSession(options: SessionOptions): Session | null {
    const { taskId, runId: requestedRunId } = options
    const demo = useDemoMode((state) => state.enabled)
    const active = useAppActive()
    const [thread, dispatchThread] = useReducer(sessionThreadReducer, false, initialSessionThread)
    const [live, setLiveState] = useState<RunStreamState | null>(null)
    const [title, setTitle] = useState<string | null>(null)
    const [history, setHistory] = useState<SessionHistory>(LOADING)
    const [notice, setNotice] = useState<string | undefined>(undefined)
    const [isSending, setSending] = useState(false)
    const [isStopping, setStopping] = useState(false)
    const [reconnecting, setReconnecting] = useState(false)
    const [partial, setPartialState] = useState<PartialAnswer | null>(null)
    const [follow, setFollow] = useState<Follow | null>(null)
    const [followEnded, setFollowEnded] = useState(false)
    const [demoPlaying, setDemoPlaying] = useState(false)

    const taskIdRef = useRef(taskId)
    taskIdRef.current = taskId
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
    const sendingRef = useRef(false)
    const stoppingRef = useRef(false)
    const stopTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

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
                if (epoch.current === mine) {
                    applySnapshot(run)
                }
            } catch {
                // The stream still reports the run's state; this fetch only makes it arrive sooner.
            }
        },
        [applySnapshot]
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
        [refreshRun, surfaceRequest]
    )

    const applyFrame = useCallback(
        (data: unknown, context: FrameContext, runId: string, signal: AbortSignal): void => {
            dispatchThread({ type: 'frame', frame: data, context })
            const current = liveRef.current
            if (!current || current.runId !== runId) {
                return
            }
            if (context.source === 'replay' && context.sourceRunId !== runId) {
                // An earlier run in the resume chain: its turn ends and requests say nothing about this run.
                return
            }
            if (isSessionUpdate(data)) {
                generating.current.add(runId)
            }
            const result = reduceFrame(current, data, context)
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
        [runEffects, setLive]
    )

    const resetState = useCallback((): void => {
        actionController.current?.abort()
        actionController.current = null
        bootController.current?.abort()
        bootController.current = null
        cursors.current.clear()
        generating.current.clear()
        runDetail.current = null
        sendingRef.current = false
        endStopping()
        setFollow(null)
        setFollowEnded(false)
        setReconnecting(false)
        setDemoPlaying(false)
        setSending(false)
        setNotice(undefined)
        setPartial(null)
        setLive(null)
        dispatchThread({ type: 'reset' })
    }, [endStopping, setLive, setPartial])

    const reloadHistory = useCallback(async (): Promise<void> => {
        epoch.current += 1
        const mine = epoch.current
        resetState()
        if (!taskId) {
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
            if (epoch.current !== mine) {
                return
            }
            setTitle(task.title || null)
            const run =
                requestedRunId && requestedRunId !== task.latest_run?.id
                    ? await getTaskRun(taskId, requestedRunId, signal)
                    : task.latest_run
            if (epoch.current !== mine) {
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
                if (epoch.current !== mine) {
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
            if (epoch.current !== mine || isAbort(error, signal)) {
                return
            }
            setHistory({ status: 'error', error: toChatError(error) })
        } finally {
            if (bootController.current === controller) {
                bootController.current = null
            }
        }
    }, [demo, requestedRunId, resetState, setLive, taskId])

    useEffect(() => {
        reloadHistory().catch(() => undefined)
    }, [reloadHistory])

    useEffect(
        () => () => {
            epoch.current += 1
            bootController.current?.abort()
            actionController.current?.abort()
            if (stopTimer.current) {
                clearTimeout(stopTimer.current)
            }
        },
        []
    )

    useEffect(() => {
        if (!follow || !taskId || !active || demo) {
            return
        }
        const controller = new AbortController()
        const { signal } = controller
        const { runId } = follow
        let entry = cursors.current.get(runId)
        if (!entry) {
            entry = { cursor: new RunStreamCursor(runId), followed: false }
            cursors.current.set(runId, entry)
        }
        if (entry.followed && entry.cursor.cursor === undefined) {
            dispatchThread({ type: 'resuming' })
        }
        entry.followed = true
        setFollowEnded(false)
        const handlers: FollowHandlers = {
            onOpen: () => {
                setHistory((current) => (current.status === 'idle' ? current : IDLE))
                setReconnecting(false)
            },
            onFrame: (data, context) => applyFrame(data, context, runId, signal),
            onResync: () => dispatchThread({ type: 'resuming' }),
            onReconnecting: setReconnecting,
            onSnapshot: applySnapshot,
            getState: () => liveRef.current ?? initialRunState(taskId, runId),
        }
        void followSessionRun(taskId, runId, entry.cursor, signal, handlers).then((outcome) => {
            if (outcome === 'aborted' || signal.aborted) {
                return
            }
            setReconnecting(false)
            setFollowEnded(true)
            if (outcome === 'gave_up') {
                setNotice(CONNECTION_LOST)
            } else if (typeof outcome === 'object') {
                const error = toChatError(outcome.fatal)
                setHistory((current) => (current.status === 'loading' ? { status: 'error', error } : current))
                setNotice((current) => current ?? error.message)
            }
        })
        return () => controller.abort()
    }, [active, applyFrame, applySnapshot, demo, follow, taskId])

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

    const startRun = useCallback(
        async (
            content: string,
            previousRunId: string | undefined,
            signal: AbortSignal,
            mine: number
        ): Promise<void> => {
            const id = taskIdRef.current
            if (!id) {
                return
            }
            const body: TaskRunCreateRequestApi = {
                mode: 'interactive',
                pending_user_message: content,
                ...(previousRunId ? { resume_from_run_id: previousRunId } : {}),
                ...successorRuntime(runDetail.current),
            }
            const response = await withWarmRetry((headers) => startTaskRun(id, body, { headers, signal }), { signal })
            const run = response.run ?? response.latest_run ?? null
            if (!run) {
                throw new RunNotStartedError()
            }
            if (epoch.current !== mine) {
                return
            }
            runDetail.current = run
            if (previousRunId) {
                // A thin-tail run's first replay is the whole resume chain, which then draws the thread again.
                dispatchThread({ type: 'resuming', resumeRun: true })
            }
            setPartial(null)
            setLive(applyRunSnapshot(initialRunState(id, run.id, run.status), run))
            setFollow({ runId: run.id, key: 0 })
        },
        [setLive, setPartial]
    )

    const send = useCallback(
        async (text: string, context: ChatContext): Promise<void> => {
            const trimmed = text.trim()
            if (!taskId || !trimmed || sendingRef.current) {
                return
            }
            const content = chatPrompt(trimmed, context)
            const reportCount = context.kind === 'reports' ? context.reports.length : 0
            const localId = `local-${randomUUID()}`
            const mine = epoch.current
            const controller = new AbortController()
            actionController.current?.abort()
            actionController.current = controller
            setNotice(undefined)
            dispatchThread({ type: 'local_user', id: localId, text: trimmed })
            if (demo) {
                const runId = liveRef.current?.runId
                if (runId) {
                    const echo = demoFrame({
                        sessionUpdate: 'user_message_chunk',
                        content: { type: 'text', text: content },
                    })
                    applyFrame(echo, { source: 'live', sourceRunId: runId }, runId, controller.signal)
                }
                track('mobile_session_sent', { resumed_run: false, report_count: reportCount })
                await playDemoFrames(demoReplyFrames(DEMO_REPLY), controller.signal)
                return
            }
            sendingRef.current = true
            setSending(true)
            let resumed = false
            try {
                const current = liveRef.current
                let delivered = false
                if (current && !isTerminalRunStatus(current.status)) {
                    const outcome = await sendUserMessage({ taskId, runId: current.runId }, content, {
                        id: randomUUID(),
                        signal: controller.signal,
                    })
                    delivered = outcome === 'queued'
                    if (delivered && epoch.current === mine) {
                        // The agent works on the message now; the stream confirms it when the turn starts.
                        updateLive(current.runId, (state) => ({ ...state, turnEnded: false }))
                    }
                }
                if (!delivered) {
                    resumed = current !== null
                    await startRun(content, current?.runId, controller.signal, mine)
                }
                if (epoch.current === mine) {
                    track('mobile_session_sent', { resumed_run: resumed, report_count: reportCount })
                }
            } catch (error) {
                if (epoch.current !== mine || controller.signal.aborted) {
                    return
                }
                dispatchThread({ type: 'withdraw', id: localId })
                setNotice(sendErrorMessage(error))
            } finally {
                if (epoch.current === mine) {
                    sendingRef.current = false
                    setSending(false)
                }
            }
        },
        [applyFrame, demo, playDemoFrames, startRun, taskId, updateLive]
    )

    const answer = useCallback(
        async (input: DecisionAnswerInput): Promise<void> => {
            const current = liveRef.current
            if (!taskId || !current || sendingRef.current) {
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
                const outcome = await deliverPermissionResponse({ taskId, runId: current.runId }, plan.params, {
                    signal: controller.signal,
                })
                if (epoch.current !== mine) {
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
                if (epoch.current !== mine || controller.signal.aborted) {
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
        [demo, playDemoFrames, refreshRun, setPartial, taskId, updateLive]
    )

    const stop = useCallback((): void => {
        if (demo) {
            if (actionController.current) {
                actionController.current.abort()
                actionController.current = null
                setDemoPlaying(false)
                dispatchThread({ type: 'settle' })
                track('mobile_session_stopped')
            }
            return
        }
        const current = liveRef.current
        if (!taskId || !current || stoppingRef.current) {
            return
        }
        if (current.status !== 'in_progress' || !generating.current.has(current.runId)) {
            setNotice(NOT_STARTED)
            return
        }
        stoppingRef.current = true
        setStopping(true)
        track('mobile_session_stopped')
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
                }
            })
    }, [demo, endStopping, taskId])

    const dismissNotice = useCallback((): void => setNotice(undefined), [])

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
    } else if (demoPlaying || (live && !terminal && !live.turnEnded && following)) {
        phase = 'working'
    }

    if (!taskId) {
        return null
    }
    const stage = live ? displayStage(live) : undefined
    return {
        taskId,
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
        ...(live?.errorMessage ? { runError: live.errorMessage } : {}),
        isSending,
        isStopping,
        ...(notice ? { notice } : {}),
        send,
        answer,
        stop,
        reloadHistory,
        dismissNotice,
    }
}
