import { useValues } from 'kea'

import { LemonTable, LemonTableColumns, LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import type { VisionActionRunApi, VisionActionRunStatusEnumApi } from '../../generated/api.schemas'
import { visionActionRunsLogic } from '../visionActionRunsLogic'

const STATUS_TAG: Record<
    VisionActionRunStatusEnumApi,
    { type: 'success' | 'danger' | 'warning' | 'primary'; label: string }
> = {
    completed: { type: 'success', label: 'Completed' },
    failed: { type: 'danger', label: 'Failed' },
    skipped: { type: 'warning', label: 'Skipped' },
    running: { type: 'primary', label: 'Running' },
}

function runTimestamp(run: VisionActionRunApi): string {
    return dayjs(run.scheduled_at ?? run.created_at).format('MMM D, YYYY · HH:mm')
}

function RunSummary({ run }: { run: VisionActionRunApi }): JSX.Element {
    if (run.synthesized_markdown) {
        return <LemonMarkdown>{run.synthesized_markdown}</LemonMarkdown>
    }
    return <div className="text-muted italic">{run.error_reason || 'No summary was produced for this run.'}</div>
}

export function VisionActionRuns(): JSX.Element {
    const { runs, runsLoading } = useValues(visionActionRunsLogic)

    const columns: LemonTableColumns<VisionActionRunApi> = [
        {
            title: 'When',
            key: 'when',
            render: (_, run) => <span className="whitespace-nowrap">{runTimestamp(run)}</span>,
        },
        {
            title: 'Status',
            key: 'status',
            render: (_, run) => {
                const tag = STATUS_TAG[run.status]
                return <LemonTag type={tag.type}>{tag.label}</LemonTag>
            },
        },
        {
            title: 'Observations',
            key: 'observations',
            render: (_, run) => <span className="tabular-nums">{run.observation_count}</span>,
        },
        {
            title: 'Outcome',
            key: 'outcome',
            render: (_, run) =>
                run.synthesized_markdown ? (
                    <span className="text-muted">Expand to read the summary</span>
                ) : (
                    <span className="text-muted">{run.error_reason || '—'}</span>
                ),
        },
    ]

    return (
        <LemonTable
            columns={columns}
            dataSource={runs}
            loading={runsLoading}
            rowKey="id"
            data-attr="vision-action-runs-table"
            emptyState="This action hasn't run yet. Runs appear here once its schedule fires."
            expandable={{
                expandedRowRender: (run) => (
                    <div className="p-2">
                        <RunSummary run={run} />
                    </div>
                ),
                rowExpandable: (run) => !!run.synthesized_markdown || !!run.error_reason,
            }}
        />
    )
}
