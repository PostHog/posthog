import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { teamLogic } from 'scenes/teamLogic'

import { metricsSamplesCreate } from 'products/metrics/frontend/generated/api'
import type { _MetricEventSampleApi } from 'products/metrics/frontend/generated/api.schemas'
import { traceUrl } from 'products/tracing/frontend/traceLinks'

import { type ExemplarMarker, exemplarMarkersFromSamples } from './exemplarMarkers'
import type { metricsSamplesLogicType } from './metricsSamplesLogicType'
import { formatSeriesName, seriesColor } from './metricsSeries'
import { type MetricsViewerSeries, metricsViewerLogic, resolveDate } from './metricsViewerLogic'

// The side panel next to the chart: per-series aggregates, or the raw emissions
// behind the chart with their trace linkage (the metric->trace pivot).
export type MetricsPanelTab = 'aggregates' | 'samples'

export const SAMPLES_LIMIT = 50

const EMPTY_MARKERS: ExemplarMarker[] = []

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
            ['metricName', 'dateFrom', 'dateTo', 'queryResults', 'queryFilters', 'groupByKeys'],
        ],
        actions: [metricsViewerLogic, ['setMetricName', 'setDateFrom', 'setDateTo', 'fetchQueryResultsSuccess']],
    })),
    actions({
        setActiveTab: (activeTab: MetricsPanelTab) => ({ activeTab }),
        setExemplarsEnabled: (enabled: boolean) => ({ enabled }),
        exemplarClicked: (marker: ExemplarMarker) => ({ marker }),
    }),
    reducers({
        activeTab: ['aggregates' as MetricsPanelTab, { setActiveTab: (_, { activeTab }) => activeTab }],
        exemplarsEnabled: [false, { setExemplarsEnabled: (_, { enabled }) => enabled }],
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
        // Dots for the chart overlay: traced samples floored onto the current
        // series' bucket grid and re-filtered like the chart. A stable empty
        // reference while disabled keeps chart-adjacent subscribers from
        // re-rendering on unrelated samples-tab loads.
        exemplarMarkers: [
            (s) => [s.exemplarsEnabled, s.samples, s.queryResults, s.queryFilters, s.groupByKeys],
            (
                exemplarsEnabled: boolean,
                samples: _MetricEventSampleApi[],
                queryResults: MetricsViewerSeries[],
                queryFilters,
                groupByKeys: string[]
            ): ExemplarMarker[] =>
                exemplarsEnabled
                    ? exemplarMarkersFromSamples(samples, queryResults, { filters: queryFilters, groupByKeys })
                    : EMPTY_MARKERS,
        ],
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
    listeners(({ actions, values }) => {
        const samplesVisible = (): boolean => values.activeTab === 'samples' || values.exemplarsEnabled
        return {
            setActiveTab: ({ activeTab }) => {
                if (activeTab === 'samples') {
                    actions.loadSamples({})
                }
            },
            setExemplarsEnabled: ({ enabled }) => {
                if (enabled) {
                    actions.loadSamples({})
                }
            },
            exemplarClicked: ({ marker }) => {
                router.actions.push(traceUrl({ traceId: marker.traceId, spanId: marker.spanId, ts: marker.timestamp }))
            },
            // Live refresh refetches the chart every 15s; the dots must track the same
            // sliding window or stale samples drift off the grid. The loader's
            // breakpoint coalesces this with the filter-change listeners below.
            fetchQueryResultsSuccess: () => {
                if (values.exemplarsEnabled) {
                    actions.loadSamples({})
                }
            },
            // The viewer's filters are the samples' filters: any change that redraws
            // the chart refreshes the visible samples too, but only when they're shown
            // (samples tab open, or exemplar dots overlaid on the chart).
            setMetricName: () => {
                if (samplesVisible()) {
                    actions.loadSamples({})
                }
            },
            setDateFrom: () => {
                if (samplesVisible()) {
                    actions.loadSamples({})
                }
            },
            setDateTo: () => {
                if (samplesVisible()) {
                    actions.loadSamples({})
                }
            },
        }
    }),
])
