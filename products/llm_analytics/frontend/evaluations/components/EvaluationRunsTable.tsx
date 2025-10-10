import { useActions, useValues } from 'kea'

import { IconCheck, IconRefresh, IconWarning, IconX } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { humanFriendlyDuration } from 'lib/utils'

import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { EvaluationRun } from '../types'

export function EvaluationRunsTable(): JSX.Element {
    const { evaluationRuns, runsLoading } = useValues(llmEvaluationLogic)
    const { refreshEvaluationRuns } = useActions(llmEvaluationLogic)

    const columns: LemonTableColumns<EvaluationRun> = [
        {
            title: 'Timestamp',
            key: 'timestamp',
            render: (_, run) => (
                <div className="flex flex-col">
                    <TZLabel time={run.timestamp} />
                    <div className="text-muted text-xs">{humanFriendlyDuration(run.timestamp)}</div>
                </div>
            ),
            sorter: (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
        },
        {
            title: 'Generation ID',
            key: 'generation_id',
            render: (_, run) => (
                <div className="font-mono text-sm">
                    <Link to={`/llm-analytics/traces?event=${run.generation_id}`} className="text-primary">
                        {run.generation_id.slice(0, 12)}...
                    </Link>
                </div>
            ),
        },
        {
            title: 'Input',
            key: 'input_preview',
            render: (_, run) => (
                <div className="max-w-xs">
                    <div className="text-sm font-mono bg-bg-light border rounded px-2 py-1 truncate">
                        {run.input_preview || '(No input)'}
                    </div>
                </div>
            ),
        },
        {
            title: 'Output',
            key: 'output_preview',
            render: (_, run) => (
                <div className="max-w-xs">
                    <div className="text-sm font-mono bg-bg-light border rounded px-2 py-1 truncate">
                        {run.output_preview || '(No output)'}
                    </div>
                </div>
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
            sorter: (a, b) => {
                if (a.status !== 'completed' || b.status !== 'completed') {
                    return a.status.localeCompare(b.status)
                }
                return Number(b.result) - Number(a.result)
            },
        },
        {
            title: 'Status',
            key: 'status',
            render: (_, run) => {
                const statusMap = {
                    completed: { type: 'success' as const, text: 'Completed' },
                    failed: { type: 'danger' as const, text: 'Failed' },
                    running: { type: 'primary' as const, text: 'Running' },
                }
                const status = statusMap[run.status]
                return <LemonTag type={status.type}>{status.text}</LemonTag>
            },
        },
    ]

    return (
        <div className="space-y-4">
            <div className="flex justify-end">
                <LemonButton
                    type="secondary"
                    icon={<IconRefresh />}
                    onClick={refreshEvaluationRuns}
                    loading={runsLoading}
                    size="small"
                >
                    Refresh
                </LemonButton>
            </div>

            <LemonTable
                columns={columns}
                dataSource={evaluationRuns}
                loading={runsLoading}
                rowKey="id"
                pagination={{
                    pageSize: 20,
                }}
                emptyState={
                    <div className="text-center py-8">
                        <div className="text-muted mb-2">No evaluation runs yet</div>
                        <div className="text-sm text-muted">
                            Runs will appear here once this evaluation starts executing based on your triggers.
                        </div>
                    </div>
                }
            />
        </div>
    )
}
