import { useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconPeople } from '@posthog/icons'
import { LemonTable, LemonTableColumns, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { CountCell } from '../components/CountCell'
import { ScopeBar, SourceScopeChip } from '../components/ScopeBar'
import { rowNavigationProps } from '../lib/rowNavigation'
import { DEFAULT_TEAMS_WINDOW, TEAMS_WINDOW_LABELS, TeamCIHealthRow, UNOWNED_TEAM, teamsLogic } from './teamsLogic'

const FIXED_WINDOW = TEAMS_WINDOW_LABELS[DEFAULT_TEAMS_WINDOW].current.toLowerCase()

/** The team's detail page, carrying the active source so it opens scoped the same. */
function detailUrlOf(ownerTeam: string, sourceId: string | null): string {
    return combineUrl(urls.engineeringAnalyticsTeam(ownerTeam), sourceId ? { source: sourceId } : {}).url
}

export function EngineeringAnalyticsTeams(): JSX.Element {
    const { teams, teamsLoading, sourceId } = useValues(teamsLogic)

    const columns: LemonTableColumns<TeamCIHealthRow> = [
        {
            title: 'Team',
            key: 'ownerTeam',
            sorter: (a, b) => a.ownerTeam.localeCompare(b.ownerTeam),
            render: (_, row) =>
                row.ownerTeam === UNOWNED_TEAM ? (
                    <div className="flex items-center gap-2">
                        <Link
                            to={detailUrlOf(row.ownerTeam, sourceId)}
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
                        to={detailUrlOf(row.ownerTeam, sourceId)}
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
            width: 120,
            align: 'right',
            tooltip: 'Test files this team owns per the daily owners.yaml census.',
            sorter: (a, b) => (a.testFileCount ?? -1) - (b.testFileCount ?? -1),
            render: (_, row) => <CountCell value={row.testFileCount} />,
        },
        {
            title: 'Flaky tests',
            key: 'flakyTestCount',
            width: 120,
            align: 'right',
            tooltip: `Owned tests one commit was seen both failing and passing in the ${FIXED_WINDOW}. Only tests with that recovery proof count as flaky.`,
            sorter: (a, b) => a.flakyTestCount - b.flakyTestCount,
            render: (_, row) => <CountCell value={row.flakyTestCount} />,
        },
        {
            title: 'Regressions',
            key: 'regressionTestCount',
            width: 120,
            align: 'right',
            tooltip: `Owned tests that failed in the ${FIXED_WINDOW} with no recorded recovery and still hit several PRs or master. Treat as real breaks until a recovery proves otherwise.`,
            sorter: (a, b) => a.regressionTestCount - b.regressionTestCount,
            render: (_, row) => <CountCell value={row.regressionTestCount} />,
        },
    ]

    return (
        <div className="flex flex-col gap-4">
            <ScopeBar repoSlot={<SourceScopeChip />} showDate={false} />
            <h3 className="m-0 flex items-center gap-1.5 text-base font-semibold">
                <IconPeople className="text-lg" />
                Team CI health
            </h3>
            <LemonTable
                data-attr="engineering-analytics-teams-table"
                size="small"
                columns={columns}
                dataSource={teams?.rows ?? []}
                rowKey={(row) => row.ownerTeam}
                rowClassName="cursor-pointer"
                onRow={(row) => rowNavigationProps(detailUrlOf(row.ownerTeam, sourceId))}
                loading={teamsLoading}
                pagination={{ pageSize: 20 }}
                useURLForSorting={false}
                emptyState="No team-attributed CI signal yet. Signal appears once CI emits test spans with ownership stamps."
                nouns={['team', 'teams']}
            />
            {teams?.truncated && (
                <div className="text-xs text-tertiary">
                    Showing the {teams.limit} teams with the most signal. More teams qualified.
                </div>
            )}
        </div>
    )
}
