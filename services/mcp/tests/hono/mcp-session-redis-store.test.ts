import { beforeEach, describe, expect, it, vi } from 'vitest'

import { McpSessionRedisStore } from '@/hono/cache/McpSessionRedisStore'
import type { RedisLike } from '@/hono/cache/RedisCache'
import type { MCPClientContext } from '@/hono/mcp-context'
import { hash } from '@/lib/utils'

import { makeRedisRateLimitStubs } from './helpers/redis-rate-limit-stubs'

interface MockRedis extends RedisLike {
    store: Map<string, string>
    eval: ReturnType<typeof vi.fn>
}

function createRedis(): MockRedis {
    const store = new Map<string, string>()
    const rateLimitStubs = makeRedisRateLimitStubs()
    return {
        store,
        get: vi.fn(async (key: string) => store.get(key) ?? null),
        set: vi.fn(async (key: string, value: string) => {
            store.set(key, value)
            return 'OK'
        }),
        eval: vi.fn(
            async (_script: string, _numberOfKeys: number, key: string, cachedRaw: string, desiredRaw: string) => {
                const current = JSON.parse(store.get(key) ?? '{}') as Record<string, string>
                const cached = cachedRaw === '' ? null : (JSON.parse(cachedRaw) as Record<string, string>)
                const desired = JSON.parse(desiredRaw) as Record<string, string>
                for (const [field, value] of Object.entries(desired)) {
                    if (current[field] === undefined || (cached !== null && current[field] === cached[field])) {
                        current[field] = value
                    }
                }
                store.set(key, JSON.stringify(current))
                return 1
            }
        ),
        del: vi.fn(async (...keys: string[]) => keys.filter((key) => store.delete(key)).length),
        scan: vi.fn(async () => ['0', []] as [string, string[]]),
        ...rateLimitStubs,
        expire: vi.fn(rateLimitStubs.expire),
    }
}

const liveContext: MCPClientContext = {
    mcpClientName: 'claude-code',
    mcpClientVersion: '1.2.3',
    mcpProtocolVersion: '2025-11-25',
    mcpConsumer: 'posthog-code',
    mcpVendorClient: 'ClaudeCode',
}

describe('McpSessionRedisStore', () => {
    beforeEach(() => {
        delete process.env.MCP_SESSION_CACHE_V2_READ_ALL
        delete process.env.MCP_SESSION_CACHE_V2_READ_PROJECT_IDS
    })

    it('dual-writes the legacy keys and one compact context key', async () => {
        const redis = createRedis()

        await new McpSessionRedisStore(redis, 'session-1').resolve(liveContext, '1')

        const keys = [...redis.store.keys()]
        expect(keys.filter((key) => key.startsWith('mcp:session:'))).toHaveLength(5)
        expect(keys.filter((key) => key.startsWith('mcp:s:'))).toHaveLength(1)
        expect(keys.find((key) => key.startsWith('mcp:s:'))).toMatch(/^mcp:s:[A-Za-z0-9_-]{22}:c$/)
        expect(JSON.parse(redis.store.get(keys.find((key) => key.startsWith('mcp:s:'))!)!)).toEqual(liveContext)
    })

    it('reads legacy keys written with the existing session hash', async () => {
        const redis = createRedis()
        redis.store.set(`mcp:session:${hash('session-1')}:mcpClientName`, JSON.stringify('legacy-client'))

        expect((await new McpSessionRedisStore(redis, 'session-1').resolve({}, '1')).mcpClientName).toBe(
            'legacy-client'
        )
    })

    it('keeps legacy state authoritative until the project is enabled', async () => {
        const redis = createRedis()
        const store = new McpSessionRedisStore(redis, 'session-1')
        await store.resolve(liveContext, '1')
        const compactKey = [...redis.store.keys()].find((key) => key.startsWith('mcp:s:'))!
        redis.store.set(compactKey, JSON.stringify({ ...liveContext, mcpClientName: 'compact-client' }))

        expect((await store.resolve({}, '1')).mcpClientName).toBe('claude-code')

        redis.store.set(compactKey, JSON.stringify({ ...liveContext, mcpClientName: 'compact-client' }))
        process.env.MCP_SESSION_CACHE_V2_READ_PROJECT_IDS = '1,2'
        expect((await store.resolve({}, '1')).mcpClientName).toBe('compact-client')
    })

    it('falls back to legacy state when compact reads fail after cutover', async () => {
        const redis = createRedis()
        const store = new McpSessionRedisStore(redis, 'session-1')
        await store.resolve(liveContext, '1')
        process.env.MCP_SESSION_CACHE_V2_READ_ALL = 'true'
        vi.mocked(redis.get).mockImplementation(async (key: string) => {
            if (key.startsWith('mcp:s:')) {
                throw new Error('Valkey read failed')
            }
            return redis.store.get(key) ?? null
        })

        expect((await store.resolve({}, '1')).mcpClientName).toBe('claude-code')
    })

    it('refreshes the compact idle TTL without extending legacy keys', async () => {
        const redis = createRedis()
        const store = new McpSessionRedisStore(redis, 'session-1')
        await store.resolve(liveContext, '1')
        vi.mocked(redis.set).mockClear()

        await store.resolve({}, '1')

        const compactKey = [...redis.store.keys()].find((key) => key.startsWith('mcp:s:'))!
        expect(redis.expire).toHaveBeenCalledWith(compactKey, 24 * 60 * 60)
        expect(redis.set).not.toHaveBeenCalled()
    })

    it('adds client context first observed after initialize to both schemas', async () => {
        const redis = createRedis()
        const store = new McpSessionRedisStore(redis, 'session-1')
        await store.resolve({ ...liveContext, mcpVendorClient: undefined }, '1')

        await store.resolve({ mcpVendorClient: 'ClaudeCode' }, '1')

        const compactKey = [...redis.store.keys()].find((key) => key.startsWith('mcp:s:'))!
        expect(JSON.parse(redis.store.get(compactKey)!)).toMatchObject({ mcpVendorClient: 'ClaudeCode' })
        expect([...redis.store.entries()]).toContainEqual([
            expect.stringMatching(/^mcp:session:.*:mcpVendorClient$/),
            JSON.stringify('ClaudeCode'),
        ])
    })

    it('preserves fields added by concurrent compact writes', async () => {
        const redis = createRedis()
        const first = new McpSessionRedisStore(redis, 'session-1').resolve({ mcpClientName: 'claude-code' }, '1')
        const second = new McpSessionRedisStore(redis, 'session-1').resolve({ mcpConsumer: 'posthog-code' }, '1')

        await Promise.all([first, second])

        process.env.MCP_SESSION_CACHE_V2_READ_ALL = 'true'
        expect(await new McpSessionRedisStore(redis, 'session-1').resolve({}, '1')).toMatchObject({
            mcpClientName: 'claude-code',
            mcpConsumer: 'posthog-code',
        })
    })

    it('starts compact and legacy reads in parallel', async () => {
        const redis = createRedis()
        let releaseLegacyReads: (() => void) | undefined
        const legacyReads = new Promise<void>((resolve) => {
            releaseLegacyReads = resolve
        })
        vi.mocked(redis.get).mockImplementation(async (key: string) => {
            if (key.startsWith('mcp:session:')) {
                await legacyReads
            }
            return null
        })

        const resolution = new McpSessionRedisStore(redis, 'session-1').resolve(liveContext, '1')
        await vi.waitFor(() => {
            expect(redis.get).toHaveBeenCalledWith(expect.stringMatching(/^mcp:s:/))
        })
        releaseLegacyReads?.()
        await resolution
    })
})
