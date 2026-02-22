import { beforeEach, describe, expect, it, vi } from 'vitest'

import { RedisCache } from '@/hono/cache/RedisCache'

type TestState = {
    region: string | undefined
    projectId: string | undefined
    distinctId: string | undefined
}

// eslint-disable-next-line @typescript-eslint/explicit-function-return-type
function createMockRedis() {
    const store = new Map<string, string>()
    const ttls = new Map<string, number>()

    return {
        get: vi.fn(async (key: string) => store.get(key) ?? null),
        set: vi.fn(async (key: string, value: string, _ex?: string, ttl?: number) => {
            store.set(key, value)
            if (ttl) {
                ttls.set(key, ttl)
            }
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
            return ['0', matching]
        }),
        _store: store,
        _ttls: ttls,
    }
}

describe('RedisCache', () => {
    let mockRedis: ReturnType<typeof createMockRedis>
    let cache: RedisCache<TestState>

    beforeEach(() => {
        mockRedis = createMockRedis()
        cache = new RedisCache<TestState>('test-user-hash', mockRedis as any)
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
    })

    describe('set', () => {
        it('should store string values', async () => {
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
            const customCache = new RedisCache<TestState>('user2', mockRedis as any, 3600)
            await customCache.set('region', 'us')
            expect(mockRedis.set).toHaveBeenCalledWith('mcp:user:user2:region', 'us', 'EX', 3600)
        })
    })

    describe('delete', () => {
        it('should delete the key', async () => {
            await cache.delete('region')
            expect(mockRedis.del).toHaveBeenCalledWith('mcp:user:test-user-hash:region')
        })
    })

    describe('clear', () => {
        it('should delete all scoped keys using SCAN', async () => {
            mockRedis._store.set('mcp:user:test-user-hash:region', '"us"')
            mockRedis._store.set('mcp:user:test-user-hash:projectId', '"123"')
            mockRedis._store.set('mcp:user:other-user:region', '"eu"')

            await cache.clear()

            expect(mockRedis.scan).toHaveBeenCalledWith('0', 'MATCH', 'mcp:user:test-user-hash:*', 'COUNT', 100)
        })
    })

    describe('key scoping', () => {
        it('should isolate different users', async () => {
            const cache1 = new RedisCache<TestState>('user-a', mockRedis as any)
            const cache2 = new RedisCache<TestState>('user-b', mockRedis as any)

            await cache1.set('region', 'us')
            await cache2.set('region', 'eu')

            expect(mockRedis._store.get('mcp:user:user-a:region')).toBe('us')
            expect(mockRedis._store.get('mcp:user:user-b:region')).toBe('eu')
        })
    })
})
