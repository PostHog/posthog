import type { QueryClient, QueryKey } from '@tanstack/react-query'

import { ApiError } from '@/api/client'
import { type DashboardApi, fetchDashboard } from '@/api/dashboards'
import { type InsightApi, readInsight } from '@/api/insights'
import { runQuery, stableStringify } from '@/api/query'
import type { ProjectScope } from '@/api/reports'
import { serverNow } from '@/api/serverClock'
import { fetchWebOverview, type WebOverviewResponseApi } from '@/api/webAnalytics'
import {
    DEMO_READ_MS,
    demoAnchor,
    demoCompareResponse,
    demoDashboardResponse,
    demoInsightResponse,
    demoWebOverviewResponse,
    useDemoViews,
} from '@/demo/views'
import { sleep } from '@/lib/sleep'
import { dashboardView, phoneTiles } from '@/model/adapters/dashboardView'
import { failedSnapshot, hasGoodResult, insightSnapshot, isRateLimited } from '@/model/adapters/insightSnapshot'
import { webOverviewSnapshot } from '@/model/adapters/webOverview'
import type { DashboardTileView, DashboardView, InsightSnapshot, PinView, WebOverviewSnapshot } from '@/model/views'

import { type FiltersOverride, overrideForTile } from './rangeOverride'
import type { ReadResult, RefreshMode } from './refreshQueue'
import { queryDisplay } from './snapshotChart'
import type { RefreshContainer, RefreshItem } from './useViewRefresh'
import { reportScopeError } from './useViewsAccess'
import {
    freshnessKey,
    getSnapshot,
    itemErrorKind,
    overrideKey,
    setSnapshot,
    useItemErrors,
    viewsKeys,
} from './viewsCache'

/** Where reads go: the API, or the demo fixtures with the same response shapes. */
export interface ItemContext {
    client: QueryClient
    scope: ProjectScope | null
    demo: boolean
}

/** One insight read as a screen asks for it. The same target always reads and writes the same cache entry. */
export interface InsightTarget {
    shortId: string
    /** The numeric id when known. Reads use it, which avoids the all-digit `short_id` lookup. */
    id?: number | null
    /** The dashboard id as a string (the pin's `ref`), sent as `from_dashboard`. Null for a standalone insight. */
    dashboardRef: string | null
    override: FiltersOverride | null
    /** The tile's `filters_overrides`, when the read comes from a dashboard response. */
    tileOverrides?: Record<string, unknown> | null
    usesOwnRange?: boolean
}

export function insightQueryKey(scope: ProjectScope | null, target: InsightTarget): QueryKey {
    return viewsKeys.insight(scope, target.shortId, target.dashboardRef, overrideKey(target.override))
}

export function insightItemKey(scope: ProjectScope | null, target: InsightTarget): string {
    return freshnessKey(insightQueryKey(scope, target))
}

/** The insight a Number or Chart pin reads, or null for a Row pin and a dashboard pin without a chosen tile. */
export function pinTarget(pin: PinView): InsightTarget | null {
    if (pin.display.mode === 'row' || !pin.native || !pin.ref) {
        return null
    }
    if (pin.kind === 'insight') {
        return { shortId: pin.ref, id: pin.display.insightId, dashboardRef: null, override: null }
    }
    const { insightId, insightShortId } = pin.display
    if (pin.kind === 'dashboard' && typeof insightId === 'number') {
        return { shortId: insightShortId ?? `#${insightId}`, id: insightId, dashboardRef: pin.ref, override: null }
    }
    return null
}

/** The read of one dashboard tile, with the override the tile takes. Null for a text tile. */
export function tileTarget(
    dashboardRef: string,
    tile: DashboardTileView,
    override: FiltersOverride | null
): InsightTarget | null {
    if (tile.kind !== 'insight' || !tile.shortId) {
        return null
    }
    return {
        shortId: tile.shortId,
        id: tile.insightId,
        dashboardRef,
        override: overrideForTile(tile, override),
        usesOwnRange: tile.usesOwnRange,
    }
}

function notFound(): ApiError {
    return new ApiError(404, { detail: 'Not found.' })
}

function rejectAborted(signal: AbortSignal): void {
    if (signal.aborted) {
        const error = new Error('Read aborted')
        error.name = 'AbortError'
        throw error
    }
}

function recordResponseStatus(key: string, response: { query_status?: InsightApi['query_status'] }): void {
    if (response.query_status?.error) {
        useItemErrors.getState().set(key, 'failed')
    } else {
        useItemErrors.getState().clear(key)
    }
}

function recordFailure<T extends { readAt: number; refreshFailed: boolean }>(
    context: ItemContext,
    queryKey: QueryKey,
    key: string,
    error: unknown
): void {
    const kind = itemErrorKind(error)
    if (!kind) {
        return
    }
    if (kind === 'scope') {
        reportScopeError(error)
    }
    useItemErrors.getState().set(key, kind)
    const previous = getSnapshot<T>(context.client, queryKey)
    if (previous) {
        setSnapshot(context.client, queryKey, failedSnapshot(previous, Date.now()))
    }
}

function outcomeOf(response: {
    is_cached?: boolean
    result?: unknown
    results?: unknown
    query_status?: InsightApi['query_status']
}): ReadResult {
    if (isRateLimited(response)) {
        return { status: 'rate_limited', computed: false }
    }
    if (response.query_status?.error) {
        return { status: 'failed', computed: false }
    }
    return { status: 'ok', computed: hasGoodResult(response) && response.is_cached === false }
}

async function demoRead<T>(
    key: string,
    mode: RefreshMode,
    signal: AbortSignal,
    build: (refreshedAt?: number) => T
): Promise<T> {
    await sleep(DEMO_READ_MS, signal)
    if (mode === 'force_blocking') {
        useDemoViews.getState().markRefreshed(key)
    }
    return build(useDemoViews.getState().refreshedAt[key])
}

/** A Number or Chart pin, a dashboard tile, or the insight screen: `GET insights/{id}/`. */
export function insightItem(context: ItemContext, target: InsightTarget): RefreshItem {
    const queryKey = insightQueryKey(context.scope, target)
    const key = freshnessKey(queryKey)
    return {
        key,
        family: 'insights',
        windowMode: 'force_cache',
        snapshot: () => getSnapshot<InsightSnapshot>(context.client, queryKey),
        drawable: () => {
            const snapshot = getSnapshot<InsightSnapshot>(context.client, queryKey)
            return !snapshot || queryDisplay(snapshot.query) !== 'web'
        },
        read: async (mode, signal) => {
            const previous = getSnapshot<InsightSnapshot>(context.client, queryKey)
            try {
                const response = context.demo
                    ? await demoRead(key, mode, signal, (refreshedAt) =>
                          demoInsightResponse({ ...target, refreshedAt }, demoAnchor())
                      )
                    : await readInsight(
                          { id: target.id ?? previous?.insightId ?? null, shortId: target.shortId },
                          {
                              refresh: mode,
                              fromDashboard: target.dashboardRef ? Number(target.dashboardRef) : null,
                              filtersOverride: target.override,
                              signal,
                          }
                      )
                if (!response) {
                    throw notFound()
                }
                rejectAborted(signal)
                const snapshot = insightSnapshot(response, previous, {
                    readAt: Date.now(),
                    serverNow: serverNow(),
                    tileOverrides: target.tileOverrides,
                    usesOwnRange: target.usesOwnRange ?? (target.dashboardRef ? previous?.usesOwnRange : undefined),
                })
                setSnapshot(context.client, queryKey, snapshot)
                recordResponseStatus(key, response)
                return outcomeOf(response)
            } catch (error) {
                recordFailure<InsightSnapshot>(context, queryKey, key, error)
                throw error
            }
        },
    }
}

/**
 * "Compare to previous period" on an insight: `POST query/` with the response's `query.source`, `compareFilter` and the
 * range. The answer becomes a full insight snapshot with a current and a previous series.
 */
export function compareItem(context: ItemContext, base: InsightSnapshot, query: Record<string, unknown>): RefreshItem {
    const queryKey = viewsKeys.compare(context.scope, stableStringify(query))
    const key = freshnessKey(queryKey)
    return {
        key,
        family: 'query',
        windowMode: 'blocking',
        snapshot: () => getSnapshot<InsightSnapshot>(context.client, queryKey),
        read: async (mode, signal) => {
            const previous = getSnapshot<InsightSnapshot>(context.client, queryKey)
            try {
                const response = (
                    context.demo
                        ? await demoRead(key, mode, signal, (refreshedAt) =>
                              demoCompareResponse(query, base.shortId, demoAnchor(), refreshedAt)
                          )
                        : await runQuery(query, {
                              refresh: mode === 'force_blocking' ? 'force_blocking' : 'blocking',
                              poll: false,
                              signal,
                          })
                ) as Partial<InsightApi> & { results?: unknown }
                const asInsight: InsightApi = {
                    id: base.insightId,
                    short_id: base.shortId,
                    name: base.name,
                    derived_name: null,
                    description: base.description,
                    query: { kind: 'InsightVizNode', source: query },
                    result: response.results ?? response.result ?? null,
                    last_refresh: response.last_refresh ?? null,
                    cache_target_age: response.cache_target_age ?? null,
                    next_allowed_client_refresh: response.next_allowed_client_refresh ?? null,
                    is_cached: response.is_cached,
                    query_status: response.query_status,
                    timezone: response.timezone,
                    resolved_date_range: response.resolved_date_range,
                }
                rejectAborted(signal)
                setSnapshot(context.client, queryKey, {
                    ...insightSnapshot(asInsight, previous, { readAt: Date.now(), serverNow: serverNow() }),
                    createdBy: base.createdBy,
                    createdAt: base.createdAt,
                })
                recordResponseStatus(key, asInsight)
                return outcomeOf(asInsight)
            } catch (error) {
                recordFailure<InsightSnapshot>(context, queryKey, key, error)
                throw error
            }
        },
    }
}

export function webOverviewQueryKey(scope: ProjectScope | null, query: Record<string, unknown>): QueryKey {
    return viewsKeys.webOverview(scope, stableStringify(query))
}

/** The web analytics overview: `POST query/` with a `WebOverviewQuery`. */
export function webOverviewItem(context: ItemContext, query: Record<string, unknown>): RefreshItem {
    const queryKey = webOverviewQueryKey(context.scope, query)
    const key = freshnessKey(queryKey)
    return {
        key,
        family: 'query',
        windowMode: 'blocking',
        snapshot: () => getSnapshot<WebOverviewSnapshot>(context.client, queryKey),
        read: async (mode, signal) => {
            const previous = getSnapshot<WebOverviewSnapshot>(context.client, queryKey)
            try {
                const response: WebOverviewResponseApi = context.demo
                    ? await demoRead(key, mode, signal, (refreshedAt) =>
                          demoWebOverviewResponse(query, demoAnchor(), refreshedAt)
                      )
                    : await fetchWebOverview(query, {
                          refresh: mode === 'force_blocking' ? 'force_blocking' : 'blocking',
                          signal,
                      })
                rejectAborted(signal)
                setSnapshot(context.client, queryKey, webOverviewSnapshot(response, previous, Date.now()))
                recordResponseStatus(key, response)
                return outcomeOf(response)
            } catch (error) {
                recordFailure<WebOverviewSnapshot>(context, queryKey, key, error)
                throw error
            }
        },
    }
}

/** The cached dashboard: its structure in phone order, and when this phone last read it. */
export interface DashboardSnapshot {
    view: DashboardView
    readAt: number
    refreshFailed: boolean
}

export function dashboardQueryKey(scope: ProjectScope | null, ref: string, override: FiltersOverride | null): QueryKey {
    return viewsKeys.dashboard(scope, ref, overrideKey(override))
}

function writeTiles(
    context: ItemContext,
    ref: string,
    api: DashboardApi,
    view: DashboardView,
    override: FiltersOverride | null,
    readAt: number
): void {
    for (const tile of phoneTiles(api)) {
        const tileViewOf = view.tiles.find((candidate) => candidate.tileId === tile.id)
        if (!tile.insight || !tileViewOf) {
            continue
        }
        const target = tileTarget(ref, tileViewOf, override)
        // A tile read without the override has its own cache entry. This response holds it with the override applied.
        if (!target || target.override !== override) {
            continue
        }
        const queryKey = insightQueryKey(context.scope, target)
        const itemKey = freshnessKey(queryKey)
        const previous = getSnapshot<InsightSnapshot>(context.client, queryKey)
        const previousRefresh = Date.parse(previous?.lastRefreshAt ?? '')
        const incomingRefresh = Date.parse(tile.insight.last_refresh ?? '')
        // A cache-only dashboard read can finish after a newer tile compute from the Views list.
        if (
            previous &&
            Number.isFinite(previousRefresh) &&
            Number.isFinite(incomingRefresh) &&
            previousRefresh > incomingRefresh &&
            stableStringify(previous.query) === stableStringify(tile.insight.query)
        ) {
            continue
        }
        setSnapshot(
            context.client,
            queryKey,
            insightSnapshot(tile.insight, previous, {
                readAt,
                serverNow: serverNow(),
                tileOverrides: tile.filters_overrides,
            })
        )
        recordResponseStatus(itemKey, tile.insight)
    }
}

/**
 * The dashboard read: `GET dashboards/{id}/?refresh=force_cache`. It writes the dashboard and the cached result of
 * every tile it carries, and never computes.
 */
export function dashboardContainer(
    context: ItemContext,
    ref: string,
    override: FiltersOverride | null
): RefreshContainer {
    const queryKey = dashboardQueryKey(context.scope, ref, override)
    const key = freshnessKey(queryKey)
    const current = (): DashboardSnapshot | undefined => getSnapshot<DashboardSnapshot>(context.client, queryKey)
    return {
        key,
        family: 'dashboards',
        readAt: () => current()?.readAt ?? null,
        lastRefresh: () => current()?.view.lastRefresh ?? null,
        read: async (signal) => {
            try {
                const api = context.demo
                    ? await demoRead(key, 'force_cache', signal, () =>
                          demoDashboardResponse(ref, override, demoAnchor(), (shortId) => {
                              const tileKey = insightItemKey(context.scope, { shortId, dashboardRef: ref, override })
                              return useDemoViews.getState().refreshedAt[tileKey]
                          })
                      )
                    : await fetchDashboard(Number(ref), { filtersOverride: override, signal })
                if (!api) {
                    throw notFound()
                }
                rejectAborted(signal)
                const readAt = Date.now()
                const view = dashboardView(api)
                writeTiles(context, ref, api, view, override, readAt)
                setSnapshot<DashboardSnapshot>(context.client, queryKey, { view, readAt, refreshFailed: false })
                useItemErrors.getState().clear(key)
                return { status: 'ok', computed: false }
            } catch (error) {
                recordFailure<DashboardSnapshot>(context, queryKey, key, error)
                throw error
            }
        },
    }
}
