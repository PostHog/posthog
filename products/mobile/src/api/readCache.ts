import type { Query, QueryClient, QueryKey } from '@tanstack/react-query'
import { asRecord } from '@/lib/records'
import { cacheable, isReadCacheKey, projectedData } from '@/model/adapters/readCache'
import { ApiError } from './client'
import { inboxCacheKey } from './readCacheKeys'
import { boundedEntries, type ReadCacheEntry, type ReadCacheScope, type ReadCacheStore } from './readCacheStore'

export function deniedRead(error: unknown): boolean {
    return error instanceof ApiError && [401, 403, 404].includes(error.status)
}

function keyId(key: QueryKey): string {
    return JSON.stringify(key)
}

function resourceKey(key: QueryKey): string {
    return keyId(key[0] === 'views' ? key.slice(0, key[3] === 'web' ? 4 : 5) : key)
}

export function persistReadCache(
    client: QueryClient,
    store: ReadCacheStore,
    scope: ReadCacheScope,
    current: () => boolean,
    deniedView: (key: QueryKey) => boolean = () => false,
    sameAccount: () => boolean = current
): {
    ready: Promise<void>
    pause: () => void
    stop: () => void
    purgeDeniedViews: (keys?: readonly QueryKey[]) => void
    flush: () => Promise<void>
} {
    // Saved inbox queries cannot refetch, so retain them before hydration creates inactive queries.
    client.setQueryDefaults(['read-inbox'], { gcTime: Infinity })
    let stopped = false
    let loading = false
    let hydrated = false
    let retryTimer: ReturnType<typeof setTimeout> | undefined
    let restoring = false
    const denied = new Set<string>()
    const deniedResources = new Set<string>()
    const good = new Map<string, ReadCacheEntry>()
    const valid = (): boolean => !stopped && current()
    const keep = (candidates: readonly ReadCacheEntry[]): void => {
        const entries = boundedEntries(candidates)
        good.clear()
        for (const saved of entries) good.set(keyId(saved.key), saved)
    }
    const remember = (key: QueryKey, data: unknown, updatedAt: number): void => {
        if (!cacheable(key, data, scope)) {
            good.delete(keyId(key))
            return
        }
        const value = asRecord(data)
        if (!value || value.refreshFailed === true) return
        let capture = updatedAt
        if (typeof value.dataReadAt === 'number') capture = value.dataReadAt
        else if (value.restoredFromDevice === true) capture = good.get(keyId(key))?.updatedAt ?? updatedAt
        if (capture <= 0) return
        good.set(keyId(key), { key, data: projectedData(key, data), updatedAt: capture })
    }
    for (const query of client.getQueryCache().getAll()) {
        remember(query.queryKey, query.state.data, query.state.dataUpdatedAt)
    }
    keep([...good.values()])
    const collect = (): ReadCacheEntry[] =>
        boundedEntries([...good.values()]).filter(
            ({ key, data }) =>
                !deniedRead(client.getQueryState(key)?.error) &&
                !denied.has(keyId(key)) &&
                !deniedResources.has(resourceKey(key)) &&
                !deniedView(key) &&
                cacheable(key, data, scope)
        )
    let timer: ReturnType<typeof setTimeout> | undefined
    const flush = async (): Promise<void> => {
        if (timer) clearTimeout(timer)
        timer = undefined
        if (!hydrated && valid()) await hydrate()
        if (hydrated && valid()) await store.save(scope, collect, valid).catch(() => undefined)
    }
    const save = (): void => {
        if (!hydrated || loading || !valid() || timer) return
        timer = setTimeout(() => {
            timer = undefined
            void flush()
        }, 500)
    }
    const clear = (key: QueryKey): void => {
        denied.add(keyId(key))
        good.delete(keyId(key))
        const query = client.getQueryCache().find({ queryKey: key, exact: true })
        if (query?.state.data !== undefined) query.setState({ data: undefined, dataUpdatedAt: 0 })
    }
    const clearResource = (key: QueryKey): void => {
        deniedResources.add(resourceKey(key))
        for (const saved of good.values()) {
            if (resourceKey(saved.key) === resourceKey(key)) good.delete(keyId(saved.key))
        }
        for (const query of client.getQueryCache().getAll()) {
            if (resourceKey(query.queryKey) === resourceKey(key)) clear(query.queryKey)
        }
    }
    const isInboxSource = (key: QueryKey): boolean =>
        key[0] === 'signals' && key[3] === 'inbox' && key[1] === scope.host && key[2] === scope.projectId
    const denyQuery = (key: QueryKey): void => {
        clearResource(key)
        if (isInboxSource(key)) clear(inboxCacheKey(scope))
    }
    const evictDenied = (): Promise<void> => {
        const resources = new Set(deniedResources)
        const keys = new Set(denied)
        return store
            .evict(
                scope,
                (entry) => resources.has(resourceKey(entry.key)) || keys.has(keyId(entry.key)) || deniedView(entry.key)
            )
            .catch(() => undefined)
    }
    const onError = (query: Query): void => {
        if (!deniedRead(query.state.error)) return
        if (!isReadCacheKey(query.queryKey, scope) && !isInboxSource(query.queryKey)) return
        denyQuery(query.queryKey)
        // Leaving a project cancels saves, but its known-denied copies must still be removed.
        void evictDenied()
    }
    const onSuccess = (query: Query): void => {
        if (!isReadCacheKey(query.queryKey, scope)) return
        denied.delete(keyId(query.queryKey))
        remember(query.queryKey, query.state.data, query.state.dataUpdatedAt)
        keep([...good.values()])
        deniedResources.delete(resourceKey(query.queryKey))
        save()
    }
    const unsubscribe = client.getQueryCache().subscribe((event) => {
        if (restoring || event.type !== 'updated') return
        if (sameAccount() && event.action.type === 'error') onError(event.query)
        if (valid() && event.action.type === 'success') onSuccess(event.query)
    })
    for (const query of client.getQueryCache().getAll()) onError(query)
    const purgeDeniedViews = (extraKeys: readonly QueryKey[] = []): void => {
        if (!sameAccount()) return
        let purged = false
        const keys = [...good.values()]
            .map((entry) => entry.key)
            .concat(
                extraKeys,
                client
                    .getQueryCache()
                    .getAll()
                    .map((query) => query.queryKey)
            )
        for (const key of keys) {
            if (isReadCacheKey(key, scope) && deniedView(key)) {
                clearResource(key)
                purged = true
            }
        }
        if (purged) void evictDenied()
    }
    const mayRestore = (entry: ReadCacheEntry): boolean =>
        cacheable(entry.key, entry.data, scope) &&
        !denied.has(keyId(entry.key)) &&
        !deniedResources.has(resourceKey(entry.key)) &&
        !deniedView(entry.key)
    const restore = (entry: ReadCacheEntry): void => {
        if (!mayRestore(entry)) return
        const state = client.getQueryState(entry.key)
        const currentData = asRecord(state?.data)
        const capturedAt =
            typeof currentData?.dataReadAt === 'number' ? currentData.dataReadAt : (state?.dataUpdatedAt ?? 0)
        if (deniedRead(state?.error) || capturedAt >= entry.updatedAt) return
        const projected = projectedData(entry.key, entry.data)
        const data =
            entry.key[0] === 'views'
                ? {
                      ...asRecord(projected),
                      ...(currentData && capturedAt === 0
                          ? Object.fromEntries(
                                [
                                    'readAt',
                                    'refreshFailed',
                                    'name',
                                    'description',
                                    'query',
                                    'savedRange',
                                    'usesOwnRange',
                                    'kindLabel',
                                    'createdBy',
                                    'createdAt',
                                ]
                                    .filter((name) => name in currentData)
                                    .map((name) => [name, currentData[name]])
                            )
                          : {}),
                      restoredFromDevice: true,
                  }
                : projected
        client.setQueryData(entry.key, data, { updatedAt: entry.updatedAt })
    }
    const hydrate = async (): Promise<void> => {
        if (loading || hydrated || !valid()) return
        if (retryTimer) clearTimeout(retryTimer)
        retryTimer = undefined
        loading = true
        try {
            const entries = await store.load(scope)
            if (!valid()) return
            restoring = true
            for (const entry of entries) {
                if (deniedView(entry.key)) deniedResources.add(resourceKey(entry.key))
            }
            const merged = new Map(good)
            for (const entry of entries) {
                if (!mayRestore(entry)) continue
                const known = merged.get(keyId(entry.key))
                if (!known || known.updatedAt < entry.updatedAt) merged.set(keyId(entry.key), entry)
            }
            keep([...merged.values()])
            for (const entry of good.values()) restore(entry)
            hydrated = true
        } catch {
            if (valid()) retryTimer = setTimeout(() => void hydrate(), 5000)
        } finally {
            restoring = false
            loading = false
            if (hydrated) {
                if (valid() && (denied.size || deniedResources.size)) await evictDenied()
                else save()
            }
        }
    }
    const ready = hydrate()
    const pause = (): void => {
        stopped = true
        good.clear()
        if (timer) clearTimeout(timer)
        if (retryTimer) clearTimeout(retryTimer)
    }
    return {
        ready,
        pause,
        purgeDeniedViews,
        flush,
        stop: () => {
            pause()
            unsubscribe()
        },
    }
}
