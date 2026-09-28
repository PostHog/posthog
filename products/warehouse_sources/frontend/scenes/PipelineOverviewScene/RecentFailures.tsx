import { useValues } from 'kea'

import { LemonSkeleton, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { PipelineActivityRowApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { pipelineOverviewSceneLogic } from './pipelineOverviewSceneLogic'

export function RecentFailures(): JSX.Element {
    const { failedRuns, recentFailures, recentFailuresLoading } = useValues(pipelineOverviewSceneLogic)

    if (recentFailuresLoading && recentFailures === null) {
        return <LemonSkeleton className="h-24 w-full" />
    }

    if (recentFailures !== null && failedRuns.length === 0) {
        return (
            <div className="rounded border border-primary bg-surface-primary px-4 py-6 text-center text-muted">
                No runs have failed recently.
            </div>
        )
    }

    return (
        <LemonTable<PipelineActivityRowApi>
            id="etl-recent-failures"
            dataSource={failedRuns}
            rowKey="id"
            size="small"
            loading={recentFailuresLoading && recentFailures !== null}
            nouns={['run', 'runs']}
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
                    width: 150,
                    render: (_, run) => <LemonTag type="danger">{run.status}</LemonTag>,
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
            ]}
        />
    )
}
