import equal from 'fast-deep-equal'
import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import { syncSearchParams, updateSearchParams } from '@posthog/products-error-tracking/frontend/utils'

import { type MetricSummary } from 'lib/components/Metric/metricSummary'
import { type SparklineTimeSeries } from 'lib/components/Sparkline'
import { dayjs } from 'lib/dayjs'
import { trackedActionToUrl } from 'lib/logic/scenes/trackedActionToUrl'
import { dateStringToDayJs } from 'lib/utils/dateFilters'
import { Params } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { metricsCharacterizeCreate, metricsQueryCreate } from 'products/metrics/frontend/generated/api'
import type {
    _MetricAnomalyReportApi,
    _MetricFilterApi,
    _MetricSeriesApi,
    MetricAnomalyDirectionEnumApi,
} from 'products/metrics/frontend/generated/api.schemas'

import { metricNamePickerLogic } from './metricNamePickerLogic'
import { formatSeriesName, seriesColor } from './metricsSeries'
import type { metricsViewerLogicType } from './metricsViewerLogicType'

export type MetricAggregation = 'sum' | 'avg' | 'count' | 'p95' | 'rate' | 'increase'

// `chart` shows the time series; `stat` shows a single headline value + change pill (a Grafana "stat" panel).
export type MetricsViewMode = 'chart' | 'stat'

export type MetricsViewerSeries = _MetricSeriesApi

// Display shape for the stat card's "vs baseline" anomaly badge (null = no anomaly / flat metric).
export interface MetricsAnomalyBadge {
    direction: MetricAnomalyDirectionEnumApi
    percent: number
    baselineMean: number
    anomalyMean: number
    onsetTime: string | null
}

const DEFAULT_AGGREGATION: MetricAggregation = 'sum'

// Aggregation applied automatically when a metric of this type is selected.
// Cumulative counters (OTel type 'sum') summed raw give meaningless ever-growing
// totals — 'increase' is the honest default and is temporality-aware server-side
// (delta samples are summed as-is), so it's correct for delta producers too.
export const RECOMMENDED_AGGREGATION_BY_TYPE: Record<string, MetricAggregation> = {
    gauge: 'avg',
    sum: 'increase',
    counter: 'increase',
    histogram: 'p95',
    summary: 'p95',
    exponential_histogram: 'p95',
}
const DEFAULT_DATE_FROM = '-1h'
const NEW_QUERY_STARTED_ERROR_MESSAGE = 'A new metrics query started, cancelling the previous one'
// The anomaly badge characterizes the most recent slice of the selected window against the rest.
const ANOMALY_WINDOW_FRACTION = 0.2
export const LIVE_REFRESH_MS = 15_000
const LIVE_REFRESH_KEY = 'metricsLiveRefresh'

// Viewer state persisted in the URL so a reloaded or shared /metrics link restores the same view.
// These defaults are the single source of truth for both the reducers below and the URL round-trip:
// updateSearchParams omits a param when it equals its default, keeping default URLs clean.
const DEFAULT_METRIC_NAME = ''
const DEFAULT_VIEW_MODE: MetricsViewMode = 'chart'
const DEFAULT_DATE_TO: string | null = null
const DEFAULT_GROUP_BY_KEYS: string[] = []
const DEFAULT_FILTER_STRINGS: string[] = []
const VALID_AGGREGATIONS: MetricAggregation[] = ['sum', 'avg', 'count', 'p95', 'rate', 'increase']

// kea-router coerces numeric- and boolean-looking values on decode, so normalize scalar params back
// to the string we stored and ignore anything that isn't a plain scalar (e.g. a hand-crafted array).
const asParamString = (value: unknown): string | undefined =>
    typeof value === 'string'
        ? value
        : typeof value === 'number' || typeof value === 'boolean'
          ? String(value)
          : undefined

// Array params round-trip as real arrays (kea-router JSON-encodes them); accept only string arrays.
const asParamStringArray = (value: unknown): string[] | undefined =>
    Array.isArray(value) && value.every((item) => typeof item === 'string') ? value : undefined

// Parse a "key=value" chip into an equality filter. Returns null for malformed input (no key before '=').
const parseFilter = (raw: string): _MetricFilterApi | null => {
    const eq = raw.indexOf('=')
    if (eq <= 0) {
        return null
    }
    return { key: raw.slice(0, eq).trim(), op: 'eq', value: raw.slice(eq + 1).trim() }
}

const resolveDate = (value: string | null | undefined): string | null => {
    if (!value) {
        return null
    }
    const dj = dateStringToDayJs(value) ?? dayjs(value)
    return dj.isValid() ? dj.toISOString() : null
}

export const metricsViewerLogic = kea<metricsViewerLogicType>([
    path(['products', 'metrics', 'frontend', 'components', 'metricsViewerLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeamId'], metricNamePickerLogic, ['items']],
    })),
    actions({
        setMetricName: (metricName: string) => ({ metricName }),
        setAggregation: (aggregation: MetricAggregation) => ({ aggregation }),
        setDateFrom: (dateFrom: string | null) => ({ dateFrom }),
        setDateTo: (dateTo: string | null) => ({ dateTo }),
        setViewMode: (viewMode: MetricsViewMode) => ({ viewMode }),
        setStatSummary: (statSummary: MetricSummary) => ({ statSummary }),
        setLiveRefresh: (liveRefresh: boolean) => ({ liveRefresh }),
        setGroupByKeys: (groupByKeys: string[]) => ({ groupByKeys }),
        setFilterStrings: (filterStrings: string[]) => ({ filterStrings }),
        // AbortController plumbing mirrors logsViewerDataLogic: a `cancelInProgress`
        // action aborts the previous controller before storing the new one.
        setQueryAbortController: (controller: AbortController | null) => ({ controller }),
        cancelInProgressQuery: (controller: AbortController | null) => ({ controller }),
    }),
    reducers({
        metricName: [DEFAULT_METRIC_NAME as string, { setMetricName: (_, { metricName }) => metricName }],
        aggregation: [
            DEFAULT_AGGREGATION as MetricAggregation,
            { setAggregation: (_, { aggregation }) => aggregation },
        ],
        dateFrom: [DEFAULT_DATE_FROM as string | null, { setDateFrom: (_, { dateFrom }) => dateFrom }],
        dateTo: [DEFAULT_DATE_TO as string | null, { setDateTo: (_, { dateTo }) => dateTo }],
        viewMode: [DEFAULT_VIEW_MODE as MetricsViewMode, { setViewMode: (_, { viewMode }) => viewMode }],
        // 'latest' (current value) is the natural default for a live single-metric stat.
        statSummary: ['latest' as MetricSummary, { setStatSummary: (_, { statSummary }) => statSummary }],
        liveRefresh: [false, { setLiveRefresh: (_, { liveRefresh }) => liveRefresh }],
        // Attribute keys to split the metric into one series each (e.g. ['service.name', 'env']).
        groupByKeys: [DEFAULT_GROUP_BY_KEYS as string[], { setGroupByKeys: (_, { groupByKeys }) => groupByKeys }],
        // Raw "key=value" filter chips; parsed into query filters by the `queryFilters` selector.
        filterStrings: [
            DEFAULT_FILTER_STRINGS as string[],
            { setFilterStrings: (_, { filterStrings }) => filterStrings },
        ],
        queryAbortController: [
            null as AbortController | null,
            { setQueryAbortController: (_, { controller }) => controller },
        ],
    }),
    listeners(({ actions, values, cache }) => ({
        setMetricName: ({ metricName }) => {
            // Each metric type has one sensible default; a manual aggregation pick
            // holds only until the next metric switch.
            const metricType = values.items.find((item) => item.name === metricName)?.metric_type
            const recommended = metricType ? RECOMMENDED_AGGREGATION_BY_TYPE[metricType] : undefined
            if (recommended && recommended !== values.aggregation) {
                actions.setAggregation(recommended)
            }
        },
        cancelInProgressQuery: ({ controller }) => {
            if (values.queryAbortController !== null) {
                values.queryAbortController.abort(NEW_QUERY_STARTED_ERROR_MESSAGE)
            }
            actions.setQueryAbortController(controller)
        },
        setLiveRefresh: ({ liveRefresh }) => {
            if (!liveRefresh) {
                cache.disposables.dispose(LIVE_REFRESH_KEY)
                return
            }
            // pauseOnPageHidden (default) stops polling on a hidden tab and resumes on focus.
            cache.disposables.add(() => {
                const intervalId = setInterval(() => {
                    actions.fetchQueryResults({})
                    if (values.viewMode === 'stat') {
                        actions.fetchAnomaly({})
                    }
                }, LIVE_REFRESH_MS)
                return () => clearInterval(intervalId)
            }, LIVE_REFRESH_KEY)
        },
    })),
    loaders(({ values, actions }) => ({
        queryResults: [
            [] as MetricsViewerSeries[],
            {
                fetchQueryResults: async (_, breakpoint) => {
                    const trimmedName = values.metricName.trim()
                    if (!trimmedName) {
                        return []
                    }
                    const dateFromISO = resolveDate(values.dateFrom)
                    if (!dateFromISO) {
                        return []
                    }
                    await breakpoint(300)
                    const dateToISO = resolveDate(values.dateTo) ?? undefined
                    const controller = new AbortController()
                    actions.cancelInProgressQuery(controller)
                    const response = await metricsQueryCreate(
                        String(values.currentTeamId),
                        {
                            query: {
                                metricName: trimmedName,
                                aggregation: values.aggregation,
                                dateFrom: dateFromISO,
                                ...(dateToISO ? { dateTo: dateToISO } : {}),
                                ...(values.groupByKeys.length
                                    ? { groupBy: values.groupByKeys.map((key) => ({ key })) }
                                    : {}),
                                ...(values.queryFilters.length ? { filters: values.queryFilters } : {}),
                            },
                        },
                        { signal: controller.signal }
                    )
                    breakpoint()
                    actions.setQueryAbortController(null)
                    return response.results
                },
            },
        ],
        anomalyReport: [
            null as _MetricAnomalyReportApi | null,
            {
                clearAnomaly: () => null,
                fetchAnomaly: async (_, breakpoint) => {
                    const trimmedName = values.metricName.trim()
                    const fromISO = resolveDate(values.dateFrom)
                    if (!trimmedName || !fromISO) {
                        return null
                    }
                    const toISO = resolveDate(values.dateTo) ?? dayjs().toISOString()
                    const spanMs = dayjs(toISO).diff(dayjs(fromISO))
                    if (spanMs <= 0) {
                        return null
                    }
                    const anomalyFrom = dayjs(toISO)
                        .subtract(spanMs * ANOMALY_WINDOW_FRACTION, 'ms')
                        .toISOString()
                    await breakpoint(300)
                    const report = await metricsCharacterizeCreate(String(values.currentTeamId), {
                        query: {
                            metricName: trimmedName,
                            aggregation: values.aggregation,
                            anomalyFrom,
                            anomalyTo: toISO,
                            ...(values.queryFilters.length ? { filters: values.queryFilters } : {}),
                        },
                    })
                    breakpoint()
                    return report
                },
            },
        ],
    })),
    selectors({
        hasMetricName: [(s) => [s.metricName], (metricName) => metricName.trim().length > 0],
        queryFilters: [
            (s) => [s.filterStrings],
            (filterStrings: string[]): _MetricFilterApi[] =>
                filterStrings.map(parseFilter).filter((f): f is _MetricFilterApi => f !== null),
        ],
        // The viewer renders the first series only for now; group-by lands
        // multi-series rendering in a later PR.
        // Metrics has no compare/previous-series concept, so "current" is simply the first series.
        currentSeries: [(s) => [s.queryResults], (results): MetricsViewerSeries | undefined => results[0]],
        // All series rendered as chart lines (a group-by query returns one series per label combination).
        // The x-axis labels come from `sparklineLabels` (the backend grids every series onto one time axis).
        chartSeries: [
            (s) => [s.queryResults, s.metricName],
            (results: MetricsViewerSeries[], metricName: string): SparklineTimeSeries[] =>
                results.map((series, index) => ({
                    name: formatSeriesName(series, metricName),
                    values: series.points.map((p) => p.value),
                    color: seriesColor(index),
                })),
        ],
        sparklineValues: [
            (s) => [s.currentSeries],
            (series: MetricsViewerSeries | undefined) => (series?.points ?? []).map((p) => p.value),
        ],
        sparklineLabels: [
            (s) => [s.currentSeries],
            (series: MetricsViewerSeries | undefined) => (series?.points ?? []).map((p) => p.time),
        ],
        // The stat card summarizes the per-bucket `sparklineValues` into one headline value;
        // `statTotal` is the grand total across buckets (the basis for the 'total' summary).
        statTotal: [(s) => [s.sparklineValues], (values: number[]) => values.reduce((sum, v) => sum + v, 0)],
        // Display shape for the anomaly badge — null when there's no report or the metric is flat.
        anomalyBadge: [
            (s) => [s.anomalyReport],
            (report: _MetricAnomalyReportApi | null): MetricsAnomalyBadge | null =>
                report && report.direction !== 'flat'
                    ? {
                          direction: report.direction,
                          percent: Math.abs(Math.round((report.change_ratio - 1) * 100)),
                          baselineMean: report.baseline_mean,
                          anomalyMean: report.anomaly_mean,
                          onsetTime: report.onset_time,
                      }
                    : null,
        ],
    }),
    // Round-trip the viewer state through the URL so a reload or shared link restores it. The scene
    // logic owns `activeTab`; these keys are disjoint and syncSearchParams merges into existing params,
    // so the two coexist. `cache.isSyncingUrl` breaks the write -> read feedback loop (same guard as
    // metricsSceneLogic).
    urlToAction(({ actions, values, cache }) => {
        const syncFromUrl = (_: any, params: Params): void => {
            if (cache.isSyncingUrl) {
                return
            }
            const metricName = asParamString(params.metric)
            if (metricName !== undefined && metricName !== values.metricName) {
                actions.setMetricName(metricName)
            }
            // After metricName so a restored aggregation wins over the type-based default its listener applies.
            const aggregation = asParamString(params.agg)
            if (
                aggregation !== undefined &&
                VALID_AGGREGATIONS.includes(aggregation as MetricAggregation) &&
                aggregation !== values.aggregation
            ) {
                actions.setAggregation(aggregation as MetricAggregation)
            }
            const dateFrom = asParamString(params.dateFrom)
            if (dateFrom !== undefined && dateFrom !== values.dateFrom) {
                actions.setDateFrom(dateFrom)
            }
            const dateTo = asParamString(params.dateTo)
            if (dateTo !== undefined && dateTo !== values.dateTo) {
                actions.setDateTo(dateTo)
            }
            const viewMode = asParamString(params.view)
            if ((viewMode === 'chart' || viewMode === 'stat') && viewMode !== values.viewMode) {
                actions.setViewMode(viewMode)
            }
            const groupByKeys = asParamStringArray(params.groupBy)
            if (groupByKeys && !equal(groupByKeys, values.groupByKeys)) {
                actions.setGroupByKeys(groupByKeys)
            }
            const filterStrings = asParamStringArray(params.filters)
            if (filterStrings && !equal(filterStrings, values.filterStrings)) {
                actions.setFilterStrings(filterStrings)
            }
        }
        return { '*': syncFromUrl }
    }),
    trackedActionToUrl(({ values, cache }) => {
        const syncUrl = (): [string, Params, Record<string, any>, { replace: boolean }] => {
            cache.isSyncingUrl = true
            const result = syncSearchParams(router, (params: Params) => {
                updateSearchParams(params, 'metric', values.metricName, DEFAULT_METRIC_NAME)
                updateSearchParams(params, 'agg', values.aggregation, DEFAULT_AGGREGATION)
                updateSearchParams(params, 'dateFrom', values.dateFrom, DEFAULT_DATE_FROM)
                updateSearchParams(params, 'dateTo', values.dateTo, DEFAULT_DATE_TO)
                updateSearchParams(params, 'view', values.viewMode, DEFAULT_VIEW_MODE)
                updateSearchParams(params, 'groupBy', values.groupByKeys, DEFAULT_GROUP_BY_KEYS)
                updateSearchParams(params, 'filters', values.filterStrings, DEFAULT_FILTER_STRINGS)
                return params
            })
            queueMicrotask(() => {
                cache.isSyncingUrl = false
            })
            return result
        }
        return {
            setMetricName: () => syncUrl(),
            setAggregation: () => syncUrl(),
            setDateFrom: () => syncUrl(),
            setDateTo: () => syncUrl(),
            setViewMode: () => syncUrl(),
            setGroupByKeys: () => syncUrl(),
            setFilterStrings: () => syncUrl(),
        }
    }),
])
