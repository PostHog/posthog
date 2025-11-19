import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { Query } from '~/queries/Query/Query'
import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'

import { evaluationMetricsLogic } from '../evaluationMetricsLogic'
import { llmEvaluationsLogic } from '../llmEvaluationsLogic'

export const EVALUATION_METRICS_COLLECTION_ID = 'evaluation-metrics'

export const PASS_RATE_SUCCESS_THRESHOLD = 70
export const PASS_RATE_WARNING_THRESHOLD = 50

function getPassRateColor(passRate: number): string {
    if (passRate >= PASS_RATE_SUCCESS_THRESHOLD) {
        return 'text-success'
    }
    if (passRate >= PASS_RATE_WARNING_THRESHOLD) {
        return 'text-warning'
    }
    return 'text-danger'
}

function SummaryCard({
    title,
    value,
    subtitle,
    colorClass,
}: {
    title: string
    value: string | number
    subtitle?: string
    colorClass?: string
}): JSX.Element {
    return (
        <div className="bg-bg-light border rounded p-4 flex flex-col">
            <div className="text-muted text-xs font-medium uppercase mb-2">{title}</div>
            <div className={`text-3xl font-semibold ${colorClass || ''}`}>{value}</div>
            {subtitle && <div className="text-muted text-sm mt-1">{subtitle}</div>}
        </div>
    )
}

export function EvaluationMetrics(): JSX.Element {
    const { summaryMetrics, statsLoading, chartQuery } = useValues(evaluationMetricsLogic)

    const { evaluations } = useValues(llmEvaluationsLogic)

    const enabledEvaluationsCount = evaluations.filter((e) => e.enabled && !e.deleted).length

    if (statsLoading) {
        return (
            <div className="space-y-4 mb-6">
                <LemonSkeleton className="h-96 w-full" />
            </div>
        )
    }

    return (
        <div className="mb-6">
            <div className="flex gap-4 h-96">
                {chartQuery ? (
                    <div className="flex-1 bg-bg-light rounded p-4 flex flex-col InsightCard h-full">
                        <h3 className="text-lg font-semibold mb-2">Pass rate over time</h3>
                        <p className="text-muted text-sm mb-4">Showing pass rate trends for enabled evaluations</p>
                        <div className="flex-1 flex flex-col min-h-0">
                            <Query
                                query={{ kind: NodeKind.InsightVizNode, source: chartQuery } as InsightVizNode}
                                readOnly
                                embedded
                                inSharedMode
                                context={{
                                    insightProps: {
                                        dashboardItemId: 'new-evaluation-metrics-chart',
                                        dataNodeCollectionId: EVALUATION_METRICS_COLLECTION_ID,
                                    },
                                }}
                            />
                        </div>
                    </div>
                ) : (
                    <div className="flex-1 bg-bg-light border rounded p-8 flex items-center justify-center">
                        <div className="text-muted text-center">
                            No enabled evaluations to display. Create and enable evaluations to see metrics.
                        </div>
                    </div>
                )}

                {/* Summary cards on the right in 2x2 grid */}
                <div className="flex-1 grid grid-cols-2 gap-4">
                    <SummaryCard
                        title="Enabled evaluations"
                        value={enabledEvaluationsCount}
                        subtitle={`${evaluations.length} total`}
                    />
                    <SummaryCard
                        title="Runs"
                        value={summaryMetrics.total_runs}
                        subtitle={summaryMetrics.total_runs === 0 ? 'No activity' : undefined}
                    />
                    <SummaryCard
                        title="Pass rate"
                        value={summaryMetrics.total_runs === 0 ? 'N/A' : `${summaryMetrics.overall_pass_rate}%`}
                        colorClass={
                            summaryMetrics.total_runs > 0 ? getPassRateColor(summaryMetrics.overall_pass_rate) : ''
                        }
                    />
                    <SummaryCard
                        title="Failing evaluations"
                        value={summaryMetrics.failing_evaluations_count}
                        subtitle="< 70% pass rate"
                        colorClass={summaryMetrics.failing_evaluations_count > 0 ? 'text-danger' : 'text-success'}
                    />
                </div>
            </div>
        </div>
    )
}
