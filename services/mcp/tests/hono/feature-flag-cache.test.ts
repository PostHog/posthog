import { gunzipSync, strFromU8 } from 'fflate'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { FeatureFlagCache, FLAG_CACHE_TTL_SECONDS } from '@/hono/cache/FeatureFlagCache'
import type { RedisLike } from '@/hono/cache/RedisCache'

import { makeRedisRateLimitStubs } from './helpers/redis-rate-limit-stubs'

interface MockRedis extends RedisLike {
    _store: Map<string, string>
}

function createMockRedis(): MockRedis {
    const store = new Map<string, string>()
    return {
        get: vi.fn(async (key: string) => store.get(key) ?? null),
        set: vi.fn(async (key: string, value: string) => {
            store.set(key, value)
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
        scan: vi.fn(async () => ['0', []] as [string, string[]]),
        ...makeRedisRateLimitStubs(),
        _store: store,
    }
}

describe('FeatureFlagCache', () => {
    let mockRedis: MockRedis
    let cache: FeatureFlagCache

    beforeEach(() => {
        mockRedis = createMockRedis()
        cache = new FeatureFlagCache(mockRedis)
    })

    it('returns undefined on a miss', async () => {
        expect(await cache.get('user-1', ['flag-a'])).toBeUndefined()
    })

    it('round-trips evaluated flags through gzip', async () => {
        const flags = { 'flag-a': true, 'flag-b': 'variant-x', 'flag-c': undefined }
        await cache.set('user-1', ['flag-a', 'flag-b', 'flag-c'], flags)

        expect(await cache.get('user-1', ['flag-a', 'flag-b', 'flag-c'])).toEqual(flags)
    })

    it('stores gzip-compressed base64, not plaintext JSON', async () => {
        const flags = { 'flag-a': true }
        await cache.set('user-1', ['flag-a'], flags)

        const [, raw] = vi.mocked(mockRedis.set).mock.calls[0]!
        expect(raw).not.toContain('flag-a')
        const bytes = Buffer.from(raw as string, 'base64')
        const json = strFromU8(gunzipSync(new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength)))
        expect(JSON.parse(json)).toEqual(flags)
    })

    it('writes with the chosen TTL', async () => {
        await cache.set('user-1', ['flag-a'], { 'flag-a': true })
        expect(mockRedis.set).toHaveBeenCalledWith(expect.any(String), expect.any(String), 'EX', FLAG_CACHE_TTL_SECONDS)
        expect(FLAG_CACHE_TTL_SECONDS).toBe(120)
    })

    it('isolates cache entries by user', async () => {
        await cache.set('user-a', ['flag-a'], { 'flag-a': true })
        await cache.set('user-b', ['flag-a'], { 'flag-a': false })

        expect(await cache.get('user-a', ['flag-a'])).toEqual({ 'flag-a': true })
        expect(await cache.get('user-b', ['flag-a'])).toEqual({ 'flag-a': false })
    })

    it('keys are stable regardless of flag-key and group ordering', () => {
        const a = cache.buildKey('user-1', ['flag-a', 'flag-b'], { organization: 'org-1', project: 'proj-1' })
        const b = cache.buildKey('user-1', ['flag-b', 'flag-a'], { project: 'proj-1', organization: 'org-1' })
        expect(a).toBe(b)
    })

    it('separates entries that differ by group context', async () => {
        await cache.set('user-1', ['flag-a'], { 'flag-a': true }, { organization: 'org-1' })
        await cache.set('user-1', ['flag-a'], { 'flag-a': false }, { organization: 'org-2' })

        expect(await cache.get('user-1', ['flag-a'], { organization: 'org-1' })).toEqual({ 'flag-a': true })
        expect(await cache.get('user-1', ['flag-a'], { organization: 'org-2' })).toEqual({ 'flag-a': false })
    })

    it('treats corrupt cache entries as a miss', async () => {
        const key = cache.buildKey('user-1', ['flag-a'])
        mockRedis._store.set(key, 'not-valid-base64-gzip')
        expect(await cache.get('user-1', ['flag-a'])).toBeUndefined()
    })

    it('never throws when the redis write fails', async () => {
        vi.mocked(mockRedis.set).mockRejectedValueOnce(new Error('redis down'))
        await expect(cache.set('user-1', ['flag-a'], { 'flag-a': true })).resolves.toBeUndefined()
    })
})
