import { type InfiniteData, useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { useFocusEffect } from 'expo-router'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { ApiError } from '@/api/client'
import {
    fetchRecentRecordings,
    fetchRecording,
    fetchSessionEvents,
    type RecordingsListApi,
    recordingKeys,
} from '@/api/recordings'
import {
    fetchFrameUrl,
    fetchSessionObservations,
    fetchWatchFeed,
    requestSessionSummary,
    type ScanOutcomeApi,
    visionKeys,
} from '@/api/replayVision'
import { type ProjectScope, retryUnlessMissing } from '@/api/reports'
import { useAuthStore } from '@/auth/authStore'
import { useProjectScope } from '@/auth/useProjectScope'
import { type DataMode, useDataMode } from '@/demo/demoMode'
import { useAiApproval } from '@/features/ai/aiApproval'
import { type OrgAiStatus, projectOrganization } from '@/features/chat/aiAccess'
import { useAppActive } from '@/features/handoff/useTaskRun'
import { reportScopeError, useFeatureAccess, type ViewsAccess } from '@/features/views/useViewsAccess'
import { actionErrorMessage, toError } from '@/lib/errors'
import { errorQuery, loadingQuery, successQuery } from '@/model/queryStates'
import type { QueryState } from '@/model/types'

import { trackSummarizeRequested, trackSummaryReady } from './replayAnalytics'
import type { RecordingView, SessionListRow, SessionSummary, SessionTimeline } from './replayModel'
import { recordingView, sessionListRows, sessionTimeline, summaryState } from './sessionAdapters'

export interface ReplayContext {
    mode: DataMode
    /** Null in demo mode and before a project is chosen. */
    scope: ProjectScope | null
    access: ViewsAccess
    ready: boolean
}

export function useReplayContext(): ReplayContext {
    const mode = useDataMode()
    const projectScope = useProjectScope()
    const access = useFeatureAccess('replay')
    const scope = mode === 'live' ? projectScope : null
    return { mode, scope, access, ready: mode === 'live' && scope !== null && access.state === 'ok' }
}

/** Reports a missing scope to the reauth state before the query sees the error. */
async function scoped<T>(load: () => Promise<T>): Promise<T> {
    try {
        return await load()
    } catch (error) {
        reportScopeError(error, 'replay')
        throw error
    }
}

export function isNotFound(error: unknown): boolean {
    return error instanceof ApiError && error.status === 404
}

export function useRecording(sessionId: string): QueryState<RecordingView> {
    const { scope, ready } = useReplayContext()
    const query = useQuery<RecordingView, Error>({
        queryKey: recordingKeys.detail(scope, sessionId),
        queryFn: ({ signal }) => scoped(async () => recordingView(await fetchRecording(sessionId, signal))),
        enabled: ready && sessionId !== '',
        retry: retryUnlessMissing,
        staleTime: 60_000,
    })
    return query
}

export function useSessionTimeline(recording: RecordingView | undefined): QueryState<SessionTimeline> {
    const { scope, ready } = useReplayContext()
    const sessionId = recording?.sessionId ?? ''
    const startedAt = recording?.startedAt ?? null
    const endedAt =
        recording?.endedAt ??
        (recording && startedAt
            ? new Date(new Date(startedAt).getTime() + recording.durationSeconds * 1000).toISOString()
            : null)
    const query = useQuery<SessionTimeline, Error>({
        queryKey: recordingKeys.events(scope, sessionId),
        queryFn: ({ signal }) =>
            scoped(async () =>
                sessionTimeline(
                    await fetchSessionEvents(sessionId, startedAt as string, endedAt as string, signal),
                    startedAt as string
                )
            ),
        enabled: ready && startedAt !== null && endedAt !== null,
        retry: retryUnlessMissing,
        staleTime: 5 * 60_000,
    })
    return query
}

export function useOrgAiStatus(): OrgAiStatus {
    const organizations = useAuthStore((state) => state.organizations)
    const projects = useAuthStore((state) => state.projects)
    const projectId = useAuthStore((state) => state.projectId)
    return projectOrganization(organizations, projects, projectId).status
}

function useScreenActive(): boolean {
    const [focused, setFocused] = useState(false)
    useFocusEffect(
        useCallback(() => {
            setFocused(true)
            return () => setFocused(false)
        }, [])
    )
    return useAppActive() && focused
}

export const SUMMARY_POLL_MS = 5_000
export const SUMMARY_WAIT_MS = 2 * 60_000

export type SummaryCardState =
    | { kind: 'loading' }
    | { kind: 'error'; retry: () => void }
    | { kind: 'ready'; summary: SessionSummary }
    | { kind: 'none'; notice: string | null }
    | { kind: 'failed'; reason: string | null }
    | { kind: 'summarizing' }
    | { kind: 'timed_out' }

export interface SessionSummaryFlow {
    card: SummaryCardState
    summary: SessionSummary | null
    summarize: () => void
    checkAgain: () => void
    pending: boolean
}

function outcomeNotice(outcome: ScanOutcomeApi | null): string | null {
    switch (outcome) {
        case 'started':
        case 'already_running':
            return null
        case 'already_scanned':
            return "This session was already summarized, but the summary isn't available to you."
        case 'skipped_quota':
            return "You've hit the monthly Replay Vision credit limit."
        case 'skipped_limit':
            return 'Too many scans are running right now. Try again in a moment.'
        default:
            return "Couldn't start the summary. Try again in a moment."
    }
}

export function useSessionSummaryFlow(sessionId: string): SessionSummaryFlow {
    const approval = useAiApproval('replay', sessionId)
    const { scope, ready } = useReplayContext()
    const queryClient = useQueryClient()
    const active = useScreenActive()
    const [waitingSince, setWaitingSince] = useState<number | null>(null)
    const [requestedAt, setRequestedAt] = useState<number | null>(null)
    const [timedOut, setTimedOut] = useState(false)
    const [notice, setNotice] = useState<string | null>(null)
    const [pending, setPending] = useState(false)
    const inFlight = useRef(false)

    const polling = waitingSince !== null && !timedOut && active
    const queryKey = visionKeys.session(scope, sessionId)
    const query = useQuery({
        queryKey,
        queryFn: ({ signal }) =>
            scoped(async () => summaryState((await fetchSessionObservations(sessionId, signal)).results ?? [])),
        enabled: ready && sessionId !== '',
        retry: retryUnlessMissing,
        refetchInterval: polling ? SUMMARY_POLL_MS : false,
    })
    const state = query.data

    // A scan someone else started counts as a wait too, so the card says so instead of offering Summarize.
    useEffect(() => {
        if (state?.kind === 'running' && waitingSince === null && !timedOut) {
            setWaitingSince(Date.now())
        }
        // A failed or ineligible scan is final too, so the wait and the polling stop there.
        if ((state?.kind === 'ready' || state?.kind === 'failed') && waitingSince !== null) {
            if (state.kind === 'ready' && requestedAt !== null) {
                trackSummaryReady(sessionId, Math.round((Date.now() - requestedAt) / 1000))
            }
            setWaitingSince(null)
            setRequestedAt(null)
            setTimedOut(false)
        }
    }, [state?.kind, waitingSince, requestedAt, timedOut, sessionId])

    useEffect(() => {
        if (waitingSince === null || timedOut) {
            return undefined
        }
        const timer = setTimeout(() => setTimedOut(true), Math.max(0, waitingSince + SUMMARY_WAIT_MS - Date.now()))
        return () => clearTimeout(timer)
    }, [waitingSince, timedOut])

    const summarize = useCallback((): void => {
        if (inFlight.current || !ready) {
            return
        }
        inFlight.current = true
        setPending(true)
        setNotice(null)
        void (async () => {
            try {
                if (!(await approval.request())) {
                    return
                }
                const outcome = await scoped(() => requestSessionSummary(sessionId, approval.signal))
                trackSummarizeRequested(sessionId, outcome)
                if (outcome === 'started' || outcome === 'already_running') {
                    const now = Date.now()
                    setRequestedAt(now)
                    setWaitingSince(now)
                    setTimedOut(false)
                } else {
                    setNotice(outcomeNotice(outcome))
                }
                await queryClient.invalidateQueries({ queryKey })
            } catch (error) {
                trackSummarizeRequested(sessionId, 'error')
                setNotice(actionErrorMessage(error))
            } finally {
                inFlight.current = false
                setPending(false)
            }
        })()
    }, [ready, sessionId, queryClient, queryKey, approval.request, approval.signal])

    const checkAgain = useCallback((): void => {
        setTimedOut(false)
        setWaitingSince(Date.now())
        void query.refetch()
    }, [query])

    const card = useMemo((): SummaryCardState => {
        if (!state) {
            return query.isError ? { kind: 'error', retry: () => void query.refetch() } : { kind: 'loading' }
        }
        if (state.kind === 'ready') {
            return { kind: 'ready', summary: state.summary }
        }
        if (state.kind === 'failed') {
            return { kind: 'failed', reason: state.reason }
        }
        if (waitingSince !== null) {
            return timedOut ? { kind: 'timed_out' } : { kind: 'summarizing' }
        }
        return { kind: 'none', notice }
    }, [state, query, waitingSince, timedOut, notice])

    return {
        card,
        summary: state?.kind === 'ready' ? state.summary : null,
        summarize,
        checkAgain,
        pending,
    }
}

/** Signed frame URLs expire, so a cached one is reused only for a few minutes. */
const FRAME_FRESH_MS = 4 * 60_000

export function useFrameUrl(observationId: string | null, chapter: number | null): QueryState<string> {
    const { scope, ready } = useReplayContext()
    const query = useQuery({
        queryKey: visionKeys.frame(scope, observationId ?? '', chapter),
        queryFn: ({ signal }) => fetchFrameUrl(observationId as string, chapter, signal),
        enabled: ready && observationId !== null,
        retry: false,
        staleTime: FRAME_FRESH_MS,
        gcTime: 2 * FRAME_FRESH_MS,
    })
    return query
}

export interface SessionList {
    rows: QueryState<SessionListRow[]>
    recommendations: SessionListRow[]
    refresh: () => Promise<void>
    refreshing: boolean
    hasMore: boolean
    isLoadingMore: boolean
    loadMoreFailed: boolean
    loadMore: () => void
}

/**
 * Recordings keep their time order while the optional feed enriches them. Separate recommendations keep a late
 * feed response from moving the rows the user is reading.
 */
export function useSessionList(): SessionList {
    const { scope, ready } = useReplayContext()
    const queryClient = useQueryClient()
    const recordings = useInfiniteQuery({
        queryKey: recordingKeys.recent(scope),
        queryFn: ({ signal, pageParam }) => scoped(() => fetchRecentRecordings(signal, pageParam)),
        initialPageParam: undefined as string | undefined,
        getNextPageParam: (page, _pages, _lastCursor, cursors) =>
            page.has_next && page.next_cursor && !cursors.includes(page.next_cursor) ? page.next_cursor : undefined,
        enabled: ready,
        retry: retryUnlessMissing,
        staleTime: 60_000,
    })
    const feed = useQuery({
        queryKey: visionKeys.feed(scope),
        queryFn: ({ signal }) => fetchWatchFeed(signal),
        enabled: ready && recordings.data !== undefined,
        retry: false,
        staleTime: 60_000,
    })
    const [refreshing, setRefreshing] = useState(false)
    const { refetch: refetchRecordings } = recordings
    const { refetch: refetchFeed } = feed
    const refresh = useCallback(async (): Promise<void> => {
        setRefreshing(true)
        try {
            await queryClient.cancelQueries({ queryKey: recordingKeys.recent(scope) })
            queryClient.setQueryData<InfiniteData<RecordingsListApi>>(recordingKeys.recent(scope), (data) =>
                data ? { pages: data.pages.slice(0, 1), pageParams: data.pageParams.slice(0, 1) } : data
            )
            await Promise.all([refetchRecordings(), refetchFeed()])
        } finally {
            setRefreshing(false)
        }
    }, [queryClient, scope, refetchRecordings, refetchFeed])

    const feedItems = feed.data?.results
    const recordingItems = useMemo(() => {
        if (!recordings.data) {
            return undefined
        }
        return [
            ...new Map(
                recordings.data.pages.flatMap((page) => page.results ?? []).map((row) => [row.id, row])
            ).values(),
        ]
    }, [recordings.data])
    const { rows, recommendations } = useMemo(() => {
        if (!recordingItems) {
            return { rows: undefined, recommendations: [] }
        }
        const combined = sessionListRows(feedItems ?? [], recordingItems)
        const byId = new Map(combined.map((row) => [row.sessionId, row]))
        const ids = new Set(recordingItems.map((row) => row.id))
        return {
            rows: recordingItems.flatMap((recording) => {
                const row = byId.get(recording.id)
                return row ? [row] : []
            }),
            recommendations: combined.filter((row) => !ids.has(row.sessionId)),
        }
    }, [feedItems, recordingItems])
    const { hasNextPage, isFetching, isFetchingNextPage, isFetchNextPageError, fetchNextPage } = recordings
    const loadMore = useCallback((): void => {
        if (hasNextPage && !isFetching) {
            void fetchNextPage({ cancelRefetch: false })
        }
    }, [hasNextPage, isFetching, fetchNextPage])
    let state: QueryState<SessionListRow[]>
    if (rows) {
        state = successQuery(rows, { isRefetching: recordings.isRefetching && !isFetchingNextPage, refetch: refresh })
    } else if (recordings.isError) {
        state = errorQuery(toError(recordings.error), recordings.refetch)
    } else {
        state = loadingQuery()
    }
    return {
        rows: state,
        recommendations,
        refresh,
        refreshing,
        hasMore: hasNextPage,
        isLoadingMore: isFetchingNextPage || (recordings.isRefetching && hasNextPage),
        loadMoreFailed: isFetchNextPageError,
        loadMore,
    }
}
