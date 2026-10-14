import {
    type InfiniteData,
    type QueryClient,
    type UseQueryResult,
    useInfiniteQuery,
    useQueries,
    useQueryClient,
} from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { NotSignedInError } from '@/api/client'
import {
    fetchInboxPage,
    INBOX_PAGE_SIZE,
    type InboxPageApi,
    type ProjectScope,
    postReadStates,
    READ_STATE_BATCH,
    type ReadStatesApi,
    reportKeys,
    retryUnlessMissing,
} from '@/api/reports'
import { useProjectScope } from '@/auth/useProjectScope'
import { useDataMode, useDemoMode } from '@/demo/demoMode'
import { useDemoInboxQuery } from '@/demo/hooks'
import { track } from '@/lib/analytics'
import { toError } from '@/lib/errors'
import { type AsyncAction, useAsyncAction } from '@/lib/useAsyncAction'
import { useNow } from '@/lib/useNow'
import { inboxFromReports, reportsFromPages, signalCountsFromReports } from '@/model/adapters/inbox'
import { errorQuery, loadingQuery } from '@/model/queryStates'
import type { InboxItem, QueryState } from '@/model/types'

import { useSnoozeEntries, wakeSnooze } from '../snooze/hooks'
import { applySnoozes } from '../snooze/snoozeEntries'

/** The inbox list, which loads one page of reports at a time. */
export interface InboxQueryState extends QueryState<InboxItem[]> {
    /** The server has ranked reports after the loaded ones. */
    hasMore: boolean
    isLoadingMore: boolean
    /** The last next-page request failed. Only `retryLoadMore` sends it again. */
    loadMoreFailed: boolean
    /** For the list end coming into view. Does nothing after a failed next page. */
    loadMore: () => void
    retryLoadMore: () => void
}

type InboxPages = InfiniteData<InboxPageApi, number>

const noop = (): void => undefined
const noMorePages = { hasMore: false, isLoadingMore: false, loadMoreFailed: false, loadMore: noop, retryLoadMore: noop }

async function fetchReadStates(ids: readonly string[]): Promise<Record<string, boolean>> {
    const batches: string[][] = []
    for (let start = 0; start < ids.length; start += READ_STATE_BATCH) {
        batches.push(ids.slice(start, start + READ_STATE_BATCH))
    }
    const responses = await Promise.all(batches.map((batch) => postReadStates(batch)))
    return Object.assign({}, ...responses.map((response: ReadStatesApi) => response.states))
}

function mergeReadStates(results: UseQueryResult<Record<string, boolean>>[]): Record<string, boolean> {
    return Object.assign({}, ...results.map((result) => result.data ?? {}))
}

function nextOffset(lastPage: InboxPageApi, _pages: InboxPageApi[], lastOffset: number): number | undefined {
    return lastPage.next ? lastOffset + INBOX_PAGE_SIZE : undefined
}

// Refetching every loaded page ranks the whole list once per page, so a refresh starts again from the first page.
function keepFirstPage(queryClient: QueryClient, scope: ProjectScope): void {
    queryClient.setQueryData<InboxPages>(reportKeys.inbox(scope), (data) =>
        data ? { pages: data.pages.slice(0, 1), pageParams: data.pageParams.slice(0, 1) } : data
    )
}

function useLiveInboxItems(enabled: boolean): InboxQueryState {
    const scope = useProjectScope()
    const active = enabled && scope !== null
    const now = useNow()
    const snoozes = useSnoozeEntries()
    const queryClient = useQueryClient()
    const [pulling, setPulling] = useState(false)

    const list = useInfiniteQuery({
        queryKey: reportKeys.inbox(scope),
        queryFn: ({ pageParam, signal }) => fetchInboxPage(pageParam, signal),
        initialPageParam: 0,
        getNextPageParam: nextOffset,
        enabled: active,
    })
    const reports = useMemo(() => (list.data ? reportsFromPages(list.data.pages) : undefined), [list.data])
    const baseItems = useMemo(() => (reports ? inboxFromReports(reports) : undefined), [reports])
    const signalCounts = useMemo(() => (reports ? signalCountsFromReports(reports) : {}), [reports])

    // One read-state request per page, so loading a page does not ask again for the pages before it.
    const pageIds = useMemo(
        () =>
            (list.data?.pages ?? [])
                .map((page) => page.results.map((report) => report.id).sort())
                .filter((ids) => ids.length > 0),
        [list.data]
    )
    const readStates = useQueries({
        queries: pageIds.map((ids) => ({
            queryKey: reportKeys.readStates(scope, ids),
            queryFn: () => fetchReadStates(ids),
            enabled: active,
            retry: retryUnlessMissing,
        })),
        combine: mergeReadStates,
    })

    const items = useMemo(() => {
        if (!baseItems || !scope) {
            return undefined
        }
        const withRead = baseItems.map((item) => ({ ...item, read: readStates[item.reportId] ?? item.read }))
        return applySnoozes(withRead, snoozes, scope, now, signalCounts)
    }, [baseItems, readStates, snoozes, scope, now, signalCounts])

    const { refetch: refetchList, fetchNextPage, hasNextPage, isFetchingNextPage, isFetchNextPageError } = list
    const refetch = useCallback(async (): Promise<void> => {
        if (!scope) {
            return
        }
        setPulling(true)
        try {
            keepFirstPage(queryClient, scope)
            await Promise.all([
                refetchList(),
                queryClient.invalidateQueries({ queryKey: reportKeys.readStatesAll(scope) }),
            ])
        } finally {
            setPulling(false)
        }
    }, [queryClient, scope, refetchList])

    const pagesLoaded = list.data?.pages.length ?? 0
    // Only a next-page fetch in flight blocks this, not a background refetch: `FlatList` calls `onEndReached` again only
    // after the content grows, so a dropped call would stop the list from loading more.
    const retryLoadMore = useCallback((): void => {
        if (!hasNextPage || isFetchingNextPage) {
            return
        }
        track('mobile_inbox_page_requested', { page: pagesLoaded + 1 })
        void fetchNextPage()
    }, [hasNextPage, isFetchingNextPage, fetchNextPage, pagesLoaded])
    // The error footer that replaces the spinner changes the content size, which makes `FlatList` call `onEndReached`
    // again. Without this guard, a server that keeps failing would get a new request after each failure.
    const loadMore = useCallback((): void => {
        if (!isFetchNextPageError) {
            retryLoadMore()
        }
    }, [isFetchNextPageError, retryLoadMore])

    if (!scope) {
        return { ...errorQuery(new NotSignedInError()), ...noMorePages }
    }
    const paging = {
        hasMore: hasNextPage,
        isLoadingMore: isFetchingNextPage,
        loadMoreFailed: isFetchNextPageError,
        loadMore,
        retryLoadMore,
    }
    if (items) {
        return { data: items, isLoading: false, isError: false, error: null, isRefetching: pulling, refetch, ...paging }
    }
    if (list.isError) {
        return { ...errorQuery(toError(list.error), refetch), ...noMorePages }
    }
    return { ...loadingQuery<InboxItem[]>(), refetch, ...noMorePages }
}

export function useInboxItems(): InboxQueryState {
    const mode = useDataMode()
    const demoQuery = useDemoInboxQuery()
    const liveQuery = useLiveInboxItems(mode === 'live')
    if (mode === 'loading') {
        return { ...loadingQuery(), ...noMorePages }
    }
    if (mode === 'demo') {
        return { ...demoQuery, ...noMorePages }
    }
    return liveQuery
}

function setCachedRead(
    queryClient: ReturnType<typeof useQueryClient>,
    scope: ProjectScope,
    reportId: string,
    read: boolean
): void {
    queryClient.setQueriesData<Record<string, boolean>>({ queryKey: reportKeys.readStatesAll(scope) }, (states) =>
        states && reportId in states ? { ...states, [reportId]: read } : states
    )
}

async function markReportRead(
    queryClient: ReturnType<typeof useQueryClient>,
    scope: ProjectScope,
    reportId: string
): Promise<void> {
    setCachedRead(queryClient, scope, reportId, true)
    try {
        await postReadStates([reportId], true)
    } catch (error) {
        void queryClient.invalidateQueries({ queryKey: reportKeys.readStatesAll(scope) })
        throw error
    }
    track('mobile_report_marked_read', { report_id: reportId })
}

export function useMarkReadAction(reportId: string): AsyncAction<[]> {
    const demo = useDemoMode((state) => state.enabled)
    const demoMarkRead = useDemoMode((state) => state.markRead)
    const scope = useProjectScope()
    const queryClient = useQueryClient()
    return useAsyncAction(async () => {
        if (demo) {
            demoMarkRead(reportId)
            return
        }
        if (!scope) {
            throw new NotSignedInError()
        }
        await markReportRead(queryClient, scope, reportId)
    })
}

// Posts without `useAsyncAction`, whose in-flight guard would drop the next report's post on a fast Prev/Next.
export function useMarkReadOnOpen(reportId: string): void {
    const demo = useDemoMode((state) => state.enabled)
    const demoMarkRead = useDemoMode((state) => state.markRead)
    const scope = useProjectScope()
    const queryClient = useQueryClient()
    useEffect(() => {
        if (demo) {
            demoMarkRead(reportId)
            return
        }
        if (!scope) {
            return
        }
        markReportRead(queryClient, scope, reportId).catch(() => undefined)
        wakeSnooze(scope, reportId).catch(() => undefined)
    }, [reportId, demo, demoMarkRead, scope, queryClient])
}
