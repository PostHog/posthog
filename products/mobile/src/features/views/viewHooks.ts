import { keepPreviousData, type QueryKey, skipToken, useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { type ActorsAtPointInput, actorsAtPointQuery, fetchActorsAtPoint } from '@/api/actors'
import { BudgetExceededError } from '@/api/budget'
import { markInsightViewed } from '@/api/insights'
import { stableStringify } from '@/api/query'
import { serverNow } from '@/api/serverClock'
import { webOverviewQuery } from '@/api/webAnalytics'
import { DEMO_READ_MS, demoActorsResponse } from '@/demo/views'
import { sleep } from '@/lib/sleep'
import { ignoresRangeOverride } from '@/model/adapters/insightSnapshot'
import { actorsFromResponse } from '@/model/adapters/webOverview'
import { errorQuery, loadingQuery, successQuery } from '@/model/queryStates'
import type { QueryState } from '@/model/types'
import type {
    ActorRow,
    DashboardTileView,
    DashboardView,
    Freshness,
    InsightSnapshot,
    PinDisplayMode,
    SavedRange,
    ViewEntry,
    ViewKind,
    WebOverviewSnapshot,
} from '@/model/views'

import { trackChartPeopleOpened, trackChartRecordingsOpened, trackViewOpened } from './analytics'
import {
    compareItem,
    type DashboardSnapshot,
    dashboardContainer,
    dashboardQueryKey,
    type InsightTarget,
    insightItem,
    insightItemKey,
    insightQueryKey,
    tileTarget,
    webOverviewItem,
    webOverviewQueryKey,
} from './items'
import { useRecordRecentView, useVisibility } from './pinHooks'
import {
    compareAllowed,
    compareQuery,
    DASHBOARD_COMPARE_SUPPORTED,
    dashboardOverride,
    rangeOverride,
    WEB_ANALYTICS_SAVED_RANGE,
    webAnalyticsRange,
} from './rangeOverride'
import { rangeValues } from './rangePresets'
import { dashboardRangeKey, insightRangeKey, useViewRange, type ViewRange, WEB_ANALYTICS_RANGE_KEY } from './rangeStore'
import { viewsQueue } from './refreshQueue'
import { useViewRefresh, type ViewRefresh } from './useViewRefresh'
import { reportScopeError, type ViewsAccess } from './useViewsAccess'
import { useViewsContext } from './useViewsContext'
import {
    freshnessKey,
    type ItemErrorKind,
    overrideKey,
    useItemError,
    useItemUpdating,
    useSnapshot,
    viewsKeys,
} from './viewsCache'

const NO_RANGE: SavedRange = { dateFrom: null, dateTo: null }

const ERROR_COPY: Record<ItemErrorKind, string> = {
    deleted: 'This view was deleted.',
    no_access: "You don't have access to this view.",
    scope: 'Sign in again to see your views.',
    failed: "Couldn't load this view. Check your connection and try again.",
}

export function itemErrorMessage(kind: ItemErrorKind): string {
    return ERROR_COPY[kind]
}

function viewState<T>(
    data: T | undefined,
    error: ItemErrorKind | null,
    ready: boolean,
    refetch: () => void
): QueryState<T> {
    if (data !== undefined) {
        return successQuery(data, { refetch })
    }
    if (error) {
        return errorQuery(new Error(ERROR_COPY[error]), refetch)
    }
    return ready ? { ...loadingQuery<T>(), refetch } : loadingQuery()
}

interface Held<T> {
    value: T | undefined
    /** True while `value` belongs to an earlier range. */
    held: boolean
}

/**
 * The last value a screen showed, kept while the value for a new range loads. The screen then keeps its header and
 * range control instead of falling back to the loading skeleton. An error for the new range drops the old value.
 */
function useHeldWhileLoading<T>(value: T | undefined, error: ItemErrorKind | null): Held<T> {
    const last = useRef<T | undefined>(value)
    if (value !== undefined) {
        last.current = value
    }
    if (value !== undefined || error) {
        return { value, held: false }
    }
    return { value: last.current, held: last.current !== undefined }
}

/** Seconds since the oldest good value among the snapshots, or null when none has one. */
function oldestAgeSeconds(snapshots: readonly (Freshness | undefined)[]): number | null {
    const times = snapshots.flatMap((snapshot) => (snapshot?.lastRefreshAt ? [Date.parse(snapshot.lastRefreshAt)] : []))
    return times.length > 0 ? Math.round((serverNow() - Math.min(...times)) / 1000) : null
}

export interface ViewOpenOptions {
    /** Where the view was opened from, for `mobile_view_opened`. */
    from: ViewEntry
    /** The pin's display mode when opened from a pin. */
    displayMode?: PinDisplayMode | null
}

/** Sends `mobile_view_opened` once per screen, with the age of the cached data at that moment. */
function useViewOpenedEvent(
    viewType: ViewKind,
    options: ViewOpenOptions,
    snapshots: () => readonly (Freshness | undefined)[]
): void {
    const sent = useRef(false)
    const read = useRef(snapshots)
    read.current = snapshots
    const { from, displayMode } = options
    useEffect(() => {
        if (sent.current) {
            return
        }
        sent.current = true
        trackViewOpened({
            viewType,
            from,
            displayMode: displayMode ?? null,
            dataAgeSeconds: oldestAgeSeconds(read.current()),
        })
    }, [viewType, from, displayMode])
}

export interface DashboardTileState {
    view: DashboardTileView
    /** Null for a text tile. */
    target: InsightTarget | null
    /** The tile's freshness key, for `refresh.refreshItem` and the tile menu. */
    itemKey: string | null
    queryKey: QueryKey | null
}

export interface DashboardScreenState {
    access: ViewsAccess
    dashboard: QueryState<DashboardView>
    error: ItemErrorKind | null
    tiles: DashboardTileState[]
    range: ViewRange
    /** False keeps the compare toggle disabled, with "Compare works on single insights. Open a chart to compare." */
    compareSupported: boolean
    refresh: ViewRefresh
    /** Pass to the tile list. Rows whose item is a `DashboardTileState` count. */
    onViewableItemsChanged: ReturnType<typeof useVisibility>['onViewableItemsChanged']
    viewabilityConfig: ReturnType<typeof useVisibility>['viewabilityConfig']
}

/**
 * A dashboard screen. It opens like the web: a cache-only dashboard read, then `blocking` for each visible tile with no
 * result or a passed `cache_target_age`. A range change starts the same path with the new override.
 */
export function useDashboardScreen(dashboardRef: string, options: ViewOpenOptions): DashboardScreenState {
    const context = useViewsContext()
    const { scope } = context.item
    const savedQuery = useQuery<DashboardSnapshot>({
        queryKey: dashboardQueryKey(scope, dashboardRef, null),
        queryFn: skipToken,
    })
    const range = useViewRange(
        dashboardRangeKey(dashboardRef),
        'dashboard',
        savedQuery.data?.view.savedRange ?? NO_RANGE
    )
    const override = dashboardOverride(range.choice, range.compare)
    const overrideId = overrideKey(override)
    // biome-ignore lint/correctness/useExhaustiveDependencies: `overrideId` stands for `override`.
    const container = useMemo(
        () => dashboardContainer(context.item, dashboardRef, override),
        [context.item, dashboardRef, overrideId]
    )
    // While a new range loads, the previous range's tiles keep the layout, already keyed for the new range.
    const current = useQuery<DashboardSnapshot>({
        queryKey: dashboardQueryKey(scope, dashboardRef, override),
        queryFn: skipToken,
        placeholderData: keepPreviousData,
    })
    const view = current.data?.view
    // biome-ignore lint/correctness/useExhaustiveDependencies: `overrideId` stands for `override`.
    const tiles = useMemo<DashboardTileState[]>(
        () =>
            (view?.tiles ?? []).map((tile) => {
                const target = tileTarget(dashboardRef, tile, override)
                return {
                    view: tile,
                    target,
                    itemKey: target ? insightItemKey(scope, target) : null,
                    queryKey: target ? insightQueryKey(scope, target) : null,
                }
            }),
        [view, dashboardRef, overrideId, scope]
    )
    const items = useMemo(
        () => tiles.flatMap((tile) => (tile.target ? [insightItem(context.item, tile.target)] : [])),
        [tiles, context.item]
    )
    // Rows count as visible by tile id. A range change gives every tile a new item key while the list keeps the same
    // rows, so the list reports no change, and keys taken from its last report would match no tile.
    const visibility = useVisibility((item) => {
        const tileId = (item as Partial<DashboardTileState> | null)?.view?.tileId
        return tileId === undefined ? null : String(tileId)
    })
    const visibleTileIds = visibility.visibleKeys
    const visibleKeys = useMemo(
        () =>
            visibleTileIds
                ? new Set(
                      tiles.flatMap((tile) =>
                          tile.itemKey && visibleTileIds.has(String(tile.view.tileId)) ? [tile.itemKey] : []
                      )
                  )
                : undefined,
        [tiles, visibleTileIds]
    )
    const refresh = useViewRefresh({
        screen: 'dashboard',
        screenKey: `dashboard:${dashboardRef}`,
        items,
        visibleKeys,
        container,
        bulkFloor: true,
        enabled: context.ready,
        rangeKey: overrideId,
    })
    const error = useItemError(container.key)
    useRecordRecentView(view ? { kind: 'dashboard', ref: dashboardRef, name: view.name } : null)
    useViewOpenedEvent('dashboard', options, () => items.map((item) => item.snapshot()))
    const reload = useCallback(() => refresh.onButton(), [refresh.onButton])
    return {
        access: context.access,
        dashboard: viewState(view, error, context.ready, reload),
        error,
        tiles,
        range,
        compareSupported: DASHBOARD_COMPARE_SUPPORTED,
        refresh,
        onViewableItemsChanged: visibility.onViewableItemsChanged,
        viewabilityConfig: visibility.viewabilityConfig,
    }
}

export interface TileData {
    snapshot: InsightSnapshot | undefined
    updating: boolean
    error: ItemErrorKind | null
}

/** One tile's data as the dashboard's refresh rules last read it. Mounting it sends nothing. */
export function useTileData(tile: Pick<DashboardTileState, 'itemKey' | 'queryKey'>): TileData {
    return {
        snapshot: useSnapshot<InsightSnapshot>(tile.queryKey),
        updating: useItemUpdating(tile.itemKey),
        error: useItemError(tile.itemKey),
    }
}

export interface InsightScreenOptions extends ViewOpenOptions {
    /** Opened from a dashboard tile: reads with `from_dashboard` and shares the dashboard's session range. */
    dashboardRef?: string | null
    /** The numeric id, when the caller knows it. */
    insightId?: number | null
}

export interface InsightScreenState {
    access: ViewsAccess
    /** The compare snapshot while compare is on and loaded, else the insight. */
    insight: QueryState<InsightSnapshot>
    error: ItemErrorKind | null
    range: ViewRange
    /** False with All time, where the server turns compare off. */
    compareAvailable: boolean
    /** True while the compare result shows. */
    comparing: boolean
    /** True while `insight` still shows the previous range because the new one has not loaded. */
    rangeLoading: boolean
    refresh: ViewRefresh
    /**
     * The cache entry of the shown snapshot, so a sheet or full screen can follow it while open. While a new range
     * loads, it is the previous range's entry.
     */
    queryKey: QueryKey | null
    /** The current range's freshness key, for `refresh.refreshItem`. */
    itemKey: string | null
}

/**
 * The insight screen. It paints from the snapshot of the pin or tile it came from (the same cache entry), reads with
 * `blocking` when due, and sends `POST insights/viewed/` once per open. Compare runs `POST query/` with the response's
 * `query.source`.
 */
export function useInsightScreen(shortId: string, options: InsightScreenOptions): InsightScreenState {
    const context = useViewsContext()
    const { client, scope } = context.item
    const dashboardRef = options.dashboardRef ?? null
    const baseSaved = useSnapshot<InsightSnapshot>(insightQueryKey(scope, { shortId, dashboardRef, override: null }))
    const dashboardSaved = dashboardRef
        ? client.getQueryData<DashboardSnapshot>(dashboardQueryKey(scope, dashboardRef, null))?.view.savedRange
        : undefined
    const saved = dashboardSaved?.dateFrom ? dashboardSaved : (baseSaved?.savedRange ?? NO_RANGE)
    const savedCompare = Boolean(
        (baseSaved?.query as { source?: { compareFilter?: { compare?: boolean } } } | undefined)?.source?.compareFilter
            ?.compare
    )
    const range = useViewRange(
        dashboardRef ? dashboardRangeKey(dashboardRef) : insightRangeKey(shortId),
        'insight',
        saved,
        savedCompare
    )
    const choiceOverride = rangeOverride(range.choice)
    // A SQL insight without `{filters}` ignores the range, so it keeps its own cache entry.
    const ignoresOverride = baseSaved ? ignoresRangeOverride(baseSaved.query) : false
    const override = ignoresOverride ? null : choiceOverride
    const overrideId = overrideKey(override)
    // biome-ignore lint/correctness/useExhaustiveDependencies: `overrideId` stands for `override`.
    const target = useMemo<InsightTarget>(
        () => ({ shortId, id: options.insightId ?? null, dashboardRef, override }),
        [shortId, options.insightId, dashboardRef, overrideId]
    )
    const base = useSnapshot<InsightSnapshot>(insightQueryKey(scope, target))
    const compareBody =
        range.compare && base && compareAllowed(range.choice ? rangeValues(range.choice).date_from : saved.dateFrom)
            ? compareQuery(base.query, range.choice)
            : null
    const compareId = compareBody ? stableStringify(compareBody) : null
    const compareSnapshot = useSnapshot<InsightSnapshot>(compareId ? viewsKeys.compare(scope, compareId) : null)
    // biome-ignore lint/correctness/useExhaustiveDependencies: `compareId` stands for `compareBody`.
    const items = useMemo(() => {
        if (compareBody && base) {
            return [compareItem(context.item, base, compareBody)]
        }
        return [insightItem(context.item, target)]
    }, [context.item, target, compareId, base?.insightId])
    const refresh = useViewRefresh({
        screen: 'insight',
        screenKey: `insight:${shortId}`,
        items,
        bulkFloor: false,
        enabled: context.ready,
        rangeKey: `${overrideId}|${compareId ?? ''}`,
    })
    const itemKey = items[0]?.key ?? null
    const error = useItemError(itemKey)

    const viewedId = base?.insightId
    const viewed = useRef(false)
    useEffect(() => {
        if (viewed.current || !viewedId || context.mode !== 'live' || !context.ready) {
            return
        }
        viewed.current = true
        void markInsightViewed(viewedId).catch(() => undefined)
    }, [viewedId, context.mode, context.ready])

    useRecordRecentView(base ? { kind: 'insight', ref: shortId, name: base.name } : null)
    useViewOpenedEvent('insight', options, () => [base])

    const comparing = Boolean(compareSnapshot && compareBody)
    const current = comparing ? compareSnapshot : base
    const currentKey = comparing && compareId ? viewsKeys.compare(scope, compareId) : insightQueryKey(scope, target)
    // The key travels with the held snapshot, so full screen and the Point sheet open the entry that is on screen.
    const shown = useHeldWhileLoading(current ? { snapshot: current, queryKey: currentKey } : undefined, error)
    const reload = useCallback(() => refresh.onButton(), [refresh.onButton])
    return {
        access: context.access,
        insight: viewState(shown.value?.snapshot, error, context.ready, reload),
        error,
        range,
        compareAvailable: compareAllowed(range.choice ? rangeValues(range.choice).date_from : saved.dateFrom),
        comparing,
        rangeLoading: shown.held,
        refresh,
        queryKey: shown.value?.queryKey ?? currentKey,
        itemKey,
    }
}

const HOURLY_FROM = new Set(['dStart', '-1dStart', '-1h', '-24h', '-48h'])

export interface WebAnalyticsScreenState {
    access: ViewsAccess
    overview: QueryState<WebOverviewSnapshot>
    error: ItemErrorKind | null
    range: ViewRange
    /** True while `overview` still shows the previous range because the new one has not loaded. */
    rangeLoading: boolean
    refresh: ViewRefresh
}

/** The web analytics overview: one `WebOverviewQuery` with compare on, as the web's overview tile sends it. */
export function useWebAnalyticsScreen(options: ViewOpenOptions): WebAnalyticsScreenState {
    const context = useViewsContext()
    const range = useViewRange(WEB_ANALYTICS_RANGE_KEY, 'web_analytics', WEB_ANALYTICS_SAVED_RANGE)
    const values = webAnalyticsRange(range.choice)
    const query = webOverviewQuery({
        dateFrom: values.date_from,
        dateTo: values.date_to,
        explicitDate: values.explicitDate,
        compare: true,
        interval: HOURLY_FROM.has(values.date_from) ? 'hour' : 'day',
    })
    const queryId = stableStringify(query)
    // biome-ignore lint/correctness/useExhaustiveDependencies: `queryId` stands for `query`.
    const items = useMemo(() => [webOverviewItem(context.item, query)], [context.item, queryId])
    const snapshot = useSnapshot<WebOverviewSnapshot>(webOverviewQueryKey(context.scope, query))
    const refresh = useViewRefresh({
        screen: 'web_analytics',
        screenKey: 'web',
        items,
        bulkFloor: false,
        enabled: context.ready,
        rangeKey: queryId,
    })
    const error = useItemError(items[0]?.key ?? null)
    useRecordRecentView({ kind: 'web_analytics', ref: null, name: 'Web analytics' })
    useViewOpenedEvent('web_analytics', options, () => [snapshot])
    const shown = useHeldWhileLoading(snapshot, error)
    const reload = useCallback(() => refresh.onButton(), [refresh.onButton])
    return {
        access: context.access,
        overview: viewState(shown.value, error, context.ready, reload),
        error,
        range,
        rangeLoading: shown.held,
        refresh,
    }
}

const POINT_SHEET_GROUP = 'point-sheet'
const ACTORS_FRESH_MS = 60_000

export interface PointActors {
    /** Null before the first load. */
    people: QueryState<ActorRow[]> | null
    includeRecordings: boolean
    /**
     * "Watch recordings" (`includeRecordings: true`) or "View people". One query runs at a time: a second load waits for
     * the first. Resolves with the rows, or null when it failed or the sheet closed.
     */
    load: (input: ActorsAtPointInput) => Promise<ActorRow[] | null>
    /** Closing the sheet drops a query that has not started. A running one finishes and fills the cache. */
    close: () => void
}

interface PointActorsLocal {
    status: 'loading' | 'ok' | 'error'
    includeRecordings: boolean
    rows?: ActorRow[]
    message?: string
}

/** People and recordings at a chart point: `POST query/` with an `ActorsQuery`, `blocking`, through the Views queue. */
export function usePointActors(): PointActors {
    const context = useViewsContext()
    const { client, scope, demo } = context.item
    const [local, setLocal] = useState<PointActorsLocal | null>(null)
    const chain = useRef<Promise<unknown>>(Promise.resolve())
    const generation = useRef(0)

    const run = useCallback(
        async (input: ActorsAtPointInput, runGeneration: number): Promise<ActorRow[] | null> => {
            const queryKey = viewsKeys.actors(scope, stableStringify(actorsAtPointQuery(input)))
            const cached = client.getQueryState<ActorRow[]>(queryKey)
            let rows = cached?.data && Date.now() - cached.dataUpdatedAt < ACTORS_FRESH_MS ? cached.data : undefined
            let message = "Couldn't load people. Try again."
            if (!rows) {
                setLocal({ status: 'loading', includeRecordings: input.includeRecordings })
                const result = await viewsQueue.enqueue({
                    key: freshnessKey(queryKey),
                    family: 'query',
                    group: POINT_SHEET_GROUP,
                    mode: 'blocking',
                    run: async (_mode, signal) => {
                        try {
                            const response = demo
                                ? await sleep(DEMO_READ_MS, signal).then(() => demoActorsResponse(input))
                                : await fetchActorsAtPoint(input, signal)
                            client.setQueryData(queryKey, actorsFromResponse(response))
                            return { status: 'ok', computed: false }
                        } catch (error) {
                            reportScopeError(error)
                            if (error instanceof BudgetExceededError) {
                                message = 'Too many requests right now. Try again in a minute.'
                            }
                            throw error
                        }
                    },
                })
                if (result.status === 'capped') {
                    message = 'Too many requests right now. Try again in a minute.'
                }
                rows = client.getQueryData<ActorRow[]>(queryKey)
            }
            if (runGeneration !== generation.current) {
                return null
            }
            if (!rows) {
                setLocal({ status: 'error', includeRecordings: input.includeRecordings, message })
                return null
            }
            setLocal({ status: 'ok', includeRecordings: input.includeRecordings, rows })
            if (input.includeRecordings) {
                trackChartRecordingsOpened({ resultCount: rows.filter((row) => row.recordings.length > 0).length })
            } else {
                trackChartPeopleOpened({ resultCount: rows.length })
            }
            return rows
        },
        [client, scope, demo]
    )

    const load = useCallback(
        (input: ActorsAtPointInput): Promise<ActorRow[] | null> => {
            const runGeneration = generation.current
            const next = chain.current.then(() => run(input, runGeneration))
            chain.current = next.catch(() => undefined)
            return next
        },
        [run]
    )

    const close = useCallback(() => {
        generation.current += 1
        viewsQueue.leave(POINT_SHEET_GROUP)
        setLocal(null)
    }, [])

    useEffect(() => () => viewsQueue.leave(POINT_SHEET_GROUP), [])

    let people: QueryState<ActorRow[]> | null = null
    if (local?.status === 'loading') {
        people = loadingQuery()
    } else if (local?.status === 'error') {
        people = errorQuery(new Error(local.message ?? "Couldn't load people. Try again."))
    } else if (local?.rows) {
        people = successQuery(local.rows)
    }
    return { people, includeRecordings: local?.includeRecordings ?? false, load, close }
}
