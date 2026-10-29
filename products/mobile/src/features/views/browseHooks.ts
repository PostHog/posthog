import { type InfiniteData, useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { DASHBOARD_PAGE_SIZE, type DashboardBasicApi, fetchDashboardPage, searchDashboards } from '@/api/dashboards'
import { fetchInsightPage, INSIGHT_PAGE_SIZE, type InsightBasicApi, searchInsights } from '@/api/insights'
import type { PaginatedApi } from '@/api/reports'
import { demoDashboardRefFor, demoDashboardRows, demoInsightRows } from '@/demo/views'
import { toError } from '@/lib/errors'
import { dashboardRows, insightRows } from '@/model/adapters/viewPins'
import { errorQuery, loadingQuery, successQuery } from '@/model/queryStates'
import type { QueryState } from '@/model/types'
import type { BrowseRow, PinView, RecentView } from '@/model/views'

import { type SearchSection, trackBrowseListPaged, trackViewsSearched } from './analytics'
import { listRead, retryListRead } from './listReads'
import { useViewsContext } from './useViewsContext'
import { viewsKeys } from './viewsCache'

/** A Browse list that loads one page of 30 at a time. */
export interface BrowseListState extends QueryState<BrowseRow[]> {
    hasMore: boolean
    isLoadingMore: boolean
    /** The last next-page request failed. Only `retryLoadMore` sends it again. */
    loadMoreFailed: boolean
    /** For `onEndReached` with a threshold of 0.5. Does nothing after a failed next page. */
    loadMore: () => void
    retryLoadMore: () => void
}

const noop = (): void => undefined
const NO_PAGING = { hasMore: false, isLoadingMore: false, loadMoreFailed: false, loadMore: noop, retryLoadMore: noop }

// Demo dashboards open by their demo ref, not by a numeric id.
function demoDashboardBrowseRows(): BrowseRow[] {
    return dashboardRows(demoDashboardRows()).map((row) => {
        const ref = demoDashboardRefFor(Number(row.ref)) ?? row.ref
        return { ...row, ref, href: `/dashboard/${ref}` }
    })
}

function useBrowseList<T extends DashboardBasicApi | InsightBasicApi>(
    kind: 'dashboards' | 'insights',
    fetchPage: (offset: number, signal: AbortSignal) => Promise<PaginatedApi<T>>,
    pageSize: number,
    toRows: (rows: T[]) => BrowseRow[],
    demoRows: () => BrowseRow[]
): BrowseListState {
    const context = useViewsContext()
    const demo = context.mode === 'demo'
    const queryKey =
        kind === 'dashboards' ? viewsKeys.browseDashboards(context.scope) : viewsKeys.browseInsights(context.scope)
    const list = useInfiniteQuery({
        queryKey,
        queryFn: ({ pageParam, signal }) => listRead(kind, signal, () => fetchPage(pageParam, signal)),
        initialPageParam: 0,
        // A short page is the last one, so the list never asks for a page past the end.
        getNextPageParam: (lastPage: PaginatedApi<T>, _pages: PaginatedApi<T>[], lastOffset: number) =>
            lastPage.results.length < pageSize ? undefined : lastOffset + pageSize,
        enabled: context.ready && !demo,
        retry: retryListRead,
    })
    const data = list.data as InfiniteData<PaginatedApi<T>, number> | undefined
    const rows = useMemo(() => {
        const seen = new Set<string>()
        return toRows((data?.pages ?? []).flatMap((page) => page.results)).filter((row) => {
            const key = row.ref ?? row.name
            if (seen.has(key)) {
                return false
            }
            seen.add(key)
            return true
        })
    }, [data, toRows])
    const { hasNextPage, isFetchingNextPage, isFetchNextPageError, fetchNextPage, refetch } = list
    const retryLoadMore = useCallback(() => {
        if (hasNextPage && !isFetchingNextPage) {
            const before = data?.pages.length ?? 0
            void fetchNextPage().then((result) => {
                // A cancelled fetch also resolves, with the pages it had before.
                const pagesLoaded = result.data?.pages.length ?? 0
                if (!result.isFetchNextPageError && pagesLoaded > before) {
                    trackBrowseListPaged({ section: kind, pagesLoaded })
                }
            })
        }
    }, [hasNextPage, isFetchingNextPage, fetchNextPage, data, kind])
    const loadMore = useCallback(() => {
        if (!isFetchNextPageError) {
            retryLoadMore()
        }
    }, [isFetchNextPageError, retryLoadMore])

    if (context.mode === 'loading') {
        return { ...loadingQuery(), ...NO_PAGING }
    }
    if (demo) {
        return { ...successQuery(demoRows()), ...NO_PAGING }
    }
    if (data) {
        return {
            ...successQuery(rows, { isRefetching: list.isRefetching && !isFetchingNextPage, refetch }),
            hasMore: hasNextPage,
            isLoadingMore: isFetchingNextPage,
            loadMoreFailed: isFetchNextPageError,
            loadMore,
            retryLoadMore,
        }
    }
    if (list.isError) {
        return { ...errorQuery(toError(list.error), refetch), ...NO_PAGING }
    }
    return { ...loadingQuery<BrowseRow[]>(), refetch, ...NO_PAGING }
}

/** Browse, Dashboards: the web Views order (`-last_viewed_at`), without deleted dashboards. */
export function useBrowseDashboards(): BrowseListState {
    return useBrowseList('dashboards', fetchDashboardPage, DASHBOARD_PAGE_SIZE, dashboardRows, demoDashboardBrowseRows)
}

/** Browse, Insights: saved insights, last modified first. */
export function useBrowseInsights(): BrowseListState {
    return useBrowseList('insights', fetchInsightPage, INSIGHT_PAGE_SIZE, insightRows, () =>
        insightRows(demoInsightRows())
    )
}

export const SEARCH_DEBOUNCE_MS = 250
export const SEARCH_MIN_LENGTH = 2

export interface ViewsSearchState {
    /** At least two characters, after the debounce. Show results instead of the sections. */
    active: boolean
    query: string
    pinned: PinView[]
    recent: RecentView[]
    dashboards: QueryState<BrowseRow[]>
    insights: QueryState<BrowseRow[]>
}

function matches(name: string, query: string): boolean {
    return name.toLowerCase().includes(query.toLowerCase())
}

function useServerSearch(kind: 'dashboards' | 'insights', query: string, active: boolean): QueryState<BrowseRow[]> {
    const context = useViewsContext()
    const demo = context.mode === 'demo'
    const queryKey =
        kind === 'dashboards'
            ? viewsKeys.searchDashboards(context.scope, query)
            : viewsKeys.searchInsights(context.scope, query)
    // A new keystroke changes the key; TanStack then cancels the old request through its signal.
    const search = useQuery({
        queryKey,
        queryFn: ({ signal }) =>
            listRead(kind, signal, async () =>
                kind === 'dashboards'
                    ? dashboardRows((await searchDashboards(query, signal)).results)
                    : insightRows((await searchInsights(query, signal)).results)
            ),
        enabled: active && context.ready && !demo,
        staleTime: 60_000,
        retry: false,
    })
    if (!active) {
        return successQuery([])
    }
    if (demo) {
        const rows = kind === 'dashboards' ? demoDashboardBrowseRows() : insightRows(demoInsightRows())
        return successQuery(rows.filter((row) => matches(row.name, query)).slice(0, 10))
    }
    if (search.data) {
        return successQuery(search.data, { refetch: search.refetch })
    }
    if (search.isError) {
        return errorQuery(toError(search.error), search.refetch)
    }
    return loadingQuery()
}

function useDebouncedSearchText(text: string): string {
    const [query, setQuery] = useState(text.trim())
    useEffect(() => {
        const timer = setTimeout(() => setQuery(text.trim()), SEARCH_DEBOUNCE_MS)
        return () => clearTimeout(timer)
    }, [text])
    return query
}

/** Sends `mobile_views_searched` once per query, when every part of the search has settled. */
function useSearchSettledEvent(
    section: SearchSection,
    active: boolean,
    settled: boolean,
    query: string,
    resultCount: number
): void {
    const tracked = useRef<string | null>(null)
    useEffect(() => {
        if (!active || !settled || tracked.current === query) {
            return
        }
        tracked.current = query
        trackViewsSearched({ section, queryLength: query.length, resultCount })
    }, [section, active, settled, query, resultCount])
}

/**
 * Search over pins and Recent on the phone, and dashboards and insights on the server (10 each), 250 ms after the
 * last keystroke and from two characters on.
 */
export function useViewsSearch(
    text: string,
    pins: readonly PinView[],
    recent: readonly RecentView[]
): ViewsSearchState {
    const query = useDebouncedSearchText(text)
    const active = query.length >= SEARCH_MIN_LENGTH
    const pinned = useMemo(() => (active ? pins.filter((pin) => matches(pin.name, query)) : []), [active, pins, query])
    const recentMatches = useMemo(
        () => (active ? recent.filter((view) => matches(view.name, query)) : []),
        [active, recent, query]
    )
    const dashboards = useServerSearch('dashboards', query, active)
    const insights = useServerSearch('insights', query, active)
    useSearchSettledEvent(
        'views',
        active,
        !dashboards.isLoading && !insights.isLoading,
        query,
        pinned.length + (dashboards.data?.length ?? 0) + (insights.data?.length ?? 0)
    )
    return { active, query, pinned, recent: recentMatches, dashboards, insights }
}

export interface BrowseSearchState {
    /** At least two characters, after the debounce. Show the results instead of the paged list. */
    active: boolean
    query: string
    rows: QueryState<BrowseRow[]>
}

/** Search inside one Browse list: the same server search as the Views list, for one kind only. */
export function useBrowseSearch(kind: 'dashboards' | 'insights', text: string): BrowseSearchState {
    const query = useDebouncedSearchText(text)
    const active = query.length >= SEARCH_MIN_LENGTH
    const rows = useServerSearch(kind, query, active)
    useSearchSettledEvent(kind, active, !rows.isLoading, query, rows.data?.length ?? 0)
    return { active, query, rows }
}
