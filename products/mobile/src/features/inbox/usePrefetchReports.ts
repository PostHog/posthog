import {
    type DefaultError,
    type FetchQueryOptions,
    type QueryClient,
    type QueryKey,
    useIsFetching,
    useQueryClient,
} from '@tanstack/react-query'
import { NetworkStateType } from 'expo-network'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ViewabilityConfig, ViewToken } from 'react-native'

import { isMissingFeature, type ProjectScope } from '@/api/reports'
import { useAuthStore } from '@/auth/authStore'
import { sessionGeneration } from '@/auth/tokens'
import { useProjectScope } from '@/auth/useProjectScope'
import { useDataMode } from '@/demo/demoMode'
import { useAppActive } from '@/features/handoff/useTaskRun'
import { useConnectivity } from '@/lib/connectivity'
import type { InboxItem } from '@/model/types'

import { reportArtefactsQuery, reportDetailQuery, reportPageQuery, reportSignalsQuery } from '../report/queries'
import { createPrefetchQueue, type PrefetchQueue, prefetchRows, prefetchWindow } from './prefetchPlan'

// The inbox refetches often (pull to refresh, the 5 s briefing poll), so a shorter stale time would prefetch the whole
// window again on each refresh. The report screen refetches on open anyway.
const PREFETCH_STALE_MS = 5 * 60_000

const VIEWABILITY_CONFIG: ViewabilityConfig = { itemVisiblePercentThreshold: 10 }

export interface ReportPrefetchListProps {
    onViewableItemsChanged: (info: { viewableItems: ViewToken<InboxItem>[]; changed: ViewToken<InboxItem>[] }) => void
    viewabilityConfig: ViewabilityConfig
}

// A failed query is always stale, so without this check every scroll would ask again for the Today page of each report
// in the window when the project has no Today.
function knownMissing(queryClient: QueryClient, scope: ProjectScope, reportId: string): boolean {
    const page = queryClient.getQueryState(reportPageQuery(scope, reportId).queryKey)
    return (
        page?.status === 'error' && isMissingFeature(page.error) && Date.now() - page.errorUpdatedAt < PREFETCH_STALE_MS
    )
}

async function prefetchReport(
    queryClient: QueryClient,
    scope: ProjectScope,
    reportId: string,
    signal: AbortSignal,
    owned: Set<QueryKey>,
    wanted: () => boolean
): Promise<void> {
    const prefetch = async <TData, TKey extends QueryKey>(
        options: FetchQueryOptions<TData, DefaultError, TData, TKey>
    ): Promise<void> => {
        if (
            signal.aborted ||
            !wanted() ||
            queryClient.isFetching({ predicate: (query) => query.getObserversCount() > 0 }) > 0
        )
            return
        const query = queryClient.getQueryCache().find({ queryKey: options.queryKey, exact: true })
        if (query && (query.getObserversCount() > 0 || query.state.fetchStatus !== 'idle')) return
        const configuredRetry = queryClient.defaultQueryOptions(options).retry
        const retry = (failureCount: number, error: DefaultError): boolean => {
            const current = queryClient.getQueryCache().find({ queryKey: options.queryKey, exact: true })
            if (!current || current.getObserversCount() === 0) return false
            // The retryer captures this callback, even after an opened report replaces the query's options.
            const policy = current.options.retry === retry ? configuredRetry : current.options.retry
            return typeof policy === 'function'
                ? policy(failureCount, error)
                : policy === true || (typeof policy === 'number' && failureCount < policy)
        }
        owned.add(options.queryKey)
        try {
            await queryClient.prefetchQuery({ ...options, staleTime: PREFETCH_STALE_MS, retry })
        } finally {
            owned.delete(options.queryKey)
        }
    }
    await prefetch(reportDetailQuery(scope, reportId))
    await prefetch(reportArtefactsQuery(scope, reportId))
    if (!knownMissing(queryClient, scope, reportId)) await prefetch(reportPageQuery(scope, reportId))
    const page = queryClient.getQueryState(reportPageQuery(scope, reportId).queryKey)
    if (page?.status === 'error' && isMissingFeature(page.error)) {
        await prefetch(reportSignalsQuery(scope, reportId))
    }
}

/** Shares the report screen's cache so visible rows can open from a prefetched copy. */
export function usePrefetchReports(items: InboxItem[] | undefined, focused: boolean): ReportPrefetchListProps {
    const queryClient = useQueryClient()
    const live = useDataMode() === 'live'
    const scope = useProjectScope()
    const account = useAuthStore((state) => JSON.stringify([state.user?.uuid, sessionGeneration()]))
    const accountRef = useRef(account)
    accountRef.current = account
    const active = useAppActive()
    const connected = useConnectivity(
        (state) =>
            state.status === 'connected' &&
            (state.type === NetworkStateType.WIFI || state.type === NetworkStateType.ETHERNET)
    )
    const foregroundFetching = useIsFetching({ predicate: (query) => query.getObserversCount() > 0 })
    const enabled = live && scope !== null && focused && active && connected && foregroundFetching === 0
    const scopeKey = scope ? JSON.stringify([scope.host, scope.projectId, account]) : ''
    const scopeKeyRef = useRef(scopeKey)
    scopeKeyRef.current = scopeKey
    const queueRef = useRef<PrefetchQueue | null>(null)
    const [visible, setVisible] = useState<{ first: number; last: number; scopeKey: string } | null>(null)
    const rows = useMemo(() => prefetchRows(items ?? []), [items])
    const currentVisible = visible?.scopeKey === scopeKey ? visible : null
    const ids = prefetchWindow(rows, currentVisible)
    const idsKey = ids.join(',')
    const idsRef = useRef(ids)
    idsRef.current = ids

    useEffect(() => {
        if (!enabled || !scope) return
        const controller = new AbortController()
        const owned = new Set<QueryKey>()
        const queue = createPrefetchQueue((id) =>
            prefetchReport(
                queryClient,
                scope,
                id,
                controller.signal,
                owned,
                () => accountRef.current === account && idsRef.current.includes(id)
            )
        )
        queueRef.current = queue
        return () => {
            controller.abort()
            queue.reset()
            queueRef.current = null
            for (const queryKey of owned) {
                // A report opened since prefetch began owns the shared request now. Leave its observed reads running.
                void queryClient.cancelQueries({
                    queryKey,
                    exact: true,
                    predicate: (query) => query.getObserversCount() === 0,
                })
            }
        }
    }, [enabled, scope, queryClient, account])

    // biome-ignore lint/correctness/useExhaustiveDependencies: idsKey represents the current window, read through the ref.
    useEffect(() => {
        queueRef.current?.enqueue(idsRef.current)
    }, [enabled, scopeKey, idsKey])

    const onViewableItemsChanged = useCallback(({ viewableItems }: { viewableItems: ViewToken<InboxItem>[] }): void => {
        const indices = viewableItems.flatMap((token) => (token.index === null ? [] : [token.index]))
        const first = Math.min(...indices)
        const last = Math.max(...indices)
        const scopeKey = scopeKeyRef.current
        setVisible((current) => {
            if (indices.length === 0) return current === null ? current : null
            return current?.first === first && current.last === last && current.scopeKey === scopeKey
                ? current
                : { first, last, scopeKey }
        })
    }, [])

    return { onViewableItemsChanged, viewabilityConfig: VIEWABILITY_CONFIG }
}
