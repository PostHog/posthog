import { useValues } from 'kea'

import { LemonCard, LemonSkeleton } from '@posthog/lemon-ui'

import { humanFriendlyLargeNumber, humanFriendlyNumber } from 'lib/utils/numbers'

import { pipelineOverviewSceneLogic } from './pipelineOverviewSceneLogic'

interface StatTileProps {
    label: string
    value: string
    /** Full value, shown on hover when `value` is compacted. */
    exact?: string
    sub?: string
    loading: boolean
    danger?: boolean
}

function StatTile({ label, value, exact, sub, loading, danger }: StatTileProps): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="flex min-w-40 flex-1 flex-col justify-center px-4 py-3">
            <div className="text-xs font-medium text-secondary">{label}</div>
            {/* Skeleton the whole tile on a first load rather than showing a zero that is about
                to change, which reads as a real answer. */}
            {loading ? (
                <LemonSkeleton className="my-1 h-7 w-20" />
            ) : (
                <div
                    className={`my-0.5 truncate text-2xl font-bold tabular-nums ${danger ? 'text-danger' : ''}`}
                    title={exact}
                >
                    {value}
                </div>
            )}
            {sub ? <div className="text-xs text-muted">{sub}</div> : null}
        </LemonCard>
    )
}

export function PipelineStatTiles(): JSX.Element {
    const {
        jobStats,
        jobStatsLoading,
        rowsStats,
        rowsStatsLoading,
        healthIssues,
        healthIssuesLoading,
        failingSyncCount,
    } = useValues(pipelineOverviewSceneLogic)

    const issueCount = healthIssues?.count ?? 0
    const running = (jobStats?.external_data_jobs?.running ?? 0) + (jobStats?.modeling_jobs?.running ?? 0)

    return (
        <div className="@container">
            <div className="grid grid-cols-2 gap-3 @3xl:grid-cols-4">
                <StatTile
                    label="Rows synced this billing period"
                    // Compacted, because a busy team's row count runs to ten digits and would
                    // otherwise wrap out of the tile.
                    value={humanFriendlyLargeNumber(rowsStats?.total_rows ?? 0)}
                    exact={humanFriendlyNumber(rowsStats?.total_rows ?? 0)}
                    sub={rowsStats?.billing_available ? undefined : 'Billing is unavailable, so this may be behind'}
                    loading={rowsStatsLoading && rowsStats === null}
                />
                <StatTile
                    label="Runs"
                    value={humanFriendlyNumber(jobStats?.total_jobs ?? 0)}
                    sub={`${humanFriendlyNumber(jobStats?.successful_jobs ?? 0)} succeeded`}
                    loading={jobStatsLoading && jobStats === null}
                />
                <StatTile
                    label="Needs attention"
                    value={humanFriendlyNumber(issueCount)}
                    sub={issueCount > 0 ? `${failingSyncCount} of them syncs` : 'Everything is healthy'}
                    loading={healthIssuesLoading && healthIssues === null}
                    danger={issueCount > 0}
                />
                <StatTile
                    label="Running now"
                    value={humanFriendlyNumber(running)}
                    sub="Syncs and materializations"
                    loading={jobStatsLoading && jobStats === null}
                />
            </div>
        </div>
    )
}
