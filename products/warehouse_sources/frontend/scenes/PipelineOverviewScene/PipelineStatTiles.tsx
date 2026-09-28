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
        issuesBySeverity,
    } = useValues(pipelineOverviewSceneLogic)

    // `job_stats` reports syncs and materialized view runs separately, and every count here
    // reads the sync half. The totals it also returns fold the two together.
    const syncJobs = jobStats?.external_data_jobs
    // The list this scene shows, not `healthIssues.count`, which counts the whole warehouse
    // including the materialized views this scene leaves out.
    const issueCount = issuesBySeverity.length

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
                    label="Sync runs"
                    value={humanFriendlyNumber(syncJobs?.total ?? 0)}
                    sub={`${humanFriendlyNumber(syncJobs?.successful ?? 0)} succeeded`}
                    loading={jobStatsLoading && jobStats === null}
                />
                <StatTile
                    label="Needs attention"
                    value={humanFriendlyNumber(issueCount)}
                    // The list can also hold a source or a destination, so name the sync share
                    // only when it is not the whole of it.
                    sub={
                        issueCount === 0
                            ? 'Every sync is healthy'
                            : failingSyncCount < issueCount
                              ? `${failingSyncCount} of them syncs`
                              : undefined
                    }
                    loading={healthIssuesLoading && healthIssues === null}
                    danger={issueCount > 0}
                />
                <StatTile
                    label="Running now"
                    value={humanFriendlyNumber(syncJobs?.running ?? 0)}
                    sub="Syncs in flight"
                    loading={jobStatsLoading && jobStats === null}
                />
            </div>
        </div>
    )
}
