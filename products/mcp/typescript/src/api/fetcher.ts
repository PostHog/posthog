import type { ApiConfig } from './client'
import type { createApiClient } from './generated'

export const buildApiFetcher: (config: ApiConfig) => Parameters<typeof createApiClient>[0] = (
    config
) => {
    return {
        fetch: async (input) => {
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

            if (!response.ok) {
                const errorResponse = await response.json()
                throw new Error(
                    `Failed request: [${response.status}] ${JSON.stringify(errorResponse)}`
                )
            }

            return response
        },
    }
}
