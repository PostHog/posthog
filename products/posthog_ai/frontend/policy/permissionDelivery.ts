import type { TaskRunCommandResponseApi } from 'products/tasks/frontend/generated/api.schemas'

const STARTUP_WAIT_MS = 10_000
const REQUEST_TIMEOUT_MS = 5_000

function abortable<T>(promise: Promise<T>, signal: AbortSignal): Promise<T> {
    return new Promise((resolve, reject) => {
        const abort = (): void => reject(signal.reason ?? new Error('Approval delivery canceled'))
        signal.addEventListener('abort', abort, { once: true })
        if (signal.aborted) {
            abort()
        }
        promise.then(resolve, reject).finally(() => signal.removeEventListener('abort', abort))
    })
}

async function waitForReadiness(ms: number, signal: AbortSignal): Promise<void> {
    let timer: ReturnType<typeof setTimeout> | undefined
    try {
        await abortable(new Promise<void>((resolve) => (timer = setTimeout(resolve, ms))), signal)
    } finally {
        clearTimeout(timer)
    }
}

export function isPermissionTargetEnded(error: unknown): boolean {
    const rejection = error as { status?: number; code?: string }
    return rejection?.status === 409 && rejection.code === 'permission_target_ended'
}

export async function deliverPermissionResponse(
    send: (signal: AbortSignal) => Promise<TaskRunCommandResponseApi>,
    signal: AbortSignal
): Promise<void> {
    const deadline = performance.now() + STARTUP_WAIT_MS
    let attempt = 0
    while (!signal.aborted) {
        const remaining = deadline - performance.now()
        if (remaining <= 0) {
            throw new Error('The agent is still starting. Please try again.')
        }
        const request = new AbortController()
        const abort = (): void => request.abort(signal.reason)
        signal.addEventListener('abort', abort, { once: true })
        const timer = setTimeout(
            () => request.abort(new Error('Approval delivery timed out')),
            Math.min(REQUEST_TIMEOUT_MS, remaining)
        )
        try {
            const response = await abortable(send(request.signal), request.signal)
            const result = response.result
            if (
                response.jsonrpc !== '2.0' ||
                'error' in response ||
                typeof result !== 'object' ||
                result === null ||
                !('resolved' in result) ||
                result.resolved !== true
            ) {
                throw new Error('The agent did not confirm this approval.')
            }
            return
        } catch (error) {
            const rejection = error as { status?: number; code?: string }
            if (signal.aborted || rejection?.status !== 503 || rejection.code !== 'agent_session_not_ready') {
                throw error
            }
        } finally {
            clearTimeout(timer)
            signal.removeEventListener('abort', abort)
        }
        await waitForReadiness(
            Math.min(250 * 2 ** Math.min(attempt++, 2), Math.max(0, deadline - performance.now())),
            signal
        )
    }
    throw signal.reason ?? new Error('Approval delivery canceled')
}
