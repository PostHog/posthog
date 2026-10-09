import { useEffect, useState } from 'react'
import { AppState, type AppStateStatus } from 'react-native'

import { ApiError, NotSignedInError } from '@/api/client'
import { readSse } from '@/api/sse'
import { getTask, getTaskRun, openTaskRunStream, type TaskRunApi } from '@/api/tasks'
import { sleep } from '@/lib/sleep'

import { deliverPermissionResponse } from './commands'
import { useHandoffStore } from './handoffStore'
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
const IDLE_TIMEOUT_MS = 60_000
const BOOTSTRAP_ATTEMPTS = 4

// Kept across screen visits and app foregrounds so a return resumes after the last event instead of replaying the log.
const cursors = new Map<string, RunStreamCursor>()

function cursorFor(runId: string): RunStreamCursor {
    let cursor = cursors.get(runId)
    if (!cursor) {
        cursor = new RunStreamCursor(runId)
        cursors.set(runId, cursor)
    }
    return cursor
}

function useAppActive(): boolean {
    const [active, setActive] = useState(() => AppState.currentState !== 'background')
    useEffect(() => {
        const subscription = AppState.addEventListener('change', (next: AppStateStatus) => {
            setActive(next !== 'background')
        })
        return () => subscription.remove()
    }, [])
    return active
}

function isAbort(error: unknown, signal: AbortSignal): boolean {
    return signal.aborted || (error instanceof Error && error.name === 'AbortError')
}

function isFatal(error: unknown): boolean {
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
}

/** The run to follow: the task's latest run, which wins over a possibly stale run id. */
async function fetchRun(taskId: string, runId: string | undefined, signal: AbortSignal): Promise<TaskRunApi | null> {
    const task = await getTask(taskId, signal)
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
        try {
            const outcome = await deliverPermissionResponse(
                { taskId, runId },
                { requestId: effect.requestId, optionId: effect.optionId },
                { signal }
            )
            if (outcome === 'ended') {
                useHandoffStore.getState().requestRefresh(reportId)
            }
        } catch (error) {
            if (isAbort(error, signal)) {
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

async function readOnce(
    args: FollowArgs,
    runId: string,
    cursor: RunStreamCursor,
    outer: AbortSignal
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
        const response = await openTaskRunStream(args.taskId, runId, {
            lastEventId: cursor.cursor,
            signal: connection.signal,
        })
        await readSse(
            response,
            (event) => {
                resetIdle()
                const outcome = cursor.accept(event)
                if (outcome.frame) {
                    result.progressed = true
                    const effects = useHandoffStore
                        .getState()
                        .applyFrame(args.reportId, runId, outcome.frame.data, outcome.frame.context)
                    if (effects.length > 0) {
                        void runEffects(args.reportId, args.taskId, runId, effects, outer)
                    }
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

async function followRun(args: FollowArgs): Promise<void> {
    const { reportId, taskId, signal } = args
    const store = useHandoffStore.getState
    let run: TaskRunApi | null = null
    for (let attempt = 0; ; attempt += 1) {
        try {
            run = await fetchRun(taskId, args.runId, signal)
            break
        } catch (error) {
            // Until this succeeds the screen shows what the report itself knows about the run.
            if (isAbort(error, signal) || isFatal(error) || attempt >= BOOTSTRAP_ATTEMPTS - 1) {
                return
            }
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
    let state = store().applySnapshot(reportId, taskId, run)
    if (isTerminalRunStatus(state.status)) {
        return
    }
    const cursor = cursorFor(runId)
    let perDrop = 0
    let total = 0
    while (!signal.aborted) {
        let control: StreamControl | undefined
        let retryAfterMs: number | undefined
        try {
            const result = await readOnce(args, runId, cursor, signal)
            control = result.control
            if (result.progressed) {
                perDrop = 0
            }
        } catch (error) {
            if (isAbort(error, signal) || isFatal(error)) {
                return
            }
            if (error instanceof ApiError && error.status === 503 && error.retryAfterSeconds) {
                retryAfterMs = error.retryAfterSeconds * 1000
            }
        }
        if (signal.aborted) {
            return
        }
        if (control?.type === 'rotated' || control?.type === 'resync') {
            continue
        }
        try {
            const latest = await getTaskRun(taskId, runId, signal)
            state = store().applySnapshot(reportId, taskId, latest)
        } catch (error) {
            if (isAbort(error, signal) || isFatal(error)) {
                return
            }
        }
        if (control?.type === 'ended' || !shouldReconnect(state, { perDrop, total })) {
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

export function useTaskRun(reportId: string, target: RunTarget | undefined, enabled: boolean): void {
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
        void followRun({ reportId, taskId, runId, signal: controller.signal })
        return () => controller.abort()
    }, [enabled, active, reportId, taskId, runId, refresh])
}
