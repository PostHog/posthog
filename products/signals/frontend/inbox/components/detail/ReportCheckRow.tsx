import { IconClock, IconTrends } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import { asReportMetricSeriesQuery } from '../../utils/reportMetrics'
import { ReportCheckMetricChart } from './ReportCheckMetricChart'
import { ReportCheckMonitoringTimeline } from './ReportCheckMonitoringTimeline'
import { ReportCheckObservation, interimCheckTag, monitoringTimeline } from './reportCheckObservations'
import { ReportCheckRowData, reportCheckMetric } from './reportCheckPresentation'
import { ReportCheckTiming } from './ReportCheckTiming'

export function ReportCheckRow({
    row,
    reportId,
    monitoringStartedAt,
    observations = [],
    cancelling,
    onCancel,
    onSuggestMetric,
    suggestionDisabledReason,
}: {
    row: ReportCheckRowData
    reportId: string
    monitoringStartedAt?: string | null
    observations?: ReportCheckObservation[]
    cancelling: boolean
    onCancel: (checkId: string) => void
    onSuggestMetric: () => void
    suggestionDisabledReason?: string | null
}): JSX.Element {
    const monitoringEnabled = useFeatureFlag('SIGNALS_REPORT_MONITORING')
    const { check, reportStatus, detail, cancelled, cancellable } = row
    const timeline = monitoringTimeline(row, observations, Date.now())
    const tag = interimCheckTag(row, timeline)
    const checkMetric = monitoringEnabled && !cancelled ? reportCheckMetric(check) : null
    const chartQuery = checkMetric ? asReportMetricSeriesQuery(checkMetric.metric) : null
    const comparison = checkMetric?.config.comparison
    const monitoringConfig = checkMetric?.config.monitoring

    return (
        <div
            className={`flex flex-col gap-1 rounded border border-primary bg-surface-primary px-2.5 py-2 ${
                cancelled ? 'opacity-60' : ''
            }`}
        >
            <div className="flex flex-wrap items-start gap-2 min-w-0">
                <span className="mt-0.5 shrink-0 text-tertiary [&_svg]:size-3.5">
                    {check.kind === 'agent' ? <IconClock /> : <IconTrends />}
                </span>
                <Tooltip title={check.rationale || undefined}>
                    <span
                        className={`min-w-0 flex-1 basis-32 text-xs leading-snug text-default line-clamp-2 ${
                            cancelled ? 'line-through' : ''
                        }`}
                    >
                        {check.title}
                    </span>
                </Tooltip>
                <Tooltip title={tag.description} openOnClick>
                    <LemonTag size="small" type={tag.type} className="shrink-0">
                        {tag.label}
                    </LemonTag>
                </Tooltip>
            </div>
            {checkMetric && chartQuery && (
                <div className="min-w-0 pl-[1.375rem]">
                    <ReportCheckMetricChart
                        reportId={reportId}
                        metric={checkMetric.metric}
                        query={chartQuery.source}
                        goalGrain="whole_window"
                        goalBounds={comparison?.operator === 'between' ? comparison.bounds : null}
                        // Its own key: sharing one with the Expected impact chart lets their queries overwrite each other.
                        version={timeline ? `${check.id}.follow-up.window` : `${check.id}.follow-up`}
                        timeline={timeline}
                        monitoring={
                            monitoringConfig
                                ? {
                                      referencePeriodMinutes: monitoringConfig.reference_period_minutes,
                                      thresholdScaling: monitoringConfig.threshold_scaling,
                                      startedAt: timeline?.startedAt ?? monitoringStartedAt,
                                      endsAt: timeline?.endsAt,
                                  }
                                : undefined
                        }
                    />
                </div>
            )}
            {(!timeline || !chartQuery) && (
                <div className="min-w-0 pl-[1.375rem]">
                    <span className="min-w-0 flex-1 text-xs leading-snug text-tertiary">
                        <ReportCheckTiming check={check} reportStatus={reportStatus} detail={detail} />
                    </span>
                </div>
            )}
            {timeline && !chartQuery && (
                <div className="pt-1">
                    <ReportCheckMonitoringTimeline timeline={timeline} />
                </div>
            )}
            {cancellable && (
                <div className="flex flex-wrap justify-end gap-1">
                    {monitoringEnabled && (
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            disabledReason={cancelling ? 'Canceling this check' : suggestionDisabledReason}
                            data-attr="signals-report-check-suggest-metric"
                            onClick={onSuggestMetric}
                        >
                            Suggest a better metric
                        </LemonButton>
                    )}
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        status="danger"
                        loading={cancelling}
                        disabledReason={cancelling ? 'Canceling this check' : undefined}
                        data-attr="signals-report-check-stop"
                        // Pinned for existing autocapture dashboards.
                        onClick={() =>
                            LemonDialog.open({
                                title: 'Cancel this check?',
                                description: `This cancels future runs of "${check.title}". Results it already recorded stay on this report.`,
                                primaryButton: {
                                    children: 'Cancel this check',
                                    status: 'danger',
                                    onClick: () => onCancel(check.id),
                                },
                                secondaryButton: { children: 'Keep it' },
                            })
                        }
                    >
                        Cancel this check
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
