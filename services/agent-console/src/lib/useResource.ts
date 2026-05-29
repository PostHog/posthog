/**
 * `useResource` — minimal data-fetching hook.
 *
 * Wraps a promise factory in `{ data, error, loading, reload }`. Used
 * everywhere the console reads from `apiClient`. Intentionally tiny —
 * react-query is overkill for v0; if we need cache invalidation,
 * suspense, retries, etc. we'll swap to it later.
 *
 * The `reloadKey` is bumped externally to force a refetch (mutation
 * stream events use this to refresh underlying data).
 */

'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

export interface ResourceState<T> {
    data: T | null
    error: Error | null
    loading: boolean
    reload: () => void
}

export function useResource<T>(factory: () => Promise<T>, deps: unknown[] = []): ResourceState<T> {
    const [data, setData] = useState<T | null>(null)
    const [error, setError] = useState<Error | null>(null)
    const [loading, setLoading] = useState(true)
    const [reloadKey, setReloadKey] = useState(0)
    const reqIdRef = useRef(0)
    const factoryRef = useRef(factory)
    factoryRef.current = factory

    useEffect(() => {
        const myReqId = ++reqIdRef.current
        setLoading(true)
        factoryRef
            .current()
            .then((result) => {
                if (myReqId !== reqIdRef.current) {
                    return
                }
                setData(result)
                setError(null)
                setLoading(false)
            })
            .catch((err) => {
                if (myReqId !== reqIdRef.current) {
                    return
                }
                setError(err instanceof Error ? err : new Error(String(err)))
                setLoading(false)
            })
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [...deps, reloadKey])

    const reload = useCallback(() => setReloadKey((k) => k + 1), [])

    return { data, error, loading, reload }
}
