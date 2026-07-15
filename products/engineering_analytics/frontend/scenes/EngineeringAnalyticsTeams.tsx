import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconPeople } from '@posthog/icons'
import { LemonSegmentedButton, LemonTable, LemonTableColumns, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { newInternalTab } from 'lib/utils/newInternalTab'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { DeltaBadge, percentChange } from '../components/MetricTile'
import { ScopeBar, SourceScopeChip } from '../components/ScopeBar'
import { TeamCIHealthRow, TeamsWindow, UNOWNED_TEAM, teamsLogic } from './teamsLogic'

/** Current count + delta vs the prior window, the roster's core comparison cell. */
function CountWithDelta({
    current,
    prior,
    goodWhenDown = true,
}: {
    current: number
    prior: number
    goodWhenDown?: boolean
}): JSX.Element {
    return (
        <div className="flex items-baseline justify-end gap-1.5">
            <span className="text-sm font-semibold tabular-nums">{humanFriendlyNumber(current)}</span>
            {prior > 0 ? (
                <DeltaBadge value={percentChange(current, prior)} goodWhenDown={goodWhenDown} />
            ) : current > 0 ? (
                <Tooltip title="No signal in the previous window. This is new.">
                    <span className="text-xs font-semibold whitespace-nowrap text-danger">new</span>
                </Tooltip>
            ) : null}
        </div>
    )
}

export function EngineeringAnalyticsTeams(): JSX.Element {
    const { teams, teamsLoading, teamsWindow } = useValues(teamsLogic)
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
                            to={urls.engineeringAnalyticsTeam(row.ownerTeam)}
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
                        to={urls.engineeringAnalyticsTeam(row.ownerTeam)}
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
                'Owned tests meeting the flaky-leaderboard bar in this window (passed on retry, or failed on 3+ distinct PRs), vs the previous window.',
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
                <LemonSegmentedButton
                    size="small"
                    value={teamsWindow}
                    onChange={(value) => setTeamsWindow(value as TeamsWindow)}
                    options={[
                        { value: '-24h', label: '1d' },
                        { value: '-7d', label: '7d' },
                        { value: '-14d', label: '14d' },
                        { value: '-30d', label: '30d' },
                    ]}
                />
            </div>
            <LemonTable
                data-attr="engineering-analytics-teams-table"
                size="small"
                columns={columns}
                dataSource={teams?.rows ?? []}
                rowKey={(row) => row.ownerTeam}
                rowClassName="cursor-pointer"
                onRow={(row) => {
                    const url = urls.engineeringAnalyticsTeam(row.ownerTeam)
                    return {
                        // Inner links (the team name) keep their own behavior.
                        onClick: (e: React.MouseEvent) => {
                            if ((e.target as HTMLElement).closest('a, button')) {
                                return
                            }
                            if (e.metaKey || e.ctrlKey) {
                                e.preventDefault()
                                newInternalTab(url)
                            } else {
                                router.actions.push(url)
                            }
                        },
                        onAuxClick: (e: React.MouseEvent) => {
                            if (e.button === 1 && !(e.target as HTMLElement).closest('a, button')) {
                                e.preventDefault()
                                newInternalTab(url)
                            }
                        },
                    }
                }}
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
