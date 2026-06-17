import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils/dateFilters'
import { teamLogic } from 'scenes/teamLogic'

import { metricsQueryCreate } from 'products/metrics/frontend/generated/api'
import type { _MetricSeriesApi } from 'products/metrics/frontend/generated/api.schemas'

import type { metricsViewerLogicType } from './metricsViewerLogicType'

export type MetricAggregation = 'sum' | 'avg' | 'count' | 'p95'

export type MetricsViewerSeries = _MetricSeriesApi

const DEFAULT_AGGREGATION: MetricAggregation = 'sum'
const DEFAULT_DATE_FROM = '-1h'
const NEW_QUERY_STARTED_ERROR_MESSAGE = 'A new metrics query started, cancelling the previous one'

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
    })),
    selectors({
        hasMetricName: [(s) => [s.metricName], (metricName) => metricName.trim().length > 0],
        // The viewer renders the first series only for now; group-by lands
        // multi-series rendering in a later PR.
        sparklineValues: [(s) => [s.queryResults], (results) => (results[0]?.points ?? []).map((p) => p.value)],
        sparklineLabels: [(s) => [s.queryResults], (results) => (results[0]?.points ?? []).map((p) => p.time)],
    }),
])
