import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconPeople } from '@posthog/icons'
import { LemonTable, LemonTableColumns, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { urls } from 'scenes/urls'

import { CountWithDelta } from '../components/MetricTile'
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
            title: 'Flaky tests',
            key: 'flakyTestCount',
            width: 140,
            align: 'right',
            tooltip:
                'Owned tests meeting the flaky-leaderboard bar in this window (passed on retry, or failed across several distinct PRs), vs the previous window.',
            sorter: (a, b) => a.flakyTestCount - b.flakyTestCount,
            render: (_, row) => <CountWithDelta current={row.flakyTestCount} prior={row.flakyTestCountPrior} />,
        },
        {
            title: 'Failures',
            key: 'failedCount',
            width: 130,
            align: 'right',
            tooltip:
                'Failed or errored runs on owned tests. Absolute counts, not rates: passing runs are mostly not recorded.',
            sorter: (a, b) => a.failedCount - b.failedCount,
            render: (_, row) => <CountWithDelta current={row.failedCount} prior={row.failedCountPrior} />,
        },
        {
            title: 'Pass on retry',
            key: 'rerunPassedCount',
            width: 130,
            align: 'right',
            tooltip: 'Failed, then passed on an automatic retry. The strongest flaky signal.',
            sorter: (a, b) => a.rerunPassedCount - b.rerunPassedCount,
            render: (_, row) => <CountWithDelta current={row.rerunPassedCount} prior={row.rerunPassedCountPrior} />,
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
                        The CI test surfaces each team owns (flaky tests and failures), with the change vs the previous
                        window. Ownership comes from the repo's ownership map, never from authorship.
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
                pagination={{ pageSize: 25 }}
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
