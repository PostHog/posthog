import type { ApiConfig } from './client'
import type { createApiClient } from './generated'
import { globalRateLimiter } from './rate-limiter'

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

export const buildApiFetcher: (config: ApiConfig) => Parameters<typeof createApiClient>[0] = (config) => {
    return {
        fetch: async (input) => {
            const maxRetries = 3
            const baseBackoffMs = 2000

            for (let attempt = 0; attempt <= maxRetries; attempt++) {
                // Apply rate limiting before making the request
                await globalRateLimiter.throttle()

                const headers = new Headers()
                headers.set('Authorization', `Bearer ${config.apiToken}`)

                // Handle query parameters
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
                        // Check for Retry-After header
                        const retryAfter = response.headers.get('Retry-After')
                        const delayMs = retryAfter
                            ? parseInt(retryAfter, 10) * 1000
                            : baseBackoffMs * Math.pow(2, attempt)

                        console.warn(
                            `Rate limited (429). Retrying in ${delayMs}ms (attempt ${attempt + 1}/${maxRetries})`
                        )
                        await sleep(delayMs)
                        continue
                    }
                    // Max retries exceeded
                    const errorResponse = await response.json()
                    throw new Error(
                        `Rate limit exceeded after ${maxRetries} retries: [${response.status}] ${JSON.stringify(errorResponse)}`
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
