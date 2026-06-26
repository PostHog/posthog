import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { type MetricSummary } from 'lib/components/Metric/metricSummary'
import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils/dateFilters'
import { teamLogic } from 'scenes/teamLogic'

import { metricsCharacterizeCreate, metricsQueryCreate } from 'products/metrics/frontend/generated/api'
import type { _MetricAnomalyReportApi, _MetricSeriesApi } from 'products/metrics/frontend/generated/api.schemas'

import type { metricsViewerLogicType } from './metricsViewerLogicType'

export type MetricAggregation = 'sum' | 'avg' | 'count' | 'p95'

// `chart` shows the time series; `stat` shows a single headline value + change pill (a Grafana "stat" panel).
export type MetricsViewMode = 'chart' | 'stat'

export type MetricsViewerSeries = _MetricSeriesApi

const DEFAULT_AGGREGATION: MetricAggregation = 'sum'
const DEFAULT_DATE_FROM = '-1h'
const NEW_QUERY_STARTED_ERROR_MESSAGE = 'A new metrics query started, cancelling the previous one'
// The anomaly badge characterizes the most recent slice of the selected window against the rest.
const ANOMALY_WINDOW_FRACTION = 0.2

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
        values: [teamLogic, ['currentTeamId']],
    })),
    actions({
        setMetricName: (metricName: string) => ({ metricName }),
        setAggregation: (aggregation: MetricAggregation) => ({ aggregation }),
        setDateFrom: (dateFrom: string | null) => ({ dateFrom }),
        setDateTo: (dateTo: string | null) => ({ dateTo }),
        setViewMode: (viewMode: MetricsViewMode) => ({ viewMode }),
        setStatSummary: (statSummary: MetricSummary) => ({ statSummary }),
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
        queryAbortController: [
            null as AbortController | null,
            { setQueryAbortController: (_, { controller }) => controller },
        ],
    }),
    listeners(({ actions, values }) => ({
        cancelInProgressQuery: ({ controller }) => {
            if (values.queryAbortController !== null) {
                values.queryAbortController.abort(NEW_QUERY_STARTED_ERROR_MESSAGE)
            }
            actions.setQueryAbortController(controller)
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
        // The viewer renders the first series only for now; group-by lands
        // multi-series rendering in a later PR.
        // Metrics has no compare/previous-series concept, so "current" is simply the first series.
        currentSeries: [(s) => [s.queryResults], (results): MetricsViewerSeries | undefined => results[0]],
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
            (report: _MetricAnomalyReportApi | null) =>
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
