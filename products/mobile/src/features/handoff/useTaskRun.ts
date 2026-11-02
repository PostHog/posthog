import { useEffect, useState } from 'react'
import { AppState, type AppStateStatus } from 'react-native'

import { ApiError, NotSignedInError } from '@/api/client'
import { readSse } from '@/api/sse'
import { getTask, getTaskRun, openTaskRunStream, type TaskApi, type TaskRunApi } from '@/api/tasks'
import { addSessionEndTask } from '@/auth/authStore'
import { sleep } from '@/lib/sleep'

import { deliverPermissionResponse } from './commands'
import { useHandoffStore } from './handoffStore'
import { HYDRATION_QUIET_MS, RunHydration } from './runHydration'
import {
    isTerminalRunStatus,
    type RunEffect,
    RunStreamCursor,
    reconnectDelayMs,
    type StreamControl,
    shouldReconnect,
} from './runStream'
import type { RunTarget } from './types'

/** The server sends a keepalive every 20 s, so a minute of silence means the connection is dead. */
export const IDLE_TIMEOUT_MS = 60_000
const BOOTSTRAP_ATTEMPTS = 4

// Kept across screen visits and app foregrounds so a return resumes after the last event instead of replaying the log.
const cursors = new Map<string, RunStreamCursor>()
addSessionEndTask(() => cursors.clear())

function cursorFor(runId: string): RunStreamCursor {
    let cursor = cursors.get(runId)
    if (!cursor) {
        cursor = new RunStreamCursor(runId)
        cursors.set(runId, cursor)
    }
    return cursor
}

export function useAppActive(): boolean {
    const [active, setActive] = useState(() => AppState.currentState === null || AppState.currentState === 'active')
    useEffect(() => {
        const subscription = AppState.addEventListener('change', (next: AppStateStatus) => {
            setActive(next === 'active')
        })
        return () => subscription.remove()
    }, [])
    return active
}

export function isAbort(error: unknown, signal: AbortSignal): boolean {
    return signal.aborted || (error instanceof Error && error.name === 'AbortError')
}

export function isFatal(error: unknown): boolean {
    return (
        error instanceof NotSignedInError ||
        (error instanceof ApiError && (error.status === 401 || error.status === 403 || error.status === 404))
    )
}

interface FollowArgs {
    reportId: string
    taskId: string
    runId?: string
    signal: AbortSignal
    onRefresh?: () => void
    onTaskSnapshot?: (task: TaskApi) => void
}

/** The run to follow: the task's latest run, which wins over a possibly stale run id. */
async function fetchRun(
    taskId: string,
    runId: string | undefined,
    signal: AbortSignal,
    onTaskSnapshot?: (task: TaskApi) => void
): Promise<TaskRunApi | null> {
    const task = await getTask(taskId, signal)
    if (signal.aborted) {
        return null
    }
    onTaskSnapshot?.(task)
    if (task.latest_run) {
        return task.latest_run
    }
    return runId ? getTaskRun(taskId, runId, signal) : null
}

async function runEffects(
    reportId: string,
    taskId: string,
    runId: string,
    effects: RunEffect[],
    signal: AbortSignal
): Promise<void> {
    for (const effect of effects) {
        if (signal.aborted) {
            return
        }
        try {
            const outcome = await deliverPermissionResponse(
                { taskId, runId },
                { requestId: effect.requestId, optionId: effect.optionId },
                { signal }
            )
            if (signal.aborted || useHandoffStore.getState().reports[reportId]?.live?.runId !== runId) {
                return
            }
            if (outcome === 'ended') {
                useHandoffStore.getState().requestRefresh(reportId)
            }
        } catch (error) {
            if (isAbort(error, signal) || useHandoffStore.getState().reports[reportId]?.live?.runId !== runId) {
                return
            }
            // Allowing on the user's behalf failed, so ask them instead of leaving the agent waiting.
            useHandoffStore.getState().surfaceRequest(reportId, effect.record)
        }
    }
}

interface ConnectionResult {
    control?: StreamControl
    /** At least one content frame arrived, so the next drop gets a fresh retry budget. */
    progressed: boolean
}

function publishHydration(args: FollowArgs, hydration: RunHydration): void {
    if (args.signal.aborted || hydration.settled) {
        return
    }
    const state = useHandoffStore.getState().publishHydration(args.reportId, hydration.state, hydration.answerAtStart)
    if (state) {
        hydration.state = state
        hydration.settled = true
        cursors.set(state.runId, hydration.cursor)
    }
}

async function readOnce(
    args: FollowArgs,
    runId: string,
    hydration: RunHydration,
    outer: AbortSignal
): Promise<ConnectionResult> {
    const connection = new AbortController()
    const abort = (): void => connection.abort()
    outer.addEventListener('abort', abort, { once: true })
    let quietTimer: ReturnType<typeof setTimeout> | undefined
    const cancelQuiet = (): void => {
        if (quietTimer) {
            clearTimeout(quietTimer)
            quietTimer = undefined
        }
    }
    const publish = (): void => {
        cancelQuiet()
        publishHydration(args, hydration)
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
        const response = await openTaskRunStream(args.taskId, runId, {
            lastEventId: hydration.cursor.cursor,
            signal: connection.signal,
        })
        if (outer.aborted) {
            return result
        }
        await readSse(
            response,
            (event) => {
                if (outer.aborted) {
                    return
                }
                const current = useHandoffStore.getState().reports[args.reportId]?.live
                if (current?.taskId !== args.taskId || current.runId !== runId) {
                    connection.abort()
                    return
                }
                resetIdle()
                const buffered = !hydration.settled
                const outcome = hydration.accept(event)
                if (buffered) {
                    if (event.event === 'keepalive' || outcome.control?.type === 'ended') {
                        publish()
                    } else if (event.event === 'message') {
                        cancelQuiet()
                        if (!event.id?.startsWith('log-')) {
                            // There is no server catchup marker; a quiet Redis tail coalesces the initial snapshot.
                            quietTimer = setTimeout(publish, HYDRATION_QUIET_MS)
                        }
                    }
                }
                if (outcome.frame) {
                    result.progressed = true
                }
                if (outcome.frame && !buffered) {
                    const effects = useHandoffStore
                        .getState()
                        .applyFrame(args.reportId, runId, outcome.frame.data, outcome.frame.context)
                    cursors.set(runId, hydration.cursor)
                    if (effects.length > 0) {
                        void runEffects(args.reportId, args.taskId, runId, effects, outer)
                    }
                }
                if (outcome.control) {
                    cancelQuiet()
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
        if (idleTimer) {
            clearTimeout(idleTimer)
        }
        outer.removeEventListener('abort', abort)
    }
}

export async function followRun(args: FollowArgs): Promise<void> {
    const { reportId, taskId, signal } = args
    const store = useHandoffStore.getState
    const previous = store().reports[reportId]?.live
    if (args.runId && (previous?.taskId !== taskId || previous.runId !== args.runId)) {
        cursors.delete(args.runId)
    }
    if (args.runId && !signal.aborted) {
        store().beginFollow(reportId, taskId, args.runId)
    }
    const setConnection = (
        connection: 'connecting' | 'connected' | 'reconnecting' | 'unavailable' | undefined
    ): void => {
        if (!signal.aborted && followedRunId) {
            store().setConnection(reportId, followedRunId, connection)
        }
    }
    let followedRunId = args.runId ?? store().reports[reportId]?.live?.runId
    setConnection('connecting')
    let run: TaskRunApi | null = null
    for (let attempt = 0; ; attempt += 1) {
        try {
            run = await fetchRun(taskId, args.runId, signal, args.onTaskSnapshot)
            break
        } catch (error) {
            // Until this succeeds the screen shows what the report itself knows about the run.
            if (isAbort(error, signal) || isFatal(error) || attempt >= BOOTSTRAP_ATTEMPTS - 1) {
                setConnection('unavailable')
                return
            }
            setConnection('reconnecting')
        }
        try {
            await sleep(reconnectDelayMs(attempt), signal)
        } catch {
            return
        }
    }
    if (!run || signal.aborted) {
        return
    }
    const runId = run.id
    followedRunId = runId
    let state = store().applySnapshot(reportId, taskId, run)
    if (runId !== args.runId) {
        args.onRefresh?.()
    }
    if (isTerminalRunStatus(state.status)) {
        setConnection(undefined)
        return
    }
    setConnection('connecting')
    if (previous?.taskId !== taskId || previous.runId !== runId) {
        cursors.delete(runId)
    }
    const hydration = new RunHydration(cursorFor(runId), state, store().reports[reportId]?.answer)
    const isCurrent = (): boolean => {
        const current = store().reports[reportId]?.live
        return current?.taskId === taskId && current.runId === runId
    }
    let perDrop = 0
    let total = 0
    while (!signal.aborted) {
        let control: StreamControl | undefined
        let retryAfterMs: number | undefined
        try {
            const current = store().reports[reportId]?.live
            if (!current || current.taskId !== taskId || current.runId !== runId) {
                return
            }
            hydration.resume(current, store().reports[reportId]?.answer)
            const result = await readOnce(args, runId, hydration, signal)
            control = result.control
            if (result.progressed) {
                perDrop = 0
            }
        } catch (error) {
            if (isAbort(error, signal) || isFatal(error)) {
                setConnection('unavailable')
                return
            }
            if (error instanceof ApiError && error.status === 503 && error.retryAfterSeconds) {
                retryAfterMs = error.retryAfterSeconds * 1000
            }
        }
        if (signal.aborted || !isCurrent()) {
            return
        }
        setConnection('reconnecting')
        if (control?.type === 'rotated' || control?.type === 'resync') {
            continue
        }
        try {
            const latest = await getTaskRun(taskId, runId, signal)
            if (signal.aborted || !isCurrent()) {
                return
            }
            state = store().applySnapshot(reportId, taskId, latest)
            hydration.applySnapshot(latest)
        } catch (error) {
            if (isAbort(error, signal) || isFatal(error)) {
                setConnection('unavailable')
                return
            }
        }
        if (control?.type === 'ended' || !shouldReconnect(state, { perDrop, total })) {
            if (isTerminalRunStatus(state.status)) {
                publishHydration(args, hydration)
            }
            if (control?.type === 'ended' && !isTerminalRunStatus(state.status)) {
                store().settleStreamEnd(reportId, runId)
            } else {
                setConnection(isTerminalRunStatus(state.status) ? undefined : 'unavailable')
            }
            args.onRefresh?.()
            return
        }
        try {
            await sleep(retryAfterMs ?? reconnectDelayMs(perDrop), signal)
        } catch {
            return
        }
        perDrop += 1
        total += 1
    }
}

export function useTaskRun(
    reportId: string,
    target: RunTarget | undefined,
    enabled: boolean,
    onRefresh?: () => void,
    onTaskSnapshot?: (task: TaskApi) => void
): void {
    const active = useAppActive()
    const refresh = useHandoffStore((state) => state.reports[reportId]?.refresh ?? 0)
    const taskId = target?.taskId
    const runId = target?.runId
    // biome-ignore lint/correctness/useExhaustiveDependencies: `refresh` restarts the follow after a command found the run ended or moved on.
    useEffect(() => {
        if (!enabled || !active || !taskId) {
            return
        }
        const controller = new AbortController()
        void followRun({ reportId, taskId, runId, signal: controller.signal, onRefresh, onTaskSnapshot })
        return () => controller.abort()
    }, [enabled, active, reportId, taskId, runId, refresh, onRefresh, onTaskSnapshot])
}
