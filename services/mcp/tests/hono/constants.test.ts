import { afterEach, describe, expect, it } from 'vitest'

import {
    POSTHOG_EU_BASE_URL,
    POSTHOG_US_BASE_URL,
    getAuthorizationServerUrl,
    getBaseUrlForRegion,
    getCustomApiBaseUrl,
    getEnv,
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
        ])('should return %s for input %s', (input, expected) => {
            expect(toCloudRegion(input)).toBe(expected)
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

    describe('getAuthorizationServerUrl', () => {
        it('should return custom URL when POSTHOG_API_BASE_URL is set', () => {
            process.env.POSTHOG_API_BASE_URL = 'https://custom.posthog.com'
            expect(getAuthorizationServerUrl('eu')).toBe('https://custom.posthog.com')
        })

        it('should return EU URL for eu region', () => {
            delete process.env.POSTHOG_API_BASE_URL
            expect(getAuthorizationServerUrl('eu')).toBe(POSTHOG_EU_BASE_URL)
        })

        it('should return US URL for us region', () => {
            delete process.env.POSTHOG_API_BASE_URL
            expect(getAuthorizationServerUrl('us')).toBe(POSTHOG_US_BASE_URL)
        })

        it('should default to US URL when region is null', () => {
            delete process.env.POSTHOG_API_BASE_URL
            expect(getAuthorizationServerUrl(null)).toBe(POSTHOG_US_BASE_URL)
        })
    })

    describe('getEnv', () => {
        it('should return env vars from process.env', () => {
            process.env.INKEEP_API_KEY = 'test-key'
            const env = getEnv()
            expect(env.INKEEP_API_KEY).toBe('test-key')
        })

        it('should return undefined for unset env vars', () => {
            delete process.env.INKEEP_API_KEY
            delete process.env.POSTHOG_API_BASE_URL
            const env = getEnv()
            expect(env.INKEEP_API_KEY).toBeUndefined()
            expect(env.POSTHOG_API_BASE_URL).toBeUndefined()
        })
    })
})
