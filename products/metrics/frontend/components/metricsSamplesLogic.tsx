import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { metricsSamplesCreate } from 'products/metrics/frontend/generated/api'
import type { _MetricEventSampleApi } from 'products/metrics/frontend/generated/api.schemas'

import type { metricsSamplesLogicType } from './metricsSamplesLogicType'
import { formatSeriesName, seriesColor } from './metricsSeries'
import { type MetricsViewerSeries, metricsViewerLogic, resolveDate } from './metricsViewerLogic'

// The side panel next to the chart: per-series aggregates, or the raw emissions
// behind the chart with their trace linkage (the metric->trace pivot).
export type MetricsPanelTab = 'aggregates' | 'samples'

export const SAMPLES_LIMIT = 50

// One row of the Aggregates tab: a series with its headline numbers.
export interface MetricsAggregateRow {
    name: string
    color: string
    latest: number
    total: number
}

export const metricsSamplesLogic = kea<metricsSamplesLogicType>([
    path(['products', 'metrics', 'frontend', 'components', 'metricsSamplesLogic']),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeamId'],
            metricsViewerLogic,
            ['metricName', 'dateFrom', 'dateTo', 'queryResults'],
        ],
        actions: [metricsViewerLogic, ['setMetricName', 'setDateFrom', 'setDateTo']],
    })),
    actions({
        setActiveTab: (activeTab: MetricsPanelTab) => ({ activeTab }),
    }),
    reducers({
        activeTab: ['aggregates' as MetricsPanelTab, { setActiveTab: (_, { activeTab }) => activeTab }],
    }),
    loaders(({ values }) => ({
        samples: [
            [] as _MetricEventSampleApi[],
            {
                loadSamples: async (_, breakpoint) => {
                    const metricName = values.metricName.trim()
                    const dateFrom = resolveDate(values.dateFrom)
                    if (!metricName || !dateFrom) {
                        return []
                    }
                    await breakpoint(300)
                    const dateTo = resolveDate(values.dateTo) ?? undefined
                    const response = await metricsSamplesCreate(String(values.currentTeamId), {
                        query: {
                            metricName,
                            dateFrom,
                            ...(dateTo ? { dateTo } : {}),
                            limit: SAMPLES_LIMIT,
                        },
                    })
                    breakpoint()
                    return response.results
                },
            },
        ],
    })),
    selectors({
        // Rows for the Aggregates tab, derived from the chart's series so both
        // views always describe the same query (colors match the chart legend).
        aggregateRows: [
            (s) => [s.queryResults, s.metricName],
            (queryResults: MetricsViewerSeries[], metricName: string): MetricsAggregateRow[] =>
                queryResults.map((series, index) => {
                    // Null points are gaps (unrepresentable buckets) — skip them
                    // rather than counting them as zero.
                    const values = series.points.map((point) => point.value).filter((value) => value !== null)
                    return {
                        name: formatSeriesName(series, metricName),
                        color: seriesColor(index),
                        latest: values.length ? values[values.length - 1] : 0,
                        total: values.reduce((sum, value) => sum + value, 0),
                    }
                }),
        ],
    }),
    listeners(({ actions, values }) => ({
        setActiveTab: ({ activeTab }) => {
            if (activeTab === 'samples') {
                actions.loadSamples({})
            }
        },
        // The viewer's filters are the samples' filters: any change that redraws
        // the chart refreshes the visible samples too, but only when they're shown.
        setMetricName: () => {
            if (values.activeTab === 'samples') {
                actions.loadSamples({})
            }
        },
        setDateFrom: () => {
            if (values.activeTab === 'samples') {
                actions.loadSamples({})
            }
        },
        setDateTo: () => {
            if (values.activeTab === 'samples') {
                actions.loadSamples({})
            }
        },
    })),
])
