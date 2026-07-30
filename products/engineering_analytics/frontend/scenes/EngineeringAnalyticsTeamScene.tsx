import { useActions, useValues } from 'kea'

import { IconPeople } from '@posthog/icons'
import { LemonTable, LemonTableColumns, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'
import { TimeSeriesLineChart, useChartTheme } from '@posthog/quill-charts'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { EntityHeader } from '../components/EntityHeader'
import { CountWithDelta } from '../components/MetricTile'
import { Section } from '../components/Section'
import { compactHoursLabel } from '../lib/format'
import { TeamDetailLogicProps, TeamTestSignalRow, teamDetailLogic } from './teamDetailLogic'
import { TEAMS_WINDOW_DATE_OPTIONS, TEAMS_WINDOW_LABELS, UNOWNED_TEAM, isTeamsWindow } from './teamsLogic'

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
    const { activity, activityLoading, mergeTrend, mergeTrendLoading, mergeTrendSeries, window, ownerTeam } =
        useValues(teamDetailLogic)
    const { setWindow } = useActions(teamDetailLogic)
    const { timezone } = useValues(teamLogic)
    const chartTheme = useChartTheme()

    const labels = TEAMS_WINDOW_LABELS[window]
    const isUnowned = ownerTeam === UNOWNED_TEAM

    const testColumns: LemonTableColumns<TeamTestSignalRow> = [
        {
            title: 'Test',
            key: 'nodeid',
            render: (_, row) => (
                <Tooltip title={row.selector}>
                    <span className="truncate font-mono text-xs">{row.nodeid}</span>
                </Tooltip>
            ),
        },
        {
            title: labels.prior,
            key: 'signalCountPrior',
            width: 140,
            align: 'right',
            sorter: (a, b) => a.signalCountPrior - b.signalCountPrior,
            render: (_, row) => <span className="tabular-nums">{humanFriendlyNumber(row.signalCountPrior)}</span>,
        },
        {
            title: labels.current,
            key: 'signalCount',
            width: 140,
            align: 'right',
            sorter: (a, b) => a.signalCount - b.signalCount,
            render: (_, row) => <CountWithDelta current={row.signalCount} prior={row.signalCountPrior} />,
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
        <SceneContent>
            <SceneTitleSection name="Team CI health" resourceType={{ type: 'health' }} />
            <div className="flex items-start justify-between gap-3">
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
                    slug={
                        <>
                            <Link to={urls.engineeringAnalyticsTeams()}>← All teams</Link>
                            {!isUnowned && <span>owner: {ownerTeam}</span>}
                        </>
                    }
                />
                <DateFilter
                    dateFrom={window}
                    onChange={(from) => isTeamsWindow(from) && setWindow(from)}
                    dateOptions={TEAMS_WINDOW_DATE_OPTIONS}
                    size="small"
                />
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

            <Section id="team-tests" title="Owned tests with signal" busy={activityLoading}>
                <LemonTable
                    data-attr="engineering-analytics-team-tests-table"
                    size="small"
                    columns={testColumns}
                    dataSource={activity?.tests ?? []}
                    rowKey={(row) => row.nodeid}
                    loading={activityLoading}
                    pagination={{ pageSize: 25 }}
                    useURLForSorting={false}
                    emptyState="No owned tests with signal in this window."
                    nouns={['test', 'tests']}
                />
                {activity?.truncatedTests && (
                    <div className="mt-2 text-xs text-tertiary">
                        Showing the strongest signals. More owned tests had signal in this window.
                    </div>
                )}
            </Section>
        </SceneContent>
    )
}

export default EngineeringAnalyticsTeamScene
