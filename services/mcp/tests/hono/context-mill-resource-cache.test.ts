import { createHash } from 'node:crypto'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { mockBodyReadsInc, mockCacheEventsInc } = vi.hoisted(() => ({
    mockBodyReadsInc: vi.fn(),
    mockCacheEventsInc: vi.fn(),
}))

vi.mock('@/hono/metrics', () => ({
    contextMillBodyReadsTotal: { inc: mockBodyReadsInc },
    contextMillCacheEventsTotal: { inc: mockCacheEventsInc },
}))

import { ContextMillResourceCache, type ContextMillResourceCacheOptions } from '@/hono/cache/ContextMillResourceCache'
import type { RedisLike } from '@/hono/cache/RedisCache'
import type { ContextMillResource } from '@/resources/manifest-types'

import { makeRedisRateLimitStubs } from './helpers/redis-rate-limit-stubs'

type EntryLoader = () => Promise<ContextMillResource[]>

class TestContextMillResourceCache extends ContextMillResourceCache {
    constructor(
        redis: RedisLike,
        private loader: EntryLoader,
        opts?: ContextMillResourceCacheOptions
    ) {
        super(redis, opts)
    }

    setLoader(loader: EntryLoader): void {
        this.loader = loader
    }

    protected override loadEntries(): Promise<ContextMillResource[]> {
        return this.loader()
    }
}

interface MockRedis extends RedisLike {
    _store: Map<string, string>
    _setCalls: string[]
}

function createMockRedis(): MockRedis {
    const store = new Map<string, string>()
    const setCalls: string[] = []
    return {
        get: vi.fn(async (key: string) => store.get(key) ?? null),
        set: vi.fn(async (key: string, value: string, ...args: (string | number)[]) => {
            setCalls.push(key)
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

const MANIFEST_BYTES_KEY = 'mcp:shared-blob:context-mill:manifest:bytes'
const MANIFEST_FRESH_KEY = 'mcp:shared-blob:context-mill:manifest:fresh'
const MANIFEST_LOCK_KEY = 'mcp:shared-blob:context-mill:manifest:lock'

function bodyKey(uri: string): string {
    const hash = createHash('sha256').update(uri).digest('hex')
    return `mcp:shared-blob:context-mill:body:${hash}`
}

function makeEntry(suffix: string, text?: string): ContextMillResource {
    return {
        id: `entry-${suffix}`,
        name: `name-${suffix}`,
        uri: `posthog://skill/${suffix}`,
        resource: {
            mimeType: 'text/markdown',
            description: `desc-${suffix}`,
            text: text ?? `# body ${suffix}`,
        },
    }
}

describe('ContextMillResourceCache', () => {
    let redis: MockRedis

    beforeEach(() => {
        mockBodyReadsInc.mockClear()
        mockCacheEventsInc.mockClear()
        redis = createMockRedis()
    })

    it('writes every body before publishing the slim manifest on cold load', async () => {
        const entries = [makeEntry('a'), makeEntry('b'), makeEntry('c')]
        const upstream = vi.fn(async () => entries)
        const cache = new TestContextMillResourceCache(redis, upstream)

        const { manifest: slim, result } = await cache.loadOrRefresh()

        expect(upstream).toHaveBeenCalledTimes(1)
        expect(result).toBe('cold_refresh')
        expect(slim.entries).toHaveLength(3)
        // Manifest exposes slim metadata only (no text).
        expect(slim.entries.map((e) => e.uri).sort()).toEqual(entries.map((e) => e.uri).sort())
        expect(slim.entries[0]).not.toHaveProperty('text')

        // Body keys must land before the manifest bytes key in Redis writes.
        const manifestIdx = redis._setCalls.indexOf(MANIFEST_BYTES_KEY)
        expect(manifestIdx).toBeGreaterThan(-1)
        for (const e of entries) {
            const bodyIdx = redis._setCalls.indexOf(bodyKey(e.uri))
            expect(bodyIdx).toBeGreaterThan(-1)
            expect(bodyIdx).toBeLessThan(manifestIdx)
        }
        expect(mockCacheEventsInc).toHaveBeenCalledWith({ event: 'cold_miss' })
        expect(mockCacheEventsInc).toHaveBeenCalledWith({ event: 'lock_acquired' })
    })

    it('serves manifest from cache on warm hit without calling upstream', async () => {
        const entries = [makeEntry('a')]
        const cache = new TestContextMillResourceCache(redis, async () => entries)
        await cache.loadOrRefresh()

        const upstream = vi.fn(async () => [makeEntry('z')])
        cache.setLoader(upstream)
        const { manifest: slim, result } = await cache.loadOrRefresh()

        expect(upstream).not.toHaveBeenCalled()
        expect(result).toBe('fresh_hit')
        expect(slim.entries[0]!.uri).toBe(entries[0]!.uri)
        expect(mockCacheEventsInc).toHaveBeenCalledWith({ event: 'fresh_hit' })
    })

    it('reads a body by uri', async () => {
        const entry = makeEntry('a')
        const cache = new TestContextMillResourceCache(redis, async () => [entry])
        await cache.loadOrRefresh()

        const body = await cache.readBody(entry.uri)
        expect(body).toEqual({ mimeType: 'text/markdown', text: '# body a' })
        expect(mockBodyReadsInc).toHaveBeenCalledWith({ status: 'hit' })
    })

    it('returns null when the body is missing entirely', async () => {
        const cache = new TestContextMillResourceCache(redis, async () => [makeEntry('a')])
        await cache.loadOrRefresh()

        const body = await cache.readBody('posthog://skill/never-published')
        expect(body).toBeNull()
        expect(mockBodyReadsInc).toHaveBeenCalledWith({ status: 'miss' })
    })

    it('records parse errors when a body is corrupt', async () => {
        const cache = new TestContextMillResourceCache(redis, async () => [makeEntry('a')])
        await cache.loadOrRefresh()
        redis._store.set(bodyKey('posthog://skill/a'), '{')

        await expect(cache.readBody('posthog://skill/a')).rejects.toThrow()

        expect(mockBodyReadsInc).toHaveBeenCalledWith({ status: 'parse_error' })
    })

    it('overwrites bodies in place so the latest publish is served immediately', async () => {
        const cache = new TestContextMillResourceCache(redis, async () => [makeEntry('a', 'old content')])

        await cache.loadOrRefresh()
        const beforeRefresh = await cache.readBody('posthog://skill/a')
        expect(beforeRefresh!.text).toBe('old content')

        // Second publish for the same URI with new content. With URI-keyed
        // bodies, the new value lands at the same Redis key — readers see
        // the update on the next GET, no gen check or in-memory refresh
        // required. Invalidate first so the publish actually runs upstream
        // (otherwise ContextMillResourceCache short-circuits on a fresh manifest).
        await cache.invalidate()
        cache.setLoader(async () => [makeEntry('a', 'new content')])
        await cache.loadOrRefresh()
        const afterRefresh = await cache.readBody('posthog://skill/a')
        expect(afterRefresh!.text).toBe('new content')
    })

    it('leaves removed-upstream bodies in place to age out via TTL', async () => {
        const cache = new TestContextMillResourceCache(redis, async () => [makeEntry('keeper'), makeEntry('removed')])

        await cache.loadOrRefresh()

        const removedBodyKey = bodyKey('posthog://skill/removed')
        expect(redis._store.has(removedBodyKey)).toBe(true)

        // Second publish drops one entry. We should NOT delete the removed
        // body — clients holding the old URI can still resolve it until the
        // TTL expires naturally.
        await cache.invalidate()
        cache.setLoader(async () => [makeEntry('keeper')])
        await cache.loadOrRefresh()

        expect(redis._store.has(removedBodyKey)).toBe(true)
        const orphanedBody = await cache.readBody('posthog://skill/removed')
        expect(orphanedBody).not.toBeNull()
    })

    it('only one writer fetches upstream when many callers race on cold cache', async () => {
        const entries = [makeEntry('a')]
        let inFlight = 0
        let peak = 0
        const upstream = vi.fn(async () => {
            inFlight += 1
            peak = Math.max(peak, inFlight)
            await new Promise((r) => setTimeout(r, 20))
            inFlight -= 1
            return entries
        })
        const cache = new TestContextMillResourceCache(redis, upstream, { waitIntervalMs: 5, waitTimeoutMs: 200 })

        const concurrency = 5
        const results = await Promise.all(Array.from({ length: concurrency }, () => cache.loadOrRefresh()))

        expect(peak).toBe(1)
        expect(upstream).toHaveBeenCalledTimes(1)
        // Every caller observes the published slim manifest.
        expect(results.every((r) => r.manifest.entries[0]!.uri === entries[0]!.uri)).toBe(true)
        expect(results.some((r) => r.result === 'waited')).toBe(true)
        expect(mockCacheEventsInc).toHaveBeenCalledWith({ event: 'lock_contended' })
        expect(mockCacheEventsInc).toHaveBeenCalledWith({ event: 'wait_success' })
    })

    it('non-writers wait for the lock holder to publish and serve that result', async () => {
        const entries = [makeEntry('waited')]
        let resolveUpstream: ((entries: ContextMillResource[]) => void) | undefined
        const upstreamPromise = new Promise<ContextMillResource[]>((resolve) => {
            resolveUpstream = resolve
        })
        const upstream = vi.fn(() => upstreamPromise)
        const cache = new TestContextMillResourceCache(redis, upstream, {
            waitIntervalMs: 5,
            waitTimeoutMs: 1000,
        })

        // First call wins the lock and stalls in upstream.
        const writerResult = cache.loadOrRefresh()
        // Give the writer time to seize the lock before the waiter starts.
        await new Promise((r) => setTimeout(r, 10))
        const waiterResult = cache.loadOrRefresh()

        // Publish the upstream after both calls are in flight.
        await new Promise((r) => setTimeout(r, 30))
        resolveUpstream!(entries)

        const [writerResultPayload, waiterResultPayload] = await Promise.all([writerResult, waiterResult])
        expect(writerResultPayload.manifest.entries[0]!.uri).toBe(entries[0]!.uri)
        expect(waiterResultPayload.manifest.entries[0]!.uri).toBe(entries[0]!.uri)
        expect(writerResultPayload.result).toBe('cold_refresh')
        expect(waiterResultPayload.result).toBe('waited')
        expect(upstream).toHaveBeenCalledTimes(1)
    })

    it('serves stale manifest and triggers a background republish', async () => {
        const initial = [makeEntry('a')]
        const refreshed = [makeEntry('a'), makeEntry('b')]
        let call = 0
        const upstream = vi.fn(async () => {
            call += 1
            return call === 1 ? initial : refreshed
        })
        const cache = new TestContextMillResourceCache(redis, upstream, {
            freshSeconds: 0,
            waitIntervalMs: 5,
            waitTimeoutMs: 100,
        })

        const first = await cache.loadOrRefresh()
        expect(first.manifest.entries).toHaveLength(1)

        // Stale read returns the cached manifest and kicks off a background refresh.
        const second = await cache.loadOrRefresh()
        expect(second.manifest.entries).toHaveLength(1)
        expect(second.result).toBe('stale_hit')

        // Allow the background refresh to settle.
        await new Promise((r) => setTimeout(r, 30))
        expect(mockCacheEventsInc).toHaveBeenCalledWith({ event: 'background_success' })

        const third = await cache.loadOrRefresh()
        expect(third.manifest.entries).toHaveLength(2)
    })

    it('records background refresh errors', async () => {
        const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
        try {
            const cache = new TestContextMillResourceCache(redis, async () => [makeEntry('a')], {
                freshSeconds: 0,
                waitIntervalMs: 5,
                waitTimeoutMs: 100,
            })
            await cache.loadOrRefresh()
            cache.setLoader(async () => {
                throw new Error('refresh failed')
            })

            await cache.loadOrRefresh()
            await new Promise((r) => setTimeout(r, 30))

            expect(mockCacheEventsInc).toHaveBeenCalledWith({ event: 'background_error' })
        } finally {
            consoleError.mockRestore()
        }
    })

    it('falls back to a direct load when the writer never publishes', async () => {
        redis._store.set(MANIFEST_LOCK_KEY, 'someone-else')
        const entries = [makeEntry('fallback')]
        const upstream = vi.fn(async () => entries)
        const cache = new TestContextMillResourceCache(redis, upstream, { waitIntervalMs: 10, waitTimeoutMs: 50 })

        const { manifest: slim, result } = await cache.loadOrRefresh()

        expect(slim.entries[0]!.uri).toBe(entries[0]!.uri)
        expect(result).toBe('fallback')
        expect(upstream).toHaveBeenCalledTimes(1)
        expect(redis._store.has(MANIFEST_BYTES_KEY)).toBe(false)
        expect(mockCacheEventsInc).toHaveBeenCalledWith({ event: 'wait_timeout' })
    })

    it('does not leave the manifest lock held after a successful publish', async () => {
        const cache = new TestContextMillResourceCache(redis, async () => [makeEntry('a')])
        await cache.loadOrRefresh()
        expect(redis._store.has(MANIFEST_LOCK_KEY)).toBe(false)
        expect(redis._store.has(MANIFEST_FRESH_KEY)).toBe(true)
    })
})
