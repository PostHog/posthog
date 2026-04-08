import { useActions, useValues } from 'kea'

import { LemonBadge, LemonButton, LemonTable } from '@posthog/lemon-ui'

import { evaluationReportLogic } from '../evaluationReportLogic'
import type { EvaluationReportRun } from '../types'
import { EvaluationReportViewer } from './EvaluationReportViewer'

interface EvaluationReportsTabProps {
    evaluationId: string
    /** Called when the user clicks the "Set up scheduled reports" CTA in the empty state. */
    onConfigureClick?: () => void
}

const STATUS_STYLES: Record<
    EvaluationReportRun['delivery_status'],
    { label: string; status: 'success' | 'warning' | 'danger' | 'muted' }
> = {
    delivered: { label: 'Delivered', status: 'success' },
    pending: { label: 'Pending', status: 'muted' },
    partial_failure: { label: 'Partial failure', status: 'warning' },
    failed: { label: 'Failed', status: 'danger' },
}

function formatPeriod(run: EvaluationReportRun): string {
    return `${new Date(run.period_start).toLocaleDateString()} – ${new Date(run.period_end).toLocaleDateString()}`
}

export function EvaluationReportsTab({ evaluationId, onConfigureClick }: EvaluationReportsTabProps): JSX.Element {
    const logic = evaluationReportLogic({ evaluationId })
    const { reportRuns, reportRunsLoading, reportsLoading, activeReport, generateResultLoading } = useValues(logic)
    const { generateReport, loadReportRuns } = useActions(logic)

    // No schedule configured at all → CTA pointing to the Configuration tab.
    // Avoids hiding the Reports tab entirely so it stays discoverable.
    if (!reportsLoading && !activeReport) {
        return (
            <div className="max-w-6xl">
                <div className="bg-bg-light border rounded p-8 text-center space-y-3">
                    <h3 className="text-lg font-semibold m-0">No scheduled reports yet</h3>
                    <p className="text-muted text-sm m-0">
                        Scheduled reports deliver AI-generated analysis of this evaluation's results to email or Slack
                        on a recurring basis.
                    </p>
                    {onConfigureClick && (
                        <LemonButton type="primary" onClick={onConfigureClick}>
                            Set up scheduled reports
                        </LemonButton>
                    )}
                </div>
            </div>
        )
    }

    return (
        <div className="max-w-6xl">
            <div className="flex items-center justify-between mb-4">
                <p className="text-muted text-sm m-0">
                    History of AI-generated reports for this evaluation. Click a row to expand the full report. Schedule
                    and delivery targets are configured in the Configuration tab.
                </p>
                {activeReport && (
                    <div className="flex items-center gap-2">
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => loadReportRuns(activeReport.id)}
                            loading={reportRunsLoading}
                        >
                            Refresh
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={() => generateReport(activeReport.id)}
                            loading={generateResultLoading}
                        >
                            Generate now
                        </LemonButton>
                    </div>
                )}
            </div>

            <LemonTable
                dataSource={reportRuns}
                loading={reportRunsLoading}
                rowKey="id"
                columns={[
                    {
                        title: 'Generated',
                        key: 'created_at',
                        render: (_, run: EvaluationReportRun) => new Date(run.created_at).toLocaleString(),
                    },
                    {
                        title: 'Period',
                        key: 'period',
                        render: (_, run: EvaluationReportRun) => formatPeriod(run),
                    },
                    {
                        title: 'Title',
                        key: 'title',
                        render: (_, run: EvaluationReportRun) => (
                            <span className="font-medium">{run.content?.title || '–'}</span>
                        ),
                    },
                    {
                        title: 'Pass rate',
                        key: 'pass_rate',
                        render: (_, run: EvaluationReportRun) => {
                            const pct = run.content?.metrics?.pass_rate ?? run.metadata?.pass_rate
                            return typeof pct === 'number' ? `${pct.toFixed(1)}%` : '–'
                        },
                    },
                    {
                        title: 'Runs',
                        key: 'total_runs',
                        render: (_, run: EvaluationReportRun) =>
                            run.content?.metrics?.total_runs ?? run.metadata?.total_runs ?? '–',
                    },
                    {
                        title: 'Delivery',
                        key: 'delivery_status',
                        render: (_, run: EvaluationReportRun) => {
                            const info = STATUS_STYLES[run.delivery_status] || {
                                label: run.delivery_status,
                                status: 'muted' as const,
                            }
                            return <LemonBadge content={info.label} status={info.status} />
                        },
                    },
                ]}
                expandable={{
                    expandedRowRender: (run: EvaluationReportRun) => (
                        <div className="p-4 bg-bg-light">
                            <EvaluationReportViewer reportRun={run} compact />
                        </div>
                    ),
                }}
                emptyState="No reports generated yet"
                size="small"
            />
        </div>
    )
}
