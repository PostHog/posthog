import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { loadConfig } from '@/server/config'

describe('config', () => {
    const originalEnv = process.env

    beforeEach(() => {
        process.env = { ...originalEnv }
    })

    afterEach(() => {
        process.env = originalEnv
    })

    describe('loadConfig', () => {
        it('returns default port when PORT not set', () => {
            delete process.env.PORT
            const config = loadConfig()
            expect(config.port).toBe(8080)
        })

        it('parses PORT from environment', () => {
            process.env.PORT = '3000'
            const config = loadConfig()
            expect(config.port).toBe(3000)
        })

        it('returns undefined for optional values when not set', () => {
            delete process.env.REDIS_URL
            delete process.env.POSTHOG_API_INTERNAL_URL_US
            delete process.env.POSTHOG_API_INTERNAL_URL_EU
            delete process.env.INKEEP_API_KEY

            const config = loadConfig()

            expect(config.redisUrl).toBeUndefined()
            expect(config.internalApiUrlUs).toBeUndefined()
            expect(config.internalApiUrlEu).toBeUndefined()
            expect(config.inkeepApiKey).toBeUndefined()
        })

        it('loads all environment variables when set', () => {
            process.env.PORT = '9000'
            process.env.REDIS_URL = 'redis://localhost:6379'
            process.env.POSTHOG_API_INTERNAL_URL_US = 'http://internal-us'
            process.env.POSTHOG_API_INTERNAL_URL_EU = 'http://internal-eu'
            process.env.INKEEP_API_KEY = 'test-key'

            const config = loadConfig()

            expect(config.port).toBe(9000)
            expect(config.redisUrl).toBe('redis://localhost:6379')
            expect(config.internalApiUrlUs).toBe('http://internal-us')
            expect(config.internalApiUrlEu).toBe('http://internal-eu')
            expect(config.inkeepApiKey).toBe('test-key')
        })
    })
})
