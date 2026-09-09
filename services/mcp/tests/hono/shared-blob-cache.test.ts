import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { RedisLike } from '@/hono/cache/RedisCache'
import { SharedBlobCache, type SharedBlobCacheOptions } from '@/hono/cache/SharedBlobCache'

import { makeRedisRateLimitStubs } from './helpers/redis-rate-limit-stubs'
import { makeSharedBlobRedisStubs } from './helpers/shared-blob-redis-stubs'

class TestSharedBlobCache extends SharedBlobCache {
    constructor(redis: RedisLike, namespace: string, opts?: SharedBlobCacheOptions) {
        super(redis, namespace, opts)
    }

    read(): Promise<{ bytes: Uint8Array; fresh: boolean } | null> {
        return this.readCache()
    }

    async write(bytes: Uint8Array, validator?: string): Promise<void> {
        await this.writeCache(bytes, validator)
    }

    acquire(token: string): Promise<boolean> {
        return this.acquireLock(token)
    }

    release(token: string): Promise<void> {
        return this.releaseLock(token)
    }

    wait(): Promise<Uint8Array | null> {
        return this.waitForCache()
    }
}

interface MockRedis extends RedisLike {
    _store: Map<string, string>
    _setCalls: Array<{ key: string; value: string; args: (string | number)[] }>
}

function createMockRedis(): MockRedis {
    const store = new Map<string, string>()
    const setCalls: Array<{ key: string; value: string; args: (string | number)[] }> = []
    return {
        get: vi.fn(async (key: string) => store.get(key) ?? null),
        set: vi.fn(async (key: string, value: string, ...args: (string | number)[]) => {
            setCalls.push({ key, value, args })
            const isNx = args.includes('NX')
            if (isNx && store.has(key)) {
                return null
            }
            store.set(key, value)
            return 'OK'
        }),
        del: vi.fn(async (...keys: string[]) => {
            let count = 0
            for (const k of keys) {
                if (store.delete(k)) {
                    count++
                }
            }
            return count
        }),
        scan: vi.fn(async () => ['0', []] as [string, string[]]),
        ...makeRedisRateLimitStubs(),
        ...makeSharedBlobRedisStubs(store),
        _store: store,
        _setCalls: setCalls,
    }
}

const NAMESPACE = 'test-blob'
const CURRENT_KEY = `mcp:shared-blob:${NAMESPACE}:v2:current`
const LOCK_KEY = `mcp:shared-blob:${NAMESPACE}:v2:lock`

describe('SharedBlobCache', () => {
    let redis: MockRedis

    beforeEach(() => {
        redis = createMockRedis()
    })

    it('writes bytes + freshness and reads them back', async () => {
        const bytes = new Uint8Array([1, 2, 3, 4, 5])
        const cache = new TestSharedBlobCache(redis, NAMESPACE)

        await cache.write(bytes)
        const cached = await cache.read()

        expect(cached).toMatchObject({ bytes, fresh: true })
        expect(redis._store.has(CURRENT_KEY)).toBe(true)
    })

    it.each(['blob', 'pointer'])('keeps the previous generation when the %s write fails', async (failure) => {
        const cache = new TestSharedBlobCache(redis, NAMESPACE)
        const original = new Uint8Array([4, 5, 6])
        await cache.write(original, 'etag-old')
        const pointer = redis._store.get(CURRENT_KEY)
        redis.set = vi.fn(async (key: string, ...rest: (string | number)[]) => {
            if (failure === 'blob' ? key.includes(':blob:') : key === CURRENT_KEY) {
                throw new Error('write failed')
            }
            redis._store.set(key, String(rest[0]))
            return 'OK'
        })
        await expect(cache.write(new Uint8Array([1, 2, 3]), 'etag-new')).rejects.toThrow('write failed')
        expect(redis._store.get(CURRENT_KEY)).toBe(pointer)
        expect(await cache.read()).toMatchObject({ bytes: original, etag: 'etag-old' })
    })

    it('marks cached bytes stale after the freshness window', async () => {
        const cache = new TestSharedBlobCache(redis, NAMESPACE, { freshSeconds: 0 })
        await cache.write(new Uint8Array([9, 8, 7]))

        const cached = await cache.read()

        expect(cached?.bytes).toEqual(new Uint8Array([9, 8, 7]))
        expect(cached?.fresh).toBe(false)
    })

    it('isolates blobs by namespace', async () => {
        const a = new TestSharedBlobCache(redis, 'alpha')
        const b = new TestSharedBlobCache(redis, 'beta')
        await a.write(new Uint8Array([1]))
        await b.write(new Uint8Array([2]))

        expect(redis._store.has(a.currentKey)).toBe(true)
        expect(redis._store.has(b.currentKey)).toBe(true)

        expect((await a.read())?.bytes).toEqual(new Uint8Array([1]))
        expect((await b.read())?.bytes).toEqual(new Uint8Array([2]))
    })

    it('allows only one lock holder', async () => {
        const cache = new TestSharedBlobCache(redis, NAMESPACE)

        expect(await cache.acquire('first')).toBe(true)
        expect(await cache.acquire('second')).toBe(false)

        expect(redis._store.get(LOCK_KEY)).toBe('first')
    })

    it.each([false, true])('releases only its own lock (replaced: %s)', async (replaced) => {
        const cache = new TestSharedBlobCache(redis, NAMESPACE)

        await cache.acquire('token')
        if (replaced) {
            redis._store.set(LOCK_KEY, 'next-writer')
        }
        await cache.release('token')

        expect(redis._store.get(LOCK_KEY)).toBe(replaced ? 'next-writer' : undefined)
    })

    it('waits for another writer to publish', async () => {
        const cache = new TestSharedBlobCache(redis, NAMESPACE, { waitIntervalMs: 5, waitTimeoutMs: 200 })
        const bytes = new Uint8Array([55, 56])

        const waited = cache.wait()
        await new Promise((r) => setTimeout(r, 20))
        await cache.write(bytes)

        expect(await waited).toEqual(bytes)
    })

    it('times out while waiting for another writer', async () => {
        const cache = new TestSharedBlobCache(redis, NAMESPACE, { waitIntervalMs: 10, waitTimeoutMs: 50 })

        expect(await cache.wait()).toBeNull()
    })
})
