import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { RedisLike } from '@/hono/cache/RedisCache'
import { HonoMcpServer, type RequestProperties } from '@/hono/mcp-server'

interface MockRedis extends RedisLike {
    _store: Map<string, string>
}

function createMockRedis(): MockRedis {
    const store = new Map<string, string>()
    return {
        get: vi.fn(async (key: string) => store.get(key) ?? null),
        set: vi.fn(async (key: string, value: string) => {
            store.set(key, value)
            return 'OK'
        }),
        del: vi.fn(async (...keys: string[]) => keys.length),
        scan: vi.fn(async () => ['0', []] as [string, string[]]),
        _store: store,
    }
}

describe('HonoMcpServer', () => {
    let mockRedis: MockRedis
    const baseProps: RequestProperties = {
        userHash: 'test-hash',
        apiToken: 'phx_test_token',
        version: 1,
    }
    const originalEnv = { ...process.env }

    beforeEach(() => {
        mockRedis = createMockRedis()
        delete process.env.POSTHOG_API_BASE_URL
    })

    afterEach(() => {
        process.env = { ...originalEnv }
    })

    describe('constructor', () => {
        it('should create a server instance', () => {
            const server = new HonoMcpServer(mockRedis, baseProps)
            expect(server.server).toBeTruthy()
        })

        it('should expose requestProperties', () => {
            const server = new HonoMcpServer(mockRedis, baseProps)
            expect(server.requestProperties.userHash).toBe('test-hash')
            expect(server.requestProperties.apiToken).toBe('phx_test_token')
        })
    })

    describe('getBaseUrl', () => {
        it('should return POSTHOG_API_BASE_URL from env', async () => {
            process.env.POSTHOG_API_BASE_URL = 'https://custom.posthog.com'
            const server = new HonoMcpServer(mockRedis, baseProps)
            const url = await server.getBaseUrl()
            expect(url).toBe('https://custom.posthog.com')
        })

        it('should default to localhost:8010 in dev when not set', async () => {
            delete process.env.POSTHOG_API_BASE_URL
            const server = new HonoMcpServer(mockRedis, baseProps)
            const url = await server.getBaseUrl()
            expect(url).toBe('http://localhost:8010')
        })

        it('should throw in production when not set', async () => {
            delete process.env.POSTHOG_API_BASE_URL
            process.env.NODE_ENV = 'production'
            const server = new HonoMcpServer(mockRedis, baseProps)
            await expect(server.getBaseUrl()).rejects.toThrow('POSTHOG_API_BASE_URL must be set')
        })
    })

    describe('sessionManager', () => {
        it('should return a SessionManager instance', () => {
            const server = new HonoMcpServer(mockRedis, baseProps)
            expect(server.sessionManager).toBeTruthy()
        })

        it('should return same instance on repeated access', () => {
            const server = new HonoMcpServer(mockRedis, baseProps)
            const sm1 = server.sessionManager
            const sm2 = server.sessionManager
            expect(sm1).toBe(sm2)
        })
    })

    describe('getContext', () => {
        it('should return a context with all required fields', async () => {
            const server = new HonoMcpServer(mockRedis, { ...baseProps, region: 'us' })
            vi.spyOn(server, 'getBaseUrl').mockResolvedValue('https://us.posthog.com')
            const ctx = await server.getContext()
            expect(ctx.api).toBeTruthy()
            expect(ctx.cache).toBeTruthy()
            expect(ctx.env).toBeTruthy()
            expect(ctx.stateManager).toBeTruthy()
            expect(ctx.sessionManager).toBeTruthy()
            expect(ctx.getDistinctId).toBeTruthy()
        })
    })

    describe('trackEvent', () => {
        it('should not throw on tracking errors', async () => {
            const server = new HonoMcpServer(mockRedis, baseProps)
            vi.spyOn(server, 'getDistinctId').mockRejectedValue(new Error('fail'))

            const { AnalyticsEvent } = await import('@/lib/posthog/analytics')
            await expect(server.trackEvent(AnalyticsEvent.MCP_INIT)).resolves.toBeUndefined()
        })
    })

    describe('api', () => {
        it('should cache the ApiClient instance', async () => {
            process.env.POSTHOG_API_BASE_URL = 'https://us.posthog.com'
            const server = new HonoMcpServer(mockRedis, baseProps)
            const api1 = await server.api()
            const api2 = await server.api()
            expect(api1).toBe(api2)
        })
    })
})
