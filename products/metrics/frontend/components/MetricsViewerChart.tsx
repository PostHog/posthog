import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo } from 'react'

import { LemonBanner, SpinnerOverlay } from '@posthog/lemon-ui'

import { traceUrl } from 'lib/components/ViewTraceButton/traceUrl'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { useOpenTraceDialog } from 'products/tracing/frontend/components/TraceDialog/useOpenTraceDialog'

import { MetricsHistogramQueryNode } from '../nodes/MetricsHistogramQueryNode'
import { MetricsPanel } from '../panels/MetricsPanel'
import { type MetricsExemplar } from './MetricsExemplarMarkers'
import { MetricsPercentileResolutionHint } from './MetricsPercentileResolutionHint'
import { metricsSamplesLogic } from './metricsSamplesLogic'
import { metricsUsageTrackingLogic } from './metricsUsageTrackingLogic'
import { MAX_UNAGGREGATED_SERIES, metricsViewerLogic } from './metricsViewerLogic'

/**
 * Clickable dots along the bottom of the chart: traced emissions (the metric->trace pivot) and
 * Error Tracking issue spikes (team-wide — spike events carry no service attribution). Each kind
 * is skipped entirely when the user can't view its target product, so a dot never leads to a dead end.
 */
function useChartMarkers(): MetricsExemplar[] {
    const { traceExemplars, errorSpikes } = useValues(metricsSamplesLogic)
    const { timezone } = useValues(teamLogic)
    const { exemplarDotClicked } = useActions(metricsUsageTrackingLogic)
    const openTraceDialog = useOpenTraceDialog()
    // Staff-only PoC gate, layered on top of the wider metrics alpha flag.
    const errorOverlaysEnabled = useFeatureFlag('METRICS_ERROR_OVERLAYS')
    const tracingDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Tracing,
        AccessControlLevel.Viewer
    )
    const errorTrackingDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.ErrorTracking,
        AccessControlLevel.Viewer
    )

    // One memo, so the chart prop keeps a stable identity across renders.
    return useMemo(() => {
        const traceMarkers: MetricsExemplar[] = tracingDisabledReason
            ? []
            : traceExemplars.map((exemplar) => ({
                  timeMs: dayjs(exemplar.timestamp).valueOf(),
                  tooltipLabel: `Traced emission at ${dayjs(exemplar.timestamp).tz(timezone).format('D MMM HH:mm:ss')}. Click to view the trace.`,
                  onClick: (event) => {
                      exemplarDotClicked(!!exemplar.spanId)
                      const trace = {
                          traceId: exemplar.traceId,
                          spanId: exemplar.spanId || null,
                          ts: exemplar.timestamp,
                      }
                      if (!openTraceDialog(event, trace, { entryPoint: 'metric_exemplar' })) {
                          router.actions.push(traceUrl(trace))
                      }
                  },
              }))
        const spikeMarkers: MetricsExemplar[] =
            !errorOverlaysEnabled || errorTrackingDisabledReason
                ? []
                : errorSpikes.map((spike) => ({
                      timeMs: dayjs(spike.detected_at).valueOf(),
                      color: 'danger',
                      tooltipLabel: `Error spike at ${dayjs(spike.detected_at).tz(timezone).format('D MMM HH:mm:ss')}: ${spike.issue_name ?? 'Untitled issue'}. Click to view the issue.`,
                      onClick: () => {
                          router.actions.push(urls.errorTrackingIssue(spike.issue_id, { timestamp: spike.detected_at }))
                      },
                  }))
        return [...traceMarkers, ...spikeMarkers]
    }, [
        traceExemplars,
        tracingDisabledReason,
        exemplarDotClicked,
        openTraceDialog,
        errorSpikes,
        errorOverlaysEnabled,
        errorTrackingDisabledReason,
        timezone,
    ])
}

/** The chart card's body: the chart or heatmap, with its empty, error and loading states. */
export function MetricsViewerChart(): JSX.Element {
    const {
        hasQuery,
        language,
        isHeatmap,
        histogramQueryNode,
        refreshCount,
        queryError,
        dateRangeError,
        hasResults,
        queryLoading,
        chartSeries,
        formula,
        metricName,
        queryText,
        metricsDisplay,
        metricsQueryNode,
        seriesCapReached,
        queryResults,
    } = useValues(metricsViewerLogic)
    const chartMarkers = useChartMarkers()

    return (
        <>
            {seriesCapReached && (
                <LemonBanner type="info" className="m-2 mb-0" data-attr="metrics-series-cap-banner">
                    Showing the {MAX_UNAGGREGATED_SERIES} most recently active series. Add a filter or an operation to
                    narrow the chart.
                </LemonBanner>
            )}
            <div className="relative h-[360px] p-3">
                {!hasQuery ? (
                    <div className="h-full flex items-center justify-center text-secondary text-sm">
                        {language === 'builder'
                            ? 'Pick a metric to see its time series.'
                            : 'Run a query to see results.'}
                    </div>
                ) : dateRangeError ? (
                    // Before the heatmap: its histogram query would hit the same span limit.
                    <div className="h-full flex items-center justify-center">
                        <LemonBanner type="error" className="w-full max-w-md">
                            {dateRangeError}
                        </LemonBanner>
                    </div>
                ) : isHeatmap && histogramQueryNode ? (
                    // The heatmap runs its own histogram query, so it mounts the histogram
                    // node rather than consuming the time-series result the other panels share.
                    // It comes before the error/loading branches: the shared time-series
                    // request still runs for the samples panel, and its failure must not
                    // mask an independently loaded histogram.
                    <MetricsHistogramQueryNode query={histogramQueryNode} context={{}} refreshCount={refreshCount} />
                ) : queryError ? (
                    <div className="h-full flex items-center justify-center">
                        <LemonBanner type="error" className="w-full max-w-md">
                            {queryError}
                        </LemonBanner>
                    </div>
                ) : hasResults ? (
                    <MetricsPanel
                        series={chartSeries}
                        fallbackName={formula || metricName || (language === 'promql' ? queryText : 'metric')}
                        display={metricsDisplay}
                        exemplars={chartMarkers}
                        query={metricsQueryNode ?? undefined}
                    />
                ) : !queryLoading ? (
                    <div className="h-full flex items-center justify-center text-secondary text-sm">
                        No data for this metric in the selected range.
                    </div>
                ) : null}
                {queryLoading && !isHeatmap && <SpinnerOverlay />}
            </div>
            {hasResults && !isHeatmap && !queryError && (
                <div className="px-3 pb-2">
                    <MetricsPercentileResolutionHint series={queryResults} metricName={metricName} />
                </div>
            )}
        </>
    )
}
