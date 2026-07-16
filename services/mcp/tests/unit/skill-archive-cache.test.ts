import { strToU8, zipSync } from 'fflate'
import { describe, expect, it, vi } from 'vitest'

import type { RedisLike } from '@/hono/cache/RedisCache'
import { SkillArchiveCache, type SkillArchiveFetchResult } from '@/hono/cache/SkillArchiveCache'
import { SkillCatalogService } from '@/hono/skill-catalog-service'

interface MockRedis extends RedisLike {
    store: Map<string, string>
}

function makeRedis(): MockRedis {
    const store = new Map<string, string>()
    return {
        store,
        get: vi.fn(async (key: string) => store.get(key) ?? null),
        set: vi.fn(async (key: string, value: string, ...args: (string | number)[]) => {
            if (args.includes('NX') && store.has(key)) {
                return null
            }
            store.set(key, value)
            return 'OK'
        }),
        del: vi.fn(async (...keys: string[]) => keys.filter((key) => store.delete(key)).length),
        scan: vi.fn(async () => ['0', []] as [string, string[]]),
        incr: vi.fn(async () => 1),
        expire: vi.fn(async () => 1),
        ttl: vi.fn(async () => -1),
    }
}

function makeArchive(seed = 'sample'): Uint8Array {
    return zipSync({
        [`${seed}/SKILL.md`]: strToU8(
            `---\nname: ${seed}\ndescription: Sample skill for tests.\n---\n\n# ${seed}\n\nUse the ${seed}.`
        ),
    })
}

function downloaded(bytes: Uint8Array = makeArchive(), etag?: string): SkillArchiveFetchResult {
    return { status: 'downloaded', bytes, etag }
}

const BYTES_KEY = 'mcp:shared-blob:product-skills:bytes'
const FRESH_KEY = 'mcp:shared-blob:product-skills:fresh'
const ETAG_KEY = 'mcp:shared-blob:product-skills:etag'

describe('SkillArchiveCache', () => {
    it('shares a downloaded archive through Redis and reuses fresh bytes', async () => {
        const redis = makeRedis()
        const fetchArchive = vi.fn(async () => downloaded())
        const first = new SkillArchiveCache(redis, { fetchArchive })
        const second = new SkillArchiveCache(redis, { fetchArchive })

        await expect(first.loadOrRefresh()).resolves.toMatchObject({ result: 'cold_refresh' })
        await expect(second.loadOrRefresh()).resolves.toMatchObject({ result: 'fresh_hit' })
        expect(fetchArchive).toHaveBeenCalledTimes(1)
    })

    it('isolates custom archive URLs from the published bundle cache', async () => {
        const redis = makeRedis()
        const fetchArchive = vi.fn(async () => downloaded())
        const first = new SkillArchiveCache(redis, { archiveUrl: 'http://localhost/skills.zip?v=one', fetchArchive })
        const second = new SkillArchiveCache(redis, { archiveUrl: 'http://localhost/skills.zip?v=two', fetchArchive })

        await expect(first.loadOrRefresh()).resolves.toMatchObject({ result: 'cold_refresh' })
        await expect(second.loadOrRefresh()).resolves.toMatchObject({ result: 'cold_refresh' })
        expect(first.cacheKey).not.toBe(second.cacheKey)
        expect(fetchArchive).toHaveBeenCalledTimes(2)
    })

    it('serves stale bytes immediately while one writer refreshes in the background', async () => {
        const redis = makeRedis()
        const fetchArchive = vi.fn(async () => downloaded())
        const cache = new SkillArchiveCache(redis, { fetchArchive, freshSeconds: 0 })
        await cache.loadOrRefresh()

        await expect(cache.loadOrRefresh()).resolves.toMatchObject({ result: 'stale_hit' })
        await vi.waitFor(() => expect(fetchArchive).toHaveBeenCalledTimes(2))
    })

    it('revalidates a stale archive with If-None-Match and reuses cached bytes on 304', async () => {
        const redis = makeRedis()
        const archive = makeArchive()
        const fetchArchive = vi.fn(
            async (_url: string, etag?: string): Promise<SkillArchiveFetchResult> =>
                etag ? { status: 'not_modified' } : downloaded(archive, 'etag-v1')
        )
        const cache = new SkillArchiveCache(redis, { fetchArchive })

        expect((await cache.loadOrRefresh()).result).toBe('cold_refresh')
        const originalBytes = redis.store.get(BYTES_KEY)
        expect(redis.store.get(ETAG_KEY)).toBe('etag-v1')

        // Expire the soft-TTL so the next load revalidates in the background.
        redis.store.set(FRESH_KEY, String(Date.now() - 1))

        const stale = await cache.loadOrRefresh()
        expect(stale.result).toBe('stale_hit')
        expect(stale.bytes).toEqual(archive)

        await vi.waitFor(() => {
            // Refresh sent the stored validator and freshness was bumped in place.
            expect(fetchArchive).toHaveBeenCalledWith(expect.any(String), 'etag-v1')
            expect(Number(redis.store.get(FRESH_KEY))).toBeGreaterThan(Date.now())
        })

        // The 304 skipped the download and left the cached bytes untouched.
        expect(fetchArchive.mock.calls.filter(([, sent]) => sent === undefined)).toHaveLength(1)
        expect(redis.store.get(BYTES_KEY)).toBe(originalBytes)
    })

    it('replaces cached bytes and etag when revalidation returns a new archive', async () => {
        const redis = makeRedis()
        const first = makeArchive('first')
        const second = makeArchive('second')
        const fetchArchive = vi.fn(
            async (_url: string, etag?: string): Promise<SkillArchiveFetchResult> =>
                etag ? downloaded(second, 'etag-v2') : downloaded(first, 'etag-v1')
        )
        const cache = new SkillArchiveCache(redis, { fetchArchive })

        expect((await cache.loadOrRefresh()).result).toBe('cold_refresh')
        redis.store.set(FRESH_KEY, String(Date.now() - 1))

        expect((await cache.loadOrRefresh()).result).toBe('stale_hit')

        await vi.waitFor(() => expect(redis.store.get(ETAG_KEY)).toBe('etag-v2'))
        expect(redis.store.get(BYTES_KEY)).toBe(Buffer.from(second).toString('base64'))

        const fresh = await cache.loadOrRefresh()
        expect(fresh.result).toBe('fresh_hit')
        expect(fresh.bytes).toEqual(second)
    })

    it('never sends If-None-Match when the server stored no validator', async () => {
        const redis = makeRedis()
        // Server returns no etag, so nothing is stored to revalidate against.
        const fetchArchive = vi.fn(async (_url: string, _etag?: string) => downloaded())
        const cache = new SkillArchiveCache(redis, { fetchArchive })

        expect((await cache.loadOrRefresh()).result).toBe('cold_refresh')
        expect(redis.store.has(ETAG_KEY)).toBe(false)

        redis.store.set(FRESH_KEY, String(Date.now() - 1))
        expect((await cache.loadOrRefresh()).result).toBe('stale_hit')

        await vi.waitFor(() => expect(fetchArchive).toHaveBeenCalledTimes(2))
        for (const [, sentEtag] of fetchArchive.mock.calls) {
            expect(sentEtag).toBeUndefined()
        }
    })

    it('does not fail core startup when the archive is unavailable on a cold cache', async () => {
        const service = new SkillCatalogService(makeRedis(), {
            fetchArchive: vi.fn(async () => {
                throw new Error('offline')
            }),
        })
        const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined)

        await expect(service.warmup()).resolves.toBeUndefined()
        expect(service.getCatalog()).toBeUndefined()
        expect(consoleError).toHaveBeenCalledWith(
            expect.stringContaining('continuing without refreshed skills'),
            expect.any(Error)
        )
        consoleError.mockRestore()
    })

    it('keeps the last valid catalog when a refreshed archive is corrupt', async () => {
        const redis = makeRedis()
        const service = new SkillCatalogService(redis, { fetchArchive: vi.fn(async () => downloaded()) })
        await service.warmup()
        const original = service.getCatalog()
        redis.store.set(BYTES_KEY, Buffer.from('not a zip').toString('base64'))
        redis.store.set(FRESH_KEY, String(Date.now() + 60_000))
        const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined)

        await service.revalidate()

        expect(service.getCatalog()).toBe(original)
        expect(consoleError).toHaveBeenCalled()
        consoleError.mockRestore()
    })
})
