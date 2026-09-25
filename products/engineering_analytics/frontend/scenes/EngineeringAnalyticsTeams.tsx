import { useActions, useValues } from 'kea'

import { LemonTable, LemonTableColumns, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { CIAnalyticsLoadError } from '../components/CIAnalyticsLoadError'
import { ConnectGitHubSource } from '../components/ConnectGitHubSource'
import { CountCell } from '../components/CountCell'
import { ScopeBar, SourceScopeChip } from '../components/ScopeBar'
import { Section } from '../components/Section'
import { timesTypical } from '../lib/format'
import { rowNavigationProps } from '../lib/rowNavigation'
import { withCurrentScope } from '../lib/scope'
import { authorFrictionLogic } from './authorFrictionLogic'
import { DEFAULT_TEAMS_WINDOW, TEAMS_WINDOW_LABELS, TeamCIHealthRow, UNOWNED_TEAM, teamsLogic } from './teamsLogic'

const FIXED_WINDOW = TEAMS_WINDOW_LABELS[DEFAULT_TEAMS_WINDOW].current.toLowerCase()

/** The team's detail page, carrying the current scope so it opens scoped the same. */
function detailUrlOf(ownerTeam: string, sourceId: string | null): string {
    return withCurrentScope(urls.engineeringAnalyticsTeam(ownerTeam), sourceId)
}

export function EngineeringAnalyticsTeams(): JSX.Element {
    const { teams, teamsFailed, teamsLoading, teamsNotConnected, sourceId } = useValues(teamsLogic)
    const { loadTeams } = useActions(teamsLogic)
    const { friction } = useValues(authorFrictionLogic)
    const medianFriction = new Map((friction?.teams ?? []).map((team) => [team.github_team, team.median_score]))

    // A dash would read as too few scored members, so without friction data or memberships the column stays out.
    const frictionColumns: LemonTableColumns<TeamCIHealthRow> =
        friction?.available && friction.has_membership_data
            ? [
                  {
                      title: 'Friction',
                      key: 'friction',
                      width: 100,
                      align: 'right',
                      tooltip: `Median friction of the team's members over the last ${friction?.window_days ?? 30} days, as a multiple of the typical author. Shown for teams with at least 3 members who have a score.`,
                      sorter: (a, b) =>
                          (medianFriction.get(a.ownerTeam) ?? -1) - (medianFriction.get(b.ownerTeam) ?? -1),
                      render: (_, row) => (
                          <span className="tabular-nums">
                              {medianFriction.has(row.ownerTeam)
                                  ? timesTypical(medianFriction.get(row.ownerTeam))
                                  : '–'}
                          </span>
                      ),
                  },
              ]
            : []

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
        ...frictionColumns,
        {
            title: 'Test files',
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
            tooltip: `Owned tests one commit was seen both failing and passing in the ${FIXED_WINDOW}. Only tests with that recovery proof count as flaky. A job attempt with 100+ failed or errored tests is a CI setup break, not test proof.`,
            sorter: (a, b) => a.flakyTestCount - b.flakyTestCount,
            render: (_, row) => <CountCell value={row.flakyTestCount} />,
        },
        {
            title: 'Regressions',
            key: 'regressionTestCount',
            width: 120,
            align: 'right',
            tooltip: `Owned tests that failed in the ${FIXED_WINDOW} with no recorded recovery and still hit several PRs or master. Failures from a CI setup break are left out. Treat as real breaks until a recovery proves otherwise.`,
            sorter: (a, b) => a.regressionTestCount - b.regressionTestCount,
            render: (_, row) => <CountCell value={row.regressionTestCount} />,
        },
    ]

    if (teamsNotConnected) {
        return <ConnectGitHubSource />
    }

    return (
        <div className="flex flex-col gap-4">
            <ScopeBar repoSlot={<SourceScopeChip />} showDate={false} />
            <Section id="team-ci-health" title="Owned tests by team">
                {teamsFailed ? (
                    <CIAnalyticsLoadError onRetry={loadTeams} loading={teamsLoading} />
                ) : (
                    <div className="flex flex-col gap-2">
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
                )}
            </Section>
        </div>
    )
}
