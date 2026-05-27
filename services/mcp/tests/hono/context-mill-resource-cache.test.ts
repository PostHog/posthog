import { createHash } from 'node:crypto'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ContextMillResourceCache } from '@/hono/cache/ContextMillResourceCache'
import type { RedisLike } from '@/hono/cache/RedisCache'
import type { ContextMillResource } from '@/resources/manifest-types'

import { makeRedisRateLimitStubs } from './helpers/redis-rate-limit-stubs'

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
        redis = createMockRedis()
    })

    it('writes every body before publishing the slim manifest on cold load', async () => {
        const cache = new ContextMillResourceCache(redis)
        const entries = [makeEntry('a'), makeEntry('b'), makeEntry('c')]
        const upstream = vi.fn(async () => entries)

        const slim = await cache.loadOrRefresh(upstream)

        expect(upstream).toHaveBeenCalledTimes(1)
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
    })

    it('serves manifest from cache on warm hit without calling upstream', async () => {
        const cache = new ContextMillResourceCache(redis)
        const entries = [makeEntry('a')]
        await cache.loadOrRefresh(async () => entries)

        const upstream = vi.fn(async () => [makeEntry('z')])
        const slim = await cache.loadOrRefresh(upstream)

        expect(upstream).not.toHaveBeenCalled()
        expect(slim.entries[0]!.uri).toBe(entries[0]!.uri)
    })

    it('reads a body by uri', async () => {
        const cache = new ContextMillResourceCache(redis)
        const entry = makeEntry('a')
        await cache.loadOrRefresh(async () => [entry])

        const body = await cache.readBody(entry.uri)
        expect(body).toEqual({ mimeType: 'text/markdown', text: '# body a' })
    })

    it('returns null when the body is missing entirely', async () => {
        const cache = new ContextMillResourceCache(redis)
        await cache.loadOrRefresh(async () => [makeEntry('a')])

        const body = await cache.readBody('posthog://skill/never-published')
        expect(body).toBeNull()
    })

    it('overwrites bodies in place so the latest publish is served immediately', async () => {
        const cache = new ContextMillResourceCache(redis)

        await cache.loadOrRefresh(async () => [makeEntry('a', 'old content')])
        const beforeRefresh = await cache.readBody('posthog://skill/a')
        expect(beforeRefresh!.text).toBe('old content')

        // Second publish for the same URI with new content. With URI-keyed
        // bodies, the new value lands at the same Redis key — readers see
        // the update on the next GET, no gen check or in-memory refresh
        // required. Invalidate first so the publish actually runs upstream
        // (otherwise SharedBlobCache short-circuits on a fresh manifest).
        await cache.invalidate()
        await cache.loadOrRefresh(async () => [makeEntry('a', 'new content')])
        const afterRefresh = await cache.readBody('posthog://skill/a')
        expect(afterRefresh!.text).toBe('new content')
    })

    it('leaves removed-upstream bodies in place to age out via TTL', async () => {
        const cache = new ContextMillResourceCache(redis)

        await cache.loadOrRefresh(async () => [makeEntry('keeper'), makeEntry('removed')])

        const removedBodyKey = bodyKey('posthog://skill/removed')
        expect(redis._store.has(removedBodyKey)).toBe(true)

        // Second publish drops one entry. We should NOT delete the removed
        // body — clients holding the old URI can still resolve it until the
        // TTL expires naturally.
        await cache.invalidate()
        await cache.loadOrRefresh(async () => [makeEntry('keeper')])

        expect(redis._store.has(removedBodyKey)).toBe(true)
        const orphanedBody = await cache.readBody('posthog://skill/removed')
        expect(orphanedBody).not.toBeNull()
    })

    it('only one writer fetches upstream when many callers race on cold cache', async () => {
        const cache = new ContextMillResourceCache(redis, { waitIntervalMs: 5, waitTimeoutMs: 200 })
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

        const concurrency = 5
        const results = await Promise.all(Array.from({ length: concurrency }, () => cache.loadOrRefresh(upstream)))

        expect(peak).toBe(1)
        // Every caller observes the published slim manifest.
        expect(results.every((r) => r.entries[0]!.uri === entries[0]!.uri)).toBe(true)
    })

    it('serves stale manifest and triggers a background republish', async () => {
        const cache = new ContextMillResourceCache(redis, {
            freshSeconds: 0,
            waitIntervalMs: 5,
            waitTimeoutMs: 100,
        })

        const initial = [makeEntry('a')]
        const refreshed = [makeEntry('a'), makeEntry('b')]
        let call = 0
        const upstream = vi.fn(async () => {
            call += 1
            return call === 1 ? initial : refreshed
        })

        const first = await cache.loadOrRefresh(upstream)
        expect(first.entries).toHaveLength(1)

        // Stale read returns the cached manifest and kicks off a background refresh.
        const second = await cache.loadOrRefresh(upstream)
        expect(second.entries).toHaveLength(1)

        // Allow the background refresh to settle.
        await new Promise((r) => setTimeout(r, 30))

        const third = await cache.loadOrRefresh(upstream)
        expect(third.entries).toHaveLength(2)
    })

    it('does not leave the manifest lock held after a successful publish', async () => {
        const cache = new ContextMillResourceCache(redis)
        await cache.loadOrRefresh(async () => [makeEntry('a')])
        expect(redis._store.has(MANIFEST_LOCK_KEY)).toBe(false)
        expect(redis._store.has(MANIFEST_FRESH_KEY)).toBe(true)
    })
})
