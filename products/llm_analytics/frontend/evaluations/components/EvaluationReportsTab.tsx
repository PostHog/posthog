import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

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
    { label: string; type: 'success' | 'warning' | 'danger' | 'muted' }
> = {
    delivered: { label: 'Delivered', type: 'success' },
    pending: { label: 'Pending', type: 'muted' },
    partial_failure: { label: 'Partial failure', type: 'warning' },
    failed: { label: 'Failed', type: 'danger' },
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
                        render: (_, run: EvaluationReportRun) => <TZLabel time={run.created_at} />,
                    },
                    {
                        title: 'Title',
                        key: 'title',
                        render: (_, run: EvaluationReportRun) => (
                            <span className="font-medium truncate block max-w-md" title={run.content?.title}>
                                {run.content?.title || '–'}
                            </span>
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
                        title: 'Status',
                        key: 'delivery_status',
                        render: (_, run: EvaluationReportRun) => {
                            const info = STATUS_STYLES[run.delivery_status] || {
                                label: run.delivery_status,
                                type: 'default' as const,
                            }
                            return (
                                <LemonTag type={info.type} size="small">
                                    {info.label}
                                </LemonTag>
                            )
                        },
                    },
                    {
                        key: 'info',
                        width: 0,
                        render: (_, run: EvaluationReportRun) => (
                            <Tooltip
                                title={`Period: ${new Date(run.period_start).toLocaleString()} – ${new Date(run.period_end).toLocaleString()}`}
                            >
                                <IconInfo className="text-muted text-base" />
                            </Tooltip>
                        ),
                    },
                ]}
                expandable={{
                    noIndent: true,
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
