import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { MetricsAnomalyPanel } from './MetricsAnomalyPanel'
import { MetricsChartSettings } from './MetricsChartSettings'
import { MetricsDisplayTypeSelect } from './MetricsDisplayTypeSelect'
import { MetricsLogsSourceTag } from './MetricsLogsSourceTag'
import { MetricsRelatedMenu } from './MetricsRelatedMenu'
import { metricsSamplesLogic } from './metricsSamplesLogic'
import { metricsViewerLogic } from './metricsViewerLogic'
import { MetricsViewerSaveMenu } from './MetricsViewerSaveMenu'

/** The chart card's header: how the result draws, overlays and links on the left, the Save menu on the right. */
export function MetricsViewerChartHeader(): JSX.Element {
    const { chartSeries, heatmapEligible, anomalyBadge, metricName, noQueryReason, isHeatmap } =
        useValues(metricsViewerLogic)
    const { showErrorSpikes } = useValues(metricsSamplesLogic)
    const { toggleShowErrorSpikes } = useActions(metricsSamplesLogic)
    // Staff-only PoC gate, layered on top of the wider metrics alpha flag.
    const errorOverlaysEnabled = useFeatureFlag('METRICS_ERROR_OVERLAYS')
    const disabledReason = getAccessControlDisabledReason(AccessControlResourceType.Metrics, AccessControlLevel.Viewer)
    const errorTrackingDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.ErrorTracking,
        AccessControlLevel.Viewer
    )
    // Gate on the result shape, not the clause edits: a formula result is ungrouped even
    // when its input clauses group, and a clause without a metric name never runs.
    const resultIsGrouped = chartSeries.some((s) => Object.keys(s.labels).length > 0)

    return (
        <div className="flex flex-wrap items-center justify-between gap-2 px-2 py-1.5 border-b">
            <div className="flex flex-wrap items-center gap-2">
                <MetricsDisplayTypeSelect
                    dataAttrPrefix="metrics-viewer"
                    resultIsGrouped={resultIsGrouped}
                    heatmap={{ eligible: heatmapEligible }}
                    disabledReason={disabledReason}
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
                        disabledReason={disabledReason}
                    />
                )}
                <MetricsRelatedMenu />
                {anomalyBadge && <MetricsAnomalyPanel anomaly={anomalyBadge} />}
                <MetricsLogsSourceTag metricName={metricName} />
            </div>
            <MetricsViewerSaveMenu noQueryReason={noQueryReason} isHeatmap={isHeatmap} />
        </div>
    )
}
