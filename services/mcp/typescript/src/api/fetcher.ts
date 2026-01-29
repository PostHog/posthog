import type { ApiConfig } from './client'
import type { createApiClient } from './generated'
import { globalRateLimiter } from './rate-limiter'
import {
    calculateBackoffDelay,
    formatRateLimitError,
    RETRY_CONFIG,
    safeJsonParse,
    sleep,
} from './retry-utils'

export const buildApiFetcher: (config: ApiConfig) => Parameters<typeof createApiClient>[0] = (config) => {
    return {
        fetch: async (input) => {
            const maxRetries = RETRY_CONFIG.MAX_RETRIES

            for (let attempt = 0; attempt <= maxRetries; attempt++) {
                // Apply rate limiting before making the request
                await globalRateLimiter.throttle()

                const headers = new Headers()
                headers.set('Authorization', `Bearer ${config.apiToken}`)

                // Handle query parameters (only set once, outside retry loop would be better but this maintains compatibility)
                if (input.urlSearchParams) {
                    input.url.search = input.urlSearchParams.toString()
                }

                // Handle request body for mutation methods
                const body = ['post', 'put', 'patch', 'delete'].includes(input.method.toLowerCase())
                    ? JSON.stringify(input.parameters?.body)
                    : undefined

                if (body) {
                    headers.set('Content-Type', 'application/json')
                }

                // Add custom headers
                if (input.parameters?.header) {
                    for (const [key, value] of Object.entries(input.parameters.header)) {
                        if (value != null) {
                            headers.set(key, String(value))
                        }
                    }
                }

                const response = await fetch(input.url, {
                    method: input.method.toUpperCase(),
                    ...(body && { body }),
                    headers,
                    ...input.overrides,
                })

                // Handle rate limiting with exponential backoff
                if (response.status === 429) {
                    if (attempt < maxRetries) {
                        // Check for Retry-After header and calculate delay
                        const retryAfter = response.headers.get('Retry-After')
                        const delayMs = calculateBackoffDelay(attempt, retryAfter)

                        console.warn(
                            `Rate limited (429). Retrying in ${delayMs}ms (attempt ${attempt + 1}/${maxRetries})`
                        )
                        await sleep(delayMs)
                        continue
                    }
                    // Max retries exceeded - safely parse response
                    const { text } = await safeJsonParse(response)
                    throw new Error(formatRateLimitError(maxRetries, response.status, text))
                }

                if (!response.ok) {
                    // Safely parse error response (might not be JSON)
                    const { json: errorResponse, text: errorText } = await safeJsonParse(response)
                    const errorMessage = errorResponse
                        ? `Failed request: [${response.status}] ${JSON.stringify(errorResponse)}`
                        : `Failed request: [${response.status}] ${errorText}`
                    throw new Error(errorMessage)
                }

                return response
            }

            // This should never be reached, but TypeScript needs it
            throw new Error('Unexpected error in retry logic')
        },
    }
}
