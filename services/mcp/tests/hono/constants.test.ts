import { afterEach, describe, expect, it } from 'vitest'

import {
    POSTHOG_EU_BASE_URL,
    POSTHOG_US_BASE_URL,
    USER_AGENT,
    getAuthorizationServerUrl,
    getBaseUrlForRegion,
    getCustomApiBaseUrl,
    getEnv,
    getPublicBaseUrl,
    getUserAgent,
    toCloudRegion,
} from '@/hono/constants'

describe('Hono Constants', () => {
    const originalEnv = { ...process.env }

    afterEach(() => {
        process.env = { ...originalEnv }
    })

    describe('toCloudRegion', () => {
        it.each([
            ['eu', 'eu'],
            ['EU', 'eu'],
            ['Eu', 'eu'],
            ['us', 'us'],
            ['US', 'us'],
            [undefined, 'us'],
            [null, 'us'],
            ['invalid', 'us'],
            ['', 'us'],
        ] as const)('should return %s for input %s', (input, expected) => {
            expect(toCloudRegion(input as string | undefined | null)).toBe(expected)
        })
    })

    describe('getBaseUrlForRegion', () => {
        it('should return EU URL for eu region', () => {
            expect(getBaseUrlForRegion('eu')).toBe(POSTHOG_EU_BASE_URL)
        })

        it('should return US URL for us region', () => {
            expect(getBaseUrlForRegion('us')).toBe(POSTHOG_US_BASE_URL)
        })
    })

    describe('getCustomApiBaseUrl', () => {
        it('should return undefined when env var not set', () => {
            delete process.env.POSTHOG_API_BASE_URL
            expect(getCustomApiBaseUrl()).toBeUndefined()
        })

        it('should return the env var value when set', () => {
            process.env.POSTHOG_API_BASE_URL = 'https://custom.posthog.com'
            expect(getCustomApiBaseUrl()).toBe('https://custom.posthog.com')
        })
    })

    describe('getPublicBaseUrl', () => {
        it('returns POSTHOG_PUBLIC_URL when set, even if POSTHOG_API_BASE_URL is also set', () => {
            process.env.POSTHOG_API_BASE_URL = 'http://posthog-web-django.posthog.svc.cluster.local:8000'
            process.env.POSTHOG_PUBLIC_URL = 'https://us.posthog.com'
            expect(getPublicBaseUrl()).toBe('https://us.posthog.com')
        })

        it('falls back to POSTHOG_API_BASE_URL when POSTHOG_PUBLIC_URL is unset', () => {
            process.env.POSTHOG_API_BASE_URL = 'https://us.posthog.com'
            delete process.env.POSTHOG_PUBLIC_URL
            expect(getPublicBaseUrl()).toBe('https://us.posthog.com')
        })

        it('returns undefined when neither env var is set', () => {
            delete process.env.POSTHOG_API_BASE_URL
            delete process.env.POSTHOG_PUBLIC_URL
            expect(getPublicBaseUrl()).toBeUndefined()
        })
    })

    describe('getAuthorizationServerUrl', () => {
        it('should return localhost URL when POSTHOG_API_BASE_URL is localhost', () => {
            process.env.POSTHOG_API_BASE_URL = 'http://localhost:8010'
            expect(getAuthorizationServerUrl()).toBe('http://localhost:8010')
        })

        it('should return oauth proxy URL when POSTHOG_API_BASE_URL is a cloud URL', () => {
            process.env.POSTHOG_API_BASE_URL = 'https://us.posthog.com'
            expect(getAuthorizationServerUrl()).toBe('https://oauth.posthog.com')
        })

        it('should return oauth proxy URL when POSTHOG_API_BASE_URL is an internal cluster URL', () => {
            process.env.POSTHOG_API_BASE_URL = 'http://posthog-web-django.posthog.svc.cluster.local:8000'
            expect(getAuthorizationServerUrl()).toBe('https://oauth.posthog.com')
        })

        it('should return self-hosted URL when POSTHOG_API_BASE_URL is a custom domain', () => {
            process.env.POSTHOG_API_BASE_URL = 'https://posthog.example.com'
            expect(getAuthorizationServerUrl()).toBe('https://posthog.example.com')
        })

        it('should return oauth proxy URL when no custom URL', () => {
            delete process.env.POSTHOG_API_BASE_URL
            expect(getAuthorizationServerUrl()).toBe('https://oauth.posthog.com')
        })
    })

    describe('getUserAgent', () => {
        it('should return base user agent when no options', () => {
            expect(getUserAgent()).toBe(USER_AGENT)
        })

        it('should append posthog client info when present', () => {
            expect(getUserAgent({ clientUserAgent: 'posthog/web-client-1.0' })).toContain('for posthog/web-client-1')
        })

        it('should return base user agent for non-posthog clients', () => {
            expect(getUserAgent({ clientUserAgent: 'Mozilla/5.0' })).toBe(USER_AGENT)
        })

        it('should prepend consumer/client token when mcpConsumer is set', () => {
            const ua = getUserAgent({ mcpConsumer: 'posthog-code', mcpClientName: 'claude-code' })
            expect(ua).toMatch(/^posthog-code\/claude-code posthog\/mcp-server/)
        })

        it('should use "unknown" for mcpClientName when not provided', () => {
            const ua = getUserAgent({ mcpConsumer: 'my-app' })
            expect(ua).toMatch(/^my-app\/unknown posthog\/mcp-server/)
        })
    })

    describe('getEnv', () => {
        it('should return env vars from process.env', () => {
            process.env.POSTHOG_ANALYTICS_API_KEY = 'test-key'
            const env = getEnv()
            expect(env.POSTHOG_ANALYTICS_API_KEY).toBe('test-key')
        })

        it('should return undefined for unset env vars', () => {
            delete process.env.POSTHOG_ANALYTICS_API_KEY
            delete process.env.POSTHOG_API_BASE_URL
            const env = getEnv()
            expect(env.POSTHOG_ANALYTICS_API_KEY).toBeUndefined()
            expect(env.POSTHOG_API_BASE_URL).toBeUndefined()
        })

        it('should return all expected fields', () => {
            const env = getEnv()
            expect(env).toHaveProperty('POSTHOG_API_BASE_URL')
            expect(env).toHaveProperty('POSTHOG_PUBLIC_URL')
            expect(env).toHaveProperty('MCP_APPS_BASE_URL')
            expect(env).toHaveProperty('POSTHOG_MCP_APPS_ANALYTICS_BASE_URL')
            expect(env).toHaveProperty('POSTHOG_UI_APPS_TOKEN')
            expect(env).toHaveProperty('POSTHOG_ANALYTICS_API_KEY')
            expect(env).toHaveProperty('POSTHOG_ANALYTICS_HOST')
        })
    })
})
