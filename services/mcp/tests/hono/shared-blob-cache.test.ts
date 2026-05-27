import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { RedisLike } from '@/hono/cache/RedisCache'
import { SharedBlobCache } from '@/hono/cache/SharedBlobCache'

import { makeRedisRateLimitStubs } from './helpers/redis-rate-limit-stubs'

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

    it('fetches upstream on cold cache and writes bytes + freshness', async () => {
        const cache = new SharedBlobCache(redis, NAMESPACE)
        const bytes = new Uint8Array([1, 2, 3, 4, 5])
        const upstream = vi.fn(async () => bytes)

        const result = await cache.fetch(upstream)

        expect(result).toEqual(bytes)
        expect(upstream).toHaveBeenCalledTimes(1)
        expect(redis._store.has(BYTES_KEY)).toBe(true)
        expect(redis._store.has(FRESH_KEY)).toBe(true)
        // Lock acquired then released.
        expect(redis._store.has(LOCK_KEY)).toBe(false)
    })

    it('serves the cached bytes on fresh hit without calling upstream', async () => {
        const cache = new SharedBlobCache(redis, NAMESPACE)
        const bytes = new Uint8Array([9, 8, 7])
        await cache.fetch(async () => bytes)

        const upstream = vi.fn(async () => new Uint8Array([0]))
        const result = await cache.fetch(upstream)

        expect(result).toEqual(bytes)
        expect(upstream).not.toHaveBeenCalled()
    })

    it('isolates blobs by namespace', async () => {
        const a = new SharedBlobCache(redis, 'alpha')
        const b = new SharedBlobCache(redis, 'beta')
        await a.fetch(async () => new Uint8Array([1]))
        await b.fetch(async () => new Uint8Array([2]))

        expect(redis._store.has('mcp:shared-blob:alpha:bytes')).toBe(true)
        expect(redis._store.has('mcp:shared-blob:beta:bytes')).toBe(true)

        const upstream = vi.fn(async () => new Uint8Array([9]))
        const result = await a.fetch(upstream)
        expect(result).toEqual(new Uint8Array([1]))
        expect(upstream).not.toHaveBeenCalled()
    })

    it('only one writer fetches upstream when many clients race on cold cache', async () => {
        const cache = new SharedBlobCache(redis, NAMESPACE, { waitIntervalMs: 5, waitTimeoutMs: 200 })
        const bytes = new Uint8Array([42])
        let inFlight = 0
        let peak = 0
        const upstream = vi.fn(async () => {
            inFlight += 1
            peak = Math.max(peak, inFlight)
            await new Promise((r) => setTimeout(r, 20))
            inFlight -= 1
            return bytes
        })

        const concurrency = 5
        const results = await Promise.all(Array.from({ length: concurrency }, () => cache.fetch(upstream)))

        expect(results.every((r) => r.toString() === bytes.toString())).toBe(true)
        expect(peak).toBe(1)
        // Exactly one writer fetched upstream. Non-writers either waited for the
        // cache to publish or fell back to a direct fetch (with no cache write).
        expect(upstream.mock.calls.length).toBeGreaterThanOrEqual(1)
    })

    it('non-writers wait for the lock holder to publish and serve that result', async () => {
        const cache = new SharedBlobCache(redis, NAMESPACE, { waitIntervalMs: 5, waitTimeoutMs: 1000 })
        const bytes = new Uint8Array([55, 56])
        let resolveUpstream: ((b: Uint8Array) => void) | undefined
        const upstreamPromise = new Promise<Uint8Array>((resolve) => {
            resolveUpstream = resolve
        })
        const writerUpstream = vi.fn(() => upstreamPromise)
        const waiterUpstream = vi.fn(async () => new Uint8Array([99]))

        // First call wins the lock and stalls in upstream.
        const writerResult = cache.fetch(writerUpstream)
        // Give the writer time to seize the lock before the waiter starts.
        await new Promise((r) => setTimeout(r, 10))
        const waiterResult = cache.fetch(waiterUpstream)

        // Publish the upstream after both calls are in flight.
        await new Promise((r) => setTimeout(r, 30))
        resolveUpstream!(bytes)

        const [w, r] = await Promise.all([writerResult, waiterResult])
        expect(w).toEqual(bytes)
        expect(r).toEqual(bytes)
        // The waiter must not have written its own value upstream.
        expect(waiterUpstream).not.toHaveBeenCalled()
    })

    it('serves stale cache while triggering a background refresh', async () => {
        // freshSeconds = 0 forces stale on read; waitTimeoutMs tightened to keep
        // the test fast in case anything goes sideways.
        const cache = new SharedBlobCache(redis, NAMESPACE, {
            freshSeconds: 0,
            waitIntervalMs: 5,
            waitTimeoutMs: 100,
        })

        const initial = new Uint8Array([1, 1])
        const refreshed = new Uint8Array([2, 2])
        let upstreamCalls = 0
        const upstream = vi.fn(async () => {
            upstreamCalls += 1
            return upstreamCalls === 1 ? initial : refreshed
        })

        // Seed the cache (writes initial and immediately marks it stale).
        const first = await cache.fetch(upstream)
        expect(first).toEqual(initial)
        expect(upstream).toHaveBeenCalledTimes(1)

        // Stale read returns the cached value, kicks off a background refresh.
        const second = await cache.fetch(upstream)
        expect(second).toEqual(initial)

        // Allow the background refresh to settle.
        await new Promise((r) => setTimeout(r, 30))

        expect(upstream).toHaveBeenCalledTimes(2)
        // After refresh, the cache reflects the new bytes.
        const third = await cache.fetch(upstream)
        expect(third).toEqual(refreshed)
    })

    it('falls back to a direct fetch when the writer never publishes', async () => {
        // Lock is pre-held by another writer that we simulate as stuck.
        redis._store.set(LOCK_KEY, 'someone-else')
        const cache = new SharedBlobCache(redis, NAMESPACE, { waitIntervalMs: 10, waitTimeoutMs: 50 })

        const fallback = new Uint8Array([7])
        const upstream = vi.fn(async () => fallback)
        const result = await cache.fetch(upstream)

        expect(result).toEqual(fallback)
        // Fallback must not write the cache — that's reserved for the lock holder.
        expect(redis._store.has(BYTES_KEY)).toBe(false)
    })
})
