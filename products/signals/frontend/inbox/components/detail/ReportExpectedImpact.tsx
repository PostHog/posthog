import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'

import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { asReportMetricSeriesQuery, formatReportMetricValue } from '../../utils/reportMetrics'
import { ReportCheckMetricChart } from './ReportCheckMetricChart'
import { ReportCheckMetricSuggestionModal } from './ReportCheckMetricSuggestionModal'
import { buildReportCheckRows, latestCheckExplanations } from './reportCheckPresentation'

const MAX_VISIBLE_MEASUREMENTS = 6

export function ReportExpectedImpact({ report, reportUrl }: { report: SignalReport; reportUrl: string }): JSX.Element {
    const [modalOpen, setModalOpen] = useState(false)
    const logic = inboxReportDetailLogic({ reportId: report.id, report })
    const { reportChecks, reportChecksLoading, reportChecksError, reportArtefacts, approvingCheckIds } =
        useValues(logic)
    const { approveReportCheck, loadReportChecks } = useActions(logic)
    const { currentProjectId, metricCheckReplacementDisabledReason } = useValues(inboxTaskKickoffLogic)
    const measurements = buildReportCheckRows(reportChecks ?? [], latestCheckExplanations(reportArtefacts ?? []))
        .filter(({ check }) => check.kind === 'metric_threshold' && check.status !== 'cancelled')
        .flatMap((row) => {
            const { check } = row
            if (!('comparison' in check.config)) {
                return []
            }
            const config = check.config
            const metric: ReportMetricApi = {
                metric_id: config.metric_id ?? check.id,
                title: check.title,
                kind: config.metric_kind ?? 'custom',
                query: config.query,
                value_format: config.value_format ?? 'number',
                unit: config.unit,
                goal_value: config.comparison.operator === 'between' ? null : config.comparison.value,
                goal_direction: config.comparison.operator === 'lte' ? 'at_most' : 'at_least',
            }
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

    return (
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
                measurements.map(({ check, config, metric, goal, detail, tag, cancellable }) => {
                    const query = asReportMetricSeriesQuery(metric)
                    return (
                        <div key={check.id} className="flex flex-col gap-2">
                            <p className="m-0 font-semibold">
                                {metric.title}: {goal}
                            </p>
                            <p className="m-0 text-secondary text-sm">
                                {cancellable ? (
                                    <span>{check.approved_at ? 'Approved measurement' : 'Proposed measurement'}</span>
                                ) : (
                                    <LemonTag type={tag.type}>{tag.label}</LemonTag>
                                )}
                                <span> · Goal for the full query window</span>
                            </p>
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
                                />
                            ) : (
                                <p className="text-tertiary m-0">The query is not available to you.</p>
                            )}
                            {config.baseline_value != null && (
                                <p className="m-0 text-secondary text-sm">
                                    Baseline:{' '}
                                    {formatReportMetricValue(metric, config.baseline_value) ?? config.baseline_value}
                                </p>
                            )}
                            <p className="m-0 text-secondary text-sm">{detail}</p>
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
            {measurements.length > 0 && (
                <div className="flex flex-wrap gap-2">
                    <LemonButton
                        data-attr="report-expected-impact-follow-up"
                        type="primary"
                        size="small"
                        loading={approving}
                        disabledReason={
                            reportChecks === null
                                ? 'Loading measurements…'
                                : currentProjectId == null
                                  ? 'Select a project to approve measurements.'
                                  : pendingApproval.length === 0
                                    ? unavailableMeasurements
                                        ? 'The measurement query is not available to you.'
                                        : 'No measurements awaiting approval.'
                                    : undefined
                        }
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
                            metricCheckReplacementDisabledReason ??
                            (openMeasurements.length === 0 ? 'No open metric checks to revise.' : undefined)
                        }
                        onClick={() => setModalOpen(true)}
                    >
                        Suggest different metrics
                    </LemonButton>
                </div>
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
