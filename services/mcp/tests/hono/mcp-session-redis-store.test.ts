import { beforeEach, describe, expect, it, type Mock, vi } from 'vitest'

import { McpSessionRedisStore } from '@/hono/cache/McpSessionRedisStore'
import type { RedisLike } from '@/hono/cache/RedisCache'
import type { MCPClientContext } from '@/hono/mcp-context'

import { makeRedisRateLimitStubs } from './helpers/redis-rate-limit-stubs'

interface MockRedis extends RedisLike {
    store: Map<string, string>
    eval: Mock<RedisLike['eval']>
}

function createRedis(): MockRedis {
    const store = new Map<string, string>()
    const rateLimitStubs = makeRedisRateLimitStubs(store)
    return {
        store,
        get: vi.fn(async (key: string) => store.get(key) ?? null),
        set: vi.fn(async (key: string, value: string) => {
            store.set(key, value)
            return 'OK'
        }),
        del: vi.fn(async (...keys: string[]) => keys.filter((key) => store.delete(key)).length),
        scan: vi.fn(async () => ['0', []] as [string, string[]]),
        ...rateLimitStubs,
        expire: vi.fn(rateLimitStubs.expire),
        eval: vi.fn(rateLimitStubs.eval),
    }
}

const liveContext: MCPClientContext = {
    mcpClientName: 'claude-code',
    mcpClientVersion: '1.2.3',
    mcpProtocolVersion: '2025-11-25',
    mcpConsumer: 'posthog-code',
    mcpVendorClient: 'ClaudeCode',
}

function compactKeyIn(redis: MockRedis): string {
    return [...redis.store.keys()].find((key) => key.startsWith('mcp:s:'))!
}

describe('McpSessionRedisStore', () => {
    let redis: MockRedis

    beforeEach(() => {
        redis = createRedis()
    })

    it('stores the whole context under one compacted key', async () => {
        await new McpSessionRedisStore(redis, 'session-1').resolve(liveContext)

        expect([...redis.store.keys()]).toHaveLength(1)
        expect(compactKeyIn(redis)).toMatch(/^mcp:s:[A-Za-z0-9_-]{22}:c$/)
        expect(JSON.parse(redis.store.get(compactKeyIn(redis))!)).toEqual(liveContext)
    })

    it('serves stored context back to a later request that carries none', async () => {
        const store = new McpSessionRedisStore(redis, 'session-1')
        await store.resolve(liveContext)

        expect(await store.resolve({})).toEqual(liveContext)
    })

    it('serves live context instead of throwing when the compact read fails', async () => {
        vi.mocked(redis.get).mockRejectedValue(new Error('Valkey read failed'))

        expect(await new McpSessionRedisStore(redis, 'session-1').resolve(liveContext)).toEqual(liveContext)
    })

    it('refreshes the idle TTL rather than rewriting an unchanged context', async () => {
        const store = new McpSessionRedisStore(redis, 'session-1')
        await store.resolve(liveContext)
        vi.mocked(redis.eval).mockClear()

        await store.resolve({})

        expect(redis.expire).toHaveBeenCalledWith(compactKeyIn(redis), 24 * 60 * 60)
        expect(redis.eval).not.toHaveBeenCalled()
    })

    it('persists a client field first observed after initialize', async () => {
        const store = new McpSessionRedisStore(redis, 'session-1')
        await store.resolve({ ...liveContext, mcpVendorClient: undefined })

        await store.resolve({ mcpVendorClient: 'ClaudeCode' })

        expect(JSON.parse(redis.store.get(compactKeyIn(redis))!)).toMatchObject({ mcpVendorClient: 'ClaudeCode' })
    })

    it('preserves fields added by concurrent writes', async () => {
        await Promise.all([
            new McpSessionRedisStore(redis, 'session-1').resolve({ mcpClientName: 'claude-code' }),
            new McpSessionRedisStore(redis, 'session-1').resolve({ mcpConsumer: 'posthog-code' }),
        ])

        expect(await new McpSessionRedisStore(redis, 'session-1').resolve({})).toMatchObject({
            mcpClientName: 'claude-code',
            mcpConsumer: 'posthog-code',
        })
    })
})
