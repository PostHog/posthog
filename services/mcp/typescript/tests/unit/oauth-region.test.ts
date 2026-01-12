import { describe, expect, it } from 'vitest'

describe('OAuth Region Routing', () => {
    describe('Protected Resource Metadata', () => {
        const testCases = [
            {
                name: 'defaults to US when no region param',
                params: '',
                expectedServer: 'https://us.posthog.com',
            },
            {
                name: 'returns EU server when region=eu',
                params: '?region=eu',
                expectedServer: 'https://eu.posthog.com',
            },
            {
                name: 'returns EU server when region=EU (case insensitive)',
                params: '?region=EU',
                expectedServer: 'https://eu.posthog.com',
            },
            {
                name: 'returns US server when region=us',
                params: '?region=us',
                expectedServer: 'https://us.posthog.com',
            },
            {
                name: 'defaults to US for unknown region',
                params: '?region=unknown',
                expectedServer: 'https://us.posthog.com',
            },
        ]

        it.each(testCases)('$name', ({ params, expectedServer }) => {
            const url = new URL(`https://mcp.posthog.com/.well-known/oauth-protected-resource${params}`)
            const regionParam = url.searchParams.get('region')?.toLowerCase()

            let authorizationServer: string
            if (regionParam === 'eu') {
                authorizationServer = 'https://eu.posthog.com'
            } else {
                authorizationServer = 'https://us.posthog.com'
            }

            expect(authorizationServer).toBe(expectedServer)
        })
    })

    describe('401 Response Metadata URL', () => {
        const testCases = [
            {
                name: 'includes region param in metadata URL when specified',
                requestUrl: 'https://mcp.posthog.com/mcp?region=eu',
                expectedMetadataUrl: 'https://mcp.posthog.com/.well-known/oauth-protected-resource?region=eu',
            },
            {
                name: 'no region param in metadata URL when not specified',
                requestUrl: 'https://mcp.posthog.com/mcp',
                expectedMetadataUrl: 'https://mcp.posthog.com/.well-known/oauth-protected-resource',
            },
            {
                name: 'preserves region param with other params',
                requestUrl: 'https://mcp.posthog.com/mcp?features=flags&region=eu',
                expectedMetadataUrl: 'https://mcp.posthog.com/.well-known/oauth-protected-resource?region=eu',
            },
        ]

        it.each(testCases)('$name', ({ requestUrl, expectedMetadataUrl }) => {
            const url = new URL(requestUrl)
            const regionParam = url.searchParams.get('region')

            const metadataUrl = new URL('/.well-known/oauth-protected-resource', requestUrl)
            if (regionParam) {
                metadataUrl.searchParams.set('region', regionParam)
            }

            expect(metadataUrl.toString()).toBe(expectedMetadataUrl)
        })
    })
})
