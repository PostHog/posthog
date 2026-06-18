import { afterEach, describe, expect, it } from 'vitest'

import {
    getAuthorizationServerUrl,
    getBaseUrlForRegion,
    getPublicBaseUrl,
    isCloudApi,
    isLocalApi,
    toCloudRegion,
} from '@/lib/constants'

describe('OAuth Region Routing', () => {
    const originalEnv = { ...process.env }

    afterEach(() => {
        process.env = { ...originalEnv }
    })

    describe('isLocalApi', () => {
        it('returns true when POSTHOG_API_BASE_URL is localhost', () => {
            process.env.POSTHOG_API_BASE_URL = 'http://localhost:8010'
            expect(isLocalApi()).toBe(true)
        })

        it('returns false when POSTHOG_API_BASE_URL is a cloud URL', () => {
            process.env.POSTHOG_API_BASE_URL = 'https://us.posthog.com'
            expect(isLocalApi()).toBe(false)
        })

        it('returns false when POSTHOG_API_BASE_URL is not set', () => {
            delete process.env.POSTHOG_API_BASE_URL
            expect(isLocalApi()).toBe(false)
        })
    })

    describe('isCloudApi', () => {
        it('returns true when POSTHOG_API_BASE_URL is not set', () => {
            delete process.env.POSTHOG_API_BASE_URL
            expect(isCloudApi()).toBe(true)
        })

        it('returns true for us.posthog.com', () => {
            process.env.POSTHOG_API_BASE_URL = 'https://us.posthog.com'
            expect(isCloudApi()).toBe(true)
        })

        it('returns true for eu.posthog.com', () => {
            process.env.POSTHOG_API_BASE_URL = 'https://eu.posthog.com'
            expect(isCloudApi()).toBe(true)
        })

        it('returns true for internal cluster URL', () => {
            process.env.POSTHOG_API_BASE_URL = 'http://posthog-web-django.posthog.svc.cluster.local:8000'
            expect(isCloudApi()).toBe(true)
        })

        it('returns false for self-hosted domain', () => {
            process.env.POSTHOG_API_BASE_URL = 'https://posthog.example.com'
            expect(isCloudApi()).toBe(false)
        })

        it('returns false for localhost', () => {
            process.env.POSTHOG_API_BASE_URL = 'http://localhost:8010'
            expect(isCloudApi()).toBe(false)
        })
    })

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

    describe('getPublicBaseUrl', () => {
        it('returns POSTHOG_PUBLIC_URL when set', () => {
            process.env.POSTHOG_API_BASE_URL = 'http://posthog-web-django.posthog.svc.cluster.local:8000'
            process.env.POSTHOG_PUBLIC_URL = 'https://us.posthog.com'
            expect(getPublicBaseUrl()).toBe('https://us.posthog.com')
        })

        it('falls back to POSTHOG_API_BASE_URL when POSTHOG_PUBLIC_URL is not set', () => {
            process.env.POSTHOG_API_BASE_URL = 'http://localhost:8010'
            delete process.env.POSTHOG_PUBLIC_URL
            expect(getPublicBaseUrl()).toBe('http://localhost:8010')
        })

        it('returns undefined when neither is set', () => {
            delete process.env.POSTHOG_API_BASE_URL
            delete process.env.POSTHOG_PUBLIC_URL
            expect(getPublicBaseUrl()).toBeUndefined()
        })
    })

    describe('getAuthorizationServerUrl', () => {
        it('returns localhost when POSTHOG_API_BASE_URL is localhost', () => {
            process.env.POSTHOG_API_BASE_URL = 'http://localhost:8010'
            expect(getAuthorizationServerUrl()).toBe('http://localhost:8010')
        })

        it('returns oauth proxy URL when POSTHOG_API_BASE_URL is a cloud URL', () => {
            process.env.POSTHOG_API_BASE_URL = 'https://us.posthog.com'
            expect(getAuthorizationServerUrl()).toBe('https://oauth.posthog.com')
        })

        it('returns oauth proxy URL when POSTHOG_API_BASE_URL is an internal cluster URL', () => {
            process.env.POSTHOG_API_BASE_URL = 'http://posthog-web-django.posthog.svc.cluster.local:8000'
            expect(getAuthorizationServerUrl()).toBe('https://oauth.posthog.com')
        })

        it('returns self-hosted URL when POSTHOG_API_BASE_URL is a custom domain', () => {
            process.env.POSTHOG_API_BASE_URL = 'https://posthog.example.com'
            expect(getAuthorizationServerUrl()).toBe('https://posthog.example.com')
        })

        it('returns oauth proxy URL when not set', () => {
            delete process.env.POSTHOG_API_BASE_URL
            expect(getAuthorizationServerUrl()).toBe('https://oauth.posthog.com')
        })
    })

    describe('401 Response Metadata URL (RFC 9728)', () => {
        // Per RFC 9728, the well-known URL is constructed by inserting the well-known path
        // between the host and the resource path:
        // - Resource /mcp → metadata at /.well-known/oauth-protected-resource/mcp
        // - Resource /sse → metadata at /.well-known/oauth-protected-resource/sse
        //   (the /sse endpoint itself is deprecated and redirects to /mcp, but the
        //   metadata generator stays generic so cached metadata for /sse remains valid)
        const testCases = [
            {
                name: 'includes region param and resource path /mcp in metadata URL',
                requestUrl: 'https://mcp.posthog.com/mcp?region=eu',
                expectedMetadataUrl: 'https://mcp.posthog.com/.well-known/oauth-protected-resource/mcp?region=eu',
            },
            {
                name: 'includes resource path /mcp when no region param',
                requestUrl: 'https://mcp.posthog.com/mcp',
                expectedMetadataUrl: 'https://mcp.posthog.com/.well-known/oauth-protected-resource/mcp',
            },
            {
                name: 'includes resource path /sse for legacy SSE endpoint',
                requestUrl: 'https://mcp.posthog.com/sse',
                expectedMetadataUrl: 'https://mcp.posthog.com/.well-known/oauth-protected-resource/sse',
            },
            {
                name: 'preserves region param with resource path',
                requestUrl: 'https://mcp.posthog.com/mcp?features=flags&region=eu',
                expectedMetadataUrl: 'https://mcp.posthog.com/.well-known/oauth-protected-resource/mcp?region=eu',
            },
            {
                name: 'normalizes uppercase region to lowercase for consistency',
                requestUrl: 'https://mcp.posthog.com/mcp?region=EU',
                expectedMetadataUrl: 'https://mcp.posthog.com/.well-known/oauth-protected-resource/mcp?region=eu',
            },
        ]

        it.each(testCases)('$name', ({ requestUrl, expectedMetadataUrl }) => {
            const url = new URL(requestUrl)
            // Matches actual behavior: normalize to lowercase and include if present
            const regionParam = url.searchParams.get('region')?.toLowerCase()

            // Per RFC 9728: insert well-known path between host and resource path
            const metadataUrl = new URL(requestUrl)
            metadataUrl.pathname = `/.well-known/oauth-protected-resource${url.pathname}`
            metadataUrl.search = ''
            if (regionParam) {
                metadataUrl.searchParams.set('region', regionParam)
            }

            expect(metadataUrl.toString()).toBe(expectedMetadataUrl)
        })
    })

    describe('Protected Resource Metadata endpoint (RFC 9728)', () => {
        // Per RFC 9728, the well-known endpoint extracts the resource path from the URL
        // e.g., /.well-known/oauth-protected-resource/mcp → resource is /mcp
        const testCases = [
            {
                name: 'extracts /mcp resource from well-known path',
                wellKnownUrl: 'https://mcp.posthog.com/.well-known/oauth-protected-resource/mcp',
                expectedResource: 'https://mcp.posthog.com/mcp',
            },
            {
                name: 'extracts /sse resource from well-known path',
                wellKnownUrl: 'https://mcp.posthog.com/.well-known/oauth-protected-resource/sse',
                expectedResource: 'https://mcp.posthog.com/sse',
            },
            {
                name: 'returns root for well-known without path suffix',
                wellKnownUrl: 'https://mcp.posthog.com/.well-known/oauth-protected-resource',
                expectedResource: 'https://mcp.posthog.com',
            },
        ]

        it.each(testCases)('$name', ({ wellKnownUrl, expectedResource }) => {
            const wellKnownPrefix = '/.well-known/oauth-protected-resource'
            const url = new URL(wellKnownUrl)
            const resourcePath = url.pathname.slice(wellKnownPrefix.length) || '/'

            const resourceUrl = new URL(wellKnownUrl)
            resourceUrl.pathname = resourcePath
            resourceUrl.search = ''

            expect(resourceUrl.toString().replace(/\/$/, '')).toBe(expectedResource)
        })
    })
})
