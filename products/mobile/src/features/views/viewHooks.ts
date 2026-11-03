import { type QueryKey, skipToken, useQuery } from '@tanstack/react-query'
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

import {
    trackChartPeopleOpened,
    trackChartRecordingsOpened,
    trackDashboardTilesShown,
    trackViewOpened,
} from './analytics'
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
    supportsCompare,
    WEB_ANALYTICS_SAVED_RANGE,
    webAnalyticsRange,
} from './rangeOverride'
import { rangeValues } from './rangePresets'
import {
    dashboardRangeKey,
    insightRangeKey,
    useViewRange,
    useViewRangeStore,
    type ViewRange,
    webAnalyticsRangeKey,
} from './rangeStore'
import { viewsQueue } from './refreshQueue'
import { type RefreshItem, useViewRefresh, type ViewRefresh } from './useViewRefresh'
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

/** `busy`: a read of the screen runs, such as after "Try again", so the screen shows its skeleton, not the error. */
function viewState<T>(
    data: T | undefined,
    error: ItemErrorKind | null,
    ready: boolean,
    busy: boolean,
    refetch: () => void
): QueryState<T> {
    if (data !== undefined) {
        return successQuery(data, { refetch })
    }
    if (error && !busy) {
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
function useHeldWhileLoading<T>(identity: string, value: T | undefined, error: ItemErrorKind | null): Held<T> {
    const owner = useRef(identity)
    const last = useRef<T | undefined>(value)
    if (owner.current !== identity) {
        owner.current = identity
        last.current = undefined
    }
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

/**
 * Sends `mobile_dashboard_tiles_shown` once per screen, when the dashboard first shows. The dashboard read writes the
 * tile snapshots before the dashboard, so each tile already knows whether only the web can draw it.
 */
function useDashboardTilesShownEvent(
    view: DashboardView | undefined,
    tiles: readonly DashboardTileState[],
    items: readonly RefreshItem[]
): void {
    const sent = useRef(false)
    useEffect(() => {
        if (sent.current || !view) {
            return
        }
        sent.current = true
        trackDashboardTilesShown({
            tilesTotal: tiles.length,
            tilesText: tiles.filter((tile) => tile.view.kind === 'text').length,
            tilesWebOnly: items.filter((item) => item.drawable?.() === false).length,
        })
    }, [view, tiles, items])
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
    const rangeKey = dashboardRangeKey(context.dataScope, dashboardRef)
    // The same choice and compare that `useViewRange` returns. The override comes first because the saved range can come
    // from the override read: its snapshot outlives the saved-range snapshot when the user stays on a session range.
    const storedChoice = useViewRangeStore((state) => state.ranges[rangeKey] ?? null)
    const storedCompare = useViewRangeStore((state) => state.compare[rangeKey] ?? false)
    const override = dashboardOverride(storedChoice, storedCompare)
    const overrideId = overrideKey(override)
    // biome-ignore lint/correctness/useExhaustiveDependencies: `overrideId` stands for `override`.
    const container = useMemo(
        () => dashboardContainer(context.item, dashboardRef, override),
        [context.item, dashboardRef, overrideId]
    )
    // Only a range change within this dashboard may retain the previous tile layout.
    const identity = `${context.identity}|dashboard:${dashboardRef}`
    const current = useQuery<DashboardSnapshot>({
        queryKey: dashboardQueryKey(scope, dashboardRef, override),
        queryFn: skipToken,
    })
    const error = useItemError(container.key)
    const shown = useHeldWhileLoading(identity, current.data, error)
    const range = useViewRange(
        rangeKey,
        'dashboard',
        savedQuery.data?.view.savedRange ?? shown.value?.view.savedRange ?? NO_RANGE
    )
    const view = shown.value?.view
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
        dataScope: context.dataScope,
        screenKey: `dashboard:${dashboardRef}`,
        items,
        visibleKeys,
        container,
        enabled: context.ready,
        rangeKey: overrideId,
    })
    useRecordRecentView(view ? { kind: 'dashboard', ref: dashboardRef, name: view.name } : null)
    useViewOpenedEvent('dashboard', options, () => items.map((item) => item.snapshot()))
    useDashboardTilesShownEvent(view, tiles, items)
    return {
        access: context.access,
        dashboard: viewState(view, error, context.ready, refresh.busy, refresh.retry),
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
    compareSupported: boolean
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
    // From a tile the insight shares the dashboard's range, but compare stays its own: dashboards send no compare.
    const range = useViewRange(
        dashboardRef ? dashboardRangeKey(context.dataScope, dashboardRef) : insightRangeKey(context.dataScope, shortId),
        'insight',
        saved,
        savedCompare,
        insightRangeKey(context.dataScope, shortId)
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
    // Compare needs the insight's `query.source`, which every read of the insight carries, and `compareQuery` sets the
    // range itself. So a range change with compare on sends only the compare query, without a retrieve first. The
    // saved range takes the source of a saved-range read only, because `compareQuery` keeps that source's dates.
    const identity = `${context.identity}|insight:${shortId}|${dashboardRef ?? ''}`
    const lastBase = useHeldWhileLoading(identity, base, null)
    const compareSource = base ?? baseSaved ?? (range.choice ? lastBase.value : undefined)
    // An insight saved with compare answers its saved range with both periods, so the retrieve shows them.
    const savedCompareShown = savedCompare && range.compare && range.choice === null
    const compareSupported = supportsCompare(compareSource?.query)
    const compareAvailable =
        compareSupported && compareAllowed(range.choice ? rangeValues(range.choice).date_from : saved.dateFrom)
    const compareBody =
        compareSource && ((range.compare && compareAvailable && !savedCompareShown) || (savedCompare && !range.compare))
            ? compareQuery(compareSource.query, range.choice, range.compare)
            : null
    const compareId = compareBody ? stableStringify(compareBody) : null
    const compareSnapshot = useSnapshot<InsightSnapshot>(compareId ? viewsKeys.compare(scope, compareId) : null)
    // biome-ignore lint/correctness/useExhaustiveDependencies: `compareId` stands for `compareBody`.
    const items = useMemo(() => {
        if (compareBody && compareSource) {
            return [compareItem(context.item, compareSource, compareBody)]
        }
        return [insightItem(context.item, target)]
    }, [context.item, target, compareId, compareSource?.insightId])
    const refresh = useViewRefresh({
        screen: 'insight',
        dataScope: context.dataScope,
        screenKey: `insight:${shortId}`,
        items,
        enabled: context.ready,
        rangeKey: `${overrideId}|${compareId ?? ''}`,
    })
    const itemKey = items[0]?.key ?? null
    const error = useItemError(itemKey)

    const viewedId = (base ?? compareSource)?.insightId
    const viewed = useRef(false)
    useEffect(() => {
        if (viewed.current || !viewedId || context.mode !== 'live' || !context.ready) {
            return
        }
        viewed.current = true
        void markInsightViewed(viewedId).catch(() => undefined)
    }, [viewedId, context.mode, context.ready])

    useRecordRecentView(compareSource ? { kind: 'insight', ref: shortId, name: compareSource.name } : null)
    useViewOpenedEvent('insight', options, () => [base])

    const querySnapshotShown = Boolean(compareSnapshot && compareBody)
    const comparing =
        range.compare &&
        (querySnapshotShown ||
            (savedCompareShown && Boolean(base?.allSeries.some((series) => series.compare === 'previous'))))
    const current = compareBody ? compareSnapshot : base
    const currentKey = compareId ? viewsKeys.compare(scope, compareId) : insightQueryKey(scope, target)
    // The key travels with the held snapshot, so full screen and the Point sheet open the entry that is on screen.
    const shown = useHeldWhileLoading(
        identity,
        current ? { snapshot: current, queryKey: currentKey } : undefined,
        error
    )
    return {
        access: context.access,
        insight: viewState(
            error && shown.value?.snapshot && !shown.value.snapshot.lastRefreshAt ? undefined : shown.value?.snapshot,
            error,
            context.ready,
            refresh.busy,
            refresh.retry
        ),
        error,
        range,
        compareAvailable,
        compareSupported,
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
    const range = useViewRange(webAnalyticsRangeKey(context.dataScope), 'web_analytics', WEB_ANALYTICS_SAVED_RANGE)
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
        dataScope: context.dataScope,
        screenKey: 'web',
        items,
        enabled: context.ready,
        rangeKey: queryId,
    })
    const error = useItemError(items[0]?.key ?? null)
    useRecordRecentView({ kind: 'web_analytics', ref: null, name: 'Web analytics' })
    useViewOpenedEvent('web_analytics', options, () => [snapshot])
    const shown = useHeldWhileLoading(`${context.identity}|web`, snapshot, error)
    return {
        access: context.access,
        overview: viewState(
            error && shown.value && !shown.value.lastRefreshAt ? undefined : shown.value,
            error,
            context.ready,
            refresh.busy,
            refresh.retry
        ),
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
                    // Every load is a tap, and rows that loaded are reused for a minute, so only a failed load goes
                    // out again inside the item's minute floor.
                    userRetry: true,
                    run: async (_mode, signal) => {
                        try {
                            const response = demo
                                ? await sleep(DEMO_READ_MS, signal).then(() => demoActorsResponse(input))
                                : await fetchActorsAtPoint(input, signal)
                            if (signal.aborted) {
                                const error = new Error('Read aborted')
                                error.name = 'AbortError'
                                throw error
                            }
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
