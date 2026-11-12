import AsyncStorage from '@react-native-async-storage/async-storage'
import {
    type InfiniteData,
    type QueryClient,
    type UseQueryResult,
    useInfiniteQuery,
    useQueries,
    useQuery,
    useQueryClient,
} from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import {
    type ExperimentApi,
    type ExperimentListItemApi,
    type ExperimentListSegment,
    type ExperimentResultsRunApi,
    type ExperimentsListInput,
    type ExperimentsPage,
    type ExperimentsSource,
    experimentKeys,
    liveExperimentsSource,
} from '@/api/experiments'
import { type ProjectScope, retryUnlessMissing } from '@/api/reports'
import { addSessionEndTask } from '@/auth/authStore'
import { useProjectScope } from '@/auth/useProjectScope'
import { type DataMode, useDataMode } from '@/demo/demoMode'
import { demoExperimentsSource } from '@/demo/experiments'
import { reportScopeError, useFeatureAccess, type ViewsAccess } from '@/features/views/useViewsAccess'
import { useConnectivity } from '@/lib/connectivity'
import { toError } from '@/lib/errors'
import { connectionLoadingQuery, errorQuery, successQuery } from '@/model/queryStates'
import type { QueryState } from '@/model/types'

import { trackExperimentsRefreshed } from './analytics'
import {
    type ExperimentRow,
    type HeadlineResult,
    headlineKey,
    headlineOf,
    type RowHeadline,
    rowOf,
    sortDone,
    sortDrafts,
    sortRunning,
} from './experimentModel'

/** Stored results change once a day unless someone refreshes, so a list a minute old is still current. */
const LIST_STALE_MS = 60_000
const EXPERIMENT_STALE_MS = 60_000
/** The list reads results for at most this many rows at once, so a long list never floods the API. */
const ROW_READS_IN_FLIGHT = 2
const SEARCH_DEBOUNCE_MS = 300

export interface ExperimentsContext {
    mode: DataMode
    /** Null in demo mode, so demo cache entries never mix with a project's. */
    scope: ProjectScope | null
    /** `demo`, or `{host}|{project id}`: last-seen headlines stay inside one. */
    dataScope: string
    access: ViewsAccess
    /** Demo mode, or live with a project and the experiments scopes. Nothing loads otherwise. */
    ready: boolean
    /** Live API calls, or the demo store with the same signatures. */
    source: ExperimentsSource
}

export function useExperimentsContext(): ExperimentsContext {
    const mode = useDataMode()
    const projectScope = useProjectScope()
    const access = useFeatureAccess('experiments')
    const demo = mode === 'demo'
    const scope = demo ? null : projectScope
    const ready = demo || (mode === 'live' && scope !== null && access.state === 'ok')
    const dataScope = demo ? 'demo' : scope ? `${scope.host}|${scope.projectId}` : 'none'
    // The live calls name the same project as the query keys, so a read in flight across a project switch can only
    // land under the old project's keys.
    const source = useMemo(() => (demo ? demoExperimentsSource : liveExperimentsSource(scope)), [demo, scope])
    return { mode, scope, dataScope, access, ready, source }
}

/** Runs a read and records a missing-scope 403, so the screen shows the sign-in state instead of an error. */
export async function readExperiments<T>(load: () => Promise<T>): Promise<T> {
    try {
        return await load()
    } catch (error) {
        reportScopeError(error, 'experiments')
        throw error
    }
}

function stateOf<T>(query: UseQueryResult<T, unknown>, offline: boolean): QueryState<T> {
    if (query.data !== undefined) {
        return successQuery(query.data, { isRefetching: query.isRefetching, refetch: query.refetch })
    }
    return query.isError
        ? errorQuery(toError(query.error), query.refetch)
        : connectionLoadingQuery(offline, query.refetch)
}

/** Lets a fixed number of reads run at once and queues the rest in call order. */
class InFlightLimiter {
    private running = 0
    private readonly queue: (() => void)[] = []

    constructor(private readonly limit: number) {}

    async run<T>(task: () => Promise<T>, signal?: AbortSignal): Promise<T> {
        if (this.running >= this.limit) {
            await new Promise<void>((resolve, reject) => {
                const start = (): void => {
                    signal?.removeEventListener('abort', cancel)
                    resolve()
                }
                const cancel = (): void => {
                    const index = this.queue.indexOf(start)
                    if (index !== -1) {
                        this.queue.splice(index, 1)
                    }
                    reject(signal?.reason ?? new Error('Aborted'))
                }
                this.queue.push(start)
                signal?.addEventListener('abort', cancel, { once: true })
            })
        }
        this.running += 1
        try {
            return await task()
        } finally {
            this.running -= 1
            this.queue.shift()?.()
        }
    }
}

const rowReads = new InFlightLimiter(ROW_READS_IN_FLIGHT)

export function useExperiment(id: string): QueryState<ExperimentApi> {
    const { scope, ready, source } = useExperimentsContext()
    const query = useQuery({
        queryKey: experimentKeys.detail(scope, id),
        queryFn: ({ signal }) => readExperiments(() => source.fetchExperiment(id, signal)),
        enabled: ready && id !== '',
        staleTime: EXPERIMENT_STALE_MS,
        retry: retryUnlessMissing,
    })
    const offline = useConnectivity((state) => state.status === 'offline')
    return stateOf(query, offline)
}

/** The stored results. `null` data means the experiment has none yet. Never starts a recalculation. */
export function useLatestResults(id: string): QueryState<ExperimentResultsRunApi | null> {
    const { scope, ready, source } = useExperimentsContext()
    const query = useQuery({
        queryKey: experimentKeys.latest(scope, id),
        queryFn: ({ signal }) => readExperiments(() => source.fetchLatestResults(id, signal)),
        enabled: ready && id !== '',
        staleTime: EXPERIMENT_STALE_MS,
        retry: retryUnlessMissing,
    })
    const offline = useConnectivity((state) => state.status === 'offline')
    return stateOf(query, offline)
}

/**
 * The headline of each row, read lazily: the detail (for the metrics) and the stored results, through a queue that
 * keeps at most two reads in flight. The detail and results land in the same cache entries the experiment screen
 * reads, so opening a row after its line loaded shows the screen at once.
 */
export function useRowResults(ids: readonly string[]): Record<string, RowHeadline> {
    const { scope, ready, source } = useExperimentsContext()
    const details = useQueries({
        queries: ids.map((id) => ({
            queryKey: experimentKeys.detail(scope, id),
            queryFn: ({ signal }: { signal: AbortSignal }) =>
                readExperiments(() => rowReads.run(() => source.fetchExperiment(id, signal), signal)),
            enabled: ready,
            staleTime: EXPERIMENT_STALE_MS,
            retry: false,
        })),
    })
    const latest = useQueries({
        queries: ids.map((id) => ({
            queryKey: experimentKeys.latest(scope, id),
            queryFn: ({ signal }: { signal: AbortSignal }) =>
                readExperiments(() => rowReads.run(() => source.fetchLatestResults(id, signal), signal)),
            enabled: ready,
            staleTime: EXPERIMENT_STALE_MS,
            retry: false,
        })),
    })
    const headlines: Record<string, RowHeadline> = {}
    ids.forEach((id, index) => {
        const detail = details[index]
        const results = latest[index]
        if (detail?.isError || results?.isError) {
            headlines[id] = 'error'
        } else if (detail?.data === undefined || results?.data === undefined) {
            headlines[id] = 'loading'
        } else {
            headlines[id] = headlineOf(detail.data, results.data)
        }
    })
    // `useQueries` answers new arrays on every render; a stable map keeps the effects that read it from looping.
    return useStableValue(headlines, sameHeadlines)
}

function sameHeadlines(a: Record<string, RowHeadline>, b: Record<string, RowHeadline>): boolean {
    const keys = Object.keys(a)
    return (
        keys.length === Object.keys(b).length && keys.every((key) => JSON.stringify(a[key]) === JSON.stringify(b[key]))
    )
}

/** The previous value while `equal` holds, so a value rebuilt on each render keeps its identity. */
function useStableValue<T>(value: T, equal: (a: T, b: T) => boolean): T {
    const ref = useRef(value)
    if (ref.current !== value && !equal(ref.current, value)) {
        ref.current = value
    }
    return ref.current
}

interface LastSeenState {
    /** `{data scope}|{experiment id}` to the headline key the person last saw. */
    seen: Record<string, string>
    mark: (key: string, headline: string) => void
    clear: () => void
}

/** Old entries drop first, so the saved map stays small on a phone that sees many projects. */
const LAST_SEEN_LIMIT = 500

const useLastSeenStore = create<LastSeenState>()(
    persist(
        (set) => ({
            seen: {},
            mark: (key, headline) =>
                set((state) => {
                    if (state.seen[key] === headline) {
                        return state
                    }
                    const { [key]: _previous, ...rest } = state.seen
                    const entries = Object.entries(rest).slice(-(LAST_SEEN_LIMIT - 1))
                    return { seen: { ...Object.fromEntries(entries), [key]: headline } }
                }),
            clear: () => set({ seen: {} }),
        }),
        {
            name: 'experiments-last-seen:v1',
            storage: createJSONStorage(() => AsyncStorage),
            partialize: (state) => ({ seen: state.seen }),
        }
    )
)

// The map holds result summaries of the signed-in account's experiments, so it goes with the session.
addSessionEndTask(() => useLastSeenStore.getState().clear())

export interface LastSeenHeadlines {
    /** The headline key last seen on this device, or null for an experiment never seen here. */
    seen: (id: string) => string | null
    mark: (id: string, headlineKey: string) => void
}

/** Device-local memory of each experiment's last seen headline, for the "changed since your last look" dot. */
export function useLastSeenHeadlines(): LastSeenHeadlines {
    const { dataScope } = useExperimentsContext()
    const seenMap = useLastSeenStore((state) => state.seen)
    const markKey = useLastSeenStore((state) => state.mark)
    return useMemo(
        () => ({
            seen: (id: string) => seenMap[`${dataScope}|${id}`] ?? null,
            mark: (id: string, key: string) => markKey(`${dataScope}|${id}`, key),
        }),
        [seenMap, markKey, dataScope]
    )
}

/** Records the headline the person sees on the experiment screen, so the list's dot goes out. */
export function markHeadlineSeen(dataScope: string, id: string, headline: HeadlineResult | 'none'): void {
    const key = headlineKey(headline)
    if (key) {
        useLastSeenStore.getState().mark(`${dataScope}|${id}`, key)
    }
}

function useDebounced<T>(value: T, delayMs: number): T {
    const [debounced, setDebounced] = useState(value)
    useEffect(() => {
        const timer = setTimeout(() => setDebounced(value), delayMs)
        return () => clearTimeout(timer)
    }, [value, delayMs])
    return debounced
}

export function matchesSearch(item: Pick<ExperimentListItemApi, 'name' | 'feature_flag_key'>, text: string): boolean {
    const query = text.trim().toLowerCase()
    return !query || item.name.toLowerCase().includes(query) || item.feature_flag_key.toLowerCase().includes(query)
}

function uniqueItems(pages: readonly ExperimentsPage[] | undefined): ExperimentListItemApi[] {
    const seen = new Set<number>()
    const items: ExperimentListItemApi[] = []
    for (const page of pages ?? []) {
        for (const item of page.results) {
            if (!seen.has(item.id)) {
                seen.add(item.id)
                items.push(item)
            }
        }
    }
    return items
}

const SORTERS: Record<ExperimentListSegment, (rows: readonly ExperimentRow[]) => ExperimentRow[]> = {
    running: sortRunning,
    complete: sortDone,
    draft: sortDrafts,
}

export interface ExperimentsListState extends QueryState<ExperimentRow[]> {
    updatedAt: number | null
    pulling: boolean
    onPull: () => Promise<void>
    hasMore: boolean
    isLoadingMore: boolean
    loadMoreFailed: boolean
    loadMore: () => void
    /** The server search is in flight; the rows show the loaded matches meanwhile. */
    searching: boolean
    /** The oldest data cutoff among the rows whose results loaded, for the status line. */
    oldestResultsAt: number | null
    /** True once every visible row's line has loaded or failed. */
    rowsSettled: boolean
}

function listInfiniteOptions(
    scope: ProjectScope | null,
    input: ExperimentsListInput,
    source: ExperimentsSource,
    enabled: boolean
) {
    return {
        queryKey: experimentKeys.list(scope, input),
        queryFn: ({ signal, pageParam }: { signal: AbortSignal; pageParam: number }) =>
            readExperiments(() => source.fetchExperiments(input, signal, pageParam)),
        initialPageParam: 0,
        getNextPageParam: (page: ExperimentsPage, _pages: ExperimentsPage[], offset: number) =>
            page.hasMore && page.nextOffset > offset ? page.nextOffset : undefined,
        enabled,
        staleTime: LIST_STALE_MS,
        retry: retryUnlessMissing,
    }
}

function firstPageOnly(queryClient: QueryClient, key: readonly unknown[]): void {
    queryClient.setQueryData<InfiniteData<ExperimentsPage>>(key, (data) =>
        data ? { pages: data.pages.slice(0, 1), pageParams: data.pageParams.slice(0, 1) } : data
    )
}

/**
 * One segment of the list. Search filters the loaded rows at once by name and flag key; when the loaded pages do not
 * hold the whole segment, it also asks the server with `search=` and shows those results once they arrive. Rows read
 * their results lazily for `visibleIds`. Running rows sort when the visible lines settle, so a line that loads late
 * does not move the row under the person's thumb more than once.
 */
export function useExperimentsList(
    segment: ExperimentListSegment,
    search: string,
    visibleIds: readonly string[] = []
): ExperimentsListState {
    const { scope, dataScope, ready, source } = useExperimentsContext()
    const offline = useConnectivity((state) => state.status === 'offline')
    const queryClient = useQueryClient()
    const baseInput = useMemo<ExperimentsListInput>(() => ({ status: segment }), [segment])
    const base = useInfiniteQuery(listInfiniteOptions(scope, baseInput, source, ready))
    const text = search.trim()
    const debounced = useDebounced(text, SEARCH_DEBOUNCE_MS)
    const baseItems = useMemo(() => uniqueItems(base.data?.pages), [base.data])
    const needsServer = debounced !== '' && base.hasNextPage === true
    const searchInput = useMemo<ExperimentsListInput>(
        () => ({ status: segment, search: debounced }),
        [segment, debounced]
    )
    const server = useInfiniteQuery(listInfiniteOptions(scope, searchInput, source, ready && needsServer))
    const serverSelected = needsServer && debounced === text
    const serverActive = serverSelected && server.data !== undefined
    const active = serverSelected ? server : base

    const items = useMemo(() => {
        if (serverActive) {
            return uniqueItems(server.data?.pages)
        }
        return text ? baseItems.filter((item) => matchesSearch(item, text)) : baseItems
    }, [serverActive, server.data, baseItems, text])

    const readIds = useMemo(() => {
        const live = new Set(items.filter((item) => item.status !== 'draft').map((item) => String(item.id)))
        return visibleIds.filter((id) => live.has(id))
    }, [items, visibleIds])
    const headlines = useRowResults(readIds)
    const lastSeen = useLastSeenHeadlines()
    const { seen, mark } = lastSeen
    // The first headline seen on this device is the baseline, so a fresh install shows no dots.
    useEffect(() => {
        for (const [id, headline] of Object.entries(headlines)) {
            const key = headlineKey(headline)
            if (key && seen(id) === null) {
                mark(id, key)
            }
        }
    }, [headlines, seen, mark])

    const rowsSettled = readIds.every((id) => headlines[id] !== undefined && headlines[id] !== 'loading')
    // Running rows sort on the headlines as they were when the visible lines last settled, so a line that lands
    // late does not move rows one at a time.
    const [sortBasis, setSortBasis] = useState(() => ({ dataScope, headlines, seen }))
    useEffect(() => {
        if (rowsSettled) {
            setSortBasis((previous) => ({
                dataScope,
                headlines: { ...(previous.dataScope === dataScope ? previous.headlines : {}), ...headlines },
                seen,
            }))
        }
    }, [rowsSettled, headlines, seen, dataScope])
    const updatedAt = active.dataUpdatedAt || null
    const ordered = useMemo(() => {
        if (!base.data && !serverActive) {
            return undefined
        }
        const now = updatedAt ?? Date.now()
        const rows = items.map((item) => {
            const id = String(item.id)
            const headline =
                (sortBasis.dataScope === dataScope ? sortBasis.headlines[id] : headlines[id]) ??
                (item.status === 'draft' ? 'none' : 'loading')
            const key = headlineKey(headline)
            const previous = (sortBasis.dataScope === dataScope ? sortBasis.seen : seen)(id)
            return rowOf(item, headline, key !== null && previous !== null && previous !== key, now)
        })
        return SORTERS[segment](rows)
    }, [items, segment, base.data, serverActive, updatedAt, sortBasis, dataScope, headlines, seen])
    // The order holds; the lines and dots inside it stay current.
    const rows = useMemo(
        () =>
            ordered?.map((row) => {
                const headline = headlines[row.id] ?? row.headline
                const key = headlineKey(headline)
                const previous = seen(row.id)
                return {
                    ...row,
                    headline,
                    method: typeof headline === 'string' ? row.method : (headline.method ?? row.method),
                    changed: key !== null && previous !== null && previous !== key,
                }
            }),
        [ordered, headlines, seen]
    )

    const visibleOldest = useMemo(() => {
        const stamps = Object.values(headlines)
            .map((headline) => (typeof headline === 'string' ? null : headline.resultsAt))
            .map((stamp) => (stamp ? Date.parse(stamp) : Number.NaN))
            .filter((stamp) => !Number.isNaN(stamp))
        return stamps.length ? Math.min(...stamps) : null
    }, [headlines])
    // Rows scrolled away or filtered out by search keep the status line on the last results it named.
    const lastOldest = useRef<{ segment: ExperimentListSegment; at: number } | null>(null)
    if (visibleOldest !== null) {
        lastOldest.current = { segment, at: visibleOldest }
    }
    const oldestResultsAt = visibleOldest ?? (lastOldest.current?.segment === segment ? lastOldest.current.at : null)

    const [pulling, setPulling] = useState(false)
    const { refetch } = active
    const onPull = useCallback(async (): Promise<void> => {
        trackExperimentsRefreshed({ segment })
        setPulling(true)
        const activeKey = experimentKeys.list(scope, serverSelected ? searchInput : baseInput)
        try {
            await queryClient.cancelQueries({ queryKey: activeKey })
            firstPageOnly(queryClient, activeKey)
            await Promise.all([
                refetch(),
                // The row reads do not retry, so a pull is how a failed detail read gets another go.
                ...readIds.flatMap((id) => [
                    queryClient.invalidateQueries({ queryKey: experimentKeys.latest(scope, id) }),
                    queryClient.invalidateQueries({ queryKey: experimentKeys.detail(scope, id) }),
                ]),
            ])
        } finally {
            setPulling(false)
        }
    }, [queryClient, scope, segment, serverSelected, searchInput, baseInput, refetch, readIds])
    const { hasNextPage, isFetching, isFetchingNextPage, isFetchNextPageError, fetchNextPage } = active
    const loadMore = useCallback((): void => {
        if (hasNextPage && !isFetching) {
            void fetchNextPage({ cancelRefetch: false })
        }
    }, [hasNextPage, isFetching, fetchNextPage])

    return {
        data: rows,
        isLoading: active.isLoading,
        isError: (active.isError || offline) && !active.data,
        error: active.error ? toError(active.error) : offline ? connectionLoadingQuery(true).error : null,
        isRefetching: active.isRefetching && !isFetchingNextPage,
        refetch,
        updatedAt,
        pulling,
        onPull,
        hasMore: hasNextPage,
        isLoadingMore: isFetchingNextPage,
        loadMoreFailed: isFetchNextPageError,
        loadMore,
        // Typing past the loaded pages waits for the server, so the empty state never flashes mid-word.
        searching: text !== '' && base.hasNextPage === true && (debounced !== text || server.isFetching),
        oldestResultsAt,
        rowsSettled,
    }
}
