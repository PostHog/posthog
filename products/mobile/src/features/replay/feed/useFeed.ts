import { type InfiniteData, useInfiniteQuery, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useMemo, useRef, useState } from 'react'

import type { RecordingApi, RecordingsListApi } from '@/api/recordings'
import { listRecentReplayVideoExports, type ReplayVideoExport } from '@/api/replayVideo'
import { retryUnlessMissing, scopeKey } from '@/api/reports'
import { reportScopeError } from '@/features/views/useViewsAccess'
import { toError } from '@/lib/errors'

import { useReplayContext } from '../hooks'
import { recordingView, summaryState } from '../sessionAdapters'
import { feedTimeline, hasReadyVideo } from './feedAdapters'
import { fetchFeedEvents, fetchFeedObservations, fetchFeedRecordings } from './feedApi'
import type { FeedItem, FeedSource, FeedTimeline } from './feedModel'

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
    hasMore: boolean
    stillRecording: number
}

/** Problem sources keep a session that is still recording: the problem already happened, so it is worth a look. */
function keepsOngoing(source: FeedSource): boolean {
    return source === 'rage' || source === 'errors'
}

export function useFeed(source: FeedSource): Feed {
    const { scope, ready } = useReplayContext()
    const queryClient = useQueryClient()
    const base = useMemo(() => ['replayFeed', ...scopeKey(scope)] as const, [scope])
    const recordingsKey = useMemo(() => [...base, 'recordings', source] as const, [base, source])
    const recordings = useInfiniteQuery({
        queryKey: recordingsKey,
        queryFn: ({ signal, pageParam }) => scoped(() => fetchFeedRecordings(source, pageParam, signal)),
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
        enabled: ready,
        retry: false,
        staleTime: 30_000,
    })
    const pages = recordings.data?.pages ?? []
    const pageIds = pages.map((page) => (page.results ?? []).map((row) => row.id))
    const observations = useQueries({
        queries: pageIds.map((ids) => ({
            queryKey: [...base, 'observations', ids.join(',')],
            queryFn: ({ signal }: { signal: AbortSignal }) => fetchFeedObservations(ids, signal),
            enabled: ready && ids.length > 0,
            retry: false,
            staleTime: 5 * 60_000,
        })),
    })
    const observationResults = observations.map((query) => query.data)
    const observationsVersion = observations.map((query) => query.dataUpdatedAt).join(',')

    // The order is fixed per page the first time the page and the exports are both known, so items never move while
    // someone watches. Ready items go first within their page.
    const frozen = useRef(new Map<string, { order: string[]; ready: Set<string> }>())
    const exportsKnown = exports.isSuccess || exports.isError
    // biome-ignore lint/correctness/useExhaustiveDependencies: observation pages change when their version does.
    const items = useMemo((): FeedItem[] | undefined => {
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
    }, [recordings.data, exportsKnown, exports.data, source, observationsVersion])

    const stillRecording = keepsOngoing(source)
        ? 0
        : pages.flatMap((page) => page.results ?? []).filter((row) => row.ongoing === true).length

    const [refreshing, setRefreshing] = useState(false)
    const { refetch: refetchRecordings } = recordings
    const { refetch: refetchExports } = exports
    const refresh = useCallback(async (): Promise<void> => {
        setRefreshing(true)
        try {
            await queryClient.cancelQueries({ queryKey: recordingsKey })
            queryClient.setQueryData<InfiniteData<RecordingsListApi>>(recordingsKey, (data) =>
                data ? { pages: data.pages.slice(0, 1), pageParams: data.pageParams.slice(0, 1) } : data
            )
            frozen.current.clear()
            await Promise.all([refetchRecordings(), refetchExports()])
        } finally {
            setRefreshing(false)
        }
    }, [queryClient, recordingsKey, refetchRecordings, refetchExports])

    const { hasNextPage, isFetching, fetchNextPage } = recordings
    const loadMore = useCallback((): void => {
        if (hasNextPage && !isFetching) {
            void fetchNextPage({ cancelRefetch: false })
        }
    }, [hasNextPage, isFetching, fetchNextPage])

    return {
        items,
        error: recordings.isError ? toError(recordings.error) : null,
        retry: () => void refetchRecordings(),
        refresh,
        refreshing,
        loadMore,
        hasMore: hasNextPage,
        stillRecording,
    }
}

export function useFeedTimeline(item: FeedItem, enabled: boolean): FeedTimeline | null {
    const { scope, ready } = useReplayContext()
    const { sessionId, startedAt, durationSeconds } = item.recording
    const endedAt =
        item.recording.endedAt ??
        (startedAt ? new Date(new Date(startedAt).getTime() + durationSeconds * 1000).toISOString() : null)
    const query = useQuery({
        queryKey: ['replayFeed', ...scopeKey(scope), 'events', sessionId],
        queryFn: ({ signal }) =>
            scoped(async () =>
                feedTimeline(
                    await fetchFeedEvents(sessionId, startedAt as string, endedAt as string, signal),
                    startedAt as string
                )
            ),
        enabled: enabled && ready && startedAt !== null && endedAt !== null,
        retry: retryUnlessMissing,
        staleTime: 5 * 60_000,
    })
    return query.data ?? null
}
