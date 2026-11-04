import { sessionGeneration } from '@/auth/tokens'
import { abortError } from '@/lib/abort'

import { BudgetExceededError, budgetRetryAfterMs } from './budget'

export type ReplayRequestState = 'queued' | 'loading'

function waitForReplayBudget(signal: AbortSignal): Promise<void> {
    return new Promise((resolve, reject) => {
        const finish = (): void => {
            signal.removeEventListener('abort', onAbort)
            resolve()
        }
        const onAbort = (): void => {
            clearTimeout(timer)
            signal.removeEventListener('abort', onAbort)
            reject(abortError())
        }
        const timer = setTimeout(finish, Math.max(1, budgetRetryAfterMs('replay')))
        signal.addEventListener('abort', onAbort, { once: true })
        if (signal.aborted) onAbort()
    })
}

export async function withReplayBudget<T>(
    work: () => Promise<T>,
    signal: AbortSignal,
    onRequestState?: (state: ReplayRequestState) => void
): Promise<T> {
    const generation = sessionGeneration()
    while (true) {
        if (signal.aborted || generation !== sessionGeneration()) throw abortError()
        onRequestState?.('loading')
        try {
            return await work()
        } catch (error) {
            if (!(error instanceof BudgetExceededError) || error.family !== 'replay') throw error
            onRequestState?.('queued')
            await waitForReplayBudget(signal)
        }
    }
}
