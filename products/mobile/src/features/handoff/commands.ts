import { ApiError } from '@/api/client'
import {
    type PermissionResponseParams,
    sendTaskRunCommand,
    type TaskRunCommandResponseApi,
    type UserMessageParams,
} from '@/api/tasks'

import { type Clock, realClock } from './clock'

const STARTUP_WAIT_MS = 10_000
const RETRY_DELAYS_MS = [250, 500, 1000]
const NOT_READY_CODES: ReadonlySet<string> = new Set(['sandbox_not_ready', 'agent_session_not_ready'])
const ENDED_CODES: ReadonlySet<string> = new Set(['permission_target_ended', 'run_ended'])

export interface RunRef {
    taskId: string
    runId: string
}

/** `gone`: someone else answered the request or the agent restarted. `ended`: the run is over. */
export type DeliveryOutcome = 'resolved' | 'gone' | 'ended'

export class CommandFailedError extends Error {
    constructor(message: string) {
        super(message)
        this.name = 'CommandFailedError'
    }
}

function isRunEnded(error: unknown): boolean {
    return error instanceof ApiError && error.status === 409 && ENDED_CODES.has(error.code ?? '')
}

function isNotReady(error: unknown): boolean {
    return error instanceof ApiError && error.status === 503 && NOT_READY_CODES.has(error.code ?? '')
}

async function retryWhileStarting<T>(
    send: () => Promise<T>,
    signal: AbortSignal | undefined,
    clock: Clock
): Promise<T> {
    const deadline = clock.now() + STARTUP_WAIT_MS
    for (let attempt = 0; ; attempt += 1) {
        try {
            return await send()
        } catch (error) {
            const remaining = deadline - clock.now()
            if (!isNotReady(error) || signal?.aborted || remaining <= 0) {
                throw error
            }
            const delay = RETRY_DELAYS_MS[Math.min(attempt, RETRY_DELAYS_MS.length - 1)] as number
            await clock.sleep(Math.min(delay, remaining), signal)
        }
    }
}

function isResolved(response: TaskRunCommandResponseApi): boolean {
    const result = response.result
    return (
        response.jsonrpc === '2.0' &&
        !response.error &&
        typeof result === 'object' &&
        result !== null &&
        (result as { resolved?: unknown }).resolved === true
    )
}

/** HTTP 200 can carry a JSON-RPC error, so success is only `result.resolved === true`. */
export async function deliverPermissionResponse(
    run: RunRef,
    params: PermissionResponseParams,
    options: { signal?: AbortSignal; clock?: Clock } = {}
): Promise<DeliveryOutcome> {
    const clock = options.clock ?? realClock
    let response: TaskRunCommandResponseApi
    try {
        response = await retryWhileStarting(
            () =>
                sendTaskRunCommand(
                    run.taskId,
                    run.runId,
                    { method: 'permission_response', params },
                    { id: `perm-${params.requestId}`, signal: options.signal }
                ),
            options.signal,
            clock
        )
    } catch (error) {
        if (isRunEnded(error)) {
            return 'ended'
        }
        throw error
    }
    if (isResolved(response)) {
        return 'resolved'
    }
    if (response.error?.message?.includes('No pending permission request')) {
        return 'gone'
    }
    throw new CommandFailedError(response.error?.message ?? 'The agent did not confirm this answer.')
}

/** A 409 means the run's workflow is over; continuing would need a new resume run. */
export async function sendUserMessage(
    run: RunRef,
    content: string,
    options: { id: string; signal?: AbortSignal; clock?: Clock; steer?: boolean; artifactIds?: readonly string[] }
): Promise<'queued' | 'ended'> {
    const clock = options.clock ?? realClock
    const artifactIds = options.artifactIds ?? []
    const params: UserMessageParams = {
        content,
        ...(artifactIds.length > 0 ? { artifact_ids: [...artifactIds] } : {}),
        ...(options.steer ? { steer: true } : {}),
    }
    try {
        const response = await retryWhileStarting(
            () =>
                sendTaskRunCommand(
                    run.taskId,
                    run.runId,
                    { method: 'user_message', params },
                    { id: options.id, signal: options.signal }
                ),
            options.signal,
            clock
        )
        if (response.error) {
            throw new CommandFailedError(response.error.message ?? 'The agent did not take the message.')
        }
        return 'queued'
    } catch (error) {
        if (error instanceof ApiError && error.status === 409) {
            return 'ended'
        }
        throw error
    }
}
