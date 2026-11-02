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
    deniedView: (key: QueryKey) => boolean = () => false
): { ready: Promise<void>; stop: () => void; purgeDeniedViews: () => void; flush: () => Promise<void> } {
    let stopped = false
    let loading = true
    let restoring = false
    const denied = new Set<string>()
    const deniedResources = new Set<string>()
    const good = new Map<string, ReadCacheEntry>()
    const valid = (): boolean => !stopped && current()
    const keep = (entry: ReadCacheEntry): void => {
        const entries = boundedEntries(
            [...good.values()].filter((saved) => keyId(saved.key) !== keyId(entry.key)).concat(entry)
        )
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
        keep({ key, data: projectedData(key, data), updatedAt: capture })
    }
    for (const query of client.getQueryCache().getAll()) {
        remember(query.queryKey, query.state.data, query.state.dataUpdatedAt)
    }
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
        if (!loading && valid()) await store.save(scope, collect, valid).catch(() => undefined)
    }
    const save = (): void => {
        if (loading || !valid() || timer) return
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
        deniedResources.delete(resourceKey(query.queryKey))
        save()
    }
    const unsubscribe = client.getQueryCache().subscribe((event) => {
        if (!valid() || restoring) return
        if (event.type === 'updated') {
            if (event.action.type === 'error') onError(event.query)
            if (event.action.type === 'success') onSuccess(event.query)
        }
    })
    for (const query of client.getQueryCache().getAll()) onError(query)
    const purgeDeniedViews = (): void => {
        let purged = false
        const keys = [...good.values()]
            .map((entry) => entry.key)
            .concat(
                client
                    .getQueryCache()
                    .getAll()
                    .map((query) => query.queryKey)
            )
        for (const key of keys) {
            if (deniedView(key)) {
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
        const known = good.get(keyId(entry.key))
        if (!known || known.updatedAt < entry.updatedAt) keep(entry)
        const state = client.getQueryState(entry.key)
        if (deniedRead(state?.error) || (state?.dataUpdatedAt ?? 0) >= entry.updatedAt) return
        const projected = projectedData(entry.key, entry.data)
        const data = entry.key[0] === 'views' ? { ...asRecord(projected), restoredFromDevice: true } : projected
        client.setQueryData(entry.key, data, { updatedAt: entry.updatedAt })
    }
    const ready = (async (): Promise<void> => {
        try {
            const entries = await store.load(scope)
            if (!valid()) return
            restoring = true
            for (const entry of entries) {
                if (deniedView(entry.key)) deniedResources.add(resourceKey(entry.key))
            }
            for (const entry of entries) restore(entry)
        } finally {
            restoring = false
            loading = false
            if (valid() && (denied.size || deniedResources.size)) await evictDenied()
            else save()
        }
    })().catch(() => undefined)
    return {
        ready,
        purgeDeniedViews,
        flush,
        stop: () => {
            stopped = true
            if (timer) clearTimeout(timer)
            unsubscribe()
        },
    }
}
