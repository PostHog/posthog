import {
    type InfiniteData,
    type QueryClient,
    type QueryKey,
    type UseQueryResult,
    useInfiniteQuery,
    useQueries,
    useQueryClient,
} from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

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
import { useAuthStore } from '@/auth/authStore'
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

import { useAppActive } from '../handoff/useTaskRun'
import { useSnoozeEntries, wakeSnooze } from '../snooze/hooks'
import { applySnoozes } from '../snooze/snoozeEntries'
import { applyInboxFilters, DEFAULT_INBOX_FILTERS, type InboxFilters, isDefaultInboxFilters } from './filters'

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
    matchedCount: number
    totalCount: number
    /** Loaded items before the filters, so a source filter can still offer the other sources. */
    unfiltered: readonly InboxItem[] | undefined
}

type InboxPages = InfiniteData<InboxPageApi, number>

const noop = (): void => undefined
const noMorePages = { hasMore: false, isLoadingMore: false, loadMoreFailed: false, loadMore: noop, retryLoadMore: noop }
const noItems = { matchedCount: 0, totalCount: 0, unfiltered: undefined }

let accountGeneration = 0
const readWrites = new Set<AbortController>()
useAuthStore.subscribe((state, previous) => {
    if (
        state.signedIn !== previous.signedIn ||
        state.user?.uuid !== previous.user?.uuid ||
        state.host !== previous.host ||
        state.projectId !== previous.projectId
    ) {
        accountGeneration += 1
        for (const controller of readWrites) controller.abort()
        readWrites.clear()
    }
})

type ReadSnapshot = [QueryKey, Record<string, boolean> | undefined][]

interface PendingRead {
    read: boolean
    promise: Promise<void>
    rollback: ReadSnapshot
}

const pendingReads = new WeakMap<QueryClient, Map<string, PendingRead>>()

function readKey(scope: ProjectScope | null, reportId: string): string {
    return JSON.stringify([accountGeneration, scope, reportId])
}

async function fetchReadStates(ids: readonly string[], signal: AbortSignal): Promise<Record<string, boolean>> {
    const batches: string[][] = []
    for (let start = 0; start < ids.length; start += READ_STATE_BATCH) {
        batches.push(ids.slice(start, start + READ_STATE_BATCH))
    }
    const responses = await Promise.all(batches.map((batch) => postReadStates(batch, undefined, signal)))
    return Object.assign({}, ...responses.map((response: ReadStatesApi) => response.states))
}

function mergeReadStates(results: UseQueryResult<Record<string, boolean>>[]): Record<string, boolean> {
    return Object.assign(
        {},
        ...results.map((result) => (result.isFetchedAfterMount && !result.isError ? (result.data ?? {}) : {}))
    )
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

function useLiveInboxItems(
    enabled: boolean,
    refreshWhileVisible: boolean,
    filters: InboxFilters,
    now: Date
): InboxQueryState {
    const scope = useProjectScope()
    const appActive = useAppActive()
    const active = enabled && scope !== null
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
            queryFn: async ({ signal }: { signal: AbortSignal }) => {
                const states = await fetchReadStates(ids, signal)
                for (const id of ids) {
                    const pending = pendingReads.get(queryClient)?.get(readKey(scope, id))
                    if (pending) states[id] = pending.read
                }
                return states
            },
            staleTime: 0,
            refetchOnMount: 'always' as const,
            refetchInterval: active && appActive && refreshWhileVisible ? 30_000 : false,
            enabled: active,
            retry: retryUnlessMissing,
        })),
        combine: mergeReadStates,
    })

    const polling = active && appActive && refreshWhileVisible
    const wasPolling = useRef(polling)
    useEffect(() => {
        if (polling && !wasPolling.current) {
            void queryClient.invalidateQueries({ queryKey: reportKeys.readStatesAll(scope) })
        }
        wasPolling.current = polling
    }, [polling, scope, queryClient])

    const items = useMemo(() => {
        if (!baseItems || !scope) {
            return undefined
        }
        const withRead = baseItems.map((item) => ({ ...item, read: readStates[item.reportId] !== false }))
        return applySnoozes(applyInboxFilters(withRead, filters, now.getTime()), snoozes, scope, now, signalCounts)
    }, [baseItems, readStates, filters, snoozes, scope, now, signalCounts])

    const {
        refetch: refetchList,
        fetchNextPage,
        hasNextPage,
        isFetching,
        isFetchingNextPage,
        isFetchNextPageError,
    } = list
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
        // The inbox and an open report can both auto-page; without this the second call cancels and repeats the request.
        void fetchNextPage({ cancelRefetch: false })
    }, [hasNextPage, isFetchingNextPage, fetchNextPage, pagesLoaded])
    // The error footer that replaces the spinner changes the content size, which makes `FlatList` call `onEndReached`
    // again. Without this guard, a server that keeps failing would get a new request after each failure.
    const loadMore = useCallback((): void => {
        if (!isFetchNextPageError) {
            retryLoadMore()
        }
    }, [isFetchNextPageError, retryLoadMore])

    // A sort or filter over part of the ranking would misorder rows or hide matches on unloaded pages, so it loads every
    // page. It waits for any fetch, because a next-page request would cancel a refresh that is still in flight.
    const autoPaging = active && !isDefaultInboxFilters(filters) && hasNextPage && !isFetchNextPageError
    useEffect(() => {
        if (autoPaging && !isFetching) {
            retryLoadMore()
        }
    }, [autoPaging, isFetching, retryLoadMore])

    if (!scope) {
        return { ...errorQuery(new NotSignedInError()), ...noMorePages, ...noItems }
    }
    const paging = {
        hasMore: hasNextPage,
        isLoadingMore: isFetchingNextPage || autoPaging,
        loadMoreFailed: isFetchNextPageError,
        loadMore,
        retryLoadMore,
    }
    if (items) {
        return {
            data: items,
            isLoading: false,
            isError: false,
            error: null,
            isRefetching: pulling,
            refetch,
            ...paging,
            matchedCount: items.length,
            totalCount: baseItems?.length ?? 0,
            unfiltered: baseItems,
        }
    }
    if (list.isError) {
        return { ...errorQuery(toError(list.error), refetch), ...noMorePages, ...noItems }
    }
    return { ...loadingQuery<InboxItem[]>(), refetch, ...noMorePages, ...noItems }
}

/** `for_you/` has no sort or filter parameters, so `filters` apply on the device to the ranked reports. */
export function useInboxItems({
    refreshWhileVisible = false,
    filters = DEFAULT_INBOX_FILTERS,
}: {
    refreshWhileVisible?: boolean
    filters?: InboxFilters
} = {}): InboxQueryState {
    const mode = useDataMode()
    const now = useNow()
    const demoQuery = useDemoInboxQuery()
    const liveQuery = useLiveInboxItems(mode === 'live', refreshWhileVisible, filters, now)
    const demoItems = useMemo(
        () => (demoQuery.data ? applyInboxFilters(demoQuery.data, filters, now.getTime()) : undefined),
        [demoQuery.data, filters, now]
    )
    if (mode === 'loading') {
        return { ...loadingQuery(), ...noMorePages, ...noItems }
    }
    if (mode === 'demo') {
        return {
            ...demoQuery,
            data: demoItems,
            ...noMorePages,
            matchedCount: demoItems?.length ?? 0,
            totalCount: demoQuery.data?.length ?? 0,
            unfiltered: demoQuery.data,
        }
    }
    return liveQuery
}

function setCachedRead(
    queryClient: ReturnType<typeof useQueryClient>,
    scope: ProjectScope,
    reportId: string,
    read: boolean
): void {
    queryClient.setQueriesData<Record<string, boolean>>(
        {
            queryKey: reportKeys.readStatesAll(scope),
            predicate: (query) => String(query.queryKey.at(-1)).split(',').includes(reportId),
        },
        (states) => ({ ...states, [reportId]: read })
    )
}

function restoreRead(queryClient: QueryClient, reportId: string, snapshot: ReadSnapshot): void {
    for (const [queryKey, states] of snapshot) {
        queryClient.setQueryData<Record<string, boolean>>(queryKey, (current) => {
            if (!current) return current
            const restored = { ...current }
            if (states && reportId in states) restored[reportId] = states[reportId] as boolean
            else delete restored[reportId]
            return restored
        })
    }
}

/** `open` is the mark that opening a report sends by itself; `manual` is a swipe or a row menu choice. */
type ReadTrigger = 'open' | 'manual'

// A write to the opposite value waits for the one in flight, so the server ends with the last value the user chose.
function setReportRead(
    queryClient: QueryClient,
    scope: ProjectScope,
    reportId: string,
    read: boolean,
    trigger: ReadTrigger
): Promise<void> {
    let pending = pendingReads.get(queryClient)
    if (!pending) {
        pending = new Map()
        pendingReads.set(queryClient, pending)
    }
    const writes = pending
    const generation = accountGeneration
    const key = readKey(scope, reportId)
    const existing = writes.get(key)
    if (existing?.read === read) return existing.promise
    const controller = new AbortController()
    readWrites.add(controller)
    const entry: PendingRead = { read, promise: Promise.resolve(), rollback: [] }
    // A superseded write leaves the cache to the newer write, which shows the newer value.
    const isLatest = (): boolean => writes.get(key) === entry
    entry.promise = (async (): Promise<void> => {
        const filters = { queryKey: reportKeys.readStatesAll(scope) }
        await queryClient.cancelQueries(filters)
        if (generation !== accountGeneration) return
        entry.rollback = queryClient.getQueriesData<Record<string, boolean>>(filters)
        setCachedRead(queryClient, scope, reportId, read)
        if (existing) {
            const previousSucceeded = await existing.promise.then(
                () => true,
                () => false
            )
            if (generation !== accountGeneration) return
            // The older write did not reach the server, so a failure here goes back to the value before it.
            if (!previousSucceeded) entry.rollback = existing.rollback
        }
        try {
            await postReadStates([reportId], read, controller.signal)
            if (generation !== accountGeneration) return
            track(read ? 'mobile_report_marked_read' : 'mobile_report_marked_unread', { report_id: reportId, trigger })
            if (!isLatest()) return
            await queryClient.cancelQueries(filters)
            if (generation !== accountGeneration || !isLatest()) return
            setCachedRead(queryClient, scope, reportId, read)
        } catch (error) {
            if (generation !== accountGeneration) return
            if (isLatest()) {
                await queryClient.cancelQueries(filters)
                if (generation !== accountGeneration) return
                if (isLatest()) restoreRead(queryClient, reportId, entry.rollback)
            }
            throw error
        }
    })().finally(() => {
        if (isLatest()) writes.delete(key)
        readWrites.delete(controller)
    })
    writes.set(key, entry)
    return entry.promise
}

/** Sets a report's read state for the current user. Not guarded, so swipes on different rows never drop each other. */
export function useSetReportRead(): (reportId: string, read: boolean) => Promise<void> {
    const demo = useDemoMode((state) => state.enabled)
    const demoMarkRead = useDemoMode((state) => state.markRead)
    const demoMarkUnread = useDemoMode((state) => state.markUnread)
    const scope = useProjectScope()
    const queryClient = useQueryClient()
    return useCallback(
        async (reportId: string, read: boolean): Promise<void> => {
            if (demo) {
                if (read) demoMarkRead(reportId)
                else demoMarkUnread(reportId)
                return
            }
            if (!scope) {
                throw new NotSignedInError()
            }
            await setReportRead(queryClient, scope, reportId, read, 'manual')
        },
        [demo, demoMarkRead, demoMarkUnread, scope, queryClient]
    )
}

export function useSetReadAction(reportId: string, read: boolean): AsyncAction<[]> {
    const setRead = useSetReportRead()
    return useAsyncAction(() => setRead(reportId, read))
}

// Posts without `useAsyncAction`, whose in-flight guard would drop the next report's post on a fast Prev/Next.
export function useMarkReadOnOpen(reportId: string | undefined): void {
    const demo = useDemoMode((state) => state.enabled)
    const demoMarkRead = useDemoMode((state) => state.markRead)
    const scope = useProjectScope()
    const queryClient = useQueryClient()
    useEffect(() => {
        if (!reportId) return
        if (demo) {
            demoMarkRead(reportId)
            return
        }
        if (!scope) {
            return
        }
        setReportRead(queryClient, scope, reportId, true, 'open').catch(() => undefined)
        wakeSnooze(scope, reportId).catch(() => undefined)
    }, [reportId, demo, demoMarkRead, scope, queryClient])
}
