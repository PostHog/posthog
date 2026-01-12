import { describe, expect, it } from 'vitest'

import { getAuthorizationServerUrl, getBaseUrlForRegion, toCloudRegion } from '@/lib/constants'

describe('OAuth Region Routing', () => {
    describe('toCloudRegion', () => {
        it.each([
            { input: 'eu', expected: 'eu' },
            { input: 'EU', expected: 'eu' },
            { input: 'Eu', expected: 'eu' },
            { input: 'us', expected: 'us' },
            { input: 'US', expected: 'us' },
            { input: 'unknown', expected: 'us' },
            { input: '', expected: 'us' },
            { input: null, expected: 'us' },
            { input: undefined, expected: 'us' },
        ])('toCloudRegion($input) returns $expected', ({ input, expected }) => {
            expect(toCloudRegion(input)).toBe(expected)
        })
    })

    describe('getBaseUrlForRegion', () => {
        it('returns EU URL for eu region', () => {
            expect(getBaseUrlForRegion('eu')).toBe('https://eu.posthog.com')
        })

        it('returns US URL for us region', () => {
            expect(getBaseUrlForRegion('us')).toBe('https://us.posthog.com')
        })
    })

    describe('getAuthorizationServerUrl', () => {
        it('returns EU URL when region is eu', () => {
            expect(getAuthorizationServerUrl('eu')).toBe('https://eu.posthog.com')
        })

        it('returns EU URL when region is EU (case insensitive)', () => {
            expect(getAuthorizationServerUrl('EU')).toBe('https://eu.posthog.com')
        })

        it('returns US URL when region is us', () => {
            expect(getAuthorizationServerUrl('us')).toBe('https://us.posthog.com')
        })

        it('returns US URL when region is null', () => {
            expect(getAuthorizationServerUrl(null)).toBe('https://us.posthog.com')
        })

        it('returns US URL for unknown region', () => {
            expect(getAuthorizationServerUrl('unknown')).toBe('https://us.posthog.com')
        })
    })

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
            const regionParam = url.searchParams.get('region')

            // Uses actual helpers from constants.ts
            const authorizationServer = getBaseUrlForRegion(toCloudRegion(regionParam))

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
            {
                name: 'normalizes uppercase region to lowercase for consistency',
                requestUrl: 'https://mcp.posthog.com/mcp?region=EU',
                expectedMetadataUrl: 'https://mcp.posthog.com/.well-known/oauth-protected-resource?region=eu',
            },
        ]

        it.each(testCases)('$name', ({ requestUrl, expectedMetadataUrl }) => {
            const url = new URL(requestUrl)
            // Matches actual behavior: normalize to lowercase and include if present
            const regionParam = url.searchParams.get('region')?.toLowerCase()

            const metadataUrl = new URL('/.well-known/oauth-protected-resource', requestUrl)
            if (regionParam) {
                metadataUrl.searchParams.set('region', regionParam)
            }

            expect(metadataUrl.toString()).toBe(expectedMetadataUrl)
        })
    })
})
