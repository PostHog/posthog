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
    _ttls: Map<string, number>
}

function createMockRedis(): MockRedis {
    const store = new Map<string, string>()
    const ttls = new Map<string, number>()

    return {
        get: vi.fn(async (key: string) => store.get(key) ?? null),
        set: vi.fn(async (key: string, value: string, _ex: string, ttl: number) => {
            store.set(key, value)
            ttls.set(key, ttl)
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
        _ttls: ttls,
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
            const result = await cache.get('region')
            expect(result).toBe('us')
        })

        it('should return raw string if JSON parse fails', async () => {
            mockRedis._store.set('mcp:user:test-user-hash:projectId', 'raw-value')
            const result = await cache.get('projectId')
            expect(result).toBe('raw-value')
        })

        it('should scope get to the user hash', async () => {
            mockRedis._store.set('mcp:user:other-user:region', '"eu"')
            const result = await cache.get('region')
            expect(result).toBeUndefined()
            expect(mockRedis.get).toHaveBeenCalledWith('mcp:user:test-user-hash:region')
        })

        it('should not read another user keys', async () => {
            const cacheA = new RedisCache<TestState>('user-a', mockRedis)
            const cacheB = new RedisCache<TestState>('user-b', mockRedis)
            mockRedis._store.set('mcp:user:user-a:region', '"us"')
            mockRedis._store.set('mcp:user:user-b:region', '"eu"')

            expect(await cacheA.get('region')).toBe('us')
            expect(await cacheB.get('region')).toBe('eu')
            expect(mockRedis.get).toHaveBeenCalledWith('mcp:user:user-a:region')
            expect(mockRedis.get).toHaveBeenCalledWith('mcp:user:user-b:region')
        })
    })

    describe('set', () => {
        it('should store string values with scoped key', async () => {
            await cache.set('region', 'eu')
            expect(mockRedis.set).toHaveBeenCalledWith('mcp:user:test-user-hash:region', 'eu', 'EX', 86400)
        })

        it('should handle undefined values', async () => {
            await cache.set('region', undefined)
            expect(mockRedis.set).toHaveBeenCalledWith(
                'mcp:user:test-user-hash:region',
                undefined,
                'EX',
                86400
            )
        })

        it('should use custom TTL when specified', async () => {
            const customCache = new RedisCache<TestState>('user2', mockRedis, 3600)
            await customCache.set('region', 'us')
            expect(mockRedis.set).toHaveBeenCalledWith('mcp:user:user2:region', 'us', 'EX', 3600)
        })

        it('should scope set to the user hash', async () => {
            const cacheA = new RedisCache<TestState>('user-a', mockRedis)
            const cacheB = new RedisCache<TestState>('user-b', mockRedis)
            await cacheA.set('projectId', '111')
            await cacheB.set('projectId', '222')

            expect(mockRedis._store.get('mcp:user:user-a:projectId')).toBe('111')
            expect(mockRedis._store.get('mcp:user:user-b:projectId')).toBe('222')
        })
    })

    describe('delete', () => {
        it('should delete the scoped key', async () => {
            await cache.delete('region')
            expect(mockRedis.del).toHaveBeenCalledWith('mcp:user:test-user-hash:region')
        })

        it('should only delete the targeted user key', async () => {
            mockRedis._store.set('mcp:user:test-user-hash:region', '"us"')
            mockRedis._store.set('mcp:user:other-user:region', '"eu"')
            await cache.delete('region')
            expect(mockRedis.del).toHaveBeenCalledWith('mcp:user:test-user-hash:region')
            expect(mockRedis._store.has('mcp:user:other-user:region')).toBe(true)
        })
    })

    describe('clear', () => {
        it('should scan with the correct user-scoped pattern', async () => {
            await cache.clear()
            expect(mockRedis.scan).toHaveBeenCalledWith('0', 'MATCH', 'mcp:user:test-user-hash:*', 'COUNT', 100)
        })

        it('should only clear keys for the scoped user', async () => {
            mockRedis._store.set('mcp:user:test-user-hash:region', '"us"')
            mockRedis._store.set('mcp:user:test-user-hash:projectId', '"123"')
            mockRedis._store.set('mcp:user:other-user:region', '"eu"')
            mockRedis._store.set('mcp:user:other-user:projectId', '"456"')

            await cache.clear()

            expect(mockRedis.del).toHaveBeenCalledWith(
                'mcp:user:test-user-hash:region',
                'mcp:user:test-user-hash:projectId'
            )
            expect(mockRedis._store.has('mcp:user:other-user:region')).toBe(true)
            expect(mockRedis._store.has('mcp:user:other-user:projectId')).toBe(true)
        })

        it('should not delete anything when no scoped keys exist', async () => {
            mockRedis._store.set('mcp:user:other-user:region', '"eu"')
            await cache.clear()
            expect(mockRedis.del).not.toHaveBeenCalled()
        })
    })

    describe('key scoping', () => {
        it('should use the mcp:user:{hash}:{key} format for all operations', async () => {
            await cache.set('region', 'us')
            await cache.get('region')
            await cache.delete('region')

            expect(mockRedis.set).toHaveBeenCalledWith('mcp:user:test-user-hash:region', 'us', 'EX', 86400)
            expect(mockRedis.get).toHaveBeenCalledWith('mcp:user:test-user-hash:region')
            expect(mockRedis.del).toHaveBeenCalledWith('mcp:user:test-user-hash:region')
        })

        it('should completely isolate different users across all operations', async () => {
            const cacheA = new RedisCache<TestState>('user-a', mockRedis)
            const cacheB = new RedisCache<TestState>('user-b', mockRedis)

            await cacheA.set('region', 'us')
            await cacheA.set('orgId', 'org-1')
            await cacheB.set('region', 'eu')
            await cacheB.set('orgId', 'org-2')

            expect(await cacheA.get('region')).toBe('us')
            expect(await cacheB.get('region')).toBe('eu')
            expect(await cacheA.get('orgId')).toBe('org-1')
            expect(await cacheB.get('orgId')).toBe('org-2')

            await cacheA.delete('region')
            expect(mockRedis._store.has('mcp:user:user-a:region')).toBe(false)
            expect(mockRedis._store.has('mcp:user:user-b:region')).toBe(true)
        })
    })
})
