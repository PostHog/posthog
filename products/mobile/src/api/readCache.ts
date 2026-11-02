import type { QueryClient, QueryKey } from '@tanstack/react-query'
import { asRecord } from '@/lib/records'
import { cacheable, isReadCacheKey, projectedData } from '@/model/adapters/readCache'
import { ApiError } from './client'
import { inboxCacheKey } from './readCacheKeys'
import type { ReadCacheEntry, ReadCacheScope, ReadCacheStore } from './readCacheStore'

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
    const remember = (key: QueryKey, data: unknown, updatedAt: number): void => {
        if (cacheable(key, data, scope) && asRecord(data)?.refreshFailed !== true) {
            good.set(keyId(key), { key, data: projectedData(key, data), updatedAt })
        }
    }
    for (const query of client.getQueryCache().getAll()) {
        remember(query.queryKey, query.state.data, query.state.dataUpdatedAt)
    }
    const collect = (): ReadCacheEntry[] =>
        client
            .getQueryCache()
            .getAll()
            .flatMap((query) => {
                const { queryKey: key, state } = query
                remember(key, state.data, state.dataUpdatedAt)
                const entry = good.get(keyId(key))
                return entry &&
                    state.status === 'success' &&
                    !denied.has(keyId(key)) &&
                    !deniedResources.has(resourceKey(key)) &&
                    !deniedView(key) &&
                    cacheable(key, state.data, scope)
                    ? [entry]
                    : []
            })
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
        for (const query of client.getQueryCache().getAll()) {
            if (resourceKey(query.queryKey) === resourceKey(key)) clear(query.queryKey)
        }
    }
    const unsubscribe = client.getQueryCache().subscribe((event) => {
        if (
            !valid() ||
            restoring ||
            event.type === 'observerResultsUpdated' ||
            event.type === 'observerAdded' ||
            event.type === 'observerRemoved' ||
            event.type === 'observerOptionsUpdated'
        )
            return
        if (
            event.type === 'updated' &&
            event.action.type === 'error' &&
            deniedRead(event.query.state.error) &&
            (isReadCacheKey(event.query.queryKey, scope) ||
                (event.query.queryKey[0] === 'signals' && event.query.queryKey[3] === 'inbox'))
        ) {
            clearResource(event.query.queryKey)
            const key = event.query.queryKey
            if (key[0] === 'signals' && key[3] === 'inbox' && key[1] === scope.host && key[2] === scope.projectId)
                clear(inboxCacheKey(scope))
            void flush()
        } else if (
            event.type === 'updated' &&
            event.action.type === 'success' &&
            isReadCacheKey(event.query.queryKey, scope)
        ) {
            denied.delete(keyId(event.query.queryKey))
            remember(event.query.queryKey, event.query.state.data, event.query.state.dataUpdatedAt)
            deniedResources.delete(resourceKey(event.query.queryKey))
            save()
        } else if (event.type === 'removed' && isReadCacheKey(event.query.queryKey, scope)) {
            good.delete(keyId(event.query.queryKey))
            save()
        }
    })
    const purgeDeniedViews = (): void => {
        let purged = false
        for (const query of client.getQueryCache().getAll()) {
            if (deniedView(query.queryKey)) {
                clearResource(query.queryKey)
                purged = true
            }
        }
        if (purged) void flush()
    }
    const ready = (async (): Promise<void> => {
        try {
            const entries = await store.load(scope)
            if (!valid()) return
            restoring = true
            for (const entry of entries) {
                if (deniedView(entry.key)) deniedResources.add(resourceKey(entry.key))
            }
            for (const entry of entries) {
                if (
                    !cacheable(entry.key, entry.data, scope) ||
                    denied.has(keyId(entry.key)) ||
                    deniedResources.has(resourceKey(entry.key)) ||
                    deniedView(entry.key)
                )
                    continue
                const known = good.get(keyId(entry.key))
                if (!known || known.updatedAt < entry.updatedAt) good.set(keyId(entry.key), entry)
                const state = client.getQueryState(entry.key)
                if (deniedRead(state?.error) || (state?.dataUpdatedAt ?? 0) >= entry.updatedAt) continue
                const data =
                    entry.key[0] === 'views'
                        ? { ...asRecord(projectedData(entry.key, entry.data)), restoredFromDevice: true }
                        : projectedData(entry.key, entry.data)
                client.setQueryData(entry.key, data, { updatedAt: entry.updatedAt })
            }
        } finally {
            restoring = false
            loading = false
            if (denied.size || deniedResources.size) await flush()
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
