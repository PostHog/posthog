/**
 * Shared retry utilities for handling rate limiting and exponential backoff
 */

/**
 * Sleep for a specified number of milliseconds
 */
export const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

/**
 * Retry configuration constants
 */
export const RETRY_CONFIG = {
    MAX_RETRIES: 3,
    BASE_BACKOFF_MS: 2000,
} as const

/**
 * Parse Retry-After header value
 * Handles both delay-seconds (number) and HTTP-date formats
 * Returns delay in milliseconds, or null if invalid
 */
export function parseRetryAfter(retryAfterHeader: string | null): number | null {
    if (!retryAfterHeader) {
        return null
    }

    // Try parsing as delay-seconds (numeric format)
    // Only accept pure integer strings (no decimals, no trailing text)
    // This rejects: '10.5', '5 seconds', '2023-13-45', etc.
    if (/^\d+$/.test(retryAfterHeader)) {
        const delaySeconds = parseInt(retryAfterHeader, 10)
        // Reject zero and negative values (though regex already excludes negatives)
        if (delaySeconds > 0) {
            return delaySeconds * 1000
        }
        // If it's a pure digit string but invalid (e.g., '0'), return null
        // Don't fall through to date parsing, as '0' is a valid date string
        return null
    }

    // Try parsing as HTTP-date format
    // HTTP-dates should contain spaces and typically commas (e.g., "Wed, 21 Oct 2015 07:28:00 GMT")
    // This prevents accepting arbitrary strings that Date() can parse (e.g., '-5', '0', '2000')
    if (retryAfterHeader.includes(' ')) {
        try {
            const retryDate = new Date(retryAfterHeader)
            const timestamp = retryDate.getTime()
            
            // Validate that the date is actually valid
            // Invalid dates like '2023-13-45' produce a valid timestamp but are semantically invalid
            // Check if the date string can round-trip correctly
            if (!isNaN(timestamp) && retryDate.toUTCString() !== 'Invalid Date') {
                const delayMs = timestamp - Date.now()
                return delayMs > 0 ? delayMs : 0
            }
        } catch {
            // Invalid date format, fall through
        }
    }

    return null
}

/**
 * Calculate exponential backoff delay for a given attempt
 */
export function calculateBackoffDelay(attempt: number, retryAfterHeader: string | null = null): number {
    const retryAfterDelay = parseRetryAfter(retryAfterHeader)
    if (retryAfterDelay !== null) {
        return retryAfterDelay
    }

    return RETRY_CONFIG.BASE_BACKOFF_MS * Math.pow(2, attempt)
}

/**
 * Safely parse JSON from response, with fallback for non-JSON responses
 */
export async function safeJsonParse(response: Response): Promise<{ json: any; text: string }> {
    const text = await response.text()
    
    try {
        const json = JSON.parse(text)
        return { json, text }
    } catch {
        // Not valid JSON, return text as-is
        return { json: null, text }
    }
}

/**
 * Format rate limit exceeded error message
 */
export function formatRateLimitError(maxRetries: number, status: number, errorText: string): string {
    return `Rate limit exceeded after ${maxRetries} retries:\n  Status: ${status}\n  Response: ${errorText}`
}
