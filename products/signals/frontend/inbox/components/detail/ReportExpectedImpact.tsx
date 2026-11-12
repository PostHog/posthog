import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { asReportMetricSeriesQuery, formatReportMetricValue } from '../../utils/reportMetrics'
import { ReportCheckMetricChart } from './ReportCheckMetricChart'
import { ReportCheckMetricSuggestionModal } from './ReportCheckMetricSuggestionModal'
import {
    buildReportCheckRows,
    latestCheckExplanations,
    monitoringPeriodLabel,
    reportCheckMetric,
} from './reportCheckPresentation'
import { ReportCheckTiming } from './ReportCheckTiming'
import { ReportMonitoringDetails } from './ReportMonitoringDetails'

const MAX_VISIBLE_MEASUREMENTS = 6

function approvalDisabledReason({
    loading,
    hasProject,
    pendingCount,
    unavailableMeasurements,
}: {
    loading: boolean
    hasProject: boolean
    pendingCount: number
    unavailableMeasurements: boolean
}): string | undefined {
    if (loading) {
        return 'Loading measurements…'
    }
    if (!hasProject) {
        return 'Select a project to approve measurements.'
    }
    if (pendingCount > 0) {
        return undefined
    }
    return unavailableMeasurements
        ? 'The measurement query is not available to you.'
        : 'No measurements awaiting approval.'
}

export function ReportExpectedImpact({
    report,
    reportUrl,
}: {
    report: SignalReport
    reportUrl: string
}): JSX.Element | null {
    const monitoringEnabled = useFeatureFlag('SIGNALS_REPORT_MONITORING')
    const [modalOpen, setModalOpen] = useState(false)
    const logic = inboxReportDetailLogic({ reportId: report.id, report })
    const { reportChecks, reportChecksLoading, reportChecksError, reportArtefacts, approvingCheckIds } =
        useValues(logic)
    const { approveReportCheck, loadReportChecks } = useActions(logic)
    const { currentProjectId } = useValues(inboxTaskKickoffLogic)
    if (!monitoringEnabled) {
        return null
    }
    const measurements = buildReportCheckRows(
        reportChecks ?? [],
        latestCheckExplanations(reportArtefacts ?? []),
        report.status
    )
        .filter(({ check }) => check.status !== 'cancelled')
        .flatMap((row) => {
            const checkMetric = reportCheckMetric(row.check)
            if (!checkMetric) {
                return []
            }
            const { config, metric } = checkMetric
            const formatValue = (value: number | null | undefined): string =>
                value == null ? 'unavailable' : (formatReportMetricValue(metric, value) ?? String(value))
            const goal =
                config.comparison.operator === 'between'
                    ? `between ${formatValue(config.comparison.bounds?.lower)} and ${formatValue(config.comparison.bounds?.upper)}`
                    : `${config.comparison.operator === 'lte' ? 'at most' : 'at least'} ${formatValue(config.comparison.value)}`
            return [{ ...row, config, metric, goal }]
        })
        .slice(0, MAX_VISIBLE_MEASUREMENTS)
    const openMeasurements = measurements.filter(({ cancellable }) => cancellable)
    const pendingApproval = openMeasurements.filter(({ check, config }) => !check.approved_at && config.query != null)
    const unavailableMeasurements = openMeasurements.some(
        ({ check, config }) => !check.approved_at && config.query == null
    )
    const approving = measurements.some(({ check }) => approvingCheckIds.includes(check.id))
    const allOpenApproved = openMeasurements.length > 0 && openMeasurements.every(({ check }) => check.approved_at)

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-col gap-3 rounded-lg border p-4" data-attr="report-expected-impact">
                {reportChecksError && (
                    <div className="flex flex-wrap items-center gap-2">
                        <p className="m-0 text-secondary text-sm">{reportChecksError}</p>
                        <LemonButton
                            data-attr="report-expected-impact-retry"
                            type="secondary"
                            size="small"
                            onClick={() => loadReportChecks()}
                            loading={reportChecksLoading}
                        >
                            Try again
                        </LemonButton>
                    </div>
                )}
                {measurements.length ? (
                    measurements.map(({ check, reportStatus, config, metric, goal, detail, tag, cancellable }) => {
                        const query = asReportMetricSeriesQuery(metric)
                        const showApprovalLabel =
                            cancellable &&
                            !check.monitoring_timing &&
                            !['resolved', 'suppressed', 'deleted'].includes(reportStatus)
                        return (
                            <div key={check.id} className="flex flex-col gap-2">
                                <p className="m-0 font-semibold">
                                    <span>{`${metric.title}: ${goal}`}</span>
                                    {config.monitoring?.threshold_scaling === 'linear' && (
                                        <span>{` per ${monitoringPeriodLabel(config.monitoring.reference_period_minutes)}`}</span>
                                    )}
                                </p>
                                <div className="m-0 flex flex-wrap items-center gap-x-1 text-secondary text-sm">
                                    {showApprovalLabel ? (
                                        <span>
                                            {check.approved_at ? 'Approved measurement' : 'Proposed measurement'}
                                        </span>
                                    ) : (
                                        <LemonTag type={tag.type}>{tag.label}</LemonTag>
                                    )}
                                    <span>
                                        {config.monitoring
                                            ? ' · Monitoring definition'
                                            : ' · Goal for the full query window'}
                                    </span>
                                </div>
                                {query ? (
                                    <ReportCheckMetricChart
                                        reportId={report.id}
                                        metric={metric}
                                        query={query.source}
                                        goalGrain="whole_window"
                                        goalBounds={
                                            config.comparison.operator === 'between' ? config.comparison.bounds : null
                                        }
                                        version={check.id}
                                        monitoring={
                                            config.monitoring
                                                ? {
                                                      referencePeriodMinutes:
                                                          config.monitoring.reference_period_minutes,
                                                      thresholdScaling: config.monitoring.threshold_scaling,
                                                      startedAt: report.monitoring_started_at,
                                                  }
                                                : undefined
                                        }
                                    />
                                ) : (
                                    <p className="text-tertiary m-0">The query is not available to you.</p>
                                )}
                                {config.monitoring ? (
                                    <ReportMonitoringDetails
                                        config={config}
                                        monitoring={config.monitoring}
                                        metric={metric}
                                        timingDescription={
                                            <ReportCheckTiming
                                                check={check}
                                                reportStatus={reportStatus}
                                                detail={
                                                    showApprovalLabel && check.soak_minutes != null
                                                        ? `Check observation window after implementation: ${monitoringPeriodLabel(check.soak_minutes)}.`
                                                        : detail
                                                }
                                            />
                                        }
                                    />
                                ) : (
                                    <>
                                        {config.baseline_value != null && (
                                            <p className="m-0 text-secondary text-sm">{`Baseline: ${formatReportMetricValue(metric, config.baseline_value) ?? config.baseline_value}`}</p>
                                        )}
                                        <p className="m-0 text-secondary text-sm">{detail}</p>
                                    </>
                                )}
                                {config.query != null && (
                                    <details className="text-sm">
                                        <summary className="cursor-pointer">View measurement query</summary>
                                        <pre className="max-h-64 overflow-auto rounded bg-surface-secondary p-2 text-xs">
                                            {JSON.stringify(config.query, null, 2)}
                                        </pre>
                                    </details>
                                )}
                            </div>
                        )
                    })
                ) : !reportChecksError ? (
                    <p className="m-0 text-secondary text-sm">
                        {reportChecks === null ? 'Loading measurements…' : 'No metric follow-up checks yet.'}
                    </p>
                ) : null}
                {measurements.length > 0 && !allOpenApproved && (
                    <div className="flex flex-wrap gap-2">
                        <LemonButton
                            data-attr="report-expected-impact-follow-up"
                            type="primary"
                            size="small"
                            loading={approving}
                            disabledReason={approvalDisabledReason({
                                loading: reportChecks === null,
                                hasProject: currentProjectId != null,
                                pendingCount: pendingApproval.length,
                                unavailableMeasurements,
                            })}
                            tooltip="Approval is feedback. Checks run automatically."
                            onClick={() => pendingApproval.forEach(({ check }) => approveReportCheck(check.id))}
                        >
                            Looks good
                        </LemonButton>
                        <LemonButton
                            data-attr="report-expected-impact-suggest-metrics"
                            type="secondary"
                            size="small"
                            disabledReason={
                                openMeasurements.length === 0 ? 'No open metric checks to revise.' : undefined
                            }
                            onClick={() => setModalOpen(true)}
                        >
                            Suggest different metrics
                        </LemonButton>
                    </div>
                )}
            </div>
            {allOpenApproved && (
                <Link
                    data-attr="report-expected-impact-suggest-another-metric"
                    className="self-start text-sm"
                    onClick={() => setModalOpen(true)}
                >
                    Suggest another metric
                </Link>
            )}
            <ReportCheckMetricSuggestionModal
                report={report}
                reportUrl={reportUrl}
                isOpen={modalOpen}
                onClose={() => setModalOpen(false)}
            />
        </div>
    )
}
