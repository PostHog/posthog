import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { type MetricSummary } from 'lib/components/Metric/metricSummary'
import { type SparklineTimeSeries } from 'lib/components/Sparkline'
import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils/dateFilters'
import { teamLogic } from 'scenes/teamLogic'

import { metricsCharacterizeCreate, metricsQueryCreate } from 'products/metrics/frontend/generated/api'
import { OtelMetricTypeEnumApi } from 'products/metrics/frontend/generated/api.schemas'
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
        metricName: ['' as string, { setMetricName: (_, { metricName }) => metricName }],
        aggregation: [
            DEFAULT_AGGREGATION as MetricAggregation,
            { setAggregation: (_, { aggregation }) => aggregation },
        ],
        dateFrom: [DEFAULT_DATE_FROM as string | null, { setDateFrom: (_, { dateFrom }) => dateFrom }],
        dateTo: [null as string | null, { setDateTo: (_, { dateTo }) => dateTo }],
        viewMode: ['chart' as MetricsViewMode, { setViewMode: (_, { viewMode }) => viewMode }],
        // 'latest' (current value) is the natural default for a live single-metric stat.
        statSummary: ['latest' as MetricSummary, { setStatSummary: (_, { statSummary }) => statSummary }],
        liveRefresh: [false, { setLiveRefresh: (_, { liveRefresh }) => liveRefresh }],
        // Attribute keys to split the metric into one series each (e.g. ['service.name', 'env']).
        groupByKeys: [[] as string[], { setGroupByKeys: (_, { groupByKeys }) => groupByKeys }],
        // Raw "key=value" filter chips; parsed into query filters by the `queryFilters` selector.
        filterStrings: [[] as string[], { setFilterStrings: (_, { filterStrings }) => filterStrings }],
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
                                ...(values.selectedMetricType ? { metricType: values.selectedMetricType } : {}),
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
        // The picked metric's type (from the names list). Sent with the query so
        // a name that exists as several types (e.g. a counter and a gauge)
        // charts only the picked one instead of blending them.
        selectedMetricType: [
            (s) => [s.metricName, s.items],
            (metricName, items): OtelMetricTypeEnumApi | null => {
                const metricType = items.find((item) => item.name === metricName.trim())?.metric_type
                const known = Object.values(OtelMetricTypeEnumApi) as string[]
                return metricType && known.includes(metricType) ? (metricType as OtelMetricTypeEnumApi) : null
            },
        ],
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
])
