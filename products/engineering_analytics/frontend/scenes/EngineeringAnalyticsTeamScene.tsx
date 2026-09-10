import { useActions, useValues } from 'kea'

import { IconPeople } from '@posthog/icons'
import { LemonTable, LemonTableColumns, LemonTag, Tooltip } from '@posthog/lemon-ui'
import { TimeSeriesLineChart, useChartTheme } from '@posthog/quill-charts'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { CountCell } from '../components/CountCell'
import { EntityHeader } from '../components/EntityHeader'
import { RepoScopeChip, ScopeBar } from '../components/ScopeBar'
import { ScopePanel } from '../components/ScopePanel'
import { Section } from '../components/Section'
import { TestIdCell } from '../components/TestIdCell'
import { WindowComparisonCard } from '../components/WindowComparisonCard'
import { compactHoursLabel } from '../lib/format'
import { githubFileUrl } from '../lib/github'
import { engineeringAnalyticsLogic } from './engineeringAnalyticsLogic'
import { TeamDetailLogicProps, TeamTestSignalRow, teamDetailLogic } from './teamDetailLogic'
import {
    DEFAULT_TEAMS_WINDOW,
    TEAMS_WINDOW_DATE_OPTIONS,
    TEAMS_WINDOW_LABELS,
    UNOWNED_TEAM,
    isTeamsWindow,
} from './teamsLogic'

export const scene: SceneExport<TeamDetailLogicProps> = {
    component: EngineeringAnalyticsTeamScene,
    logic: teamDetailLogic,
    paramsToProps: ({ params: { ownerTeam }, searchParams: { source, window } }) => ({
        ownerTeam: decodeURIComponent(ownerTeam ?? ''),
        sourceId: source ?? null,
        window: isTeamsWindow(window) ? window : null,
    }),
}

export function EngineeringAnalyticsTeamScene(): JSX.Element {
    const {
        activity,
        activityLoading,
        healthRow,
        healthRowLoading,
        mergeTrend,
        mergeTrendLoading,
        mergeTrendSeries,
        window,
        ownerTeam,
    } = useValues(teamDetailLogic)
    const { setWindow } = useActions(teamDetailLogic)
    const { activeSource } = useValues(engineeringAnalyticsLogic)
    const { timezone } = useValues(teamLogic)
    const repository = activeSource?.repo ?? null
    const chartTheme = useChartTheme()

    const isUnowned = ownerTeam === UNOWNED_TEAM

    const testColumns: LemonTableColumns<TeamTestSignalRow> = [
        {
            title: 'Test',
            key: 'nodeid',
            className: 'w-full max-w-0',
            render: (_, row) => {
                const file = row.selector.split('::')[0]
                return (
                    <TestIdCell
                        nodeid={row.nodeid}
                        url={repository && file ? githubFileUrl(repository, file) : null}
                        tooltip={row.selector}
                    />
                )
            },
        },
        {
            title: 'Runner',
            key: 'runner',
            width: 90,
            render: (_, row) => row.runner,
        },
        {
            title: TEAMS_WINDOW_LABELS[DEFAULT_TEAMS_WINDOW].current,
            key: 'signalCount',
            width: 140,
            align: 'right',
            tooltip:
                'Runs where this test failed, errored, or a retry recovered it. Fixed window; the picker above does not move this list.',
            sorter: (a, b) => a.signalCount - b.signalCount,
            render: (_, row) => <CountCell value={row.signalCount} />,
        },
        {
            title: 'Last seen',
            key: 'lastSeenAt',
            width: 110,
            align: 'right',
            render: (_, row) => (
                <span className="text-xs whitespace-nowrap text-secondary">
                    <TZLabel time={row.lastSeenAt} />
                </span>
            ),
        },
    ]

    return (
        <SceneContent className="pb-16">
            <SceneTitleSection name="Team CI health" resourceType={{ type: 'health' }} />
            <EntityHeader
                icon={<IconPeople />}
                title={isUnowned ? 'Unowned surfaces' : ownerTeam}
                titleSuffix={
                    isUnowned ? (
                        <Tooltip title="Tests whose CI spans carry no ownership stamp. An ownership gap to close, not a real team.">
                            <LemonTag type="warning">ownership gap</LemonTag>
                        </Tooltip>
                    ) : undefined
                }
                slug={null}
            />
            <ScopeBar
                repoSlot={<RepoScopeChip label={repository ?? 'repository'} to={urls.engineeringAnalytics()} />}
                crumbs={[
                    { label: 'teams', to: urls.engineeringAnalyticsTeams() },
                    { label: isUnowned ? 'unowned' : ownerTeam },
                ]}
                showDate={false}
            />

            <ScopePanel
                busy={healthRowLoading || mergeTrendLoading}
                controls={
                    <DateFilter
                        dateFrom={window}
                        onChange={(from) => isTeamsWindow(from) && setWindow(from)}
                        dateOptions={TEAMS_WINDOW_DATE_OPTIONS}
                        size="small"
                    />
                }
            >
                <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                    <WindowComparisonCard
                        title="Tests owned"
                        tooltip="Test files this team owns per the daily owners.yaml census."
                        value={healthRow?.testFileCount}
                        previousValue={healthRow?.testFileCountPrior}
                        formatValue={humanFriendlyNumber}
                        loading={healthRowLoading}
                        emptyText="No census yet for this repository."
                    />
                    <WindowComparisonCard
                        title="Flaky tests"
                        tooltip="Owned tests one commit was seen both failing and passing in this window. Only tests with that recovery proof count as flaky."
                        value={healthRow?.flakyTestCount}
                        previousValue={healthRow?.flakyTestCountPrior}
                        formatValue={humanFriendlyNumber}
                        goodWhenDown
                        loading={healthRowLoading}
                        emptyText="No signal in this window."
                    />
                    <WindowComparisonCard
                        title="Failed runs"
                        tooltip="CI runs where an owned test failed or errored. Absolute counts, not rates: passing runs are mostly not recorded."
                        value={healthRow?.failedRunCount}
                        previousValue={healthRow?.failedRunCountPrior}
                        formatValue={humanFriendlyNumber}
                        goodWhenDown
                        loading={healthRowLoading}
                        emptyText="No signal in this window."
                    />
                    {!isUnowned && (
                        <WindowComparisonCard
                            title="PRs merged"
                            tooltip="PRs merged by this team's members in the window, bots excluded. Attribution comes from the GitHub team membership snapshot."
                            value={healthRow?.mergedPrCount}
                            previousValue={healthRow?.mergedPrCountPrior}
                            formatValue={humanFriendlyNumber}
                            loading={healthRowLoading}
                            emptyText="No team membership data. Sync the GitHub source's team_members endpoint to attribute merges."
                        />
                    )}
                </div>

                {!isUnowned && (
                    <Section id="team-merge-trend" title="Time to merge" busy={mergeTrendLoading}>
                        {mergeTrendSeries ? (
                            // Flex column: the quill chart root is flex-1 and only gets height from a flex parent.
                            <div className="flex h-48 w-full flex-col">
                                <TimeSeriesLineChart
                                    series={[
                                        { key: 'median', label: 'Median', data: mergeTrendSeries.median },
                                        { key: 'average', label: 'Average', data: mergeTrendSeries.average },
                                    ]}
                                    labels={mergeTrendSeries.labels}
                                    theme={chartTheme}
                                    config={{
                                        xAxis: { timezone, interval: 'day' },
                                        yAxis: { format: 'duration' },
                                        tooltip: { valueFormatter: (value) => compactHoursLabel(value) },
                                        legend: { show: true },
                                    }}
                                />
                            </div>
                        ) : mergeTrend && !mergeTrend.hasMembershipData ? (
                            <div className="flex h-32 items-center text-xs text-secondary">
                                No team membership data. Sync the GitHub source's team_members endpoint (needs the org
                                Members read grant) to attribute merges to teams.
                            </div>
                        ) : (
                            <div className="flex h-32 items-center text-xs text-secondary">
                                No merged PRs in this window.
                            </div>
                        )}
                    </Section>
                )}
            </ScopePanel>

            <Section id="team-tests" title="Owned tests with signal" busy={activityLoading}>
                <LemonTable
                    data-attr="engineering-analytics-team-tests-table"
                    size="small"
                    columns={testColumns}
                    dataSource={activity?.tests ?? []}
                    rowKey={(row) => `${row.runner}:${row.nodeid}`}
                    loading={activityLoading}
                    pagination={{ pageSize: 25 }}
                    useURLForSorting={false}
                    emptyState="No owned tests with signal."
                    nouns={['test', 'tests']}
                />
                {activity?.truncatedTests && (
                    <div className="mt-2 text-xs text-tertiary">
                        Showing the strongest signals. More owned tests had signal.
                    </div>
                )}
            </Section>
        </SceneContent>
    )
}

export default EngineeringAnalyticsTeamScene
