import type { QueryKey } from '@tanstack/react-query'
import { useCallback, useMemo } from 'react'

import { stableStringify } from '@/api/query'
import type { ProjectScope } from '@/api/reports'
import { serverNow } from '@/api/serverClock'
import {
    type WebQueryWindow,
    webActiveHoursQuery,
    webBreakdownQuery,
    webOverviewQuery,
    webRetentionQuery,
    webTrendQuery,
} from '@/api/webAnalytics'
import {
    WEB_TREND_LABELS,
    webActiveHoursSnapshot,
    webBreakdownSnapshot,
    webInsightSnapshot,
} from '@/model/adapters/webAnalytics'
import {
    DRILL_DOWN,
    toggleFilter,
    WEB_TILES,
    type WebTileDef,
    webTileDef,
} from '@/model/adapters/webAnalyticsBreakdowns'
import type { MetricInterval, QueryState } from '@/model/types'
import type {
    InsightSnapshot,
    WebActiveHoursSnapshot,
    WebBreakdown,
    WebBreakdownSnapshot,
    WebFilter,
    WebOverviewSnapshot,
    WebTileId,
    WebTrendMetric,
} from '@/model/views'

import { webOverviewItem, webQueryItem, webQueryKey } from '../items'
import { useRecordRecentView } from '../pinHooks'
import { WEB_ANALYTICS_SAVED_RANGE, webAnalyticsRange } from '../rangeOverride'
import { useViewRange, type ViewRange, webAnalyticsRangeKey } from '../rangeStore'
import { type RefreshItem, useViewRefresh, type ViewRefresh } from '../useViewRefresh'
import type { ViewsAccess } from '../useViewsAccess'
import { useViewsContext } from '../useViewsContext'
import type { Toasts } from '../ViewsToast'
import { useHeldWhileLoading, useViewOpenedEvent, type ViewOpenOptions, viewState } from '../viewHooks'
import { freshnessKey, type ItemErrorKind, useItemError, useItemUpdating, useSnapshot } from '../viewsCache'
import {
    trackWebBreakdownChanged,
    trackWebFilterAdded,
    trackWebFilterRemoved,
    trackWebMetricSelected,
    type WebAnalyticsSurface,
} from './analytics'
import { webAnalyticsInterval } from './interval'
import {
    DEFAULT_WEB_CHOICES,
    useWebAnalyticsChoices,
    useWebAnalyticsStore,
    type WebAnalyticsChoices,
} from './webAnalyticsStore'

/** A breakdown card asks for the web's 10 rows and shows 6; the full list asks for 50. */
export const CARD_LIMIT = 10
export const CARD_ROWS = 6
export const LIST_LIMIT = 50

/** Where a card reads its data. Mounting the card sends nothing: the screen's refresh rules decide every request. */
export interface WebItemRef {
    queryKey: QueryKey
    itemKey: string
    /** Changes when the card shows something else (another metric or tab), so it does not hold the old value. */
    identity: string
}

export interface WebItemData<T> {
    snapshot: T | undefined
    /** True while `snapshot` belongs to an earlier range or filter set, because the new one has not loaded. */
    held: boolean
    updating: boolean
    error: ItemErrorKind | null
}

export function useWebItemData<T>(ref: WebItemRef): WebItemData<T> {
    const snapshot = useSnapshot<T>(ref.queryKey)
    const error = useItemError(ref.itemKey)
    const updating = useItemUpdating(ref.itemKey)
    const shown = useHeldWhileLoading(ref.identity, snapshot, error)
    return { snapshot: shown.value, held: shown.held, updating, error }
}

function itemRef(scope: ProjectScope | null, query: Record<string, unknown>, identity: string): WebItemRef {
    const queryKey = webQueryKey(scope, query)
    return { queryKey, itemKey: freshnessKey(queryKey), identity }
}

export function tileBreakdown(
    def: WebTileDef,
    choices: WebAnalyticsChoices,
    fallback: WebBreakdown | null = null
): WebBreakdown {
    const chosen = choices.tabs[def.id]
    if (chosen && def.tabs.includes(chosen)) {
        return chosen
    }
    return fallback && def.tabs.includes(fallback) ? fallback : (def.tabs[0] as WebBreakdown)
}

interface SharedWindow {
    range: ViewRange
    values: ReturnType<typeof webAnalyticsRange>
    interval: MetricInterval
    choices: WebAnalyticsChoices
    window: WebQueryWindow
    /** Changes with the range and the filters, which start a new open path like a range change does. */
    windowKey: string
}

function useSharedWindow(dataScope: string): SharedWindow {
    const range = useViewRange(webAnalyticsRangeKey(dataScope), 'web_analytics', WEB_ANALYTICS_SAVED_RANGE)
    const values = webAnalyticsRange(range.choice)
    const interval = webAnalyticsInterval(values)
    const choices = useWebAnalyticsChoices(dataScope)
    const window: WebQueryWindow = {
        dateFrom: values.date_from,
        dateTo: values.date_to,
        explicitDate: values.explicitDate,
        interval,
        properties: choices.filters.flatMap((filter) => filter.properties),
    }
    return { range, values, interval, choices, window, windowKey: stableStringify(window) }
}

export interface WebTileState {
    def: WebTileDef
    breakdown: WebBreakdown
    data: WebItemRef
}

export interface WebAnalyticsScreenState {
    access: ViewsAccess
    overview: QueryState<WebOverviewSnapshot>
    error: ItemErrorKind | null
    range: ViewRange
    rangeLoading: boolean
    refresh: ViewRefresh
    interval: MetricInterval
    metric: WebTrendMetric
    filters: WebFilter[]
    trend: WebItemRef
    tiles: WebTileState[]
    retention: WebItemRef
    activeHours: WebItemRef
}

/** Every item counts as visible, because the screen is one scroll view without row reports. */
export function useWebAnalyticsScreen(options: ViewOpenOptions): WebAnalyticsScreenState {
    const context = useViewsContext()
    const { scope } = context
    const shared = useSharedWindow(context.dataScope)
    const { choices, window, windowKey } = shared
    const metric = choices.metric
    const breakdowns = WEB_TILES.map((def) => tileBreakdown(def, choices))
    const breakdownKey = breakdowns.join('|')
    const base = `${context.identity}|web`

    // biome-ignore lint/correctness/useExhaustiveDependencies: `windowKey` and `breakdownKey` stand for the queries.
    const plan = useMemo(() => {
        const overviewQuery = webOverviewQuery({ ...window, compare: true })
        const trendQuery = webTrendQuery({ ...window, metric })
        const tileQueries = WEB_TILES.map((def, index) => {
            const breakdown = breakdowns[index] as WebBreakdown
            return { def, breakdown, query: webBreakdownQuery({ ...window, breakdown, limit: CARD_LIMIT }) }
        })
        const retentionQuery = webRetentionQuery(window)
        const activeHoursQuery = webActiveHoursQuery(window)
        const items: RefreshItem[] = [
            webOverviewItem(context.item, overviewQuery),
            webQueryItem<InsightSnapshot>(context.item, trendQuery, (response, previous, readAt) =>
                webInsightSnapshot(trendQuery, WEB_TREND_LABELS[metric], response, previous, {
                    readAt,
                    serverNow: serverNow(),
                })
            ),
            ...tileQueries.map(({ breakdown, query }) =>
                webQueryItem<WebBreakdownSnapshot>(context.item, query, (response, previous, readAt) =>
                    webBreakdownSnapshot(breakdown, response, previous, readAt)
                )
            ),
            webQueryItem<InsightSnapshot>(context.item, retentionQuery, (response, previous, readAt) =>
                webInsightSnapshot(retentionQuery, 'Retention', response, previous, { readAt, serverNow: serverNow() })
            ),
            webQueryItem<WebActiveHoursSnapshot>(context.item, activeHoursQuery, webActiveHoursSnapshot),
        ]
        return {
            overviewQuery,
            items,
            trend: itemRef(scope, trendQuery, `${base}|trend|${metric}`),
            tiles: tileQueries.map(({ def, breakdown, query }) => ({
                def,
                breakdown,
                data: itemRef(scope, query, `${base}|tile|${def.id}|${breakdown}`),
            })),
            retention: itemRef(scope, retentionQuery, `${base}|retention`),
            activeHours: itemRef(scope, activeHoursQuery, `${base}|active-hours`),
        }
    }, [context.item, scope, base, windowKey, metric, breakdownKey])

    const visibleKeys = useMemo(() => new Set(plan.items.map((item) => item.key)), [plan.items])
    const overviewKey = webQueryKey(scope, plan.overviewQuery)
    const snapshot = useSnapshot<WebOverviewSnapshot>(overviewKey)
    const refresh = useViewRefresh({
        screen: 'web_analytics',
        dataScope: context.dataScope,
        screenKey: 'web',
        items: plan.items,
        visibleKeys,
        enabled: context.ready && !context.offline,
        rangeKey: windowKey,
    })
    const error = useItemError(plan.items[0]?.key ?? null)
    useRecordRecentView({ kind: 'web_analytics', ref: null, name: 'Web analytics' })
    useViewOpenedEvent('web_analytics', options, () => [snapshot])
    const shown = useHeldWhileLoading(base, snapshot, error)
    return {
        access: context.access,
        overview: viewState(
            error && shown.value && !shown.value.lastRefreshAt ? undefined : shown.value,
            error,
            context.ready,
            refresh.busy,
            refresh.retry,
            context.offline
        ),
        error,
        range: shared.range,
        rangeLoading: shown.held,
        refresh,
        interval: shared.interval,
        metric,
        filters: choices.filters,
        trend: plan.trend,
        tiles: plan.tiles,
        retention: plan.retention,
        activeHours: plan.activeHours,
    }
}

export interface WebBreakdownListState {
    access: ViewsAccess
    tile: WebTileDef
    breakdown: WebBreakdown
    filters: WebFilter[]
    range: ViewRange
    data: WebItemRef
    refresh: ViewRefresh
}

export function useWebBreakdownList(tileId: WebTileId, fallback: WebBreakdown | null): WebBreakdownListState {
    const context = useViewsContext()
    const { scope } = context
    const shared = useSharedWindow(context.dataScope)
    const { choices, window, windowKey } = shared
    const tile = webTileDef(tileId)
    const breakdown = tileBreakdown(tile, choices, fallback)
    // biome-ignore lint/correctness/useExhaustiveDependencies: `windowKey` stands for `window`.
    const plan = useMemo(() => {
        const query = webBreakdownQuery({ ...window, breakdown, limit: LIST_LIMIT })
        return {
            items: [
                webQueryItem<WebBreakdownSnapshot>(context.item, query, (response, previous, readAt) =>
                    webBreakdownSnapshot(breakdown, response, previous, readAt)
                ),
            ],
            data: itemRef(scope, query, `${context.identity}|web-list|${tile.id}|${breakdown}`),
        }
    }, [context.item, context.identity, scope, windowKey, tile.id, breakdown])
    const refresh = useViewRefresh({
        screen: 'web_analytics',
        dataScope: context.dataScope,
        screenKey: `web-list:${tile.id}`,
        items: plan.items,
        enabled: context.ready && !context.offline,
        rangeKey: windowKey,
    })
    return {
        access: context.access,
        tile,
        breakdown,
        filters: choices.filters,
        range: shared.range,
        data: plan.data,
        refresh,
    }
}

export interface WebAnalyticsActions {
    selectMetric: (metric: WebTrendMetric) => void
    setTab: (tile: WebTileId, breakdown: WebBreakdown, from: WebAnalyticsSurface) => void
    /** A second tap on the same value turns its filter off, as on the web. A new filter drills the tile down. */
    tapRow: (tile: WebTileId, breakdown: WebBreakdown, filter: WebFilter, from: WebAnalyticsSurface) => void
    removeFilter: (id: string) => void
    clearFilters: () => void
}

export function useWebAnalyticsActions(toasts: Toasts, fallback: WebBreakdown | null = null): WebAnalyticsActions {
    const { dataScope } = useViewsContext()
    const update = useWebAnalyticsStore((state) => state.update)
    const { show } = toasts

    const restore = useCallback(
        (before: WebAnalyticsChoices) => {
            update(dataScope, () => ({ filters: before.filters, tabs: before.tabs }))
        },
        [update, dataScope]
    )

    const current = useCallback(
        (): WebAnalyticsChoices => useWebAnalyticsStore.getState().scopes[dataScope] ?? DEFAULT_WEB_CHOICES,
        [dataScope]
    )

    const selectMetric = useCallback(
        (metric: WebTrendMetric) => {
            if (current().metric === metric) {
                return
            }
            trackWebMetricSelected({ metric })
            update(dataScope, () => ({ metric }))
        },
        [current, update, dataScope]
    )

    const setTab = useCallback(
        (tile: WebTileId, breakdown: WebBreakdown, from: WebAnalyticsSurface) => {
            if (tileBreakdown(webTileDef(tile), current(), fallback) === breakdown) {
                return
            }
            trackWebBreakdownChanged({ tile, breakdown, from, source: 'user' })
            update(dataScope, (choices) => ({ tabs: { ...choices.tabs, [tile]: breakdown } }))
        },
        [current, update, dataScope, fallback]
    )

    const tapRow = useCallback(
        (tile: WebTileId, breakdown: WebBreakdown, filter: WebFilter, from: WebAnalyticsSurface) => {
            const before = current()
            const change = toggleFilter(before.filters, filter)
            const next = change.kind === 'removed' ? undefined : DRILL_DOWN[breakdown]
            update(dataScope, (choices) => ({
                filters: change.filters,
                ...(next ? { tabs: { ...choices.tabs, [tile]: next } } : {}),
            }))
            if (change.kind === 'removed') {
                trackWebFilterRemoved({ property: filter.id, source: 'row' })
                show('Filter removed', () => {
                    trackWebFilterAdded({ property: filter.id, source: 'undo' })
                    restore(before)
                })
                return
            }
            trackWebFilterAdded({ property: filter.id, source: from })
            if (next) {
                trackWebBreakdownChanged({ tile, breakdown: next, from, source: 'drill_down' })
            }
            show(`Filtered by ${filter.value}`, () => {
                trackWebFilterRemoved({ property: filter.id, source: 'undo' })
                restore(before)
            })
        },
        [current, update, dataScope, show, restore]
    )

    const removeFilter = useCallback(
        (id: string) => {
            const before = current()
            if (!before.filters.some((filter) => filter.id === id)) {
                return
            }
            trackWebFilterRemoved({ property: id, source: 'chip' })
            update(dataScope, (choices) => ({ filters: choices.filters.filter((filter) => filter.id !== id) }))
            show('Filter removed', () => {
                trackWebFilterAdded({ property: id, source: 'undo' })
                restore(before)
            })
        },
        [current, update, dataScope, show, restore]
    )

    const clearFilters = useCallback(() => {
        const before = current()
        if (before.filters.length === 0) {
            return
        }
        for (const filter of before.filters) {
            trackWebFilterRemoved({ property: filter.id, source: 'clear_all' })
        }
        update(dataScope, () => ({ filters: [] }))
        show('Filters cleared', () => {
            for (const filter of before.filters) {
                trackWebFilterAdded({ property: filter.id, source: 'undo' })
            }
            restore(before)
        })
    }, [current, update, dataScope, show, restore])

    return useMemo(
        () => ({ selectMetric, setTab, tapRow, removeFilter, clearFilters }),
        [selectMetric, setTab, tapRow, removeFilter, clearFilters]
    )
}
