import {
    type InfiniteData,
    keepPreviousData,
    type QueryClient,
    type UseQueryResult,
    useInfiniteQuery,
    useQueries,
    useQuery,
    useQueryClient,
} from '@tanstack/react-query'
import { useCallback, useMemo, useState } from 'react'

import {
    assignIssue,
    type ErrorsWindow,
    errorTrackingKeys,
    fetchIssue,
    fetchIssueBreakdown,
    fetchIssueEvents,
    fetchIssueReports,
    fetchIssueSummary,
    fetchIssues,
    fetchSpikeEvents,
    type IssueApi,
    type IssueBreakdownApi,
    type IssueEventsResponseApi,
    type IssueStatusApi,
    type IssueSummaryApi,
    type IssuesListResponseApi,
    updateIssueStatus,
    type WritableIssueStatus,
} from '@/api/errorTracking'
import type { ProjectScope } from '@/api/reports'
import { retryUnlessMissing } from '@/api/reports'
import { useAuthStore } from '@/auth/authStore'
import { useProjectScope } from '@/auth/useProjectScope'
import { type DataMode, useDataMode } from '@/demo/demoMode'
import { reportScopeError } from '@/features/views/useViewsAccess'
import { toError } from '@/lib/errors'
import { type AsyncAction, useAsyncAction } from '@/lib/useAsyncAction'
import { errorQuery, loadingQuery, successQuery } from '@/model/queryStates'
import type { QueryState } from '@/model/types'

import { trackErrorsRefreshed, trackIssueAssigned, trackIssueStatusChanged } from './analytics'
import { type IssueFilter, type IssueRow, issueRowFrom, spikingIssueIds, windowStart } from './issueModel'

/** Issue counts move slowly enough that a list a minute old is still the right list to triage from. */
const LIST_STALE_MS = 60_000
const ISSUE_STALE_MS = 60_000

export interface ErrorsContext {
    mode: DataMode
    scope: ProjectScope | null
    /** The viewer's numeric user id, which assignments use. Null until the account loads it. */
    myUserId: number | null
    ready: boolean
}

export function useErrorsContext(): ErrorsContext {
    const mode = useDataMode()
    const scope = useProjectScope()
    const myUserId = useAuthStore((state) => state.user?.id ?? null)
    return { mode, scope, myUserId, ready: mode === 'live' && scope !== null }
}

async function read<T>(load: () => Promise<T>): Promise<T> {
    try {
        return await load()
    } catch (error) {
        reportScopeError(error, 'errors')
        throw error
    }
}

function stateOf<T>(query: UseQueryResult<T, unknown>): QueryState<T> {
    if (query.data !== undefined) {
        return successQuery(query.data, { isRefetching: query.isRefetching, refetch: query.refetch })
    }
    return query.isError ? errorQuery(toError(query.error), query.refetch) : loadingQuery()
}

export interface IssuesListState extends QueryState<IssueRow[]> {
    updatedAt: number | null
    pulling: boolean
    onPull: () => Promise<void>
    hasMore: boolean
    isLoadingMore: boolean
    loadMoreFailed: boolean
    loadMore: () => void
    spikesLoading: boolean
    spikesFailed: boolean
    retrySpikes: () => void
}

export function useIssuesList(window: ErrorsWindow, filter: IssueFilter): IssuesListState {
    const context = useErrorsContext()
    const { scope, myUserId, ready } = context
    const queryClient = useQueryClient()
    const input = useMemo(
        () => ({ window, assigneeUserId: filter === 'mine' && myUserId !== null ? myUserId : undefined }),
        [window, filter, myUserId]
    )
    const list = useInfiniteQuery({
        queryKey: errorTrackingKeys.list(scope, input),
        queryFn: ({ signal, pageParam }) => read(() => fetchIssues(input, signal, pageParam)),
        initialPageParam: 0,
        getNextPageParam: (page, _pages, offset) =>
            page.hasMore && page.nextOffset !== undefined && page.nextOffset > offset ? page.nextOffset : undefined,
        enabled: ready && (filter !== 'mine' || myUserId !== null),
        staleTime: LIST_STALE_MS,
        retry: retryUnlessMissing,
    })
    const pageIds = useMemo(
        () =>
            (list.data?.pages ?? [])
                .map((page) => page.results.map((issue) => issue.id))
                .filter((ids) => ids.length > 0),
        [list.data]
    )
    // Spikes only add a badge, so a failed read leaves the list without them instead of failing it.
    const spikes = useQueries({
        queries: pageIds.map((ids) => ({
            queryKey: errorTrackingKeys.spikes(scope, window, ids),
            queryFn: ({ signal }: { signal: AbortSignal }) =>
                read(() => fetchSpikeEvents(ids, windowStart(window, new Date()).toISOString(), signal)),
            enabled: ready,
            staleTime: LIST_STALE_MS,
            retry: false,
        })),
    })
    const updatedAt = list.dataUpdatedAt || null
    const rows = useMemo(() => {
        if (!list.data) {
            return undefined
        }
        const now = new Date(updatedAt ?? Date.now())
        const spiking = spikingIssueIds(spikes.flatMap((page) => page.data?.results ?? []))
        const seen = new Set<string>()
        return list.data.pages
            .flatMap((page) => page.results)
            .filter((issue) => {
                if (seen.has(issue.id)) {
                    return false
                }
                seen.add(issue.id)
                return true
            })
            .map((issue) => issueRowFrom(issue, { window, now, spiking, myUserId }))
    }, [list.data, spikes, updatedAt, window, myUserId])

    const [pulling, setPulling] = useState(false)
    const { refetch: refetchList } = list
    const onPull = useCallback(async (): Promise<void> => {
        trackErrorsRefreshed({ window })
        setPulling(true)
        try {
            await queryClient.cancelQueries({ queryKey: errorTrackingKeys.list(scope, input) })
            queryClient.setQueryData<InfiniteData<IssuesListResponseApi>>(
                errorTrackingKeys.list(scope, input),
                (data) => (data ? { pages: data.pages.slice(0, 1), pageParams: data.pageParams.slice(0, 1) } : data)
            )
            await Promise.all([
                refetchList(),
                queryClient.invalidateQueries({ queryKey: [...errorTrackingKeys.all(scope), 'spikes', window] }),
            ])
        } finally {
            setPulling(false)
        }
    }, [queryClient, scope, input, refetchList, window])
    const { hasNextPage, isFetching, isFetchingNextPage, isFetchNextPageError, fetchNextPage } = list
    const loadMore = useCallback((): void => {
        if (hasNextPage && !isFetching) {
            void fetchNextPage({ cancelRefetch: false })
        }
    }, [hasNextPage, isFetching, fetchNextPage])
    const retrySpikes = useCallback((): void => {
        void queryClient.refetchQueries({
            queryKey: [...errorTrackingKeys.all(scope), 'spikes', window],
            type: 'active',
        })
    }, [queryClient, scope, window])

    return {
        data: rows,
        isError: list.isError && !list.data,
        error: list.error ? toError(list.error) : null,
        isRefetching: list.isRefetching && !isFetchingNextPage,
        refetch: refetchList,
        // A Mine list waits for the account's user id, which a session restored from an older build may not have yet.
        isLoading: list.isLoading || (filter === 'mine' && myUserId === null && context.mode === 'live'),
        updatedAt,
        pulling,
        onPull,
        hasMore: hasNextPage,
        isLoadingMore: isFetchingNextPage || (list.isRefetching && hasNextPage),
        loadMoreFailed: isFetchNextPageError,
        loadMore,
        spikesLoading: spikes.some((page) => page.isPending),
        spikesFailed: spikes.some((page) => page.isError),
        retrySpikes,
    }
}

export function useIssue(issueId: string): QueryState<IssueApi> {
    const { scope, ready } = useErrorsContext()
    const query = useQuery({
        queryKey: errorTrackingKeys.issue(scope, issueId),
        queryFn: ({ signal }) => read(() => fetchIssue(issueId, signal)),
        enabled: ready && issueId !== '',
        staleTime: ISSUE_STALE_MS,
        retry: retryUnlessMissing,
    })
    return stateOf(query)
}

export function useIssueSummary(issueId: string, window: ErrorsWindow): QueryState<IssueSummaryApi> {
    const { scope, ready } = useErrorsContext()
    const query = useQuery({
        queryKey: errorTrackingKeys.summary(scope, issueId, window),
        queryFn: ({ signal }) => read(() => fetchIssueSummary(issueId, window, signal)),
        enabled: ready && issueId !== '',
        staleTime: ISSUE_STALE_MS,
        placeholderData: keepPreviousData,
        retry: retryUnlessMissing,
    })
    return stateOf(query)
}

export function useIssueBreakdown(issueId: string, window: ErrorsWindow): QueryState<IssueBreakdownApi | null> {
    const { scope, ready } = useErrorsContext()
    const query = useQuery({
        queryKey: errorTrackingKeys.breakdown(scope, issueId, window),
        queryFn: ({ signal }) => read(() => fetchIssueBreakdown(issueId, window, signal)),
        enabled: ready && issueId !== '',
        staleTime: ISSUE_STALE_MS,
        placeholderData: keepPreviousData,
        retry: false,
    })
    return stateOf(query)
}

export function useIssueEvents(issueId: string, window: ErrorsWindow): QueryState<IssueEventsResponseApi> {
    const { scope, ready } = useErrorsContext()
    const query = useQuery({
        queryKey: errorTrackingKeys.events(scope, issueId, window),
        queryFn: ({ signal }) => read(() => fetchIssueEvents(issueId, window, signal)),
        enabled: ready && issueId !== '',
        staleTime: ISSUE_STALE_MS,
        placeholderData: keepPreviousData,
        retry: false,
    })
    return stateOf(query)
}

/** Whether the server detected a spike for this issue in the window. A failed read counts as no spike. */
export function useIssueSpiking(issueId: string, window: ErrorsWindow): boolean {
    const { scope, ready } = useErrorsContext()
    const query = useQuery({
        queryKey: errorTrackingKeys.spikes(scope, window, [issueId]),
        queryFn: ({ signal }) =>
            read(() => fetchSpikeEvents([issueId], windowStart(window, new Date()).toISOString(), signal)),
        enabled: ready && issueId !== '',
        staleTime: ISSUE_STALE_MS,
        retry: false,
    })
    return (query.data?.results.length ?? 0) > 0
}

export interface LinkedReport {
    id: string
    title: string
    updatedAt: string
}

/** The Inbox report built from this issue's signals, if there is one. A failed read hides the row. */
export function useIssueReport(issueId: string): LinkedReport | null {
    const { scope, ready } = useErrorsContext()
    const query = useQuery({
        queryKey: errorTrackingKeys.reports(scope, issueId),
        queryFn: ({ signal }) => fetchIssueReports(issueId, signal),
        enabled: ready && issueId !== '',
        staleTime: ISSUE_STALE_MS,
        retry: false,
    })
    const report = query.data?.results[0]
    return report ? { id: report.id, title: report.title || 'Untitled report', updatedAt: report.updated_at } : null
}

export function useRefreshIssue(issueId: string): () => Promise<void> {
    const queryClient = useQueryClient()
    const { scope } = useErrorsContext()
    return useCallback(
        () => queryClient.refetchQueries({ queryKey: errorTrackingKeys.issueAll(scope, issueId), type: 'active' }),
        [queryClient, scope, issueId]
    )
}

function patchIssue(queryClient: QueryClient, key: readonly unknown[], patch: Partial<IssueApi>): IssueApi | undefined {
    const previous = queryClient.getQueryData<IssueApi>(key)
    if (previous) {
        queryClient.setQueryData<IssueApi>(key, { ...previous, ...patch })
    }
    return previous
}

export interface StatusChange {
    to: WritableIssueStatus
    undo: boolean
    /** Runs after the server saved the change, never for a tap the in-flight guard dropped. */
    onSaved?: () => void
}

/**
 * Sets the status at once on the screen and rolls it back when the server refuses. Rejects on failure so the caller can
 * say so. Lists refetch the next time they show, because a resolved issue leaves the active list.
 */
export function useIssueStatusAction(issueId: string): AsyncAction<[StatusChange]> {
    const queryClient = useQueryClient()
    const { scope } = useErrorsContext()
    return useAsyncAction(async ({ to, undo, onSaved }: StatusChange) => {
        const key = errorTrackingKeys.issue(scope, issueId)
        // A refresh that lands after the optimistic patch would put the old status back.
        await Promise.all([
            queryClient.cancelQueries({ queryKey: key }),
            queryClient.cancelQueries({ queryKey: errorTrackingKeys.lists(scope) }),
        ])
        const previous = patchIssue(queryClient, key, { status: to })
        const from: IssueStatusApi = previous?.status ?? 'active'
        try {
            const updated = await updateIssueStatus(issueId, to)
            queryClient.setQueryData<IssueApi>(key, updated)
            trackIssueStatusChanged({ from, to, undo })
            onSaved?.()
        } catch (error) {
            if (previous) {
                queryClient.setQueryData<IssueApi>(key, previous)
            }
            reportScopeError(error, 'errors')
            throw error
        } finally {
            void queryClient.invalidateQueries({ queryKey: errorTrackingKeys.lists(scope) })
        }
    })
}

export function useAssignToMeAction(issueId: string): AsyncAction<[boolean, (() => void)?]> {
    const queryClient = useQueryClient()
    const { scope, myUserId } = useErrorsContext()
    return useAsyncAction(async (assign: boolean, onSaved?: () => void) => {
        if (myUserId === null) {
            throw new Error('Your account is still loading. Try again in a moment.')
        }
        const key = errorTrackingKeys.issue(scope, issueId)
        await queryClient.cancelQueries({ queryKey: key })
        const previous = patchIssue(queryClient, key, { assignee: assign ? { type: 'user', id: myUserId } : null })
        try {
            await assignIssue(issueId, assign ? myUserId : null)
            trackIssueAssigned({ self: true, assigned: assign })
            onSaved?.()
        } catch (error) {
            if (previous) {
                queryClient.setQueryData<IssueApi>(key, previous)
            }
            reportScopeError(error, 'errors')
            throw error
        } finally {
            void queryClient.invalidateQueries({ queryKey: errorTrackingKeys.lists(scope) })
        }
    })
}
