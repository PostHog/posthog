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
        eval: vi.fn(async () => null),
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
const SHA_KEY = 'mcp:shared-blob:product-skills:sha'
const LOCK_KEY = 'mcp:shared-blob:product-skills:lock'

function expireSharedCopy(redis: MockRedis): void {
    redis.store.set(FRESH_KEY, String(Date.now() - 1))
}

describe('SkillArchiveCache', () => {
    it('downloads once for a fleet and serves the shared copy to every later pod', async () => {
        const redis = makeRedis()
        const fetchArchive = vi.fn(async () => downloaded())
        const first = new SkillArchiveCache(redis, { fetchArchive })
        const second = new SkillArchiveCache(redis, { fetchArchive })

        const cold = await first.loadOrRefresh()
        const warm = await second.loadOrRefresh()

        expect(cold.result).toBe('cold_refresh')
        expect(warm).toMatchObject({ result: 'fresh_hit', sha: cold.sha })
        expect(fetchArchive).toHaveBeenCalledTimes(1)
        expect(redis.store.get(SHA_KEY)).toBe(cold.sha)
    })

    it('serves a stale shared copy at startup without touching the source', async () => {
        const redis = makeRedis()
        const fetchArchive = vi.fn(async () => downloaded())
        const cache = new SkillArchiveCache(redis, { fetchArchive })
        await cache.loadOrRefresh()
        expireSharedCopy(redis)

        await expect(cache.loadOrRefresh()).resolves.toMatchObject({ result: 'stale_hit' })
        expect(fetchArchive).toHaveBeenCalledTimes(1)
    })

    it('backfills the sha for a shared copy stored without one', async () => {
        const redis = makeRedis()
        const cache = new SkillArchiveCache(redis, { fetchArchive: vi.fn(async () => downloaded()) })
        await cache.loadOrRefresh()
        redis.store.delete(SHA_KEY)

        const loaded = await cache.loadOrRefresh()

        // Otherwise every poll reads `missing` and pulls the whole archive from Redis again.
        expect(redis.store.get(SHA_KEY)).toBe(loaded.sha)
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

    // The July incident: every handshake pulled the whole archive out of Redis. A pod
    // that already holds the current sha must read only the small keys.
    it('reads no archive bytes when the shared sha matches what the pod holds', async () => {
        const redis = makeRedis()
        const cache = new SkillArchiveCache(redis, { fetchArchive: vi.fn(async () => downloaded()) })
        const { sha } = await cache.loadOrRefresh()
        vi.mocked(redis.get).mockClear()

        await expect(cache.readIfChanged(sha)).resolves.toBeNull()
        expect(redis.get).not.toHaveBeenCalledWith(BYTES_KEY)
    })

    it('returns the new bytes when another pod published a different sha', async () => {
        const redis = makeRedis()
        const cache = new SkillArchiveCache(redis, {
            fetchArchive: vi.fn(async () => downloaded(makeArchive('first'))),
        })
        const { sha } = await cache.loadOrRefresh()
        const publisher = new SkillArchiveCache(redis, {
            fetchArchive: vi.fn(async () => downloaded(makeArchive('second'), 'etag-v2')),
        })
        expireSharedCopy(redis)
        await expect(publisher.refreshIfStale()).resolves.toBe('downloaded')

        const changed = await cache.readIfChanged(sha)

        expect(changed?.sha).not.toBe(sha)
        expect(changed?.bytes).toEqual(makeArchive('second'))
    })

    describe('refreshIfStale', () => {
        it('does nothing while the shared copy is fresh', async () => {
            const redis = makeRedis()
            const fetchArchive = vi.fn(async () => downloaded())
            const cache = new SkillArchiveCache(redis, { fetchArchive })
            await cache.loadOrRefresh()

            await expect(cache.refreshIfStale()).resolves.toBe('fresh')
            expect(fetchArchive).toHaveBeenCalledTimes(1)
        })

        it('revalidates a stale copy with If-None-Match and only bumps freshness on 304', async () => {
            const redis = makeRedis()
            const archive = makeArchive()
            const fetchArchive = vi.fn(
                async (_url: string, etag?: string): Promise<SkillArchiveFetchResult> =>
                    etag ? { status: 'not_modified' } : downloaded(archive, 'etag-v1')
            )
            const cache = new SkillArchiveCache(redis, { fetchArchive })
            const { sha } = await cache.loadOrRefresh()
            const originalBytes = redis.store.get(BYTES_KEY)
            expireSharedCopy(redis)

            await expect(cache.refreshIfStale()).resolves.toBe('not_modified')

            expect(fetchArchive).toHaveBeenLastCalledWith(expect.any(String), 'etag-v1')
            expect(Number(redis.store.get(FRESH_KEY))).toBeGreaterThan(Date.now())
            expect(redis.store.get(BYTES_KEY)).toBe(originalBytes)
            expect(redis.store.get(SHA_KEY)).toBe(sha)
        })

        it('replaces bytes, etag and sha when the source has a new archive', async () => {
            const redis = makeRedis()
            const second = makeArchive('second')
            const fetchArchive = vi.fn(
                async (_url: string, etag?: string): Promise<SkillArchiveFetchResult> =>
                    etag ? downloaded(second, 'etag-v2') : downloaded(makeArchive('first'), 'etag-v1')
            )
            const cache = new SkillArchiveCache(redis, { fetchArchive })
            const { sha } = await cache.loadOrRefresh()
            expireSharedCopy(redis)

            await expect(cache.refreshIfStale()).resolves.toBe('downloaded')

            expect(redis.store.get(ETAG_KEY)).toBe('etag-v2')
            expect(redis.store.get(BYTES_KEY)).toBe(Buffer.from(second).toString('base64'))
            expect(redis.store.get(SHA_KEY)).not.toBe(sha)
        })

        it('never sends If-None-Match when the server stored no validator', async () => {
            const redis = makeRedis()
            const fetchArchive = vi.fn(async (_url: string, _etag?: string) => downloaded())
            const cache = new SkillArchiveCache(redis, { fetchArchive })
            await cache.loadOrRefresh()
            expect(redis.store.has(ETAG_KEY)).toBe(false)
            expireSharedCopy(redis)

            await cache.refreshIfStale()

            expect(fetchArchive).toHaveBeenCalledTimes(2)
            for (const [, sentEtag] of fetchArchive.mock.calls) {
                expect(sentEtag).toBeUndefined()
            }
        })

        it('leaves the network to the pod holding the writer lock', async () => {
            const redis = makeRedis()
            const fetchArchive = vi.fn(async () => downloaded())
            const cache = new SkillArchiveCache(redis, { fetchArchive })
            await cache.loadOrRefresh()
            expireSharedCopy(redis)
            redis.store.set(LOCK_KEY, 'another-pod')

            await expect(cache.refreshIfStale()).resolves.toBe('lock_busy')
            expect(fetchArchive).toHaveBeenCalledTimes(1)
        })

        it('reports a missing shared copy instead of downloading outside the startup path', async () => {
            const cache = new SkillArchiveCache(makeRedis(), { fetchArchive: vi.fn(async () => downloaded()) })

            await expect(cache.refreshIfStale()).resolves.toBe('missing')
        })
    })

    it('keeps the previous shared copy when a downloaded archive fails validation', async () => {
        const redis = makeRedis()
        let release = 'good'
        const fetchArchive = vi.fn(async (): Promise<SkillArchiveFetchResult> => {
            return release === 'good' ? downloaded(makeArchive('good'), 'etag-good') : downloaded(strToU8('not a zip'))
        })
        const cache = new SkillArchiveCache(redis, {
            fetchArchive,
            validateArchive: (bytes) => {
                if (bytes.length < 100) {
                    throw new Error('corrupt archive')
                }
            },
        })
        const { sha } = await cache.loadOrRefresh()
        release = 'bad'
        expireSharedCopy(redis)

        await expect(cache.refreshIfStale()).rejects.toThrow('corrupt archive')

        expect(redis.store.get(SHA_KEY)).toBe(sha)
        expect(redis.store.get(ETAG_KEY)).toBe('etag-good')
        // The lock is released, so the next stale poll can try the source again.
        expect(redis.store.has(LOCK_KEY)).toBe(false)
    })
})

describe('SkillCatalogService', () => {
    function quietConsole(): ReturnType<typeof vi.spyOn> {
        return vi.spyOn(console, 'error').mockImplementation(() => undefined)
    }

    it('retries warmup inside its budget and starts without skills when the source stays down', async () => {
        const fetchArchive = vi.fn(async () => {
            throw new Error('offline')
        })
        const service = new SkillCatalogService(makeRedis(), { fetchArchive, warmupTimeoutMs: 50, warmupRetryMs: 10 })
        const consoleError = quietConsole()

        await expect(service.warmup()).resolves.toBeUndefined()

        expect(service.getCatalog()).toBeUndefined()
        expect(fetchArchive.mock.calls.length).toBeGreaterThan(1)
        expect(consoleError).toHaveBeenCalledWith(
            expect.stringContaining('starting without product skills'),
            expect.any(Error)
        )
        consoleError.mockRestore()
    })

    it('loads the catalog at warmup and adopts a newer archive another pod published', async () => {
        const redis = makeRedis()
        const first = new SkillCatalogService(redis, {
            fetchArchive: vi.fn(async () => downloaded(makeArchive('first'), 'etag-v1')),
        })
        await first.warmup()
        expect(first.getCatalog()?.listNames()).toEqual(['first'])

        const second = new SkillCatalogService(redis, {
            fetchArchive: vi.fn(async () => downloaded(makeArchive('second'), 'etag-v2')),
        })
        await second.warmup()
        expect(second.getCatalog()?.listNames()).toEqual(['first'])
        expireSharedCopy(redis)

        // The second pod wins the refresh and adopts its own download; the first pod
        // sees the new sha on its next poll and reparses without touching the source.
        await second.poll()
        await first.poll()

        expect(second.getCatalog()?.listNames()).toEqual(['second'])
        expect(first.getCatalog()?.listNames()).toEqual(['second'])
    })

    it('keeps the last catalog when the shared copy turns corrupt', async () => {
        const redis = makeRedis()
        const service = new SkillCatalogService(redis, { fetchArchive: vi.fn(async () => downloaded()) })
        await service.warmup()
        const original = service.getCatalog()
        redis.store.set(BYTES_KEY, Buffer.from('not a zip').toString('base64'))
        redis.store.set(SHA_KEY, 'corrupt')
        redis.store.set(FRESH_KEY, String(Date.now() + 60_000))
        const consoleError = quietConsole()

        await service.poll()

        expect(service.getCatalog()).toBe(original)
        expect(consoleError).toHaveBeenCalledWith(
            expect.stringContaining('keeping the current catalog'),
            expect.any(Error)
        )
        consoleError.mockRestore()
    })

    it('repairs a shared copy that Redis lost', async () => {
        const redis = makeRedis()
        const fetchArchive = vi.fn(async () => downloaded())
        const service = new SkillCatalogService(redis, { fetchArchive })
        await service.warmup()
        redis.store.clear()

        await service.poll()

        expect(fetchArchive).toHaveBeenCalledTimes(2)
        expect(redis.store.has(BYTES_KEY)).toBe(true)
        expect(service.getCatalog()?.listNames()).toEqual(['sample'])
    })
})
