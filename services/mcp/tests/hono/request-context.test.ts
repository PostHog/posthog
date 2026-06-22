import { afterEach, describe, expect, it, vi } from 'vitest'

const { mockMe, mockApiClientCtor } = vi.hoisted(() => {
    const mockMe = vi.fn()
    const mockApiClientCtor = vi.fn().mockImplementation(function () {
        return {
            users: () => ({ me: mockMe }),
        }
    })
    return { mockMe, mockApiClientCtor }
})

vi.mock('@/api/client', () => ({
    ApiClient: mockApiClientCtor,
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

function spyRedis(): RedisLike {
    return {
        get: vi.fn(async () => null),
        set: vi.fn(async () => 'OK'),
        del: vi.fn(async () => 0),
        scan: vi.fn(async () => ['0', []] as [string, string[]]),
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
    describe('ApiClient construction', () => {
        const originalEnv = { ...process.env }

        afterEach(() => {
            process.env = { ...originalEnv }
            mockApiClientCtor.mockClear()
            mockMe.mockClear()
        })

        it('passes POSTHOG_PUBLIC_URL as publicBaseUrl to the ApiClient', async () => {
            process.env.POSTHOG_API_BASE_URL = 'http://posthog-web-django.posthog.svc.cluster.local:8000'
            process.env.POSTHOG_PUBLIC_URL = 'https://us.posthog.com'

            mockMe.mockResolvedValue({ success: true, data: { distinct_id: 'user-1' } })
            const ctx = new RequestContext(fakeRedis(), env, makeProps())
            await ctx.getDistinctId()

            expect(mockApiClientCtor).toHaveBeenCalledTimes(1)
            const config = mockApiClientCtor.mock.calls[0]![0]
            expect(config.baseUrl).toBe('http://posthog-web-django.posthog.svc.cluster.local:8000')
            expect(config.publicBaseUrl).toBe('https://us.posthog.com')
        })

        it('falls back to POSTHOG_API_BASE_URL when POSTHOG_PUBLIC_URL is not set', async () => {
            process.env.POSTHOG_API_BASE_URL = 'https://us.posthog.com'
            delete process.env.POSTHOG_PUBLIC_URL

            mockMe.mockResolvedValue({ success: true, data: { distinct_id: 'user-1' } })
            const ctx = new RequestContext(fakeRedis(), env, makeProps())
            await ctx.getDistinctId()

            const config = mockApiClientCtor.mock.calls[0]![0]
            expect(config.baseUrl).toBe('https://us.posthog.com')
            expect(config.publicBaseUrl).toBe('https://us.posthog.com')
        })
    })

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

    describe('getEffectiveSessionUuid', () => {
        it.each([
            { sessionId: 'sess-1', mcpSessionId: 'mcp-1', expectedKey: 'sess-1' },
            { sessionId: undefined, mcpSessionId: 'mcp-1', expectedKey: 'mcp-1' },
            { sessionId: undefined, mcpSessionId: undefined, expectedKey: undefined },
        ])(
            'sessionId=$sessionId mcpSessionId=$mcpSessionId → resolves via expectedKey=$expectedKey',
            async ({ sessionId, mcpSessionId, expectedKey }) => {
                const ctx = new RequestContext(fakeRedis(), env, makeProps())
                const effective = await ctx.getEffectiveSessionUuid({ sessionId, mcpSessionId } as any)

                expect(effective).toBe(expectedKey ? await ctx.getSessionUuid(expectedKey) : undefined)
                if (expectedKey) {
                    expect(effective).toMatch(/^[0-9a-f-]{36}$/)
                }
            }
        )
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

        it('adds stable session properties without replacing request properties', () => {
            const ctx = new RequestContext(
                fakeRedis(),
                env,
                makeProps({
                    mcpClientName: 'Claude Desktop',
                    mcpClientVersion: '2.0',
                    mcpProtocolVersion: '2025-03-26',
                    mcpConsumer: 'request-consumer',
                    mcpVendorClient: 'ClaudeAI',
                    transport: 'streamable-http',
                })
            )
            ctx.setMcpContexts(
                {
                    sessionId: 'sess-1',
                    mcpClientName: 'Claude Desktop',
                    mcpClientVersion: '2.0',
                    mcpProtocolVersion: '2025-03-26',
                    mcpConsumer: 'request-consumer',
                    mcpVendorClient: 'ClaudeAI',
                    transport: 'streamable-http',
                    mode: 'cli',
                },
                {
                    mcpClientName: 'claude-code',
                    mcpClientVersion: '1.0',
                    mcpProtocolVersion: '2025-03-26',
                    mcpConsumer: 'session-consumer',
                    mcpVendorClient: 'ClaudeCode',
                }
            )

            const result = ctx.buildClientProperties()
            expect(result).toMatchObject({
                $mcp_client_name: 'Claude Desktop',
                $mcp_client_version: '2.0',
                $mcp_consumer: 'request-consumer',
                mcp_vendor_client: 'ClaudeAI',
                mcp_session_client_name: 'claude-code',
                mcp_session_client_version: '1.0',
                mcp_session_consumer: 'session-consumer',
                mcp_session_vendor_client: 'ClaudeCode',
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

        it('keeps MCP session cache entries on the default 7 day TTL', async () => {
            const redis = spyRedis()
            const ctx = new RequestContext(redis, env, makeProps({ mcpSessionId: 'mcp-session-1' }))

            await ctx.sessionCache.set('mcpClientName', 'claude-code')

            expect(redis.set).toHaveBeenCalledWith(
                expect.stringMatching(/^mcp:session:/),
                JSON.stringify('claude-code'),
                'EX',
                7 * 24 * 60 * 60
            )
        })

        it('keeps token cache entries on the default 7 day TTL', async () => {
            const redis = spyRedis()
            const ctx = new RequestContext(redis, env, makeProps())

            await ctx.tokenCache.set('distinctId', 'user-123')

            expect(redis.set).toHaveBeenCalledWith(
                'mcp:token:test-user:distinctId',
                JSON.stringify('user-123'),
                'EX',
                7 * 24 * 60 * 60
            )
        })
    })
})
