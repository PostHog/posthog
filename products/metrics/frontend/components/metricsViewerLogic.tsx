import { actions, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils'

import type { metricsViewerLogicType } from './metricsViewerLogicType'

export type MetricAggregation = 'sum' | 'avg' | 'count' | 'p95'

export interface MetricsViewerLogicProps {
    tabId: string
}

export interface MetricsViewerPoint {
    time: string
    value: number
}

const DEFAULT_AGGREGATION: MetricAggregation = 'sum'
const DEFAULT_DATE_FROM = '-1h'

const resolveDate = (value: string | null | undefined): string | null => {
    if (!value) {
        return null
    }
    const dj = dateStringToDayJs(value) ?? dayjs(value)
    return dj.isValid() ? dj.toISOString() : null
}

export const metricsViewerLogic = kea<metricsViewerLogicType>([
    path(['products', 'metrics', 'frontend', 'components', 'metricsViewerLogic']),
    props({} as MetricsViewerLogicProps),
    key((p) => p.tabId),
    actions({
        setMetricName: (metricName: string) => ({ metricName }),
        setAggregation: (aggregation: MetricAggregation) => ({ aggregation }),
        setDateFrom: (dateFrom: string | null) => ({ dateFrom }),
        setDateTo: (dateTo: string | null) => ({ dateTo }),
    }),
    reducers({
        metricName: ['' as string, { setMetricName: (_, { metricName }) => metricName }],
        aggregation: [
            DEFAULT_AGGREGATION as MetricAggregation,
            { setAggregation: (_, { aggregation }) => aggregation },
        ],
        dateFrom: [DEFAULT_DATE_FROM as string | null, { setDateFrom: (_, { dateFrom }) => dateFrom }],
        dateTo: [null as string | null, { setDateTo: (_, { dateTo }) => dateTo }],
    }),
    loaders(({ values }) => ({
        queryResults: [
            [] as MetricsViewerPoint[],
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
                    const response = await api.metrics.query({
                        query: {
                            metricName: trimmedName,
                            aggregation: values.aggregation,
                            dateFrom: dateFromISO,
                            ...(dateToISO ? { dateTo: dateToISO } : {}),
                        },
                    })
                    breakpoint()
                    return response.results
                },
            },
        ],
    })),
    selectors({
        hasMetricName: [(s) => [s.metricName], (metricName) => metricName.trim().length > 0],
        sparklineValues: [(s) => [s.queryResults], (results) => results.map((p) => p.value)],
        sparklineLabels: [(s) => [s.queryResults], (results) => results.map((p) => p.time)],
    }),
])
