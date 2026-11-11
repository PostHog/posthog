import { useValues } from 'kea'

import { LemonButton, LemonSkeleton, LemonTable, LemonTag, Spinner } from '@posthog/lemon-ui'
import type { LemonTagType } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import type { PipelineActivityRowApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { pipelineOverviewSceneLogic } from './pipelineOverviewSceneLogic'

const STATUS_TAG_TYPES: Record<string, LemonTagType> = {
    Running: 'primary',
    Completed: 'success',
    Failed: 'danger',
    BillingLimitReached: 'warning',
    BillingLimitTooLow: 'warning',
}

const STATUS_LABELS: Record<string, string> = {
    BillingLimitReached: 'Billing limit',
    BillingLimitTooLow: 'Billing limit',
}

export function RecentRuns(): JSX.Element {
    const { recentRunRows, recentRuns, recentRunsLoading } = useValues(pipelineOverviewSceneLogic)

    if (recentRunsLoading && recentRuns === null) {
        return <LemonSkeleton className="h-24 w-full" />
    }

    if (recentRuns !== null && recentRunRows.length === 0) {
        return (
            <div className="rounded border border-primary bg-surface-primary px-4 py-6 text-center text-muted">
                No syncs have run in this window.
            </div>
        )
    }

    return (
        <LemonTable<PipelineActivityRowApi>
            id="etl-recent-runs"
            dataSource={recentRunRows}
            rowKey="id"
            size="small"
            nouns={['run', 'runs']}
            pagination={{ pageSize: 15 }}
            columns={[
                {
                    title: 'Table',
                    key: 'name',
                    render: (_, run) => (
                        <div className="flex min-w-0 flex-col">
                            <span className="truncate font-medium">{run.name ?? 'Unnamed'}</span>
                            <span className="text-xs text-muted">{run.type ?? 'Unknown'}</span>
                        </div>
                    ),
                },
                {
                    title: 'Status',
                    key: 'status',
                    width: 140,
                    render: (_, run) => (
                        <span className="flex items-center gap-1.5">
                            {run.status === 'Running' ? <Spinner className="text-sm" /> : null}
                            <LemonTag type={STATUS_TAG_TYPES[run.status] ?? 'default'}>
                                {STATUS_LABELS[run.status] ?? run.status}
                            </LemonTag>
                        </span>
                    ),
                },
                {
                    title: 'Rows',
                    key: 'rows',
                    align: 'right',
                    width: 90,
                    // A running job has not reported its rows yet, so a zero would read as
                    // "moved nothing" rather than "still going".
                    render: (_, run) =>
                        run.status === 'Running' ? (
                            <span className="text-muted">—</span>
                        ) : (
                            <span className="tabular-nums">{humanFriendlyNumber(run.rows ?? 0)}</span>
                        ),
                },
                {
                    title: 'Error',
                    key: 'latest_error',
                    render: (_, run) =>
                        run.latest_error ? (
                            <span className="line-clamp-2 font-mono text-xs text-secondary">{run.latest_error}</span>
                        ) : (
                            <span className="text-muted">—</span>
                        ),
                },
                {
                    title: 'When',
                    key: 'created_at',
                    width: 140,
                    render: (_, run) => <TZLabel time={run.created_at} />,
                },
                {
                    title: '',
                    key: 'actions',
                    width: 80,
                    render: (_, run) => {
                        const sourceId = (run as { source_id?: string | null }).source_id
                        // The source scene keys on a prefixed id; a bare UUID renders nothing.
                        return sourceId ? (
                            <LemonButton
                                type="tertiary"
                                size="xsmall"
                                to={urls.dataWarehouseSource(`managed-${sourceId}`, 'syncs')}
                                data-attr="etl-run-view-source"
                            >
                                View
                            </LemonButton>
                        ) : null
                    },
                },
            ]}
        />
    )
}
