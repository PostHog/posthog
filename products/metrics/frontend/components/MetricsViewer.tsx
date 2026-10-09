import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useMemo } from 'react'

import { LemonBanner, LemonButton, LemonSwitch, SpinnerOverlay } from '@posthog/lemon-ui'

import { AddToDashboardModal } from 'lib/components/AddToDashboard/AddToDashboardModal'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { NewDashboardModal } from 'scenes/dashboard/NewDashboardModal'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { traceUrl } from 'products/tracing/frontend/traceLinks'

import { getMetricsInsightEditorDisabledReason } from '../metricsAccess'
import { MetricsHistogramQueryNode } from '../nodes/MetricsHistogramQueryNode'
import { MetricsPanel } from '../panels/MetricsPanel'
import { MetricsAnomalyPanel } from './MetricsAnomalyPanel'
import { type MetricsExemplar } from './MetricsExemplarMarkers'
import { MetricsLogsSourceTag } from './MetricsLogsSourceTag'
import { MetricsQueryControls } from './MetricsQueryEditor'
import { switchMetricsQueryLanguage } from './metricsQueryLanguageSwitch'
import { MetricsRelatedMenu } from './MetricsRelatedMenu'
import { metricsSamplesLogic } from './metricsSamplesLogic'
import { MetricsSamplesPanel } from './MetricsSamplesPanel'
import { metricsStarterDashboardLogic } from './metricsStarterDashboardLogic'
import { MetricsStarterDashboardModal } from './MetricsStarterDashboardModal'
import { metricsUsageTrackingLogic } from './metricsUsageTrackingLogic'
import { LIVE_REFRESH_MS, MAX_UNAGGREGATED_SERIES, metricsViewerLogic } from './metricsViewerLogic'

export const MetricsViewer = (): JSX.Element => {
    const logic = metricsViewerLogic()
    // The side panel's logic listens to this viewer's filter changes; mounting it
    // here keeps samples in sync even while the panel itself is off-screen.
    useMountedLogic(metricsSamplesLogic())
    const { openModal: openStarterDashboardModal } = useActions(metricsStarterDashboardLogic)
    const {
        formula,
        queryFingerprint,
        anomalyFingerprint,
        metricName,
        dateFrom,
        dateTo,
        chartSeries,
        anomalyBadge,
        liveRefresh,
        queryLoading,
        queryError,
        savedInsightLoading,
        savedInsight,
        isAddToDashboardModalOpen,
        hasMetricName,
        hasQuery,
        language,
        queryText,
        hasResults,
        seriesCapReached,
        displayType,
        metricsDisplay,
        heatmapEligible,
        histogramQueryNode,
    } = useValues(logic)
    const {
        setLiveRefresh,
        fetchQueryResults,
        fetchAnomaly,
        clearAnomaly,
        saveAsInsight,
        addToDashboard,
        createAlert,
        closeAddToDashboardModal,
        applyQuery,
    } = useActions(logic)
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
                  onClick: () => {
                      exemplarDotClicked(!!exemplar.spanId)
                      router.actions.push(
                          traceUrl({
                              traceId: exemplar.traceId,
                              spanId: exemplar.spanId || null,
                              ts: exemplar.timestamp,
                          })
                      )
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

    return (
        <div className="flex flex-col gap-3">
            <MetricsQueryControls
                dataAttrPrefix="metrics-viewer"
                onSwitchLanguage={
                    languagesEnabled ? (current, to) => switchMetricsQueryLanguage(current, to, applyQuery) : undefined
                }
                onRerun={() => fetchQueryResults({})}
                resultIsGrouped={resultIsGrouped}
                heatmap={{ eligible: heatmapEligible }}
                toolbarExtras={
                    <>
                        <LemonSwitch
                            label="Auto-refresh"
                            checked={liveRefresh}
                            onChange={setLiveRefresh}
                            tooltip={`Refreshes every ${LIVE_REFRESH_MS / 1000}s`}
                            bordered
                            data-attr="metrics-viewer-live-toggle"
                            disabledReason={metricsViewerDisabledReason}
                        />
                        {/* Hidden (not disabled) without Error Tracking view access, so the
                            toggle never references a product the user cannot see. */}
                        {errorOverlaysEnabled && !errorTrackingDisabledReason && (
                            <LemonSwitch
                                label="Error spikes"
                                checked={showErrorSpikes}
                                onChange={toggleShowErrorSpikes}
                                tooltip="Mark Error Tracking issue spikes on the chart (team-wide, PoC)"
                                bordered
                                data-attr="metrics-viewer-error-spikes-toggle"
                                disabledReason={metricsViewerDisabledReason}
                            />
                        )}
                    </>
                }
                displayExtras={
                    <>
                        <MetricsRelatedMenu />
                        {anomalyBadge && <MetricsAnomalyPanel anomaly={anomalyBadge} />}
                        <MetricsLogsSourceTag metricName={metricName} />
                    </>
                }
                actions={
                    <>
                        <LemonButton
                            size="small"
                            type="secondary"
                            onClick={() => saveAsInsight()}
                            loading={savedInsightLoading}
                            disabledReason={insightEditorDisabledReason ?? noQueryReason}
                        >
                            Save as insight
                        </LemonButton>
                        <LemonButton
                            size="small"
                            type="secondary"
                            onClick={() => createAlert()}
                            loading={savedInsightLoading}
                            tooltip="Get notified when this metric crosses a threshold (uses insight alerts)"
                            disabledReason={
                                insightEditorDisabledReason ??
                                noQueryReason ??
                                (isHeatmap ? 'Alerts are not supported for the heatmap display' : undefined)
                            }
                            data-attr="metrics-viewer-create-alert"
                        >
                            Create alert
                        </LemonButton>
                        <LemonButton
                            size="small"
                            type="primary"
                            onClick={() => addToDashboard()}
                            loading={savedInsightLoading}
                            disabledReason={insightEditorDisabledReason ?? noQueryReason}
                            data-attr="metrics-viewer-add-to-dashboard"
                        >
                            Add to dashboard
                        </LemonButton>
                        <LemonButton
                            size="small"
                            type="secondary"
                            onClick={openStarterDashboardModal}
                            tooltip="Create a dashboard with one insight per metric, charted as one line per series"
                            data-attr="metrics-viewer-starter-dashboard"
                            disabledReason={insightEditorDisabledReason}
                        >
                            New service dashboard
                        </LemonButton>
                    </>
                }
            />
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
            <div className="flex flex-col xl:flex-row gap-3 items-stretch">
                <div className="flex-1 min-w-0">
                    {seriesCapReached && (
                        <LemonBanner type="info" className="mb-2" data-attr="metrics-series-cap-banner">
                            Showing the {MAX_UNAGGREGATED_SERIES} most recently active series. Add a filter or an
                            operation to narrow the chart.
                        </LemonBanner>
                    )}
                    <div className="relative h-[360px] border rounded p-3">
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
                                <LemonBanner type="error" className="max-w-md">
                                    {queryError}
                                </LemonBanner>
                            </div>
                        ) : hasResults ? (
                            <MetricsPanel
                                series={chartSeries}
                                fallbackName={formula || metricName || (language === 'promql' ? queryText : 'metric')}
                                display={metricsDisplay}
                                exemplars={chartMarkers}
                            />
                        ) : !queryLoading ? (
                            <div className="h-full flex items-center justify-center text-secondary text-sm">
                                No data for this metric in the selected range.
                            </div>
                        ) : null}
                        {queryLoading && !isHeatmap && <SpinnerOverlay />}
                    </div>
                </div>
                {hasMetricName && (
                    <div className="xl:w-[26rem] shrink-0 xl:max-h-[360px] flex flex-col">
                        <MetricsSamplesPanel />
                    </div>
                )}
            </div>
        </div>
    )
}
