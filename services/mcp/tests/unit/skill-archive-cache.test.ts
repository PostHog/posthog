import { strToU8, zipSync } from 'fflate'
import { describe, expect, it, vi } from 'vitest'

import type { RedisLike } from '@/hono/cache/RedisCache'
import { SkillArchiveCache } from '@/hono/cache/SkillArchiveCache'
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

function makeArchive(): Uint8Array {
    return zipSync({
        'sample/SKILL.md': strToU8(
            '---\nname: sample\ndescription: Sample skill for tests.\n---\n\n# Sample\n\nUse the sample.'
        ),
    })
}

describe('SkillArchiveCache', () => {
    it('shares a downloaded archive through Redis and reuses fresh bytes', async () => {
        const redis = makeRedis()
        const fetchArchive = vi.fn(async () => makeArchive())
        const first = new SkillArchiveCache(redis, { fetchArchive })
        const second = new SkillArchiveCache(redis, { fetchArchive })

        await expect(first.loadOrRefresh()).resolves.toMatchObject({ result: 'cold_refresh' })
        await expect(second.loadOrRefresh()).resolves.toMatchObject({ result: 'fresh_hit' })
        expect(fetchArchive).toHaveBeenCalledTimes(1)
    })

    it('isolates custom archive URLs from the published bundle cache', async () => {
        const redis = makeRedis()
        const fetchArchive = vi.fn(async () => makeArchive())
        const first = new SkillArchiveCache(redis, { archiveUrl: 'http://localhost/skills.zip?v=one', fetchArchive })
        const second = new SkillArchiveCache(redis, { archiveUrl: 'http://localhost/skills.zip?v=two', fetchArchive })

        await expect(first.loadOrRefresh()).resolves.toMatchObject({ result: 'cold_refresh' })
        await expect(second.loadOrRefresh()).resolves.toMatchObject({ result: 'cold_refresh' })
        expect(first.cacheKey).not.toBe(second.cacheKey)
        expect(fetchArchive).toHaveBeenCalledTimes(2)
    })

    it('serves stale bytes immediately while one writer refreshes in the background', async () => {
        const redis = makeRedis()
        const fetchArchive = vi.fn(async () => makeArchive())
        const cache = new SkillArchiveCache(redis, { fetchArchive, freshSeconds: 0 })
        await cache.loadOrRefresh()

        await expect(cache.loadOrRefresh()).resolves.toMatchObject({ result: 'stale_hit' })
        await vi.waitFor(() => expect(fetchArchive).toHaveBeenCalledTimes(2))
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
        const service = new SkillCatalogService(redis, { fetchArchive: vi.fn(async () => makeArchive()) })
        await service.warmup()
        const original = service.getCatalog()
        redis.store.set('mcp:shared-blob:product-skills:bytes', Buffer.from('not a zip').toString('base64'))
        redis.store.set('mcp:shared-blob:product-skills:fresh', String(Date.now() + 60_000))
        const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined)

        await service.revalidate()

        expect(service.getCatalog()).toBe(original)
        expect(consoleError).toHaveBeenCalled()
        consoleError.mockRestore()
    })
})
