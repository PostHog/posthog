import { retryWithBackoff } from 'lib/utils/async'
import { isUserInitiatedError } from 'lib/utils/kea-logic-builders'

export const FAST_FAILURE_MS = 3000

// Other 4xx responses, 429 included, would fail again on an immediate retry.
function isRetryableError(error: unknown): boolean {
    const status = (error as { status?: number } | null)?.status
    return status === undefined || status >= 500 || status === 408
}

export function retryOnFastFailure<T>(
    fn: () => Promise<T>,
    {
        signal,
        fastFailureMs = FAST_FAILURE_MS,
        retryDelayMs = 300,
    }: { signal?: AbortSignal; fastFailureMs?: number; retryDelayMs?: number } = {}
): Promise<T> {
    const startedAt = performance.now()
    return retryWithBackoff(fn, {
        maxAttempts: 2,
        initialDelayMs: retryDelayMs,
        signal,
        shouldRetry: (error) =>
            !signal?.aborted &&
            !isUserInitiatedError(error) &&
            performance.now() - startedAt < fastFailureMs &&
            isRetryableError(error),
    })
}
