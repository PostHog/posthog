import { QueryClient } from '@tanstack/react-query'

import type { StringStorage } from '@/lib/secureStorage'
import { insightSnapshot } from '@/model/adapters/insightSnapshot'
import { cacheable } from '@/model/adapters/readCache'
import { webOverviewSnapshot } from '@/model/adapters/webOverview'
import { ApiError } from './client'
import { persistReadCache } from './readCache'
import { inboxCacheKey } from './readCacheKeys'
import { boundedEntries, cacheKey, READ_CACHE_TTL_MS, type ReadCacheScope, ReadCacheStore } from './readCacheStore'

const scope: ReadCacheScope = { account: 'account-1', host: 'https://example.com', projectId: 1 }
const key = ['views', scope.host, 1, 'insight', 'view-1', '-', '-']
const aggregate = {
    queryKind: 'TrendsQuery',
    sqlTable: null,
    value: 42,
    readAt: 100,
    lastRefreshAt: '2026-10-01T12:00:00Z',
}

function memoryStorage(): StringStorage {
    const values = new Map<string, string>()
    return {
        getItem: async (name) => values.get(name) ?? null,
        setItem: async (name, value) => {
            values.set(name, value)
        },
        removeItem: async (name) => {
            values.delete(name)
        },
    }
}

function client(): QueryClient {
    return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
}

describe('bounded offline read cache', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2026-10-01T13:00:00Z'))
    })
    afterEach(() => jest.useRealTimers())

    it('restores supported aggregate data with its original age and excludes raw or unrelated queries', async () => {
        const store = new ReadCacheStore(memoryStorage())
        const source = client()
        const subscription = persistReadCache(source, store, scope, () => true)
        await subscription.ready
        const updatedAt = Date.now() - 60_000
        source.setQueryData(key, aggregate, { updatedAt })
        source.setQueryData(['views', scope.host, 1, 'actors', 'query'], [{ id: 'private-person' }])
        source.setQueryData(['tasks', scope.host, 1, 'task', '1'], { transcript: 'Private message' })
        source.setQueryData(['views', scope.host, 1, 'insight', 'sql', '-', '-'], {
            queryKind: 'HogQLQuery',
            sqlTable: { rows: [['private-person']] },
        })
        await subscription.flush()
        await store.settled()
        subscription.stop()
        const restored = client()
        const restarted = persistReadCache(restored, store, scope, () => true)
        await restarted.ready
        expect(restored.getQueryData(key)).toEqual({ ...aggregate, restoredFromDevice: true })
        expect(restored.getQueryState(key)?.dataUpdatedAt).toBe(updatedAt)
        expect(restored.getQueryCache().getAll()).toHaveLength(1)
        restarted.stop()
    })

    test.each([401, 403, 404])('purges denied data on %s so the next restart cannot resurrect it', async (status) => {
        const store = new ReadCacheStore(memoryStorage())
        const otherRange = [...key.slice(0, -1), 'other-range']
        await store.save(
            scope,
            () => [key, otherRange].map((variant) => ({ key: variant, data: aggregate, updatedAt: Date.now() })),
            () => true
        )
        const active = client()
        const session = persistReadCache(active, store, scope, () => true)
        await session.ready
        expect(active.getQueryData(key)).toBeDefined()
        await expect(
            active.fetchQuery({
                queryKey: key,
                queryFn: async () => {
                    throw new ApiError(status, {})
                },
            })
        ).rejects.toBeInstanceOf(ApiError)
        await store.settled()
        expect(active.getQueryData(key)).toBeUndefined()
        session.stop()
        const next = client()
        const restarted = persistReadCache(next, store, scope, () => true)
        await restarted.ready
        expect(next.getQueryData(key)).toBeUndefined()
        expect(next.getQueryData(otherRange)).toBeUndefined()
        restarted.stop()
    })

    it('drops the read-only inbox fallback after a live inbox denial', async () => {
        const store = new ReadCacheStore(memoryStorage())
        const cached = inboxCacheKey(scope)
        await store.save(
            scope,
            () => [{ key: cached, data: { items: [], sourceUpdatedAt: Date.now() }, updatedAt: Date.now() }],
            () => true
        )
        const active = client()
        const session = persistReadCache(active, store, scope, () => true)
        await session.ready
        await active
            .fetchQuery({
                queryKey: ['signals', scope.host, 1, 'inbox'],
                queryFn: async () => {
                    throw new ApiError(403, {})
                },
            })
            .catch(() => undefined)
        await store.settled()
        session.stop()
        const next = client()
        const restarted = persistReadCache(next, store, scope, () => true)
        await restarted.ready
        expect(next.getQueryData(cached)).toBeUndefined()
        restarted.stop()
    })

    it('does not let delayed hydration cross a scope switch or replace a newer response', async () => {
        const storage = memoryStorage()
        const store = new ReadCacheStore(storage)
        await store.save(
            scope,
            () => [{ key, data: aggregate, updatedAt: Date.now() - 1000 }],
            () => true
        )
        const read = storage.getItem
        let finish!: () => void
        const gate = new Promise<void>((resolve) => {
            finish = resolve
        })
        storage.getItem = async (name) => {
            await gate
            return read(name)
        }
        let current = true
        const active = client()
        const session = persistReadCache(active, store, scope, () => current)
        current = false
        finish()
        await session.ready
        expect(active.getQueryData(key)).toBeUndefined()
        session.stop()
        const newer = client()
        newer.setQueryData(key, { ...aggregate, value: 99 }, { updatedAt: Date.now() })
        const next = persistReadCache(newer, store, scope, () => true)
        await next.ready
        expect(newer.getQueryData(key)).toMatchObject({ value: 99 })
        next.stop()
    })

    test.each(['timer', 'flush'] as const)(
        'retries failed hydration on %s before replacing saved entries',
        async (retry) => {
            const storage = memoryStorage()
            const store = new ReadCacheStore(storage)
            const savedAt = Date.now() - 1000
            await store.save(
                scope,
                () => [{ key, data: aggregate, updatedAt: savedAt }],
                () => true
            )
            const read = storage.getItem
            const original = await read(cacheKey(scope))
            let unavailable = true
            storage.getItem = async (name) => {
                if (unavailable) throw new Error('Temporary read failure')
                return read(name)
            }
            const active = client()
            const session = persistReadCache(active, store, scope, () => true)
            await session.ready
            const newerKey = [...key.slice(0, 4), 'new-view', '-', '-']
            active.setQueryData(newerKey, { ...aggregate, value: 99 })
            await session.flush()
            await jest.advanceTimersByTimeAsync(1000)
            expect(await read(cacheKey(scope))).toBe(original)
            unavailable = false
            if (retry === 'timer') await jest.advanceTimersByTimeAsync(5000)
            else await session.flush()
            expect(active.getQueryData(key)).toMatchObject({ value: 42, restoredFromDevice: true })
            expect(active.getQueryState(key)?.dataUpdatedAt).toBe(savedAt)
            expect(active.getQueryData(newerKey)).toMatchObject({ value: 99 })
            await session.flush()
            expect(await store.load(scope)).toHaveLength(2)
            session.stop()
        }
    )

    it('clears every account project and pending writes on sign-out without touching another account', async () => {
        const store = new ReadCacheStore(memoryStorage())
        const other = { ...scope, account: 'account-2' }
        const entries = () => [{ key, data: aggregate, updatedAt: Date.now() }]
        await store.save(scope, entries, () => true)
        await store.save(
            { ...scope, projectId: 2 },
            () => [{ data: aggregate, updatedAt: Date.now(), key: ['views', scope.host, 2, 'web', '-'] }],
            () => true
        )
        await store.save(other, entries, () => true)
        const waiting = store.save(scope, entries, () => true)
        const clearing = store.clearAccount(scope.account)
        await Promise.all([waiting, clearing])
        expect(await store.load(scope)).toEqual([])
        expect(await store.load({ ...scope, projectId: 2 })).toEqual([])
        expect(await store.load(other)).toHaveLength(1)
    })

    it('bounds age, count and encoded size and rejects host/project mismatches', async () => {
        const now = Date.now()
        const entries = Array.from({ length: 30 }, (_, index) => ({ key, updatedAt: now - index, data: aggregate }))
        expect(boundedEntries(entries)).toHaveLength(24)
        const beyondLimit = {
            key,
            updatedAt: now - 31,
            data: {
                toJSON: () => {
                    throw new Error('Outside the entry budget')
                },
            },
        }
        expect(() => boundedEntries([...entries, beyondLimit])).not.toThrow()
        expect(boundedEntries([{ key, updatedAt: now - READ_CACHE_TTL_MS, data: aggregate }])).toEqual([])
        expect(boundedEntries([{ key, updatedAt: now, data: '界'.repeat(20_000) }])).toEqual([])
        const storage = memoryStorage()
        await storage.setItem(
            cacheKey(scope),
            JSON.stringify([
                { key: ['views', 'https://other.example.com', 1, 'web', '-'], updatedAt: now, data: aggregate },
            ])
        )
        expect(await new ReadCacheStore(storage).load(scope)).toEqual([])
        expect(cacheable(key, aggregate, { ...scope, projectId: 2 })).toBe(false)
    })
    it('purges a view denied during hydration and does not restore it on the next restart', async () => {
        const storage = memoryStorage()
        const store = new ReadCacheStore(storage)
        await store.save(
            scope,
            () => [{ key, data: aggregate, updatedAt: Date.now() }],
            () => true
        )
        const read = storage.getItem
        let finish!: () => void
        const gate = new Promise<void>((resolve) => {
            finish = resolve
        })
        storage.getItem = async (name) => {
            await gate
            return read(name)
        }
        let blocked = false
        const active = client()
        const session = persistReadCache(
            active,
            store,
            scope,
            () => true,
            () => blocked
        )
        blocked = true
        session.purgeDeniedViews()
        finish()
        await session.ready
        await session.flush()
        await store.settled()
        session.stop()
        const next = client()
        const reopened = persistReadCache(next, store, scope, () => true)
        await reopened.ready
        expect(next.getQueryData(key)).toBeUndefined()
        reopened.stop()
    })
    it('coalesces read updates and strips nested dashboard response payloads', async () => {
        const storage = memoryStorage()
        const store = new ReadCacheStore(storage)
        const active = client()
        const session = persistReadCache(active, store, scope, () => true)
        await session.ready
        const dashboard = ['views', scope.host, 1, 'dashboard', '1', '-']
        active.setQueryData(dashboard, {
            view: {
                id: 1,
                name: 'Dashboard',
                tiles: [
                    {
                        tileId: 1,
                        kind: 'insight',
                        shortId: 'view-1',
                        name: 'Count',
                        response: { persons: ['private-person-row'] },
                        query: { kind: 'HogQLQuery' },
                    },
                ],
            },
            readAt: Date.now(),
            refreshFailed: false,
        })
        active.setQueryData(key, { ...aggregate, value: 10, secretResponse: 'private-person-row' })
        active.setQueryData(key, { ...aggregate, value: 20, secretResponse: 'private-person-row' })
        expect(await storage.getItem(cacheKey(scope))).toBeNull()
        await jest.advanceTimersByTimeAsync(500)
        await store.settled()
        const raw = await storage.getItem(cacheKey(scope))
        expect(raw).not.toContain('private-person-row')
        expect(raw).not.toContain('HogQLQuery')
        expect((await store.load(scope)).find((entry) => entry.key[3] === 'insight')?.data).toMatchObject({ value: 20 })
        session.stop()
    })
    it('does not renew the offline TTL when an attempted refresh only updates failure metadata', async () => {
        const store = new ReadCacheStore(memoryStorage())
        const active = client()
        const session = persistReadCache(active, store, scope, () => true)
        await session.ready
        const savedAt = Date.now()
        active.setQueryData(key, { ...aggregate, refreshFailed: false })
        await session.flush()
        jest.setSystemTime(savedAt + READ_CACHE_TTL_MS - 1000)
        active.setQueryData(key, { ...aggregate, readAt: Date.now(), refreshFailed: true })
        await session.flush()
        expect((await store.load(scope))[0]?.updatedAt).toBe(savedAt)
        jest.setSystemTime(savedAt + READ_CACHE_TTL_MS + 1000)
        active.setQueryData(key, { ...aggregate, readAt: Date.now(), refreshFailed: true })
        await session.flush()
        expect(await store.load(scope)).toEqual([])
        session.stop()
    })

    it('keeps a retained result age when a metadata-only insight or web read misses the server cache', async () => {
        const store = new ReadCacheStore(memoryStorage())
        const active = client()
        const session = persistReadCache(active, store, scope, () => true)
        await session.ready
        const savedAt = Date.now()
        const response = {
            id: 1,
            short_id: 'view-1',
            name: 'Count',
            derived_name: null,
            query: {
                kind: 'InsightVizNode',
                source: { kind: 'TrendsQuery', series: [{ kind: 'EventsNode', event: 'example' }] },
            },
            result: [{ action: { order: 0 }, days: ['2026-10-01'], data: [42] }],
            last_refresh: new Date(savedAt).toISOString(),
            cache_target_age: null,
            next_allowed_client_refresh: null,
        }
        const original = insightSnapshot(response, undefined, { readAt: savedAt, serverNow: savedAt })
        const originalWeb = webOverviewSnapshot(
            { results: [{ key: 'visitors', kind: 'unit', value: 42 }] },
            undefined,
            savedAt
        )
        const webKey = ['views', scope.host, 1, 'web', '-']
        active.setQueryData(key, original)
        active.setQueryData(webKey, originalWeb)
        await session.flush()
        jest.setSystemTime(savedAt + READ_CACHE_TTL_MS - 1000)
        const miss = insightSnapshot({ ...response, result: null }, original, {
            readAt: Date.now(),
            serverNow: Date.now(),
        })
        active.setQueryData(key, miss)
        active.setQueryData(webKey, webOverviewSnapshot({}, originalWeb, Date.now()))
        await session.flush()
        expect((await store.load(scope)).map((entry) => entry.updatedAt)).toEqual([savedAt, savedAt])
        jest.setSystemTime(savedAt + READ_CACHE_TTL_MS + 1000)
        active.setQueryData(
            key,
            insightSnapshot({ ...response, result: null }, miss, { readAt: Date.now(), serverNow: Date.now() })
        )
        active.setQueryData(webKey, webOverviewSnapshot({}, originalWeb, Date.now()))
        await session.flush()
        expect(await store.load(scope)).toEqual([])
        session.stop()
    })

    test.each(['insight', 'web'] as const)(
        'restores %s results after a metadata-only read during hydration',
        async (kind) => {
            const storage = memoryStorage()
            const store = new ReadCacheStore(storage)
            const savedAt = Date.now() - 1000
            const response = {
                id: 1,
                short_id: 'view-1',
                name: 'Saved name',
                derived_name: null,
                query: {
                    kind: 'InsightVizNode',
                    source: { kind: 'TrendsQuery', series: [{ kind: 'EventsNode', event: 'example' }] },
                },
                result: [{ action: { order: 0 }, days: ['2026-09-30'], data: [42], count: 42 }],
                last_refresh: new Date(savedAt).toISOString(),
                cache_target_age: null,
                next_allowed_client_refresh: null,
            }
            const target = kind === 'insight' ? key : ['views', scope.host, 1, 'web', '-']
            const original =
                kind === 'insight'
                    ? insightSnapshot(response, undefined, { readAt: savedAt, serverNow: savedAt })
                    : webOverviewSnapshot(
                          { results: [{ key: 'visitors', kind: 'unit', value: 42 }] },
                          undefined,
                          savedAt
                      )
            await store.save(
                scope,
                () => [{ key: target, data: original, updatedAt: savedAt }],
                () => true
            )
            const read = storage.getItem
            let finish!: () => void
            const gate = new Promise<void>((resolve) => {
                finish = resolve
            })
            storage.getItem = async (name) => {
                await gate
                return read(name)
            }
            const active = client()
            const session = persistReadCache(active, store, scope, () => true)
            const placeholder =
                kind === 'insight'
                    ? insightSnapshot({ ...response, name: 'Current name', result: null }, undefined, {
                          readAt: Date.now(),
                          serverNow: Date.now(),
                      })
                    : webOverviewSnapshot({}, undefined, Date.now())
            active.setQueryData(target, placeholder)
            finish()
            await session.ready
            expect(active.getQueryData(target)).toMatchObject({
                dataReadAt: savedAt,
                readAt: Date.now(),
                restoredFromDevice: true,
            })
            if (kind === 'insight')
                expect(active.getQueryData(target)).toMatchObject({ value: 42, name: 'Current name' })
            else
                expect(active.getQueryData(target)).toMatchObject({
                    metrics: expect.arrayContaining([expect.objectContaining({ value: 42 })]),
                })
            await session.flush()
            expect((await store.load(scope))[0]?.updatedAt).toBe(savedAt)
            session.stop()
        }
    )

    it('retains a hydrated inbox until its first visit after the normal query GC interval', async () => {
        const store = new ReadCacheStore(memoryStorage())
        const inbox = inboxCacheKey(scope)
        await store.save(
            scope,
            () => [
                {
                    key: inbox,
                    data: { items: [], signalCounts: { report: 12 }, sourceUpdatedAt: Date.now() },
                    updatedAt: Date.now(),
                },
            ],
            () => true
        )
        const active = new QueryClient({ defaultOptions: { queries: { gcTime: 5 * 60_000 } } })
        const session = persistReadCache(active, store, scope, () => true)
        await session.ready
        await jest.advanceTimersByTimeAsync(6 * 60_000)
        expect(active.getQueryData(inbox)).toMatchObject({ items: [], signalCounts: { report: 12 } })
        session.stop()
        active.clear()
    })

    it('bounds a full hydration batch without repeatedly serializing earlier entries', async () => {
        const storage = memoryStorage()
        const entries = Array.from({ length: 24 }, (_, index) => ({
            key: [...key.slice(0, 4), String(index), '-', '-'],
            data: { ...aggregate, value: String(index) },
            updatedAt: Date.now(),
        }))
        await storage.setItem(cacheKey(scope), JSON.stringify(entries))
        const stringify = jest.spyOn(JSON, 'stringify')
        const active = client()
        const session = persistReadCache(active, new ReadCacheStore(storage), scope, () => true)
        await session.ready
        const serializedEntries = stringify.mock.calls.filter(
            ([value]) => typeof value === 'object' && value !== null && 'updatedAt' in value
        ).length
        stringify.mockRestore()
        expect(serializedEntries).toBeLessThanOrEqual(entries.length * 2)
        expect(active.getQueryCache().getAll()).toHaveLength(24)
        session.stop()
    })

    it('writes only changed entries in a full project and removes all payloads on logout', async () => {
        const storage = memoryStorage()
        const store = new ReadCacheStore(storage)
        const entries = Array.from({ length: 24 }, (_, index) => ({
            key: [...key.slice(0, 4), String(index), '-', '-'],
            data: { ...aggregate, series: 'x'.repeat(5000) },
            updatedAt: Date.now(),
        }))
        const write = jest.spyOn(storage, 'setItem')
        await store.save(
            scope,
            () => entries,
            () => true
        )
        expect(await store.load(scope)).toHaveLength(24)
        write.mockClear()
        const changed = entries[0]
        if (!changed) throw new Error('Missing full-cache fixture')
        entries[0] = { ...changed, data: { ...changed.data, value: 43 } }
        await store.save(
            scope,
            () => entries,
            () => true
        )
        expect(write).toHaveBeenCalledTimes(1)
        expect(write.mock.calls[0]?.[1].length).toBeLessThan(6000)
        write.mockClear()
        await store.save(
            scope,
            () => entries,
            () => true
        )
        expect(write).not.toHaveBeenCalled()
        await store.clearAccount(scope.account)
        expect(await store.load(scope)).toEqual([])
        for (let slot = 0; slot < 24; slot++)
            expect(await storage.getItem(`${cacheKey(scope)}.entry.${slot}`)).toBeNull()
    })

    it('keeps disk copies after query garbage collection and still purges denied resource variants', async () => {
        const store = new ReadCacheStore(memoryStorage())
        const otherRange = [...key.slice(0, -1), 'other-range']
        await store.save(
            scope,
            () => [key, otherRange].map((variant) => ({ key: variant, data: aggregate, updatedAt: Date.now() })),
            () => true
        )
        const active = client()
        const session = persistReadCache(active, store, scope, () => true)
        await session.ready
        active.removeQueries()
        await session.flush()
        expect(await store.load(scope)).toHaveLength(2)
        await active
            .fetchQuery({
                queryKey: key,
                queryFn: async () => {
                    throw new ApiError(403, {})
                },
            })
            .catch(() => undefined)
        await store.settled()
        session.stop()
        const next = client()
        const restored = persistReadCache(next, store, scope, () => true)
        await restored.ready
        expect(next.getQueryData(key)).toBeUndefined()
        expect(next.getQueryData(otherRange)).toBeUndefined()
        restored.stop()
    })

    it('keeps at most eight recently saved projects without touching the draft namespace', async () => {
        const storage = memoryStorage()
        const store = new ReadCacheStore(storage)
        await storage.setItem('mobile-drafts-example', 'Keep draft')
        for (let projectId = 1; projectId <= 9; projectId++) {
            const target = { ...scope, projectId }
            await store.save(
                target,
                () => [
                    { key: ['views', scope.host, projectId, 'web', '-'], data: { metrics: [] }, updatedAt: Date.now() },
                ],
                () => true
            )
        }
        expect(await store.load(scope)).toEqual([])
        expect(await store.load({ ...scope, projectId: 9 })).toHaveLength(1)
        expect(JSON.parse((await storage.getItem(`${scope.account}.scopes`)) ?? '[]')).toHaveLength(8)
        expect(await storage.getItem('mobile-drafts-example')).toBe('Keep draft')
    })
    test.each([
        { name: 'offline', error: new TypeError('Offline') },
        { name: 'server error', error: new ApiError(500, {}) },
    ])('keeps a saved value after transient refetch failure: $name', async ({ error }) => {
        const store = new ReadCacheStore(memoryStorage())
        const updatedAt = Date.now() - 60_000
        await store.save(
            scope,
            () => [{ key, data: aggregate, updatedAt }],
            () => true
        )
        const active = client()
        const session = persistReadCache(active, store, scope, () => true)
        await session.ready
        await active
            .fetchQuery({
                queryKey: key,
                queryFn: async () => {
                    throw error
                },
            })
            .catch(() => undefined)
        expect(active.getQueryData(key)).toMatchObject({ value: 42 })
        await session.flush()
        session.stop()
        const next = client()
        const restored = persistReadCache(next, store, scope, () => true)
        await restored.ready
        expect(next.getQueryData(key)).toMatchObject({ value: 42 })
        expect(next.getQueryState(key)?.dataUpdatedAt).toBe(updatedAt)
        restored.stop()
    })

    it('respects a permission denial that arrived before the cache lifecycle started', async () => {
        const store = new ReadCacheStore(memoryStorage())
        const otherRange = [...key.slice(0, -1), 'other-range']
        await store.save(
            scope,
            () => [key, otherRange].map((variant) => ({ key: variant, data: aggregate, updatedAt: Date.now() })),
            () => true
        )
        const active = client()
        active.setQueryData(key, aggregate)
        await active
            .fetchQuery({
                queryKey: key,
                queryFn: async () => {
                    throw new ApiError(403, {})
                },
            })
            .catch(() => undefined)
        const session = persistReadCache(active, store, scope, () => true)
        await session.ready
        expect(active.getQueryData(otherRange)).toBeUndefined()
        await session.flush()
        session.stop()
        const next = client()
        const restored = persistReadCache(next, store, scope, () => true)
        await restored.ready
        expect(next.getQueryData(otherRange)).toBeUndefined()
        restored.stop()
    })

    it('finishes denying an old project even when the active project changes during disk access', async () => {
        const storage = memoryStorage()
        const store = new ReadCacheStore(storage)
        await store.save(
            scope,
            () => [{ key, data: aggregate, updatedAt: Date.now() }],
            () => true
        )
        let current = true
        const active = client()
        const session = persistReadCache(active, store, scope, () => current)
        await session.ready
        let started!: () => void
        let finish!: () => void
        const reading = new Promise<void>((resolve) => {
            started = resolve
        })
        const gate = new Promise<void>((resolve) => {
            finish = resolve
        })
        const read = storage.getItem
        storage.getItem = async (name) => {
            if (name === `${scope.account}.scopes` || name === cacheKey(scope)) {
                started()
                await gate
            }
            return read(name)
        }
        await active
            .fetchQuery({
                queryKey: key,
                queryFn: async () => {
                    throw new ApiError(403, {})
                },
            })
            .catch(() => undefined)
        await reading
        current = false
        finish()
        await store.settled()
        session.stop()
        const next = client()
        const restored = persistReadCache(next, store, scope, () => true)
        await restored.ready
        expect(next.getQueryData(key)).toBeUndefined()
        restored.stop()
    })

    it('does not resurrect denied data after an older device write finishes late', async () => {
        const storage = memoryStorage()
        const store = new ReadCacheStore(storage)
        const active = client()
        const session = persistReadCache(active, store, scope, () => true)
        await session.ready
        let started!: () => void
        let finish!: () => void
        const writing = new Promise<void>((resolve) => {
            started = resolve
        })
        const gate = new Promise<void>((resolve) => {
            finish = resolve
        })
        const write = storage.setItem
        let delayed = false
        storage.setItem = async (name, value) => {
            if (name === cacheKey(scope) && !delayed) {
                delayed = true
                started()
                await gate
            }
            await write(name, value)
        }
        active.setQueryData(key, aggregate)
        const pending = session.flush()
        await writing
        await active
            .fetchQuery({
                queryKey: key,
                queryFn: async () => {
                    throw new ApiError(403, {})
                },
            })
            .catch(() => undefined)
        finish()
        await pending
        await store.settled()
        session.stop()
        const next = client()
        const restored = persistReadCache(next, store, scope, () => true)
        await restored.ready
        expect(next.getQueryData(key)).toBeUndefined()
        restored.stop()
    })
})
