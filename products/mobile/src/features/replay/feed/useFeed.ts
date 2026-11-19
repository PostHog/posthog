import {
    type InfiniteData,
    type UseQueryOptions,
    useInfiniteQuery,
    useQueries,
    useQuery,
    useQueryClient,
} from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import type { RecordingApi, RecordingsListApi } from '@/api/recordings'
import { listRecentReplayVideoExports, type ReplayVideoExport } from '@/api/replayVideo'
import { fetchSessionObservations } from '@/api/replayVision'
import { type ProjectScope, retryUnlessMissing, scopeKey } from '@/api/reports'
import { sessionGeneration } from '@/auth/tokens'
import { useDemoMode } from '@/demo/demoMode'
import { demoReplayItems, demoReplaySignals, demoReplayTimeline } from '@/demo/replays'
import { useInternalUsersFilter } from '@/features/settings/internalUsersPreference'
import { reportScopeError } from '@/features/views/useViewsAccess'
import { toError } from '@/lib/errors'

import { useReplayContext } from '../hooks'
import { recordingView, summaryState } from '../sessionAdapters'
import { feedTimeline, hasReadyVideo } from './feedAdapters'
import { FEED_PAGE_SIZE, fetchFeedEvents, fetchFeedRecordings, fetchFeedSignals, type SignalWindow } from './feedApi'
import type { FeedItem, FeedSource, FeedTimeline } from './feedModel'
import { FEED_PLAYER_KIND } from './feedPlayerKind'
import { useFeedSettings } from './feedSettingsStore'
import { parseSignals, type SessionSignals } from './sessionRows'

async function scoped<T>(load: () => Promise<T>): Promise<T> {
    try {
        return await load()
    } catch (error) {
        reportScopeError(error, 'replay')
        throw error
    }
}

export interface Feed {
    items: FeedItem[] | undefined
    error: Error | null
    retry: () => void
    refresh: () => Promise<void>
    refreshing: boolean
    loadMore: () => void
    retryMore: () => void
    loadingMore: boolean
    pageError: boolean
    stillRecording: number
}

/** Problem sources keep a session that is still recording: the problem already happened, so it is worth a look. */
// The WebView player plays without a video, so it never reads the exports list.
const VIDEO_PLAYER = FEED_PLAYER_KIND === 'video'

/** Problem sources keep a recording still in progress: the problem already happened, and the part so far plays. */
function keepsOngoing(source: FeedSource): boolean {
    return source === 'rage' || source === 'errors'
}

/** The feed looks through this many pages for a visible, playable recording before it shows an empty state. */
const EMPTY_PAGE_LIMIT = 5

export function useFeed(source: FeedSource): Feed {
    const { mode, scope, ready: liveReady } = useReplayContext()
    const demo = mode === 'demo'
    const demoAnchor = useDemoMode((state) => (demo ? state.anchor : 0))
    const filterTestAccounts = useInternalUsersFilter()
    const ready = liveReady && filterTestAccounts !== undefined
    const queryClient = useQueryClient()
    const hidden = useFeedSettings((state) => state.hidden)
    const generation = sessionGeneration()
    const base = useMemo(() => ['replayFeed', generation, ...scopeKey(scope)] as const, [generation, scope])
    const recordingsKey = useMemo(
        () => [...base, 'recordings', source, filterTestAccounts] as const,
        [base, source, filterTestAccounts]
    )
    const recordings = useInfiniteQuery({
        queryKey: recordingsKey,
        queryFn: ({ signal, pageParam }) =>
            scoped(() => fetchFeedRecordings(source, pageParam, signal, filterTestAccounts)),
        initialPageParam: undefined as string | undefined,
        getNextPageParam: (page, _pages, _cursor, cursors) =>
            page.has_next && page.next_cursor && !cursors.includes(page.next_cursor) ? page.next_cursor : undefined,
        enabled: ready,
        retry: retryUnlessMissing,
        staleTime: 60_000,
    })
    const exports = useQuery({
        queryKey: [...base, 'exports'],
        queryFn: ({ signal }) => listRecentReplayVideoExports(signal),
        enabled: ready && VIDEO_PLAYER,
        retry: false,
        staleTime: 30_000,
    })
    const pages = recordings.data?.pages ?? []
    const sessionIds = [...new Set(pages.flatMap((page) => (page.results ?? []).map((row) => row.id)))]
    const observations = useQueries({
        queries: sessionIds.map((id) => ({
            queryKey: [...base, 'observations', id],
            queryFn: ({ signal }: { signal: AbortSignal }) => fetchSessionObservations(id, signal),
            enabled: ready,
            retry: false,
            staleTime: 5 * 60_000,
        })),
    })
    const observationResults = observations.map((query) => query.data)
    const observationsVersion = observations.map((query) => query.dataUpdatedAt).join(',')

    // The order is fixed per page the first time the page and the exports are both known, so items never move while
    // someone watches. Ready items go first within their page.
    const frozen = useRef(new Map<string, { order: string[]; ready: Set<string> }>())
    const exportsKnown = !VIDEO_PLAYER || exports.isSuccess || exports.isError
    // biome-ignore lint/correctness/useExhaustiveDependencies: observation pages change when their version does.
    const allItems = useMemo((): FeedItem[] | undefined => {
        if (demo) {
            return demoReplayItems(source, demoAnchor)
        }
        if (!recordings.data || !exportsKnown) {
            return undefined
        }
        const exportsBySession = new Map<string, ReplayVideoExport[]>()
        for (const asset of exports.data ?? []) {
            const id = asset.export_context?.session_recording_id as string
            exportsBySession.set(id, [...(exportsBySession.get(id) ?? []), asset])
        }
        const allObservations = observationResults.flatMap((page) => page?.results ?? [])
        const seen = new Set<string>()
        const result: FeedItem[] = []
        recordings.data.pages.forEach((page, pageIndex) => {
            const rows = (page.results ?? []).filter(
                (row) => !seen.has(row.id) && (keepsOngoing(source) || row.ongoing !== true)
            )
            const pageKey = `${source}:${pageIndex}:${rows.map((row) => row.id).join(',')}`
            let plan = frozen.current.get(pageKey)
            if (!plan) {
                const readyIds = new Set(
                    rows.filter((row) => hasReadyVideo(exportsBySession.get(row.id) ?? [])).map((row) => row.id)
                )
                const order = [
                    ...rows.filter((row) => readyIds.has(row.id) && row.ongoing !== true),
                    ...rows.filter((row) => !readyIds.has(row.id) && row.ongoing !== true),
                    ...rows.filter((row) => row.ongoing === true),
                ].map((row) => row.id)
                plan = { order, ready: readyIds }
                frozen.current.set(pageKey, plan)
            }
            const byId = new Map<string, RecordingApi>(rows.map((row) => [row.id, row]))
            for (const id of plan.order) {
                const row = byId.get(id)
                if (!row || seen.has(id)) {
                    continue
                }
                seen.add(id)
                const summary = summaryState(allObservations.filter((observation) => observation.session_id === id))
                result.push({
                    recording: recordingView(row),
                    summary: summary.kind === 'ready' ? summary.summary : null,
                    exports: exportsBySession.get(id) ?? [],
                    readyAtLoad: plan.ready.has(id),
                })
            }
        })
        return result
    }, [demo, demoAnchor, recordings.data, exportsKnown, exports.data, source, observationsVersion])

    const items = useMemo(() => {
        const hiddenIds = new Set(hidden)
        return allItems?.filter((item) => !hiddenIds.has(item.recording.sessionId))
    }, [allItems, hidden])

    const stillRecording = keepsOngoing(source)
        ? 0
        : pages.flatMap((page) => page.results ?? []).filter((row) => row.ongoing === true).length

    const [refreshing, setRefreshing] = useState(false)
    const { refetch: refetchRecordings } = recordings
    const { refetch: refetchExports } = exports
    const refresh = useCallback(async (): Promise<void> => {
        if (!ready) {
            return
        }
        setRefreshing(true)
        try {
            await queryClient.cancelQueries({ queryKey: recordingsKey })
            queryClient.setQueryData<InfiniteData<RecordingsListApi>>(recordingsKey, (data) =>
                data ? { pages: data.pages.slice(0, 1), pageParams: data.pageParams.slice(0, 1) } : data
            )
            frozen.current.clear()
            await Promise.all([refetchRecordings(), VIDEO_PLAYER ? refetchExports() : undefined])
        } finally {
            setRefreshing(false)
        }
    }, [ready, queryClient, recordingsKey, refetchRecordings, refetchExports])

    const { hasNextPage, isFetching, isFetchingNextPage, isFetchNextPageError, fetchNextPage } = recordings
    const retryMore = useCallback((): void => {
        if (hasNextPage && !isFetching) {
            void fetchNextPage({ cancelRefetch: false })
        }
    }, [hasNextPage, isFetching, fetchNextPage])
    const loadMore = useCallback((): void => {
        if (!isFetchNextPageError) {
            retryMore()
        }
    }, [isFetchNextPageError, retryMore])
    const searching =
        items !== undefined &&
        items.length === 0 &&
        hasNextPage &&
        !isFetchNextPageError &&
        pages.length < EMPTY_PAGE_LIMIT
    useEffect(() => {
        if (searching) {
            loadMore()
        }
    }, [searching, loadMore])

    return {
        items: searching ? undefined : items,
        error: recordings.isError ? toError(recordings.error) : null,
        retry: () => {
            if (ready) {
                void refetchRecordings()
            }
        },
        refresh,
        refreshing,
        loadMore,
        retryMore,
        loadingMore: isFetchingNextPage,
        pageError: isFetchNextPageError,
        stillRecording,
    }
}

/** The events behind one recording's moments, Info and ticks. The screen and the cards share the cached result. */
export function feedTimelineQuery(
    scope: ProjectScope | null,
    item: FeedItem,
    enabled: boolean,
    demo = false
): UseQueryOptions<FeedTimeline, Error, FeedTimeline, readonly unknown[]> {
    const { sessionId, startedAt, durationSeconds } = item.recording
    const endedAt =
        item.recording.endedAt ??
        (startedAt ? new Date(new Date(startedAt).getTime() + durationSeconds * 1000).toISOString() : null)
    return {
        queryKey: ['replayFeed', ...scopeKey(scope), 'events', sessionId],
        queryFn: ({ signal }) =>
            scoped(async () =>
                feedTimeline(
                    await fetchFeedEvents(sessionId, startedAt as string, endedAt as string, signal),
                    startedAt as string
                )
            ),
        initialData: demo ? demoReplayTimeline(sessionId) : undefined,
        enabled: !demo && enabled && startedAt !== null && endedAt !== null,
        retry: retryUnlessMissing,
        staleTime: 5 * 60_000,
    }
}

export function useFeedTimeline(item: FeedItem, enabled: boolean): FeedTimeline | null {
    const { mode, scope, ready } = useReplayContext()
    const query = useQuery(feedTimelineQuery(scope, item, enabled && ready, mode === 'demo'))
    return query.data ?? null
}

/** Events can land a little before a recording's first snapshot or after its last one. */
const SIGNAL_PADDING_MS = 60_000

function signalWindow(page: readonly FeedItem[]): SignalWindow | null {
    let from = Number.POSITIVE_INFINITY
    let to = Number.NEGATIVE_INFINITY
    for (const { recording } of page) {
        const start = recording.startedAt ? Date.parse(recording.startedAt) : Number.NaN
        if (Number.isNaN(start)) {
            continue
        }
        const end = recording.endedAt ? Date.parse(recording.endedAt) : start + recording.durationSeconds * 1000
        from = Math.min(from, start)
        to = Math.max(to, end)
    }
    if (!Number.isFinite(from) || !Number.isFinite(to)) {
        return null
    }
    return {
        sessionIds: page.map((item) => item.recording.sessionId),
        from: new Date(from - SIGNAL_PADDING_MS).toISOString(),
        to: new Date(to + SIGNAL_PADDING_MS).toISOString(),
    }
}

/** The rage clicks and errors of each listed recording: one query per page of rows, never one per row. */
export function useSessionSignals(items: readonly FeedItem[] | undefined): ReadonlyMap<string, SessionSignals> {
    const { mode, scope, ready } = useReplayContext()
    const pages = useMemo(() => {
        const list = items ?? []
        const chunks: FeedItem[][] = []
        for (let start = 0; start < list.length; start += FEED_PAGE_SIZE) {
            chunks.push(list.slice(start, start + FEED_PAGE_SIZE))
        }
        return chunks
    }, [items])
    const queries = useQueries({
        queries: pages.map((page) => {
            const window = signalWindow(page)
            return {
                queryKey: ['replayFeed', ...scopeKey(scope), 'signals', window?.sessionIds.join(',') ?? ''],
                queryFn: ({ signal }: { signal: AbortSignal }) =>
                    scoped(() => fetchFeedSignals(window as SignalWindow, signal)),
                enabled: ready && window !== null,
                retry: false,
                staleTime: 5 * 60_000,
            }
        }),
    })
    const version = queries.map((query) => query.dataUpdatedAt).join(',')
    // biome-ignore lint/correctness/useExhaustiveDependencies: the queries change when their version does.
    return useMemo(() => {
        if (mode === 'demo') {
            return new Map(items?.map(({ recording: { sessionId } }) => [sessionId, demoReplaySignals(sessionId)]))
        }
        const merged = new Map<string, SessionSignals>()
        queries.forEach((query, index) => {
            const page = pages[index] ?? []
            const starts = new Map(
                page.flatMap((item) =>
                    item.recording.startedAt ? [[item.recording.sessionId, Date.parse(item.recording.startedAt)]] : []
                ) as [string, number][]
            )
            for (const [sessionId, signals] of parseSignals(query.data ?? [], starts)) {
                merged.set(sessionId, signals)
            }
        })
        return merged
    }, [version, pages, mode, items])
}
