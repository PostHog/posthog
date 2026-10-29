import { type QueryClient, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef } from 'react'
import type { ViewabilityConfig, ViewToken } from 'react-native'

import { isMissingFeature, type ProjectScope } from '@/api/reports'
import { useProjectScope } from '@/auth/useProjectScope'
import { useDataMode } from '@/demo/demoMode'
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

async function prefetchReport(queryClient: QueryClient, scope: ProjectScope, reportId: string): Promise<void> {
    const options = { staleTime: PREFETCH_STALE_MS }
    await Promise.all([
        queryClient.prefetchQuery({ ...reportDetailQuery(scope, reportId), ...options }),
        queryClient.prefetchQuery({ ...reportArtefactsQuery(scope, reportId), ...options }),
        knownMissing(queryClient, scope, reportId)
            ? Promise.resolve()
            : queryClient.prefetchQuery({ ...reportPageQuery(scope, reportId), ...options }),
    ])
    // The screen shows the signals as the evidence only when the report has no Today page.
    const page = queryClient.getQueryState(reportPageQuery(scope, reportId).queryKey)
    if (page?.status === 'error' && isMissingFeature(page.error)) {
        await queryClient.prefetchQuery({ ...reportSignalsQuery(scope, reportId), ...options })
    }
}

/** Fills the report screen's cache for the rows on screen and a few ahead, so opening a row renders at once. */
export function usePrefetchReports(items: InboxItem[] | undefined): ReportPrefetchListProps {
    const queryClient = useQueryClient()
    const live = useDataMode() === 'live'
    const scope = useProjectScope()
    const scopeRef = useRef(scope)
    scopeRef.current = scope
    const queueRef = useRef<PrefetchQueue | null>(null)
    if (queueRef.current === null) {
        queueRef.current = createPrefetchQueue(async (reportId) => {
            const current = scopeRef.current
            if (current) {
                await prefetchReport(queryClient, current, reportId)
            }
        })
    }
    const lastVisibleRef = useRef<number | null>(null)

    const rows = useMemo(() => prefetchRows(items ?? []), [items])
    const idsKey = rows.ids.join(',')
    const rowsRef = useRef(rows)
    rowsRef.current = rows
    const enabled = live && scope !== null
    const enabledRef = useRef(enabled)
    enabledRef.current = enabled

    const scopeKey = scope ? `${scope.host}|${scope.projectId}` : ''
    const scopeKeyRef = useRef(scopeKey)

    // Keyed on the id string, not `items`, so the inbox's once-a-minute clock re-render does not enqueue again.
    // biome-ignore lint/correctness/useExhaustiveDependencies: `idsKey` stands for `rows.ids`, read through the ref.
    useEffect(() => {
        if (scopeKeyRef.current !== scopeKey) {
            scopeKeyRef.current = scopeKey
            queueRef.current?.reset()
            lastVisibleRef.current = null
        }
        if (enabled) {
            queueRef.current?.enqueue(prefetchWindow(rowsRef.current.ids, lastVisibleRef.current))
        }
    }, [enabled, idsKey, scopeKey])

    const onViewableItemsChanged = useCallback(({ viewableItems }: { viewableItems: ViewToken<InboxItem>[] }): void => {
        const maxRow = viewableItems.reduce((max, token) => Math.max(max, token.index ?? -1), -1)
        if (maxRow < 0) {
            return
        }
        const { ids, idIndexByRow } = rowsRef.current
        const lastVisible = idIndexByRow[maxRow] ?? ids.length - 1
        if (lastVisible === lastVisibleRef.current) {
            return
        }
        lastVisibleRef.current = lastVisible
        if (enabledRef.current) {
            queueRef.current?.enqueue(prefetchWindow(ids, lastVisible))
        }
    }, [])

    return { onViewableItemsChanged, viewabilityConfig: VIEWABILITY_CONFIG }
}
