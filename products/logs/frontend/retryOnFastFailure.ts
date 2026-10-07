import { retryWithBackoff } from 'lib/utils/async'
import { isUserInitiatedError } from 'lib/utils/kea-logic-builders'

/** A query that fails faster than this most likely hit a transient blip (a dropped connection, a
 *  gateway restart) rather than a slow or broken query, so it is worth one more attempt. */
export const FAST_FAILURE_MS = 3000

// A 4xx says the request itself is wrong, and a 429 asks us to back off, so the same request
// sent again straight away would fail the same way. 408 is the one client status worth repeating.
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
