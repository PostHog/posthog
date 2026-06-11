// Shared 429 retry policy for outbound PostHog API requests. The API is the
// source of truth for rate limits (per-scope, with per-team overrides), so we
// don't pace requests pre-emptively — we react to its Retry-After signal.
export const MAX_RETRIES = 3
export const BASE_BACKOFF_MS = 2000
// Sustained-scope throttles can ask for waits of many minutes. Past this cap,
// sleeping inside a tool call is worse than surfacing the 429 to the caller.
export const MAX_RETRY_AFTER_MS = 30_000

export interface RetryDecision {
    retry: boolean
    delayMs: number
    reason?: 'exhausted' | 'retry_after_exceeds_cap'
}

export function decide429Retry(
    retryAfterHeader: string | null,
    attempt: number,
    maxRetries: number = MAX_RETRIES
): RetryDecision {
    if (attempt >= maxRetries) {
        return { retry: false, delayMs: 0, reason: 'exhausted' }
    }

    // Retry-After may also be an HTTP-date, which parseInt rejects — treat
    // that like a missing header and fall back to backoff.
    const retryAfterSeconds = retryAfterHeader ? Number.parseInt(retryAfterHeader, 10) : Number.NaN
    if (!Number.isNaN(retryAfterSeconds)) {
        const delayMs = retryAfterSeconds * 1000
        if (delayMs > MAX_RETRY_AFTER_MS) {
            return { retry: false, delayMs, reason: 'retry_after_exceeds_cap' }
        }
        return { retry: true, delayMs }
    }

    // Equal jitter so concurrent 429s don't retry in lockstep.
    const backoffMs = Math.min(BASE_BACKOFF_MS * 2 ** attempt, MAX_RETRY_AFTER_MS)
    return { retry: true, delayMs: backoffMs / 2 + Math.random() * (backoffMs / 2) }
}
