import type { ApiConfig } from './client'
import type { createApiClient } from './generated'
import { globalRateLimiter } from './rate-limiter'
import { RETRY_CONFIG, calculateRetryDelay } from './retry-config'

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

export const buildApiFetcher: (config: ApiConfig) => Parameters<typeof createApiClient>[0] = (config) => {
    return {
        fetch: async (input) => {
            // Handle query parameters once before retry loop
            if (input.urlSearchParams) {
                input.url.search = input.urlSearchParams.toString()
            }

            for (let attempt = 0; attempt <= RETRY_CONFIG.MAX_RETRIES; attempt++) {
                // Apply rate limiting before making the request
                await globalRateLimiter.throttle()

                const headers = new Headers()
                headers.set('Authorization', `Bearer ${config.apiToken}`)

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
                    if (attempt < RETRY_CONFIG.MAX_RETRIES) {
                        // Check for Retry-After header with validation
                        const retryAfter = response.headers.get('Retry-After')
                        const delayMs = calculateRetryDelay(attempt, retryAfter)

                        console.warn(
                            `Rate limited (429). Retrying in ${delayMs}ms (attempt ${attempt + 1}/${RETRY_CONFIG.MAX_RETRIES})`
                        )
                        await sleep(delayMs)
                        continue
                    }
                    // Max retries exceeded
                    const errorResponse = await response.json()
                    throw new Error(
                        `Rate limit exceeded after ${RETRY_CONFIG.MAX_RETRIES} retries:\n` +
                            `  Status: ${response.status}\n` +
                            `  Response: ${JSON.stringify(errorResponse, null, 2)}`
                    )
                }

                if (!response.ok) {
                    const errorResponse = await response.json()
                    throw new Error(`Failed request: [${response.status}] ${JSON.stringify(errorResponse)}`)
                }

                return response
            }

            // This should never be reached, but TypeScript needs it
            throw new Error('Unexpected error in retry logic')
        },
    }
}
