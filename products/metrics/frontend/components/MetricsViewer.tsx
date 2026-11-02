import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useMemo } from 'react'

import { LemonBanner, LemonButton, LemonSwitch, SpinnerOverlay } from '@posthog/lemon-ui'

import { AddToDashboardModal } from 'lib/components/AddToDashboard/AddToDashboardModal'
import { traceUrl } from 'lib/components/ViewTraceButton/traceUrl'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { NewDashboardModal } from 'scenes/dashboard/NewDashboardModal'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { type MetricsQueryLanguage, NodeKind } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { useOpenTraceDialog } from 'products/tracing/frontend/components/TraceDialog/useOpenTraceDialog'

import { getMetricsInsightEditorDisabledReason } from '../metricsAccess'
import { MetricsHistogramQueryNode } from '../nodes/MetricsHistogramQueryNode'
import { MetricsPanel } from '../panels/MetricsPanel'
import { MetricsFacetRail, MetricsFacetRailToggle } from './FacetRail/MetricsFacetRail'
import { MetricsAnomalyPanel } from './MetricsAnomalyPanel'
import { MetricsChartSettings } from './MetricsChartSettings'
import { MetricsDateRangeFilter } from './MetricsDateRangeFilter'
import { MetricsDisplayTypeSelect } from './MetricsDisplayTypeSelect'
import { type MetricsExemplar } from './MetricsExemplarMarkers'
import { MetricsIntervalPicker } from './MetricsIntervalPicker'
import { MetricsLogsSourceTag } from './MetricsLogsSourceTag'
import { MetricsPercentileResolutionHint } from './MetricsPercentileResolutionHint'
import { MetricsQueryLanguagePicker } from './MetricsQueryLanguagePicker'
import { switchMetricsQueryLanguage } from './metricsQueryLanguageSwitch'
import { MetricsQueryTextEditor } from './MetricsQueryTextEditor'
import { MetricsRefreshButton } from './MetricsRefreshButton'
import { MetricsRelatedMenu } from './MetricsRelatedMenu'
import { metricsSamplesLogic } from './metricsSamplesLogic'
import { MetricsSamplesPanel } from './MetricsSamplesPanel'
import { MetricsSeriesBuilder } from './MetricsSeriesBuilder'
import { MetricsStarterDashboardModal } from './MetricsStarterDashboardModal'
import { metricsUsageTrackingLogic } from './metricsUsageTrackingLogic'
import { MAX_UNAGGREGATED_SERIES, metricsViewerLogic } from './metricsViewerLogic'
import { MetricsViewerSaveMenu } from './MetricsViewerSaveMenu'

export const MetricsViewer = (): JSX.Element => {
    const logic = metricsViewerLogic()
    // The side panel's logic listens to this viewer's filter changes; mounting it
    // here keeps samples in sync even while the panel itself is off-screen.
    useMountedLogic(metricsSamplesLogic())
    const {
        formula,
        queryFingerprint,
        anomalyFingerprint,
        metricName,
        dateFrom,
        dateTo,
        chartSeries,
        anomalyBadge,
        queryLoading,
        queryError,
        savedInsight,
        isAddToDashboardModalOpen,
        hasMetricName,
        hasQuery,
        language,
        queryText,
        hasResults,
        queryResults,
        seriesCapReached,
        displayType,
        metricsDisplay,
        heatmapEligible,
        histogramQueryNode,
        metricsQueryNode,
    } = useValues(logic)
    const { fetchQueryResults, fetchAnomaly, clearAnomaly, closeAddToDashboardModal, applyQuery } = useActions(logic)
    const { traceExemplars, errorSpikes, showErrorSpikes } = useValues(metricsSamplesLogic)
    const { timezone } = useValues(teamLogic)
    const { toggleShowErrorSpikes } = useActions(metricsSamplesLogic)
    // Staff-only PoC gate, layered on top of the wider metrics alpha flag.
    const errorOverlaysEnabled = useFeatureFlag('METRICS_ERROR_OVERLAYS')

    // Gate on the result shape, not the clause edits: a formula result is ungrouped even
    // when its input clauses group, and a clause without a metric name never runs.
    const resultIsGrouped = chartSeries.some((s) => Object.keys(s.labels).length > 0)
    // The heatmap saves a MetricsHistogramQuery, but insight alerts only support MetricsQuery,
    // so alert creation would save a query the alerts page cannot validate.
    const isHeatmap = displayType === 'heatmap' && histogramQueryNode !== null
    const { exemplarDotClicked } = useActions(metricsUsageTrackingLogic)
    const metricsViewerDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Metrics,
        AccessControlLevel.Viewer
    )
    const insightEditorDisabledReason = getMetricsInsightEditorDisabledReason()
    const noQueryReason = hasQuery ? undefined : language === 'builder' ? 'Pick a metric first' : 'Write a query first'
    const openTraceDialog = useOpenTraceDialog()
    const tracingDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Tracing,
        AccessControlLevel.Viewer
    )
    const errorTrackingDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.ErrorTracking,
        AccessControlLevel.Viewer
    )

    // Clickable dots along the bottom of the chart: traced emissions (the
    // metric->trace pivot) and Error Tracking issue spikes (team-wide — spike
    // events carry no service attribution). Each kind is skipped entirely when
    // the user can't view its target product, so a dot never leads to a dead
    // end. One memo, so the chart prop keeps a stable identity across renders.
    const chartMarkers: MetricsExemplar[] = useMemo(() => {
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

    // Refetch the chart whenever the effective query changes — the fingerprints are
    // strings, so edits that don't change the request (a blank just-added row, a
    // group-by tweak the anomaly body doesn't carry) don't refire the effects.
    // The loader breakpoint debounces input.
    useEffect(() => {
        fetchQueryResults({})
    }, [queryFingerprint, dateFrom, dateTo, timezone]) // eslint-disable-line react-hooks/exhaustive-deps

    // Characterize the recent window against the rest, so the chart carries a "vs baseline"
    // badge without the user having to eyeball the shape. The loader suppresses the badge
    // for multi-series and formula queries, where no single input series describes the chart.
    useEffect(() => {
        if (hasMetricName) {
            fetchAnomaly({})
        } else {
            clearAnomaly()
        }
    }, [anomalyFingerprint, dateFrom, dateTo, hasMetricName, timezone]) // eslint-disable-line react-hooks/exhaustive-deps

    const languagesEnabled = useFeatureFlag('METRICS_QUERY_LANGUAGES')
    // The rail writes builder filter chips, which PromQL and SQL queries do not read.
    const facetRailEnabled = useFeatureFlag('METRICS') && language === 'builder'
    const { interval, queryDraft } = useValues(logic)
    const { setInterval, runQueryText: runQueryTextAction } = useActions(logic)
    const mountedLogic = useMountedLogic(logic)
    // A changed query runs through the query node. An unchanged one (after a failure) runs again in place.
    const runQueryText = (): void =>
        mountedLogic.values.queryTextChanged ? runQueryTextAction() : fetchQueryResults({})
    const switchLanguage = (to: MetricsQueryLanguage): void => {
        // Read the logic at click time, so a draft the user has not run yet still converts.
        const { metricsQueryNode: node, queryDraft: draft } = mountedLogic.values
        const current = node ?? { kind: NodeKind.MetricsQuery, clauses: [] }
        switchMetricsQueryLanguage(
            language === 'builder' ? current : { ...current, [language]: draft.trim() },
            to,
            applyQuery
        )
    }

    return (
        <div
            className="@container/facet-rail-host flex flex-col gap-2 flex-1 min-h-0 overflow-y-auto"
            data-attr="metrics-viewer"
        >
            <div className="flex flex-wrap items-center justify-between gap-2">
                {languagesEnabled ? (
                    <MetricsQueryLanguagePicker
                        value={language}
                        onChange={switchLanguage}
                        disabledReason={metricsViewerDisabledReason}
                    />
                ) : (
                    <span />
                )}
                <div className="flex flex-wrap items-center gap-2">
                    <MetricsDateRangeFilter disabledReason={metricsViewerDisabledReason} />
                    <MetricsIntervalPicker
                        value={interval}
                        onChange={setInterval}
                        disabledReason={metricsViewerDisabledReason}
                    />
                    <MetricsRefreshButton disabledReason={metricsViewerDisabledReason} noQueryReason={noQueryReason} />
                </div>
            </div>
            {language === 'builder' ? (
                <MetricsSeriesBuilder dataAttrPrefix="metrics-viewer" disabledReason={metricsViewerDisabledReason} />
            ) : (
                <div className="flex items-start gap-2">
                    <div className="flex-1 min-w-0">
                        <MetricsQueryTextEditor
                            language={language}
                            disabledReason={metricsViewerDisabledReason}
                            onRun={runQueryText}
                        />
                    </div>
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={runQueryText}
                        disabledReason={
                            metricsViewerDisabledReason ?? (queryDraft.trim() ? undefined : 'Write a query first')
                        }
                        data-attr={`metrics-query-editor-run-${language}`}
                    >
                        Run
                    </LemonButton>
                </div>
            )}
            <MetricsStarterDashboardModal />
            {savedInsight && (
                <>
                    <AddToDashboardModal
                        isOpen={isAddToDashboardModalOpen}
                        closeModal={closeAddToDashboardModal}
                        insightProps={{ dashboardItemId: savedInsight.short_id, cachedInsight: savedInsight }}
                        canEditInsight={!insightEditorDisabledReason}
                        data-attr="metrics-viewer-add-to-dashboard-modal"
                    />
                    {/* The picker's "Add to a new dashboard" only opens this dialog, so the two
                        have to be rendered together (as the insight scene does). */}
                    <NewDashboardModal />
                </>
            )}
            <div className="flex flex-col border rounded bg-surface-primary shrink-0">
                <div className="flex flex-wrap items-center justify-between gap-2 px-2 py-1.5 border-b">
                    <div className="flex flex-wrap items-center gap-2">
                        <MetricsDisplayTypeSelect
                            dataAttrPrefix="metrics-viewer"
                            resultIsGrouped={resultIsGrouped}
                            heatmap={{ eligible: heatmapEligible }}
                            disabledReason={metricsViewerDisabledReason}
                        />
                        <MetricsChartSettings />
                        {/* Hidden (not disabled) without Error Tracking view access, so the
                            toggle never references a product the user cannot see. */}
                        {errorOverlaysEnabled && !errorTrackingDisabledReason && (
                            <LemonSwitch
                                label="Error spikes"
                                checked={showErrorSpikes}
                                onChange={toggleShowErrorSpikes}
                                tooltip="Mark Error Tracking issue spikes on the chart (team-wide, PoC)"
                                size="small"
                                bordered
                                data-attr="metrics-viewer-error-spikes-toggle"
                                disabledReason={metricsViewerDisabledReason}
                            />
                        )}
                        <MetricsRelatedMenu />
                        {anomalyBadge && <MetricsAnomalyPanel anomaly={anomalyBadge} />}
                        <MetricsLogsSourceTag metricName={metricName} />
                    </div>
                    <MetricsViewerSaveMenu noQueryReason={noQueryReason} isHeatmap={isHeatmap} />
                </div>
                {seriesCapReached && (
                    <LemonBanner type="info" className="m-2 mb-0" data-attr="metrics-series-cap-banner">
                        Showing the {MAX_UNAGGREGATED_SERIES} most recently active series. Add a filter or an operation
                        to narrow the chart.
                    </LemonBanner>
                )}
                <div className="relative h-[360px] p-3">
                    {!hasQuery ? (
                        <div className="h-full flex items-center justify-center text-secondary text-sm">
                            {language === 'builder'
                                ? 'Pick a metric to see its time series.'
                                : 'Run a query to see results.'}
                        </div>
                    ) : isHeatmap && histogramQueryNode ? (
                        // The heatmap runs its own histogram query, so it mounts the histogram
                        // node rather than consuming the time-series result the other panels share.
                        // It comes before the error/loading branches: the shared time-series
                        // request still runs for the samples panel, and its failure must not
                        // mask an independently loaded histogram.
                        <MetricsHistogramQueryNode query={histogramQueryNode} context={{}} />
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
            </div>
            {(facetRailEnabled || hasMetricName) && (
                // At least the rail's own minimum, so its facets stay usable when the scene is short.
                <div className="flex flex-row gap-2 flex-1 min-h-96 @max-[48rem]/facet-rail-host:flex-col">
                    {facetRailEnabled && <MetricsFacetRail />}
                    <div className="flex flex-col gap-2 flex-1 min-w-0 min-h-0">
                        {facetRailEnabled && (
                            <div className="flex">
                                <MetricsFacetRailToggle />
                            </div>
                        )}
                        {hasMetricName && <MetricsSamplesPanel />}
                    </div>
                </div>
            )}
        </div>
    )
}
