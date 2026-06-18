import { beforeEach, describe, expect, it, vi } from 'vitest'

import { RedisCache, type RedisLike } from '@/hono/cache/RedisCache'

import { makeRedisRateLimitStubs } from './helpers/redis-rate-limit-stubs'

type TestState = {
    region: string | undefined
    projectId: string | undefined
    distinctId: string | undefined
    orgId: string | undefined
    mcpClientName: string | undefined
    mcpClientVersion: string | undefined
    mcpProtocolVersion: string | undefined
}

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
        del: vi.fn(async (...keys: string[]) => {
            let count = 0
            for (const key of keys) {
                if (store.delete(key)) {
                    count++
                }
            }
            return count
        }),
        scan: vi.fn(async (_cursor: string, _match: string, pattern: string) => {
            const matching = Array.from(store.keys()).filter((k) => {
                const regex = new RegExp('^' + pattern.replace(/\*/g, '.*') + '$')
                return regex.test(k)
            })
            return ['0', matching] as [string, string[]]
        }),
        ...makeRedisRateLimitStubs(),
        _store: store,
    }
}

describe('RedisCache', () => {
    let mockRedis: MockRedis
    let cache: RedisCache<TestState>

    beforeEach(() => {
        mockRedis = createMockRedis()
        cache = new RedisCache<TestState>('test-user-hash', mockRedis)
    })

    describe('get', () => {
        it('should return undefined for missing keys', async () => {
            const result = await cache.get('region')
            expect(result).toBeUndefined()
            expect(mockRedis.get).toHaveBeenCalledWith('mcp:token:test-user-hash:region')
        })

        it('should return parsed JSON values', async () => {
            mockRedis._store.set('mcp:token:test-user-hash:region', '"us"')
            expect(await cache.get('region')).toBe('us')
        })

        it('should not read another user keys', async () => {
            const cacheA = new RedisCache<TestState>('user-a', mockRedis)
            const cacheB = new RedisCache<TestState>('user-b', mockRedis)
            mockRedis._store.set('mcp:token:user-a:region', '"us"')
            mockRedis._store.set('mcp:token:user-b:region', '"eu"')

            expect(await cacheA.get('region')).toBe('us')
            expect(await cacheB.get('region')).toBe('eu')
        })
    })

    describe('set', () => {
        it('should store JSON-serialized values with scoped key', async () => {
            await cache.set('region', 'eu')
            expect(mockRedis.set).toHaveBeenCalledWith('mcp:token:test-user-hash:region', '"eu"', 'EX', 7 * 24 * 60 * 60)
        })

        it('should isolate different users', async () => {
            const cacheA = new RedisCache<TestState>('user-a', mockRedis)
            const cacheB = new RedisCache<TestState>('user-b', mockRedis)
            await cacheA.set('projectId', '111')
            await cacheB.set('projectId', '222')

            expect(mockRedis._store.get('mcp:token:user-a:projectId')).toBe('"111"')
            expect(mockRedis._store.get('mcp:token:user-b:projectId')).toBe('"222"')
        })
    })

    describe('delete', () => {
        it('should only delete the targeted user key', async () => {
            mockRedis._store.set('mcp:token:test-user-hash:region', '"us"')
            mockRedis._store.set('mcp:token:other-user:region', '"eu"')
            await cache.delete('region')
            expect(mockRedis._store.has('mcp:token:other-user:region')).toBe(true)
        })
    })

    describe('setMany', () => {
        it('should set multiple keys in a single call', async () => {
            await cache.setMany({ region: 'us', projectId: '123' })

            expect(await cache.get('region')).toBe('us')
            expect(await cache.get('projectId')).toBe('123')
            expect(mockRedis.set).toHaveBeenCalledTimes(2)
        })

        it('should skip undefined values', async () => {
            await cache.setMany({ region: 'eu', projectId: undefined })

            expect(await cache.get('region')).toBe('eu')
            expect(await cache.get('projectId')).toBeUndefined()
            expect(mockRedis.set).toHaveBeenCalledTimes(1)
        })

        it('should handle empty entries', async () => {
            await cache.setMany({})
            expect(mockRedis.set).not.toHaveBeenCalled()
        })
    })

    describe('client info caching across requests', () => {
        it('seeds client info on initialize and reads it back on subsequent requests', async () => {
            await cache.setMany({
                mcpClientName: 'claude-code',
                mcpClientVersion: '1.2.3',
                mcpProtocolVersion: '2025-03-26',
            })

            expect(await cache.get('mcpClientName')).toBe('claude-code')
            expect(await cache.get('mcpClientVersion')).toBe('1.2.3')
            expect(await cache.get('mcpProtocolVersion')).toBe('2025-03-26')
        })

        it('does not overwrite cached client info when subsequent request has no client info', async () => {
            await cache.setMany({ mcpClientName: 'claude-code' })
            await cache.setMany({})

            expect(await cache.get('mcpClientName')).toBe('claude-code')
        })
    })

    describe('clear', () => {
        it('should only clear keys for the scoped user', async () => {
            mockRedis._store.set('mcp:token:test-user-hash:region', '"us"')
            mockRedis._store.set('mcp:token:test-user-hash:projectId', '"123"')
            mockRedis._store.set('mcp:token:other-user:region', '"eu"')

            await cache.clear()

            expect(mockRedis.del).toHaveBeenCalledWith(
                'mcp:token:test-user-hash:region',
                'mcp:token:test-user-hash:projectId'
            )
            expect(mockRedis._store.has('mcp:token:other-user:region')).toBe(true)
        })
    })
})
