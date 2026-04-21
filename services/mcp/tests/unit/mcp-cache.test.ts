import { beforeEach, describe, expect, it, vi } from 'vitest'

import { MemoryCache } from '@/lib/cache/MemoryCache'
import type { ScopedCache } from '@/lib/cache/ScopedCache'
import type { State } from '@/tools/types'

const mockCaptureException = vi.fn()

vi.mock('@/lib/analytics', () => ({
    getPostHogClient: () => ({
        captureException: mockCaptureException,
        capture: vi.fn(),
    }),
    AnalyticsEvent: {},
    generateId: () => 'test-id',
}))

// Extracted getOrFetchCached logic matching MCP.getOrFetchCached exactly,
// so we can test it without importing the MCP class (which requires Cloudflare runtime).
async function getOrFetchCached<D extends keyof State, T extends keyof State>(deps: {
    cache: ScopedCache<State>
    waitUntil: (p: Promise<any>) => void
    cacheTtlMs: number
    opts: {
        name: string
        cacheKey: D
        fetchedAtKey: T
        fetcher: () => Promise<State[D]>
    }
}): Promise<State[D] | undefined> {
    const { getPostHogClient } = await import('@/lib/analytics')
    const { cache, waitUntil, cacheTtlMs, opts } = deps

    try {
        const cached = await cache.get(opts.cacheKey)
        const fetchedAt = (await cache.get(opts.fetchedAtKey)) as number | undefined
        const isStale = !fetchedAt || Date.now() - fetchedAt > cacheTtlMs

        if (cached !== undefined && !isStale) {
            return cached
        }

        const fetchAndCache = async (): Promise<State[D]> => {
            const data = await opts.fetcher()
            await cache.set(opts.cacheKey, data)
            await cache.set(opts.fetchedAtKey, Date.now() as State[T])
            return data
        }

        if (cached !== undefined) {
            waitUntil(
                fetchAndCache().catch((error) => {
                    getPostHogClient().captureException(error, undefined, {
                        tag: 'max_ai',
                        context: `${opts.name}_background_revalidation`,
                    })
                })
            )
            return cached
        }

        return await fetchAndCache()
    } catch (error) {
        getPostHogClient().captureException(error, undefined, {
            tag: 'max_ai',
            context: `get_or_fetch_${opts.name}`,
        })
        return undefined
    }
}

describe('getOrFetchCached', () => {
    let cache: MemoryCache<State>
    let waitUntilFns: Promise<any>[]
    const CACHE_TTL_MS = 10 * 60 * 1000

    function callGetOrFetchCached<D extends keyof State, T extends keyof State>(opts: {
        name: string
        cacheKey: D
        fetchedAtKey: T
        fetcher: () => Promise<State[D]>
    }): Promise<State[D] | undefined> {
        return getOrFetchCached({
            cache,
            waitUntil: (p) => waitUntilFns.push(p),
            cacheTtlMs: CACHE_TTL_MS,
            opts,
        })
    }

    async function flushBackgroundTasks(): Promise<void> {
        await Promise.allSettled(waitUntilFns)
        waitUntilFns = []
    }

    beforeEach(async () => {
        cache = new MemoryCache('test-user')
        await cache.clear()
        waitUntilFns = []
        vi.restoreAllMocks()
        mockCaptureException.mockClear()
    })

    it('should fetch and cache on first call (cache miss)', async () => {
        const fetcher = vi.fn().mockResolvedValue({ name: 'Org 1' })

        const result = await callGetOrFetchCached({
            name: 'org',
            cacheKey: 'cachedOrg:org-1',
            fetchedAtKey: 'cachedOrgFetchedAt:org-1',
            fetcher,
        })

        expect(result).toEqual({ name: 'Org 1' })
        expect(fetcher).toHaveBeenCalledOnce()
        expect(await cache.get('cachedOrg:org-1')).toEqual({ name: 'Org 1' })
        expect(await cache.get('cachedOrgFetchedAt:org-1')).toBeTypeOf('number')
    })

    it('should return cached data without fetching when fresh', async () => {
        await cache.set('cachedOrg:org-1', { name: 'Org 1' } as any)
        await cache.set('cachedOrgFetchedAt:org-1', Date.now() as any)

        const fetcher = vi.fn().mockResolvedValue({ name: 'Org 2' })

        const result = await callGetOrFetchCached({
            name: 'org',
            cacheKey: 'cachedOrg:org-1',
            fetchedAtKey: 'cachedOrgFetchedAt:org-1',
            fetcher,
        })

        expect(result).toEqual({ name: 'Org 1' })
        expect(fetcher).not.toHaveBeenCalled()
    })

    it('should return stale data immediately and revalidate in background', async () => {
        const staleTimestamp = Date.now() - 15 * 60 * 1000 // 15 minutes ago
        await cache.set('cachedOrg:org-1', { name: 'Org Stale' } as any)
        await cache.set('cachedOrgFetchedAt:org-1', staleTimestamp as any)

        const fetcher = vi.fn().mockResolvedValue({ name: 'Org Fresh' })

        const result = await callGetOrFetchCached({
            name: 'org',
            cacheKey: 'cachedOrg:org-1',
            fetchedAtKey: 'cachedOrgFetchedAt:org-1',
            fetcher,
        })

        expect(result).toEqual({ name: 'Org Stale' })
        expect(fetcher).toHaveBeenCalledOnce()

        await flushBackgroundTasks()
        expect(await cache.get('cachedOrg:org-1')).toEqual({ name: 'Org Fresh' })
    })

    it('should treat missing fetchedAt as stale', async () => {
        await cache.set('cachedOrg:org-1', { name: 'Org No Timestamp' } as any)

        const fetcher = vi.fn().mockResolvedValue({ name: 'Org Fresh' })

        const result = await callGetOrFetchCached({
            name: 'org',
            cacheKey: 'cachedOrg:org-1',
            fetchedAtKey: 'cachedOrgFetchedAt:org-1',
            fetcher,
        })

        expect(result).toEqual({ name: 'Org No Timestamp' })
        expect(fetcher).toHaveBeenCalledOnce()
    })

    it('should return undefined and capture exception when fetcher throws on cache miss', async () => {
        const fetcher = vi.fn().mockRejectedValue(new Error('API down'))

        const result = await callGetOrFetchCached({
            name: 'org',
            cacheKey: 'cachedOrg:org-1',
            fetchedAtKey: 'cachedOrgFetchedAt:org-1',
            fetcher,
        })

        expect(result).toBeUndefined()
        expect(fetcher).toHaveBeenCalledOnce()
        expect(mockCaptureException).toHaveBeenCalledWith(expect.any(Error), undefined, {
            tag: 'max_ai',
            context: 'get_or_fetch_org',
        })
    })

    it('should still return stale data when background revalidation fails', async () => {
        const staleTimestamp = Date.now() - 15 * 60 * 1000
        await cache.set('cachedUser:u1', { distinct_id: 'u1' } as any)
        await cache.set('cachedUserFetchedAt:u1', staleTimestamp as any)

        const fetcher = vi.fn().mockRejectedValue(new Error('Network error'))

        const result = await callGetOrFetchCached({
            name: 'user',
            cacheKey: 'cachedUser:u1',
            fetchedAtKey: 'cachedUserFetchedAt:u1',
            fetcher,
        })

        expect(result).toEqual({ distinct_id: 'u1' })
        await flushBackgroundTasks()
        expect(await cache.get('cachedUser:u1')).toEqual({ distinct_id: 'u1' })
        expect(mockCaptureException).toHaveBeenCalledWith(expect.any(Error), undefined, {
            tag: 'max_ai',
            context: 'user_background_revalidation',
        })
    })

    it('should cache undefined values from fetcher', async () => {
        const fetcher = vi.fn().mockResolvedValue(undefined)

        const result = await callGetOrFetchCached({
            name: 'project',
            cacheKey: 'cachedProject:p1',
            fetchedAtKey: 'cachedProjectFetchedAt:p1',
            fetcher,
        })

        expect(result).toBeUndefined()
        expect(fetcher).toHaveBeenCalledOnce()
        expect(await cache.get('cachedProjectFetchedAt:p1')).toBeTypeOf('number')
    })
})
