import { actions, connect, kea, listeners, path } from 'kea'
import posthog from 'posthog-js'

import type { _MetricEventSampleApi } from 'products/metrics/frontend/generated/api.schemas'

import { metricsSceneLogic } from '../metricsSceneLogic'
import { metricsSamplesLogic } from './metricsSamplesLogic'
import type { metricsUsageTrackingLogicType } from './metricsUsageTrackingLogicType'
import { isUserInitiatedError, metricsViewerLogic } from './metricsViewerLogic'

// Central usage tracking for the metrics scene, following the metricsSqlEditorTrackingLogic
// precedent: captures fire from listeners on the source logics' actions, not from onClick
// handlers scattered through components.
//
// Privacy rule: never capture customer metric names, series labels, attribute keys, or
// attribute values — only counts, booleans, durations, and our own enum values.
export const metricsUsageTrackingLogic = kea<metricsUsageTrackingLogicType>([
    path(['products', 'metrics', 'frontend', 'components', 'metricsUsageTrackingLogic']),
    connect(() => ({
        actions: [
            metricsSceneLogic,
            ['setActiveTab as sceneTabChanged'],
            metricsViewerLogic,
            [
                'setMetricName',
                'setAggregation',
                'setDateFrom',
                'setViewMode',
                'setStatSummary',
                'setLiveRefresh',
                'setGroupByKeys',
                'setFilterGroup',
                'fetchQueryResults',
                'fetchQueryResultsSuccess',
                'fetchQueryResultsFailure',
            ],
            metricsSamplesLogic,
            ['setActiveTab as samplesPanelTabChanged', 'loadSamplesSuccess'],
        ],
        values: [metricsViewerLogic, ['hasMetricName', 'aggregation', 'groupByKeys', 'queryFilters']],
    })),
    actions({
        // Component-only interactions with no source-logic action to listen to.
        sampleRowExpanded: (sample: _MetricEventSampleApi) => ({ sample }),
        tracePivotClicked: (sample: _MetricEventSampleApi) => ({ sample }),
    }),
    listeners(({ values, cache }) => ({
        sceneTabChanged: ({ activeTab }) => {
            posthog.capture('metrics tab changed', { tab: activeTab })
        },
        setMetricName: ({ metricName }) => {
            if (metricName.trim()) {
                posthog.capture('metrics viewer metric selected')
            }
        },
        setAggregation: ({ aggregation }) => {
            posthog.capture('metrics viewer aggregation changed', { aggregation })
        },
        // The DateFilter dispatches setDateFrom and setDateTo together on every change,
        // so listening to setDateFrom alone captures each range change exactly once.
        setDateFrom: ({ dateFrom }) => {
            posthog.capture('metrics viewer date range changed', { date_from: dateFrom })
        },
        setViewMode: ({ viewMode }) => {
            posthog.capture('metrics viewer view mode changed', { view_mode: viewMode })
        },
        setStatSummary: ({ statSummary }) => {
            posthog.capture('metrics viewer stat summary changed', { stat_summary: statSummary })
        },
        setLiveRefresh: ({ liveRefresh }) => {
            posthog.capture('metrics viewer live toggled', { enabled: liveRefresh })
        },
        setGroupByKeys: ({ groupByKeys }) => {
            posthog.capture('metrics viewer group by changed', { group_by_count: groupByKeys.length })
        },
        setFilterGroup: () => {
            // queryFilters counts only complete, backend-valid chips (reducers ran before us).
            posthog.capture('metrics viewer attribute filter changed', { filter_count: values.queryFilters.length })
        },
        fetchQueryResults: () => {
            cache.queryStartedAt = performance.now()
        },
        fetchQueryResultsSuccess: ({ queryResults }) => {
            // The loader resolves [] without querying when no metric is picked yet — not a query.
            if (!values.hasMetricName) {
                return
            }
            // load_ms includes the loader's 300ms debounce breakpoint — consistent overhead,
            // fine for trend comparisons.
            const loadMs =
                cache.queryStartedAt !== undefined ? Math.round(performance.now() - cache.queryStartedAt) : null
            posthog.capture('metrics query completed', {
                series_count: queryResults.length,
                point_count: queryResults.reduce((sum: number, series) => sum + series.points.length, 0),
                load_ms: loadMs,
                aggregation: values.aggregation,
                has_group_by: values.groupByKeys.length > 0,
                has_filters: values.queryFilters.length > 0,
            })
        },
        fetchQueryResultsFailure: ({ error, errorObject }) => {
            // A superseded/unmounted query aborts — user-initiated, not a failure.
            if (isUserInitiatedError(error) || isUserInitiatedError(errorObject)) {
                return
            }
            // Only a coarse class — the message can embed the customer's metric name.
            const status = (errorObject as { status?: number } | undefined)?.status
            posthog.capture('metrics query failed', { error_type: status ? `http_${status}` : 'unknown' })
        },
        samplesPanelTabChanged: ({ activeTab }) => {
            posthog.capture('metrics samples panel tab changed', { tab: activeTab })
        },
        loadSamplesSuccess: ({ samples }) => {
            if (!values.hasMetricName) {
                return
            }
            const withTrace = samples.filter((sample) => !!sample.trace_id).length
            posthog.capture('metrics samples loaded', {
                sample_count: samples.length,
                trace_coverage: samples.length ? Math.round((100 * withTrace) / samples.length) : 0,
            })
        },
        sampleRowExpanded: ({ sample }) => {
            posthog.capture('metrics sample row expanded', {
                attribute_count: Object.keys(sample.attributes).length + Object.keys(sample.resource_attributes).length,
                has_trace: !!sample.trace_id,
            })
        },
        tracePivotClicked: ({ sample }) => {
            posthog.capture('metrics trace pivot clicked', { has_span_id: !!sample.span_id })
        },
    })),
])
