import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { type MetricSummary } from 'lib/components/Metric/metricSummary'
import { type SparklineTimeSeries } from 'lib/components/Sparkline'
import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils/dateFilters'
import { teamLogic } from 'scenes/teamLogic'

import { metricsCharacterizeCreate, metricsQueryCreate } from 'products/metrics/frontend/generated/api'
import type {
    _MetricAnomalyReportApi,
    _MetricFilterApi,
    _MetricQueryBodyApi,
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

export interface MetricsViewerClause {
    metricName: string
    aggregation: MetricAggregation
    groupByKeys: string[]
    filterStrings: string[]
}

export type MetricsQuerySelection = Omit<_MetricQueryBodyApi, 'dateFrom' | 'dateTo'>

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
export const MAX_CLAUSES = 10

const DEFAULT_CLAUSE: MetricsViewerClause = {
    metricName: '',
    aggregation: DEFAULT_AGGREGATION,
    groupByKeys: [],
    filterStrings: [],
}

export const clauseLabel = (index: number): string => String.fromCharCode(97 + index)

const patchClause = (
    clauses: MetricsViewerClause[],
    index: number,
    patch: Partial<MetricsViewerClause>
): MetricsViewerClause[] => clauses.map((clause, i) => (i === index ? { ...clause, ...patch } : clause))

// Parse a "key=value" chip into an equality filter. Returns null for malformed input (no key before '=').
const parseFilter = (raw: string): _MetricFilterApi | null => {
    const eq = raw.indexOf('=')
    if (eq <= 0) {
        return null
    }
    return { key: raw.slice(0, eq).trim(), op: 'eq', value: raw.slice(eq + 1).trim() }
}

const parseFilters = (filterStrings: string[]): _MetricFilterApi[] =>
    filterStrings.map(parseFilter).filter((f): f is _MetricFilterApi => f !== null)

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
        setGroupByKeys: (groupByKeys: string[]) => ({ groupByKeys }),
        setFilterStrings: (filterStrings: string[]) => ({ filterStrings }),
        addClause: true,
        removeClause: (index: number) => ({ index }),
        updateClause: (index: number, clause: Partial<MetricsViewerClause>) => ({ index, clause }),
        setFormula: (formula: string) => ({ formula }),
        setFormulaEnabled: (formulaEnabled: boolean) => ({ formulaEnabled }),
        setDateFrom: (dateFrom: string | null) => ({ dateFrom }),
        setDateTo: (dateTo: string | null) => ({ dateTo }),
        setViewMode: (viewMode: MetricsViewMode) => ({ viewMode }),
        setStatSummary: (statSummary: MetricSummary) => ({ statSummary }),
        setLiveRefresh: (liveRefresh: boolean) => ({ liveRefresh }),
        // AbortController plumbing mirrors logsViewerDataLogic: a `cancelInProgress`
        // action aborts the previous controller before storing the new one.
        setQueryAbortController: (controller: AbortController | null) => ({ controller }),
        cancelInProgressQuery: (controller: AbortController | null) => ({ controller }),
    }),
    reducers({
        clauses: [
            [DEFAULT_CLAUSE] as MetricsViewerClause[],
            {
                setMetricName: (state, { metricName }) => patchClause(state, 0, { metricName }),
                setAggregation: (state, { aggregation }) => patchClause(state, 0, { aggregation }),
                setGroupByKeys: (state, { groupByKeys }) => patchClause(state, 0, { groupByKeys }),
                setFilterStrings: (state, { filterStrings }) => patchClause(state, 0, { filterStrings }),
                updateClause: (state, { index, clause }) => patchClause(state, index, clause),
                addClause: (state) => (state.length < MAX_CLAUSES ? [...state, { ...DEFAULT_CLAUSE }] : state),
                removeClause: (state, { index }) => (state.length > 1 ? state.filter((_, i) => i !== index) : state),
            },
        ],
        formula: ['', { setFormula: (_, { formula }) => formula }],
        formulaEnabled: [false, { setFormulaEnabled: (_, { formulaEnabled }) => formulaEnabled }],
        dateFrom: [DEFAULT_DATE_FROM as string | null, { setDateFrom: (_, { dateFrom }) => dateFrom }],
        dateTo: [null as string | null, { setDateTo: (_, { dateTo }) => dateTo }],
        viewMode: ['chart' as MetricsViewMode, { setViewMode: (_, { viewMode }) => viewMode }],
        // 'latest' (current value) is the natural default for a live single-metric stat.
        statSummary: ['latest' as MetricSummary, { setStatSummary: (_, { statSummary }) => statSummary }],
        liveRefresh: [false, { setLiveRefresh: (_, { liveRefresh }) => liveRefresh }],
        queryAbortController: [
            null as AbortController | null,
            { setQueryAbortController: (_, { controller }) => controller },
        ],
    }),
    listeners(({ actions, values, cache }) => {
        // Each metric type has one sensible default; a manual aggregation pick
        // holds only until the next metric switch on that clause.
        const applyRecommendedAggregation = (index: number, metricName: string): void => {
            const metricType = values.items.find((item) => item.name === metricName)?.metric_type
            const recommended = metricType ? RECOMMENDED_AGGREGATION_BY_TYPE[metricType] : undefined
            if (recommended && recommended !== values.clauses[index]?.aggregation) {
                actions.updateClause(index, { aggregation: recommended })
            }
        }
        return {
            setMetricName: ({ metricName }) => applyRecommendedAggregation(0, metricName),
            updateClause: ({ index, clause }) => {
                if (clause.metricName !== undefined) {
                    applyRecommendedAggregation(index, clause.metricName)
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
                        if (values.effectiveViewMode === 'stat') {
                            actions.fetchAnomaly({})
                        }
                    }, LIVE_REFRESH_MS)
                    return () => clearInterval(intervalId)
                }, LIVE_REFRESH_KEY)
            },
        }
    }),
    loaders(({ values, actions }) => ({
        queryResults: [
            [] as MetricsViewerSeries[],
            {
                fetchQueryResults: async (_, breakpoint) => {
                    const selection = values.querySelection
                    if (!selection) {
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
                                ...selection,
                                dateFrom: dateFromISO,
                                ...(dateToISO ? { dateTo: dateToISO } : {}),
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
                    if (!values.isSimpleMode) {
                        return null
                    }
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
        metricName: [(s) => [s.clauses], (clauses) => clauses[0]?.metricName ?? ''],
        aggregation: [(s) => [s.clauses], (clauses) => clauses[0]?.aggregation ?? DEFAULT_AGGREGATION],
        groupByKeys: [(s) => [s.clauses], (clauses) => clauses[0]?.groupByKeys ?? []],
        filterStrings: [(s) => [s.clauses], (clauses) => clauses[0]?.filterStrings ?? []],
        hasMetricName: [(s) => [s.metricName], (metricName) => metricName.trim().length > 0],
        queryFilters: [
            (s) => [s.filterStrings],
            (filterStrings: string[]): _MetricFilterApi[] => parseFilters(filterStrings),
        ],
        clauseLabels: [(s) => [s.clauses], (clauses): string[] => clauses.map((_, index) => clauseLabel(index))],
        activeFormula: [
            (s) => [s.formulaEnabled, s.formula],
            (formulaEnabled, formula): string | null => (formulaEnabled && formula.trim() ? formula.trim() : null),
        ],
        isSimpleMode: [
            (s) => [s.clauses, s.activeFormula],
            (clauses, activeFormula): boolean => clauses.length === 1 && !activeFormula,
        ],
        effectiveViewMode: [
            (s) => [s.viewMode, s.isSimpleMode],
            (viewMode, isSimpleMode): MetricsViewMode => (isSimpleMode ? viewMode : 'chart'),
        ],
        querySelection: [
            (s) => [s.clauses, s.activeFormula],
            (clauses, activeFormula): MetricsQuerySelection | null => {
                if (clauses.some((clause) => !clause.metricName.trim())) {
                    return null
                }
                if (clauses.length === 1 && !activeFormula) {
                    const clause = clauses[0]
                    const filters = parseFilters(clause.filterStrings)
                    return {
                        metricName: clause.metricName.trim(),
                        aggregation: clause.aggregation,
                        ...(clause.groupByKeys.length ? { groupBy: clause.groupByKeys.map((key) => ({ key })) } : {}),
                        ...(filters.length ? { filters } : {}),
                    }
                }
                return {
                    clauses: clauses.map((clause, index) => {
                        const filters = parseFilters(clause.filterStrings)
                        return {
                            name: clauseLabel(index),
                            metricName: clause.metricName.trim(),
                            aggregation: clause.aggregation,
                            ...(clause.groupByKeys.length
                                ? { groupBy: clause.groupByKeys.map((key) => ({ key })) }
                                : {}),
                            ...(filters.length ? { filters } : {}),
                        }
                    }),
                    ...(activeFormula ? { formula: activeFormula } : {}),
                }
            },
        ],
        // The viewer renders the first series only for now; group-by lands
        // multi-series rendering in a later PR.
        // Metrics has no compare/previous-series concept, so "current" is simply the first series.
        currentSeries: [(s) => [s.queryResults], (results): MetricsViewerSeries | undefined => results[0]],
        // All series rendered as chart lines (a group-by query returns one series per label combination).
        // The x-axis labels come from `sparklineLabels` (the backend grids every series onto one time axis).
        chartSeries: [
            (s) => [s.queryResults, s.metricName, s.formula, s.isSimpleMode],
            (
                results: MetricsViewerSeries[],
                metricName: string,
                formula: string,
                isSimpleMode: boolean
            ): SparklineTimeSeries[] =>
                results.map((series, index) => ({
                    name: formatSeriesName(
                        series,
                        series.clause === 'formula' ? formula.trim() || 'Formula' : metricName,
                        !isSimpleMode
                    ),
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
