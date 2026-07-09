import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { type MetricSummary } from 'lib/components/Metric/metricSummary'
import { type SparklineTimeSeries } from 'lib/components/Sparkline'
import { DEFAULT_UNIVERSAL_GROUP_FILTER } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { dayjs } from 'lib/dayjs'
import { escapeRegex } from 'lib/utils/actions'
import { dateStringToDayJs } from 'lib/utils/dateFilters'
import { teamLogic } from 'scenes/teamLogic'

import { PropertyOperator, UniversalFilterValue, UniversalFiltersGroup } from '~/types'

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
export const NEW_QUERY_STARTED_ERROR_MESSAGE = 'A new metrics query started, cancelling the previous one'

// A superseded or unmounted request rejects with an abort, not a real failure — never surface it as an error.
// The cancel path aborts with NEW_QUERY_STARTED_ERROR_MESSAGE, whose text doesn't contain "abort", so match it
// explicitly alongside the generic abort check (mirrors logsViewerDataLogic's isUserInitiatedError).
const isUserInitiatedError = (error: unknown): boolean => {
    const errorStr = String(error).toLowerCase()
    return error === NEW_QUERY_STARTED_ERROR_MESSAGE || errorStr.includes('abort')
}
// The anomaly badge characterizes the most recent slice of the selected window against the rest.
const ANOMALY_WINDOW_FRACTION = 0.2
export const LIVE_REFRESH_MS = 15_000
const LIVE_REFRESH_KEY = 'metricsLiveRefresh'

// The metrics backend speaks Prometheus-style label matchers, not the full PropertyOperator set.
export const METRIC_FILTER_OPERATOR_ALLOWLIST: PropertyOperator[] = [
    PropertyOperator.Exact,
    PropertyOperator.IsNot,
    PropertyOperator.Regex,
    PropertyOperator.NotRegex,
]

const OPERATOR_TO_FILTER_OP: Partial<Record<PropertyOperator, _MetricFilterApi['op']>> = {
    [PropertyOperator.Exact]: 'eq',
    [PropertyOperator.IsNot]: 'neq',
    [PropertyOperator.Regex]: 'regex',
    [PropertyOperator.NotRegex]: 'not_regex',
}

const toValueStrings = (value: unknown): string[] => {
    const raw = Array.isArray(value) ? value : value === null || value === undefined ? [] : [value]
    return raw.map((item) => String(item)).filter((item) => item.length > 0)
}

// Convert one filter-bar chip into the backend's `{key, op, value}` matcher. Filters run with
// scope 'auto' (resource attributes first, datapoint attributes as fallback), so scope is omitted.
// Returns null for chips still being edited (no key/value) or unsupported operators.
const propertyFilterToMetricFilter = (filter: UniversalFilterValue): _MetricFilterApi | null => {
    const key = 'key' in filter && filter.key ? String(filter.key) : ''
    const operator = 'operator' in filter && filter.operator ? filter.operator : PropertyOperator.Exact
    // A non-PropertyOperator value (e.g. an ActionFilter's fields) simply isn't in the map -> null.
    const op = OPERATOR_TO_FILTER_OP[operator as PropertyOperator]
    if (!key || !op) {
        return null
    }
    const values = toValueStrings('value' in filter ? filter.value : null)
    if (values.length === 0) {
        return null
    }
    if (values.length === 1) {
        return { key, op, value: values[0] }
    }
    // Multi-value chips become Prometheus-style alternations: eq/neq turn into an anchored
    // (not-)regex over the escaped literals; regex operators just OR the patterns together.
    if (op === 'eq' || op === 'neq') {
        return {
            key,
            op: op === 'eq' ? 'regex' : 'not_regex',
            value: `^(?:${values.map(escapeRegex).join('|')})$`,
        }
    }
    return { key, op, value: values.map((pattern) => `(?:${pattern})`).join('|') }
}

const flattenFilterValues = (group: UniversalFiltersGroup): UniversalFilterValue[] =>
    group.values.flatMap((value) => (isUniversalGroupFilterLike(value) ? flattenFilterValues(value) : [value]))

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
        setFilterGroup: (filterGroup: UniversalFiltersGroup) => ({ filterGroup }),
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
        // The filter bar's UniversalFilters group; converted into backend matchers by `queryFilters`.
        filterGroup: [DEFAULT_UNIVERSAL_GROUP_FILTER, { setFilterGroup: (_, { filterGroup }) => filterGroup }],
        queryAbortController: [
            null as AbortController | null,
            { setQueryAbortController: (_, { controller }) => controller },
        ],
        // A real query failure (bad regex, 500, timeout) — surfaced as a banner so it isn't mistaken
        // for the empty-result state. Cleared when a new query starts or one succeeds; an aborted
        // (superseded) query leaves the previous state untouched so refetches don't flash an error.
        queryError: [
            null as string | null,
            {
                fetchQueryResults: () => null,
                fetchQueryResultsSuccess: () => null,
                fetchQueryResultsFailure: (state, { error }) =>
                    isUserInitiatedError(error) ? state : error || 'Something went wrong running this query.',
            },
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
                // An AbortError-named DOMException (not a bare string) is what api.ts and the global
                // loader onFailure recognize as a cancellation, so a superseded query is swallowed
                // rather than logged/captured as a real error.
                values.queryAbortController.abort(new DOMException(NEW_QUERY_STARTED_ERROR_MESSAGE, 'AbortError'))
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
            (s) => [s.filterGroup],
            (filterGroup: UniversalFiltersGroup): _MetricFilterApi[] =>
                flattenFilterValues(filterGroup)
                    .map(propertyFilterToMetricFilter)
                    .filter((f): f is _MetricFilterApi => f !== null),
        ],
        // Scopes the filter bar's key/value suggestions to the viewer's window; splatted onto the
        // taxonomic endpoints as query params.
        attributeEndpointFilters: [
            (s) => [s.dateFrom, s.dateTo],
            (dateFrom, dateTo): Record<string, string> => ({
                ...(resolveDate(dateFrom) ? { dateFrom: resolveDate(dateFrom) as string } : {}),
                ...(resolveDate(dateTo) ? { dateTo: resolveDate(dateTo) as string } : {}),
            }),
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
                    // A null value is a gap (non-representable aggregate); Sparkline
                    // takes plain numbers, so gaps chart as 0 for now.
                    values: series.points.map((p) => p.value ?? 0),
                    color: seriesColor(index),
                })),
        ],
        sparklineValues: [
            (s) => [s.currentSeries],
            (series: MetricsViewerSeries | undefined) => (series?.points ?? []).map((p) => p.value ?? 0),
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
