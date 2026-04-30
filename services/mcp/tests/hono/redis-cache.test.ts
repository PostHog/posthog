import { beforeEach, describe, expect, it, vi } from 'vitest'

import { RedisCache, type RedisLike } from '@/hono/cache/RedisCache'

type TestState = {
    region: string | undefined
    projectId: string | undefined
    distinctId: string | undefined
    orgId: string | undefined
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
            expect(mockRedis.get).toHaveBeenCalledWith('mcp:user:test-user-hash:region')
        })

        it('should return parsed JSON values', async () => {
            mockRedis._store.set('mcp:user:test-user-hash:region', '"us"')
            expect(await cache.get('region')).toBe('us')
        })

        it('should not read another user keys', async () => {
            const cacheA = new RedisCache<TestState>('user-a', mockRedis)
            const cacheB = new RedisCache<TestState>('user-b', mockRedis)
            mockRedis._store.set('mcp:user:user-a:region', '"us"')
            mockRedis._store.set('mcp:user:user-b:region', '"eu"')

            expect(await cacheA.get('region')).toBe('us')
            expect(await cacheB.get('region')).toBe('eu')
        })
    })

    describe('set', () => {
        it('should store string values with scoped key', async () => {
            await cache.set('region', 'eu')
            // 7-day default TTL (see DEFAULT_TTL_SECONDS in RedisCache.ts).
            expect(mockRedis.set).toHaveBeenCalledWith('mcp:user:test-user-hash:region', 'eu', 'EX', 7 * 24 * 60 * 60)
        })

        it('should isolate different users', async () => {
            const cacheA = new RedisCache<TestState>('user-a', mockRedis)
            const cacheB = new RedisCache<TestState>('user-b', mockRedis)
            await cacheA.set('projectId', '111')
            await cacheB.set('projectId', '222')

            expect(mockRedis._store.get('mcp:user:user-a:projectId')).toBe('111')
            expect(mockRedis._store.get('mcp:user:user-b:projectId')).toBe('222')
        })
    })

    describe('delete', () => {
        it('should only delete the targeted user key', async () => {
            mockRedis._store.set('mcp:user:test-user-hash:region', '"us"')
            mockRedis._store.set('mcp:user:other-user:region', '"eu"')
            await cache.delete('region')
            expect(mockRedis._store.has('mcp:user:other-user:region')).toBe(true)
        })
    })

    describe('clear', () => {
        it('should only clear keys for the scoped user', async () => {
            mockRedis._store.set('mcp:user:test-user-hash:region', '"us"')
            mockRedis._store.set('mcp:user:test-user-hash:projectId', '"123"')
            mockRedis._store.set('mcp:user:other-user:region', '"eu"')

            await cache.clear()

            expect(mockRedis.del).toHaveBeenCalledWith(
                'mcp:user:test-user-hash:region',
                'mcp:user:test-user-hash:projectId'
            )
            expect(mockRedis._store.has('mcp:user:other-user:region')).toBe(true)
        })
    })
})
