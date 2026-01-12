/**
 * Configuration constants for retry logic
 */
export const RETRY_CONFIG = {
    /** Maximum number of retry attempts for rate-limited requests */
    MAX_RETRIES: 3,
    /** Base delay in milliseconds for exponential backoff */
    BASE_BACKOFF_MS: 2000,
} as const

/**
 * Calculate the delay for a retry attempt with exponential backoff
 * @param attempt The current attempt number (0-indexed)
 * @param retryAfterHeader Optional Retry-After header value in seconds
 * @returns Delay in milliseconds
 */
export function calculateRetryDelay(attempt: number, retryAfterHeader?: string | null): number {
    if (retryAfterHeader != null) {
        const parsedSeconds = parseInt(retryAfterHeader, 10)
        if (!Number.isNaN(parsedSeconds) && parsedSeconds >= 0) {
            return parsedSeconds * 1000
        }
    }
    
    // Exponential backoff: baseDelay * 2^attempt
    return RETRY_CONFIG.BASE_BACKOFF_MS * Math.pow(2, attempt)
}
