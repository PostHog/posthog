import { IconClock, IconPerson, IconTarget } from '@posthog/icons'
import { LemonTable, LemonTableColumns, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import type { IdentityMatchingRunApi } from './generated/api.schemas'

function durationLabel(start: string, end: string): string {
    const diff = dayjs(end).diff(dayjs(start), 'second')
    if (diff < 60) {
        return `${diff}s`
    }
    if (diff < 3600) {
        return `${Math.round(diff / 60)}m`
    }
    return `${Math.round(diff / 3600)}h ${Math.round((diff % 3600) / 60)}m`
}

export function RunsHistory({
    runs,
    selectedJobId,
    onSelect,
    loading,
}: {
    runs: IdentityMatchingRunApi[]
    selectedJobId: string | null
    onSelect: (jobId: string | null) => void
    loading: boolean
}): JSX.Element {
    const columns: LemonTableColumns<IdentityMatchingRunApi> = [
        {
            title: (
                <span className="flex items-center gap-1">
                    <IconClock className="text-sm" />
                    Computed
                </span>
            ),
            dataIndex: 'computed_at',
            render: (_, run) => (
                <div>
                    <div className="font-medium">{dayjs(run.computed_at).format('MMM D, YYYY HH:mm')}</div>
                    <div className="text-xs text-tertiary">
                        {run.first_link_at && run.last_link_at
                            ? durationLabel(run.first_link_at, run.last_link_at)
                            : ''}
                    </div>
                </div>
            ),
            width: 160,
        },
        {
            title: 'Models',
            dataIndex: 'models',
            render: (_, run) => (
                <div className="flex flex-wrap gap-1">
                    {run.models.map((model) => (
                        <Tooltip
                            key={model.model_version}
                            title={`${model.high_confidence} high · ${model.medium_confidence} medium · ${model.low_confidence} low`}
                        >
                            <LemonTag>
                                {model.model_version}: {model.link_count}
                            </LemonTag>
                        </Tooltip>
                    ))}
                </div>
            ),
        },
        {
            title: (
                <span className="flex items-center gap-1">
                    <IconPerson className="text-sm" />
                    Visitors
                </span>
            ),
            dataIndex: 'unique_orphans',
            render: (_, run) => <span className="font-mono tabular-nums">{run.unique_orphans}</span>,
            width: 100,
            sorter: (a, b) => a.unique_orphans - b.unique_orphans,
        },
        {
            title: 'Tier breakdown',
            key: 'tiers',
            render: (_, run) => {
                const high = run.models.reduce((sum, m) => sum + m.high_confidence, 0)
                const medium = run.models.reduce((sum, m) => sum + m.medium_confidence, 0)
                const low = run.models.reduce((sum, m) => sum + m.low_confidence, 0)
                return (
                    <div className="flex items-center gap-1.5">
                        <LemonTag type="success">{high} high</LemonTag>
                        <LemonTag type="warning">{medium} med</LemonTag>
                        <LemonTag>{low} low</LemonTag>
                    </div>
                )
            },
            width: 200,
        },
        {
            title: (
                <span className="flex items-center gap-1">
                    <IconTarget className="text-sm" />
                    Paid touches
                </span>
            ),
            dataIndex: 'paid_touches',
            render: (_, run) => (
                <span className="font-mono tabular-nums">
                    {run.paid_touches > 0 ? <span className="text-success">{run.paid_touches}</span> : '—'}
                </span>
            ),
            width: 120,
            sorter: (a, b) => a.paid_touches - b.paid_touches,
        },
        {
            title: 'Total',
            dataIndex: 'total_links',
            render: (_, run) => <span className="font-mono tabular-nums font-semibold">{run.total_links}</span>,
            width: 80,
            sorter: (a, b) => a.total_links - b.total_links,
        },
    ]

    return (
        <LemonTable
            dataSource={runs}
            columns={columns}
            loading={loading}
            rowKey="job_id"
            size="small"
            onRow={(run) => ({
                onClick: () => onSelect(selectedJobId === run.job_id ? null : run.job_id),
                className: selectedJobId === run.job_id ? 'bg-accent-highlight-secondary' : 'cursor-pointer',
            })}
            emptyState="No runs yet. The identity matching Dagster job hasn't produced any results for this project."
        />
    )
}
