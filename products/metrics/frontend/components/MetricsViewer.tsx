import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect } from 'react'

import { AddToDashboardModal } from 'lib/components/AddToDashboard/AddToDashboardModal'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { NewDashboardModal } from 'scenes/dashboard/NewDashboardModal'
import { teamLogic } from 'scenes/teamLogic'

import { getMetricsInsightEditorDisabledReason } from '../metricsAccess'
import { MetricsFacetRail, MetricsFacetRailToggle } from './FacetRail/MetricsFacetRail'
import { metricsSamplesLogic } from './metricsSamplesLogic'
import { MetricsSamplesPanel } from './MetricsSamplesPanel'
import { MetricsStarterDashboardModal } from './MetricsStarterDashboardModal'
import { MetricsViewerChart } from './MetricsViewerChart'
import { MetricsViewerChartHeader } from './MetricsViewerChartHeader'
import { metricsViewerLogic } from './metricsViewerLogic'
import { MetricsViewerQueryBar } from './MetricsViewerQueryBar'

export const MetricsViewer = (): JSX.Element => {
    const logic = metricsViewerLogic()
    // The side panel's logic listens to this viewer's filter changes; mounting it
    // here keeps samples in sync even while the panel itself is off-screen.
    useMountedLogic(metricsSamplesLogic())
    const {
        queryFingerprint,
        anomalyFingerprint,
        dateFrom,
        dateTo,
        savedInsight,
        isAddToDashboardModalOpen,
        hasMetricName,
        language,
    } = useValues(logic)
    const { fetchQueryResults, fetchAnomaly, clearAnomaly, closeAddToDashboardModal } = useActions(logic)
    const { timezone } = useValues(teamLogic)
    const insightEditorDisabledReason = getMetricsInsightEditorDisabledReason()

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

    // The rail writes builder filter chips, which PromQL and SQL queries do not read.
    const facetRailEnabled = useFeatureFlag('METRICS') && language === 'builder'

    return (
        <div
            className="@container/facet-rail-host flex flex-col gap-2 flex-1 min-h-0 overflow-y-auto"
            data-attr="metrics-viewer"
        >
            <MetricsViewerQueryBar />
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
                <MetricsViewerChartHeader />
                <MetricsViewerChart />
            </div>
            {(facetRailEnabled || hasMetricName) && (
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
