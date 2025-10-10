import { BindLogic, useValues } from 'kea'

import { IconCheck, IconWarning, IconX } from '@posthog/icons'
import { LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { urls } from 'scenes/urls'

import { EvaluationRun } from '../evaluations/types'
import { generationEvaluationRunsLogic } from '../generationEvaluationRunsLogic'

export function GenerationEvalRunsTable({ generationEventId }: { generationEventId: string }): JSX.Element {
    return (
        <BindLogic logic={generationEvaluationRunsLogic} props={{ generationEventId }}>
            <GenerationEvalRunsTableContent />
        </BindLogic>
    )
}

function GenerationEvalRunsTableContent(): JSX.Element {
    const { generationEvaluationRuns, generationEvaluationRunsLoading } = useValues(generationEvaluationRunsLogic)

    const columns: LemonTableColumns<EvaluationRun> = [
        {
            title: 'Timestamp',
            key: 'timestamp',
            render: (_, run) => <TZLabel time={run.timestamp} />,
            sorter: (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
        },
        {
            title: 'Evaluation',
            key: 'evaluation',
            render: (_, run) => (
                <Link to={urls.llmAnalyticsEvaluation(run.evaluation_id)} className="text-primary font-medium">
                    {run.evaluation_name}
                </Link>
            ),
        },
        {
            title: 'Result',
            key: 'result',
            render: (_, run) => {
                if (run.status === 'failed') {
                    return (
                        <LemonTag type="danger" icon={<IconWarning />}>
                            Error
                        </LemonTag>
                    )
                }
                if (run.status === 'running') {
                    return <LemonTag type="primary">Running...</LemonTag>
                }
                return (
                    <div className="flex items-center gap-2">
                        {run.result ? (
                            <LemonTag type="success" icon={<IconCheck />}>
                                True
                            </LemonTag>
                        ) : (
                            <LemonTag type="danger" icon={<IconX />}>
                                False
                            </LemonTag>
                        )}
                    </div>
                )
            },
            sorter: (a, b) => Number(b.result) - Number(a.result),
        },
        {
            title: 'Reasoning',
            key: 'reasoning',
            render: (_, run) => (
                <div className="max-w-md">
                    <div className="text-sm text-default line-clamp-2">{run.reasoning}</div>
                </div>
            ),
        },
    ]

    return (
        <div>
            <LemonTable
                columns={columns}
                dataSource={generationEvaluationRuns}
                loading={generationEvaluationRunsLoading}
                rowKey="id"
                pagination={{
                    pageSize: 20,
                }}
                emptyState={
                    <div className="text-center py-8">
                        <div className="text-muted mb-2">No evaluations run yet</div>
                        <div className="text-sm text-muted">
                            Click "Run Evaluation" above to run an evaluation on this generation.
                        </div>
                    </div>
                }
            />
        </div>
    )
}
