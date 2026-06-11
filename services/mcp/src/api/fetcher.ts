import { getUserAgent } from '@/lib/constants'
import { parseRetryAfterSeconds, PostHogApiError, PostHogRateLimitError } from '@/lib/errors'

import type { ApiConfig } from './client'

export interface Fetcher {
    fetch: (input: {
        method: string
        url: URL
        urlSearchParams?: URLSearchParams
        parameters?: { body?: unknown; header?: Record<string, unknown> }
        path: string
        overrides?: RequestInit
    }) => Promise<Response>
}

export const buildApiFetcher: (config: ApiConfig) => Fetcher = (config) => {
    return {
        fetch: async (input) => {
            const headers = new Headers()
            headers.set('Authorization', `Bearer ${config.apiToken}`)
            headers.set('User-Agent', getUserAgent({ clientUserAgent: config.clientUserAgent }))
            if (config.clientUserAgent) {
                // Forward the originating client's User-Agent so the PostHog API can
                // attach it to analytics events for MCP source attribution.
                headers.set('x-posthog-mcp-user-agent', config.clientUserAgent)
            }
            if (config.mcpConsumer) {
                headers.set('x-posthog-mcp-consumer', config.mcpConsumer)
            }
            if (config.oauthClientName) {
                headers.set('x-posthog-mcp-oauth-client-name', config.oauthClientName)
            }

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

            // No server-side retries on 429 — surface the rate limit and its
            // Retry-After hint to the caller so pending requests don't pile up
            // behind sleeps.
            if (response.status === 429) {
                const retryAfterSeconds = parseRetryAfterSeconds(response.headers.get('Retry-After'))
                const errorBody = await response.text()
                console.warn(`Rate limited (429) on ${input.method.toUpperCase()} ${input.url}`)
                throw new PostHogRateLimitError({
                    body: errorBody,
                    url: input.url.toString(),
                    method: input.method.toUpperCase(),
                    retryAfterSeconds,
                })
            }

            if (!response.ok) {
                const errorResponse = await response.json()
                const errorBody = JSON.stringify(errorResponse)
                throw new PostHogApiError({
                    status: response.status,
                    statusText: response.statusText,
                    body: errorBody,
                    url: input.url.toString(),
                    method: input.method.toUpperCase(),
                    message: `Failed request: [${response.status}] ${errorBody}`,
                })
            }

            return response
        },
    }
}
