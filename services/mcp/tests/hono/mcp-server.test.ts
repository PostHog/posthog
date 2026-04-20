import { beforeEach, describe, expect, it, vi } from 'vitest'

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

    beforeEach(() => {
        mockRedis = createMockRedis()
    })

    describe('constructor', () => {
        it('should create a server instance', () => {
            const server = new HonoMcpServer(mockRedis, baseProps)
            expect(server.server).toBeTruthy()
        })
    })

    describe('getBaseUrl', () => {
        it('should return US base URL by default', async () => {
            const server = new HonoMcpServer(mockRedis, baseProps)
            vi.spyOn(server, 'detectRegion').mockResolvedValue(undefined)
            const url = await server.getBaseUrl()
            expect(url).toBe('https://us.posthog.com')
        })

        it('should return EU base URL when region is eu', async () => {
            const server = new HonoMcpServer(mockRedis, { ...baseProps, region: 'eu' })
            const url = await server.getBaseUrl()
            expect(url).toBe('https://eu.posthog.com')
        })

        it('should use cached region when available', async () => {
            mockRedis._store.set('mcp:user:test-hash:region', '"eu"')
            const server = new HonoMcpServer(mockRedis, baseProps)
            const url = await server.getBaseUrl()
            expect(url).toBe('https://eu.posthog.com')
        })

        it('should cache region from props', async () => {
            const server = new HonoMcpServer(mockRedis, { ...baseProps, region: 'eu' })
            await server.getBaseUrl()
            expect(mockRedis.set).toHaveBeenCalledWith(
                'mcp:user:test-hash:region',
                'eu',
                'EX',
                expect.any(Number)
            )
        })

        it('should use custom API base URL from env', async () => {
            const originalEnv = process.env.POSTHOG_API_BASE_URL
            process.env.POSTHOG_API_BASE_URL = 'https://custom.posthog.com'
            try {
                const server = new HonoMcpServer(mockRedis, baseProps)
                const url = await server.getBaseUrl()
                expect(url).toBe('https://custom.posthog.com')
            } finally {
                if (originalEnv !== undefined) {
                    process.env.POSTHOG_API_BASE_URL = originalEnv
                } else {
                    delete process.env.POSTHOG_API_BASE_URL
                }
            }
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
        })
    })

    describe('trackEvent', () => {
        it('should not throw on tracking errors', async () => {
            const server = new HonoMcpServer(mockRedis, baseProps)
            vi.spyOn(server, 'getDistinctId').mockRejectedValue(new Error('fail'))

            const { AnalyticsEvent } = await import('@/lib/analytics')
            await expect(server.trackEvent(AnalyticsEvent.MCP_INIT)).resolves.toBeUndefined()
        })
    })

    describe('api', () => {
        it('should cache the ApiClient instance', async () => {
            const server = new HonoMcpServer(mockRedis, { ...baseProps, region: 'us' })
            const api1 = await server.api()
            const api2 = await server.api()
            expect(api1).toBe(api2)
        })
    })
})
