import type { BreakPointFunction } from 'kea'
import {
    MakeLogicType,
    actions,
    afterMount,
    connect,
    isBreakpoint,
    kea,
    listeners,
    path,
    reducers,
    selectors,
    sharedListeners,
} from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router } from 'kea-router'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { retryWithBackoff } from 'lib/utils/async'
import { objectsEqual } from 'lib/utils/objects'
import { projectLogic } from 'scenes/projectLogic'

import { signalsAnomaliesPointsCreate, signalsAnomaliesSearchRetrieve } from 'products/signals/frontend/generated/api'
import type {
    AnomalyPointsResponseApi,
    AnomalySearchResponseApi,
    AnomalySeriesApi,
    AnomalySeriesPointApi,
} from 'products/signals/frontend/generated/api.schemas'
import {
    SignalsAnomaliesSearchRetrieveInterval,
    SignalsAnomaliesSearchRetrieveOrder,
    SignalsAnomaliesSearchRetrieveViewedWithinDays,
} from 'products/signals/frontend/generated/api.schemas'

export const ANOMALIES_PAGE_SIZE = 50
// Matches `scored_history_ready` in the anomaly search, which needs 14 scored days.
export const SCORED_HISTORY_READY_DAYS = 14
export const CHART_POINTS_MAX_ATTEMPTS = 3
export const CHART_POINTS_RETRY_DELAY_MS = 1000

// Null lists the insights of the whole project.
export type AnomaliesScope = SignalsAnomaliesSearchRetrieveViewedWithinDays | null

const DEFAULT_ANOMALIES_SCOPE: AnomaliesScope = SignalsAnomaliesSearchRetrieveViewedWithinDays.Number30
const ANOMALIES_SCOPE_PARAM = 'anomalies_scope'
const WHOLE_PROJECT_SCOPE_PARAM = 'project'

export interface AnomaliesFilters {
    dateFrom: string
    // Null lists the series of every interval.
    interval: SignalsAnomaliesSearchRetrieveInterval | null
    dashboardId: number | null
    search: string
    viewedWithinDays: AnomaliesScope
}

export const DEFAULT_ANOMALIES_FILTERS: AnomaliesFilters = {
    dateFrom: '-3d',
    interval: null,
    dashboardId: null,
    search: '',
    viewedWithinDays: DEFAULT_ANOMALIES_SCOPE,
}

// An unknown value opens the default scope, so an old or edited link still loads.
function scopeFromUrl(value: unknown): AnomaliesScope {
    if (value === WHOLE_PROJECT_SCOPE_PARAM) {
        return null
    }
    const days = Number(value)
    return (
        Object.values(SignalsAnomaliesSearchRetrieveViewedWithinDays).find((d) => d === days) ?? DEFAULT_ANOMALIES_SCOPE
    )
}

function scopeToUrl(scope: AnomaliesScope): string | undefined {
    if (scope === DEFAULT_ANOMALIES_SCOPE) {
        return undefined
    }
    return scope == null ? WHOLE_PROJECT_SCOPE_PARAM : String(scope)
}

export type AnomaliesLoadError = 'not_available' | 'failed'

export interface AnomalyChartPoints {
    // The start of the chart window. It does not follow the flag window.
    chartFrom: string
    points: AnomalySeriesPointApi[]
}

export type AnomalyRowRating = 'useful' | 'not_useful'

export function anomalySeriesKey(series: Pick<AnomalySeriesApi, 'insight_id' | 'series_key' | 'interval'>): string {
    return `${series.insight_id}-${series.series_key}-${series.interval}`
}

// Feedback is about the newest flagged bucket, so a later flag on the same series asks again.
export function anomalyRatingKey(series: AnomalySeriesApi): string {
    return `${anomalySeriesKey(series)}-${series.last_flagged_bucket ?? ''}`
}

function errorStatus(error: unknown): number | undefined {
    return (error as { status?: number } | undefined)?.status
}

function errorKind(error: unknown): AnomaliesLoadError {
    // The search endpoint answers 404 while its own feature flag is off for the user.
    return errorStatus(error) === 404 ? 'not_available' : 'failed'
}

// A client error gives the same answer on the next try.
function isRetryableChartError(error: unknown): boolean {
    const status = errorStatus(error)
    return status == null || status >= 500
}

// Leaves out the search text, which can hold insight names.
function filterProperties(filters: AnomaliesFilters): Record<string, unknown> {
    return {
        date_from: filters.dateFrom,
        interval: filters.interval,
        has_dashboard: filters.dashboardId != null,
        has_search: !!filters.search.trim(),
        viewed_within_days: filters.viewedWithinDays,
    }
}

async function searchAnomalies(
    projectId: number,
    filters: AnomaliesFilters,
    offset: number
): Promise<AnomalySearchResponseApi> {
    return await signalsAnomaliesSearchRetrieve(String(projectId), {
        date_from: filters.dateFrom,
        order: SignalsAnomaliesSearchRetrieveOrder.Recent,
        group_by: 'series',
        only_flagged: true,
        include_points: false,
        limit: ANOMALIES_PAGE_SIZE,
        offset,
        ...(filters.interval != null && { interval: filters.interval }),
        ...(filters.dashboardId != null && { dashboard_id: filters.dashboardId }),
        ...(filters.search.trim() && { search: filters.search.trim() }),
        ...(filters.viewedWithinDays != null && { viewed_within_days: filters.viewedWithinDays }),
    })
}

// The flagged bucket identifies what the person judged. Names and labels stay out, because they can hold user data.
function seriesProperties(series: AnomalySeriesApi): Record<string, unknown> {
    return {
        insight_id: series.insight_id,
        series_key: series.series_key,
        interval: series.interval,
        flagged_bucket: series.last_flagged_bucket,
        flagged_buckets: series.flagged_buckets,
        scored_buckets: series.scored_buckets,
        anomaly_rate: series.anomaly_rate,
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface anomaliesTabLogicValues {
    currentProjectId: number | null // projectLogic
    anomalies: AnomalySearchResponseApi | null
    anomaliesLoading: boolean
    chartPoints: Record<string, AnomalyChartPoints>
    chartPointsStatus: Record<string, 'failed' | 'loading'>
    filters: AnomaliesFilters
    hasMore: boolean
    loadError: AnomaliesLoadError | null
    loadingMore: boolean
    series: AnomalySeriesApi[]
    seriesRatings: Record<string, AnomalyRowRating>
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface anomaliesTabLogicActions {
    loadAnomalies: ({ debounce }?: { debounce?: boolean }) => {
        debounce?: boolean
    }
    loadAnomaliesFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadAnomaliesSuccess: (
        anomalies: AnomalySearchResponseApi | null,
        payload?: {
            debounce?: boolean
        }
    ) => {
        anomalies: AnomalySearchResponseApi | null
        payload?: {
            debounce?: boolean
        }
    }
    loadChartPoints: (series: AnomalySeriesApi[]) => {
        series: AnomalySeriesApi[]
    }
    loadMoreAnomalies: () => any
    loadMoreAnomaliesFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadMoreAnomaliesSuccess: (
        anomalies: AnomalySearchResponseApi | null,
        payload?: any
    ) => {
        anomalies: AnomalySearchResponseApi | null
        payload?: any
    }
    rateSeries: (
        series: AnomalySeriesApi,
        rating: AnomalyRowRating,
        position: number
    ) => {
        position: number
        rating: AnomalyRowRating
        series: AnomalySeriesApi
    }
    reportCreateAlertOpened: (
        series: AnomalySeriesApi,
        position: number
    ) => {
        position: number
        series: AnomalySeriesApi
    }
    reportInsightOpened: (
        series: AnomalySeriesApi,
        position: number
    ) => {
        position: number
        series: AnomalySeriesApi
    }
    resetFilters: () => {
        value: true
    }
    setChartPoints: (
        requested: string[],
        response: AnomalyPointsResponseApi
    ) => {
        requested: string[]
        response: AnomalyPointsResponseApi
    }
    setChartPointsFailed: (requested: string[]) => {
        requested: string[]
    }
    setFilters: (filters: Partial<AnomaliesFilters>) => {
        filters: Partial<AnomaliesFilters>
    }
    setLoadError: (loadError: AnomaliesLoadError) => {
        loadError: AnomaliesLoadError
    }
    setScopeFromUrl: (viewedWithinDays: AnomaliesScope) => {
        viewedWithinDays: AnomaliesScope
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface anomaliesTabLogicMeta {
    sharedListeners: {
        loadMissingChartPoints: (
            payload: any,
            breakpoint: BreakPointFunction,
            action: {
                type: string
                payload: any
            },
            previousState: any
        ) => void | Promise<void>
    }
    __keaTypeGenInternalSelectorTypes: {
        series: (anomalies: AnomalySearchResponseApi | null) => AnomalySeriesApi[]
        hasMore: (anomalies: AnomalySearchResponseApi | null) => boolean
    }
}

export type anomaliesTabLogicType = MakeLogicType<
    anomaliesTabLogicValues,
    anomaliesTabLogicActions,
    Record<string, any>,
    anomaliesTabLogicMeta
>

export const anomaliesTabLogic = kea<anomaliesTabLogicType>([
    path(['products', 'product_analytics', 'frontend', 'insights', 'anomalies', 'anomaliesTabLogic']),
    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),
    actions({
        setFilters: (filters: Partial<AnomaliesFilters>) => ({ filters }),
        setScopeFromUrl: (viewedWithinDays: AnomaliesScope) => ({ viewedWithinDays }),
        resetFilters: true,
        reportInsightOpened: (series: AnomalySeriesApi, position: number) => ({ series, position }),
        rateSeries: (series: AnomalySeriesApi, rating: AnomalyRowRating, position: number) => ({
            series,
            rating,
            position,
        }),
        reportCreateAlertOpened: (series: AnomalySeriesApi, position: number) => ({ series, position }),
        setLoadError: (loadError: AnomaliesLoadError) => ({ loadError }),
        loadChartPoints: (series: AnomalySeriesApi[]) => ({ series }),
        setChartPoints: (requested: string[], response: AnomalyPointsResponseApi) => ({ requested, response }),
        setChartPointsFailed: (requested: string[]) => ({ requested }),
    }),
    reducers({
        filters: [
            DEFAULT_ANOMALIES_FILTERS as AnomaliesFilters,
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
                setScopeFromUrl: (state, { viewedWithinDays }) => ({ ...state, viewedWithinDays }),
                // The scope picks whose insights the tab lists, so clearing the filters inside it keeps it.
                resetFilters: (state) => ({ ...DEFAULT_ANOMALIES_FILTERS, viewedWithinDays: state.viewedWithinDays }),
            },
        ],
    }),
    loaders(({ actions, values }) => ({
        anomalies: [
            null as AnomalySearchResponseApi | null,
            {
                loadAnomalies: async ({ debounce }: { debounce?: boolean } = {}, breakpoint) => {
                    if (debounce) {
                        await breakpoint(300)
                    }
                    if (values.currentProjectId == null) {
                        return null
                    }
                    try {
                        const response = await searchAnomalies(values.currentProjectId, values.filters, 0)
                        breakpoint()
                        return response
                    } catch (error) {
                        if (error instanceof Error && isBreakpoint(error)) {
                            throw error
                        }
                        // A newer search replaced this one, so its failure must not hide the newer results.
                        breakpoint()
                        // Handled here rather than as a loader failure, so the app shows no generic error toast
                        // and does not report the expected 404 as an exception.
                        actions.setLoadError(errorKind(error))
                        return null
                    }
                },
                loadMoreAnomalies: async () => {
                    const current = values.anomalies
                    if (values.currentProjectId == null || !current?.has_more) {
                        return current
                    }
                    const filters = values.filters
                    let response: AnomalySearchResponseApi
                    try {
                        response = await searchAnomalies(values.currentProjectId, filters, current.series.length)
                    } catch {
                        lemonToast.error("Couldn't load more anomalies. Try again.")
                        return current
                    }
                    // A filter change while this page loaded starts a new list, so this page belongs to the old one.
                    if (!objectsEqual(filters, values.filters) || values.anomalies !== current) {
                        return values.anomalies
                    }
                    return { ...response, series: [...current.series, ...response.series] }
                },
            },
        ],
    })),
    reducers({
        loadError: [
            null as AnomaliesLoadError | null,
            {
                loadAnomalies: () => null,
                setLoadError: (_, { loadError }) => loadError,
            },
        ],
        seriesRatings: [
            {} as Record<string, AnomalyRowRating>,
            {
                rateSeries: (state, { series, rating }) => ({ ...state, [anomalyRatingKey(series)]: rating }),
            },
        ],
        loadingMore: [
            false,
            {
                loadMoreAnomalies: () => true,
                loadMoreAnomaliesSuccess: () => false,
                loadMoreAnomaliesFailure: () => false,
            },
        ],
        chartPoints: [
            {} as Record<string, AnomalyChartPoints>,
            {
                loadAnomalies: () => ({}),
                setChartPoints: (state, { requested, response }) => {
                    const next = { ...state }
                    // The response leaves out a series the user cannot read. It charts as empty, not as loading.
                    for (const id of requested) {
                        next[id] = { chartFrom: response.date_to, points: [] }
                    }
                    for (const row of response.series) {
                        next[anomalySeriesKey(row)] = { chartFrom: row.date_from, points: row.points }
                    }
                    return next
                },
            },
        ],
        chartPointsStatus: [
            {} as Record<string, 'loading' | 'failed'>,
            {
                loadAnomalies: () => ({}),
                loadChartPoints: (state, { series }) => ({
                    ...state,
                    ...Object.fromEntries(series.map((row) => [anomalySeriesKey(row), 'loading' as const])),
                }),
                setChartPoints: (state, { requested }) =>
                    Object.fromEntries(Object.entries(state).filter(([id]) => !requested.includes(id))),
                setChartPointsFailed: (state, { requested }) => ({
                    ...state,
                    ...Object.fromEntries(requested.map((id) => [id, 'failed' as const])),
                }),
            },
        ],
    }),
    selectors({
        series: [
            (s) => [s.anomalies],
            (anomalies: AnomalySearchResponseApi | null): AnomalySeriesApi[] => anomalies?.series ?? [],
        ],
        hasMore: [(s) => [s.anomalies], (anomalies: AnomalySearchResponseApi | null): boolean => !!anomalies?.has_more],
    }),
    sharedListeners(({ actions, values }) => ({
        // Skips failed rows too, so a new page does not retry them. The next list load does.
        loadMissingChartPoints: () => {
            const missing = values.series.filter((row) => {
                const id = anomalySeriesKey(row)
                return !values.chartPoints[id] && !values.chartPointsStatus[id]
            })
            for (let start = 0; start < missing.length; start += ANOMALIES_PAGE_SIZE) {
                actions.loadChartPoints(missing.slice(start, start + ANOMALIES_PAGE_SIZE))
            }
        },
    })),
    listeners(({ actions, values, selectors, sharedListeners, cache }) => ({
        loadAnomalies: () => {
            // Re-adding the key aborts the chart requests of the replaced list. The unmount aborts the last one.
            cache.disposables.add(
                () => {
                    const controller = new AbortController()
                    cache.chartPointsSignal = controller.signal
                    return () => controller.abort()
                },
                'chartPointsRequests',
                { pauseOnPageHidden: false }
            )
        },
        loadAnomaliesSuccess: sharedListeners.loadMissingChartPoints,
        loadMoreAnomaliesSuccess: sharedListeners.loadMissingChartPoints,
        loadChartPoints: async ({ series }) => {
            const requested = series.map(anomalySeriesKey)
            const signal: AbortSignal = cache.chartPointsSignal
            const projectId = values.currentProjectId
            if (projectId == null) {
                actions.setChartPointsFailed(requested)
                return
            }
            const body = {
                series: series.map(({ insight_id, series_key, interval }) => ({ insight_id, series_key, interval })),
            }
            try {
                const response = await retryWithBackoff(
                    () => signalsAnomaliesPointsCreate(String(projectId), body, { signal }),
                    {
                        maxAttempts: CHART_POINTS_MAX_ATTEMPTS,
                        initialDelayMs: CHART_POINTS_RETRY_DELAY_MS,
                        signal,
                        shouldRetry: isRetryableChartError,
                    }
                )
                // The response can arrive after the abort, so the signal is checked here too.
                if (!signal.aborted) {
                    actions.setChartPoints(requested, response)
                }
            } catch {
                if (!signal.aborted) {
                    actions.setChartPointsFailed(requested)
                }
            }
        },
        setFilters: ({ filters }) => {
            const changed = Object.keys(filters)
            posthog.capture('anomalies tab filter changed', { changed, ...filterProperties(values.filters) })
            actions.loadAnomalies({ debounce: changed.includes('search') })
        },
        resetFilters: () => {
            actions.loadAnomalies()
        },
        loadMoreAnomalies: () => {
            posthog.capture('anomalies tab load more', { offset: values.series.length })
        },
        reportInsightOpened: ({ series, position }) => {
            posthog.capture('anomalies tab insight opened', {
                insight_id: series.insight_id,
                interval: series.interval,
                flagged_buckets: series.flagged_buckets,
                position,
            })
        },
        rateSeries: ({ series, rating, position }, _, __, previousState) => {
            if (selectors.seriesRatings(previousState)[anomalyRatingKey(series)] === rating) {
                return
            }
            posthog.capture('anomalies tab series rated', {
                ...seriesProperties(series),
                rating,
                position,
            })
        },
        reportCreateAlertOpened: ({ series, position }) => {
            posthog.capture('anomalies tab create alert opened', {
                ...seriesProperties(series),
                position,
            })
        },
    })),
    actionToUrl(({ values }) => ({
        setFilters: () => {
            const { location, searchParams, hashParams } = router.values
            const { [ANOMALIES_SCOPE_PARAM]: _, ...otherParams } = searchParams
            const scope = scopeToUrl(values.filters.viewedWithinDays)
            return [
                location.pathname,
                scope ? { ...otherParams, [ANOMALIES_SCOPE_PARAM]: scope } : otherParams,
                hashParams,
                { replace: true },
            ]
        },
    })),
    afterMount(({ actions, values }) => {
        const scope = scopeFromUrl(router.values.searchParams[ANOMALIES_SCOPE_PARAM])
        if (scope !== values.filters.viewedWithinDays) {
            actions.setScopeFromUrl(scope)
        }
        posthog.capture('anomalies tab viewed', filterProperties(values.filters))
        actions.loadAnomalies()
    }),
])
