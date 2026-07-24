import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { RedisLike } from '@/hono/cache/RedisCache'
import { SharedBlobCache, type SharedBlobCacheOptions } from '@/hono/cache/SharedBlobCache'

import { makeRedisRateLimitStubs } from './helpers/redis-rate-limit-stubs'

class TestSharedBlobCache extends SharedBlobCache {
    constructor(redis: RedisLike, namespace: string, opts?: SharedBlobCacheOptions) {
        super(redis, namespace, opts)
    }

    read(): Promise<{ bytes: Uint8Array; fresh: boolean } | null> {
        return this.readCache()
    }

    write(bytes: Uint8Array): Promise<void> {
        return this.writeCache(bytes)
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
        _store: store,
        _setCalls: setCalls,
    }
}

const NAMESPACE = 'test-blob'
const BYTES_KEY = `mcp:shared-blob:${NAMESPACE}:bytes`
const FRESH_KEY = `mcp:shared-blob:${NAMESPACE}:fresh`
const LOCK_KEY = `mcp:shared-blob:${NAMESPACE}:lock`

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

        expect(cached).toEqual({ bytes, fresh: true })
        expect(redis._store.has(BYTES_KEY)).toBe(true)
        expect(redis._store.has(FRESH_KEY)).toBe(true)
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

        expect(redis._store.has('mcp:shared-blob:alpha:bytes')).toBe(true)
        expect(redis._store.has('mcp:shared-blob:beta:bytes')).toBe(true)

        expect((await a.read())?.bytes).toEqual(new Uint8Array([1]))
        expect((await b.read())?.bytes).toEqual(new Uint8Array([2]))
    })

    it('allows only one lock holder', async () => {
        const cache = new TestSharedBlobCache(redis, NAMESPACE)

        expect(await cache.acquire('first')).toBe(true)
        expect(await cache.acquire('second')).toBe(false)

        expect(redis._store.get(LOCK_KEY)).toBe('first')
    })

    it('releases the lock', async () => {
        const cache = new TestSharedBlobCache(redis, NAMESPACE)

        await cache.acquire('token')
        await cache.release('token')

        expect(redis._store.has(LOCK_KEY)).toBe(false)
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
