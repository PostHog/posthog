import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconPeople } from '@posthog/icons'
import { LemonTable, LemonTableColumns, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { urls } from 'scenes/urls'

import { CountWithPrior } from '../components/MetricTile'
import { ScopeBar, SourceScopeChip } from '../components/ScopeBar'
import { rowNavigationProps } from '../lib/rowNavigation'
import {
    TEAMS_WINDOW_DATE_OPTIONS,
    TeamCIHealthRow,
    TeamsWindow,
    UNOWNED_TEAM,
    isTeamsWindow,
    teamsLogic,
} from './teamsLogic'

/** The team's detail page, carrying the roster's window and active source so it opens scoped the same. */
function detailUrlOf(ownerTeam: string, window: TeamsWindow, sourceId: string | null): string {
    return combineUrl(urls.engineeringAnalyticsTeam(ownerTeam), { window, ...(sourceId ? { source: sourceId } : {}) })
        .url
}

export function EngineeringAnalyticsTeams(): JSX.Element {
    const { teams, teamsLoading, teamsWindow, sourceId } = useValues(teamsLogic)
    const { setTeamsWindow } = useActions(teamsLogic)

    const columns: LemonTableColumns<TeamCIHealthRow> = [
        {
            title: 'Team',
            key: 'ownerTeam',
            width: 260,
            sorter: (a, b) => a.ownerTeam.localeCompare(b.ownerTeam),
            render: (_, row) =>
                row.ownerTeam === UNOWNED_TEAM ? (
                    <div className="flex items-center gap-2">
                        <Link
                            to={detailUrlOf(row.ownerTeam, teamsWindow, sourceId)}
                            className="font-semibold"
                            data-attr="eng-analytics-team-link"
                        >
                            Unowned
                        </Link>
                        <Tooltip title="Tests whose CI spans carry no ownership stamp. An ownership gap to close, not a real team.">
                            <LemonTag type="warning" size="small">
                                ownership gap
                            </LemonTag>
                        </Tooltip>
                    </div>
                ) : (
                    <Link
                        to={detailUrlOf(row.ownerTeam, teamsWindow, sourceId)}
                        className="font-mono text-xs font-semibold"
                        data-attr="eng-analytics-team-link"
                    >
                        {row.ownerTeam}
                    </Link>
                ),
        },
        {
            title: 'Tests',
            key: 'testFileCount',
            width: 110,
            align: 'right',
            tooltip:
                'Test files this team owns per the daily owners.yaml census, with the value at the window start. The denominator the signal columns lack.',
            sorter: (a, b) => (a.testFileCount ?? -1) - (b.testFileCount ?? -1),
            render: (_, row) => <CountWithPrior current={row.testFileCount} prior={row.testFileCountPrior} />,
        },
        {
            title: 'Flaky tests',
            key: 'flakyTestCount',
            width: 140,
            align: 'right',
            tooltip:
                'Owned tests one commit was seen both failing and passing in this window, vs the previous one. Only tests with that recovery proof count as flaky.',
            sorter: (a, b) => a.flakyTestCount - b.flakyTestCount,
            render: (_, row) => <CountWithPrior current={row.flakyTestCount} prior={row.flakyTestCountPrior} />,
        },
        {
            title: 'Regressions',
            key: 'regressionTestCount',
            width: 140,
            align: 'right',
            tooltip:
                'Owned tests that failed with no recorded recovery and still hit several PRs or master. Treat as real breaks until a recovery proves otherwise.',
            sorter: (a, b) => a.regressionTestCount - b.regressionTestCount,
            render: (_, row) => (
                <CountWithPrior current={row.regressionTestCount} prior={row.regressionTestCountPrior} />
            ),
        },
        {
            title: 'Failed runs',
            key: 'failedRunCount',
            width: 130,
            align: 'right',
            tooltip:
                'CI runs where an owned test failed or errored. Absolute counts, not rates: passing runs are mostly not recorded.',
            sorter: (a, b) => a.failedRunCount - b.failedRunCount,
            render: (_, row) => <CountWithPrior current={row.failedRunCount} prior={row.failedRunCountPrior} />,
        },
        {
            title: 'Recoveries',
            key: 'sameCommitRecoveryRunCount',
            width: 130,
            align: 'right',
            tooltip:
                'Runs where one commit both failed and passed an owned test (a re-run went green, or an in-job retry recovered it). This is what proves a flake.',
            sorter: (a, b) => a.sameCommitRecoveryRunCount - b.sameCommitRecoveryRunCount,
            render: (_, row) => (
                <CountWithPrior current={row.sameCommitRecoveryRunCount} prior={row.sameCommitRecoveryRunCountPrior} />
            ),
        },
        {
            title: 'PRs merged',
            key: 'mergedPrCount',
            width: 110,
            align: 'right',
            tooltip:
                "PRs merged by this team's members in the window, bots excluded. Attribution comes from the GitHub team membership snapshot; teams are never ranked by author.",
            sorter: (a, b) => (a.mergedPrCount ?? -1) - (b.mergedPrCount ?? -1),
            render: (_, row) => <CountWithPrior current={row.mergedPrCount} prior={row.mergedPrCountPrior} />,
        },
    ]

    return (
        <div className="flex flex-col gap-4">
            <ScopeBar repoSlot={<SourceScopeChip />} showDate={false} />
            <div className="flex items-start justify-between gap-2">
                <div className="flex flex-col gap-0.5">
                    <h3 className="m-0 flex items-center gap-1.5 text-base font-semibold">
                        <IconPeople className="text-lg" />
                        Team CI health
                    </h3>
                    <p className="m-0 text-xs text-tertiary">
                        The CI test surfaces each team owns (flaky tests and failures), with the previous window for
                        comparison. Ownership comes from the repo's owners.yaml files, never from authorship.
                    </p>
                </div>
                <DateFilter
                    dateFrom={teamsWindow}
                    onChange={(from) => isTeamsWindow(from) && setTeamsWindow(from)}
                    dateOptions={TEAMS_WINDOW_DATE_OPTIONS}
                    size="small"
                />
            </div>
            <LemonTable
                data-attr="engineering-analytics-teams-table"
                size="small"
                columns={columns}
                dataSource={teams?.rows ?? []}
                rowKey={(row) => row.ownerTeam}
                rowClassName="cursor-pointer"
                onRow={(row) => rowNavigationProps(detailUrlOf(row.ownerTeam, teamsWindow, sourceId))}
                loading={teamsLoading}
                pagination={{ pageSize: 10 }}
                useURLForSorting={false}
                emptyState="No team-attributed CI signal in this window. Signal appears once CI emits test spans with ownership stamps."
                nouns={['team', 'teams']}
            />
            {teams?.truncated && (
                <div className="text-xs text-tertiary">
                    Showing the {teams.limit} teams with the most signal. More teams qualified in this window.
                </div>
            )}
        </div>
    )
}
