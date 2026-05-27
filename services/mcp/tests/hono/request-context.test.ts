import { describe, expect, it, vi } from 'vitest'

const mockMe = vi.fn()

vi.mock('@/api/client', () => ({
    ApiClient: vi.fn().mockImplementation(() => ({
        users: () => ({ me: mockMe }),
    })),
}))

import type { RedisLike } from '@/hono/cache/RedisCache'
import { RequestContext } from '@/hono/request-context'
import type { RequestProperties } from '@/lib/request-properties'

import { makeRedisRateLimitStubs } from './helpers/redis-rate-limit-stubs'

function fakeRedis(): RedisLike {
    const store = new Map<string, string>()
    return {
        get: async (key) => store.get(key) ?? null,
        set: async (key, value) => {
            store.set(key, String(value))
            return 'OK'
        },
        del: async (...keys) => {
            let n = 0
            for (const k of keys) {
                if (store.delete(k)) {
                    n++
                }
            }
            return n
        },
        scan: async () => ['0', [...store.keys()]],
        ...makeRedisRateLimitStubs(),
    }
}

const env = {} as any

function makeProps(overrides: Partial<RequestProperties> = {}): RequestProperties {
    return {
        userHash: 'test-user',
        apiToken: 'phx_test',
        sessionId: 'sess-1',
        mcpClientName: 'test-client',
        mcpClientVersion: '1.0',
        mcpProtocolVersion: '2025-03-26',
        transport: 'streamable-http',
        requestStartTime: Date.now(),
        ...overrides,
    }
}

describe('RequestContext', () => {
    describe('getDistinctId', () => {
        it('deduplicates concurrent calls into a single API request', async () => {
            mockMe.mockResolvedValue({ success: true, data: { distinct_id: 'user-123' } })
            const ctx = new RequestContext(fakeRedis(), env, makeProps())

            const [a, b, c] = await Promise.all([ctx.getDistinctId(), ctx.getDistinctId(), ctx.getDistinctId()])

            expect(a).toBe('user-123')
            expect(b).toBe('user-123')
            expect(c).toBe('user-123')
            expect(mockMe).toHaveBeenCalledTimes(1)
        })

        it('returns cached distinctId without calling API', async () => {
            const redis = fakeRedis()
            await redis.set('mcp:token:test-user:distinctId', JSON.stringify('cached-id'))
            mockMe.mockClear()

            const ctx = new RequestContext(redis, env, makeProps())
            const result = await ctx.getDistinctId()

            expect(result).toBe('cached-id')
            expect(mockMe).not.toHaveBeenCalled()
        })

        it('caches the resolved distinctId for subsequent calls', async () => {
            mockMe.mockResolvedValueOnce({ success: true, data: { distinct_id: 'fresh-id' } })
            const redis = fakeRedis()
            const ctx = new RequestContext(redis, env, makeProps())

            await ctx.getDistinctId()
            const cached = await redis.get('mcp:token:test-user:distinctId')
            expect(JSON.parse(cached!)).toBe('fresh-id')
        })

        it('throws when API returns an error', async () => {
            mockMe.mockResolvedValue({ success: false, error: { message: 'Unauthorized' } })
            const ctx = new RequestContext(fakeRedis(), env, makeProps())

            await expect(ctx.getDistinctId()).rejects.toThrow('Failed to get user')
        })
    })

    describe('getSessionUuid', () => {
        it('returns undefined when sessionId is undefined', async () => {
            const ctx = new RequestContext(fakeRedis(), env, makeProps())
            expect(await ctx.getSessionUuid(undefined)).toBeUndefined()
        })

        it('returns a stable UUID for the same sessionId', async () => {
            const ctx = new RequestContext(fakeRedis(), env, makeProps())
            const first = await ctx.getSessionUuid('sess-abc')
            const second = await ctx.getSessionUuid('sess-abc')

            expect(first).toBe(second)
            expect(first).toMatch(/^[0-9a-f-]{36}$/)
        })

        it('returns different UUIDs for different sessionIds', async () => {
            const ctx = new RequestContext(fakeRedis(), env, makeProps())
            const a = await ctx.getSessionUuid('sess-1')
            const b = await ctx.getSessionUuid('sess-2')

            expect(a).not.toBe(b)
        })
    })

    describe('buildClientProperties', () => {
        it('includes all request properties', () => {
            const ctx = new RequestContext(
                fakeRedis(),
                env,
                makeProps({
                    mcpClientName: 'claude-code',
                    mcpClientVersion: '2.0',
                    mcpProtocolVersion: '2025-03-26',
                    mcpConsumer: 'posthog-code',
                    transport: 'streamable-http',
                })
            )

            const result = ctx.buildClientProperties()
            expect(result).toMatchObject({
                $ai_product: 'mcp',
                $mcp_source: 'posthog_mcp_analytics',
                $mcp_server_name: 'PostHog',
                $mcp_server_version: '1.0.0',
                $mcp_client_name: 'claude-code',
                $mcp_client_version: '2.0',
                $mcp_protocol_version: '2025-03-26',
                $mcp_consumer: 'posthog-code',
                $mcp_transport: 'streamable-http',
                mcp_runtime: 'hono',
            })
        })

        it('omits undefined properties', () => {
            const ctx = new RequestContext(
                fakeRedis(),
                env,
                makeProps({
                    mcpClientName: undefined,
                    mcpClientVersion: undefined,
                    mcpProtocolVersion: undefined,
                    mcpConsumer: undefined,
                    transport: undefined,
                })
            )

            const result = ctx.buildClientProperties()
            expect(result).toMatchObject({
                $ai_product: 'mcp',
                $mcp_source: 'posthog_mcp_analytics',
                $mcp_server_name: 'PostHog',
                $mcp_server_version: '1.0.0',
                mcp_runtime: 'hono',
            })
            expect(result.$mcp_client_name).toBeUndefined()
            expect(result.$mcp_consumer).toBeUndefined()
            expect(result.$mcp_transport).toBeUndefined()
        })
    })

    describe('cache', () => {
        it('throws when userHash is missing', () => {
            const ctx = new RequestContext(fakeRedis(), env, makeProps({ userHash: '' }))
            expect(() => ctx.cache).toThrow('User hash is required')
        })

        it('returns the same cache instance on repeated access', () => {
            const ctx = new RequestContext(fakeRedis(), env, makeProps())
            expect(ctx.cache).toBe(ctx.cache)
        })
    })
})
