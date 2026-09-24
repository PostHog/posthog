import { useActions, useValues } from 'kea'

import { IconPeople } from '@posthog/icons'
import { LemonBanner, LemonSkeleton, LemonTable, LemonTableColumns, LemonTag, Tooltip } from '@posthog/lemon-ui'
import { TimeSeriesLineChart, useChartTheme } from '@posthog/quill-charts'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { CIAnalyticsLoadError } from '../components/CIAnalyticsLoadError'
import { ConnectGitHubSource } from '../components/ConnectGitHubSource'
import { CountCell } from '../components/CountCell'
import { EntityHeader } from '../components/EntityHeader'
import { RepoScopeChip, ScopeBar, ScopeDateFilter } from '../components/ScopeBar'
import { ScopePanel } from '../components/ScopePanel'
import { Section } from '../components/Section'
import { TeamQuarantinedTestsTable } from '../components/TeamQuarantinedTestsTable'
import { TestIdCell } from '../components/TestIdCell'
import { WindowComparisonCard } from '../components/WindowComparisonCard'
import { compactHoursLabel } from '../lib/format'
import { githubFileUrl } from '../lib/github'
import { withCurrentScope } from '../lib/scope'
import { engineeringAnalyticsLogic } from './engineeringAnalyticsLogic'
import { TeamDeliveryPanel } from './TeamDeliveryPanel'
import { TeamDetailLogicProps, TeamTestSignalRow, teamDetailLogic } from './teamDetailLogic'
import { DEFAULT_TEAMS_WINDOW, TEAMS_WINDOW_DATE_OPTIONS, TEAMS_WINDOW_LABELS, UNOWNED_TEAM } from './teamsLogic'

export const scene: SceneExport<TeamDetailLogicProps> = {
    component: EngineeringAnalyticsTeamScene,
    logic: teamDetailLogic,
    paramsToProps: ({ params: { ownerTeam }, searchParams: { source } }) => ({
        ownerTeam: decodeURIComponent(ownerTeam ?? ''),
        sourceId: source ?? null,
    }),
}

export function EngineeringAnalyticsTeamScene(): JSX.Element {
    const {
        activity,
        activityLoading,
        activityStatus,
        healthRow,
        healthRowLoading,
        healthRowStatus,
        mergeTrend,
        mergeTrendLoading,
        mergeTrendStatus,
        mergeTrendSeries,
        ownerTeam,
        deliveryScope,
        sourceId,
        quarantinedTests,
    } = useValues(teamDetailLogic)
    const { loadActivity, loadHealthRow, loadMergeTrend } = useActions(teamDetailLogic)
    const { activeSource, trunkQuarantine, trunkQuarantineLoading, trunkQuarantineStatus } =
        useValues(engineeringAnalyticsLogic)
    const { loadTrunkQuarantine } = useActions(engineeringAnalyticsLogic)
    const { timezone } = useValues(teamLogic)
    const repository = activeSource?.repo ?? null
    const chartTheme = useChartTheme()

    const isUnowned = ownerTeam === UNOWNED_TEAM
    const mainDataNotConnected = [activityStatus, healthRowStatus, mergeTrendStatus].includes('notConnected')
    const hubUrl = withCurrentScope(urls.engineeringAnalytics(), sourceId)
    const teamsUrl = withCurrentScope(urls.engineeringAnalyticsTeams(), sourceId)

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
                'Runs where this test failed, errored, or a retry recovered it. Failures from a CI setup break are left out. Fixed window; the picker above does not move this list.',
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

    const windowControls = <ScopeDateFilter dateOptions={TEAMS_WINDOW_DATE_OPTIONS} />
    const windowBusy = healthRowLoading || mergeTrendLoading
    const windowedSections = (
        <>
            {healthRowStatus === 'error' ? (
                <CIAnalyticsLoadError onRetry={loadHealthRow} loading={healthRowLoading} />
            ) : (
                <div className="grid grid-cols-1 gap-2 @2xl/main-content:grid-cols-2">
                    <WindowComparisonCard
                        title="Test files owned"
                        tooltip="Test files this team owns per the daily owners.yaml census."
                        value={healthRow?.testFileCount}
                        previousValue={healthRow?.testFileCountPrior}
                        formatValue={humanFriendlyNumber}
                        loading={healthRowLoading}
                        emptyText="No census yet for this repository."
                    />
                    <WindowComparisonCard
                        title="Flaky tests"
                        tooltip="Owned tests one commit was seen both failing and passing in this window. Only tests with that recovery proof count as flaky. A job attempt with 100+ failed or errored tests is a CI setup break, not test proof."
                        value={healthRow?.flakyTestCount}
                        previousValue={healthRow?.flakyTestCountPrior}
                        formatValue={humanFriendlyNumber}
                        goodWhenDown
                        loading={healthRowLoading}
                        emptyText="No signal in this window."
                    />
                    <WindowComparisonCard
                        title="Failed runs"
                        tooltip="CI runs where at least one test this team owns failed or errored. A run counts once, however many tests failed. CI setup breaks (many jobs or teams, or 100 or more failed or errored tests in one job) are left out. Absolute counts, not rates: passing runs are mostly not recorded."
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
            )}

            {!isUnowned && (
                <Section id="team-merge-trend" title="Time to merge" busy={mergeTrendLoading && !!mergeTrend}>
                    {mergeTrendStatus === 'error' ? (
                        <CIAnalyticsLoadError onRetry={loadMergeTrend} loading={mergeTrendLoading} />
                    ) : mergeTrendLoading && !mergeTrend ? (
                        <LemonSkeleton className="h-48 w-full" />
                    ) : mergeTrendSeries ? (
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
                                    yAxis: { tickFormatter: compactHoursLabel },
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
        </>
    )

    return (
        <SceneContent className="pb-16">
            <SceneTitleSection name="Team" resourceType={{ type: 'health' }} />
            <ScopeBar
                repoSlot={<RepoScopeChip label={repository ?? 'repository'} to={hubUrl} />}
                crumbs={[{ label: 'teams', to: teamsUrl }, { label: isUnowned ? 'unowned' : ownerTeam }]}
                showDate={false}
            />
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

            {mainDataNotConnected ? (
                <ConnectGitHubSource />
            ) : (
                <>
                    {deliveryScope ? (
                        <TeamDeliveryPanel
                            scope={deliveryScope}
                            sourceId={sourceId}
                            busy={windowBusy}
                            controls={windowControls}
                        >
                            {windowedSections}
                        </TeamDeliveryPanel>
                    ) : (
                        <ScopePanel busy={windowBusy} controls={windowControls}>
                            {windowedSections}
                        </ScopePanel>
                    )}

                    <Section id="team-tests" title="Owned tests with signal" busy={activityLoading && !!activity}>
                        {activityStatus === 'error' ? (
                            <CIAnalyticsLoadError onRetry={loadActivity} loading={activityLoading} />
                        ) : (
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
                        )}
                        {activity?.truncatedTests && (
                            <div className="mt-2 text-xs text-tertiary">
                                Showing the strongest signals. More owned tests had signal.
                            </div>
                        )}
                    </Section>

                    <Section
                        id="team-quarantined-tests"
                        title="Quarantined tests"
                        busy={trunkQuarantineLoading && !!trunkQuarantine}
                    >
                        {trunkQuarantineStatus === 'error' ? (
                            <CIAnalyticsLoadError
                                title="Couldn't load quarantined tests"
                                description="Loading Trunk quarantine data failed. Retry, or check the source's sync status."
                                onRetry={loadTrunkQuarantine}
                                loading={trunkQuarantineLoading}
                            />
                        ) : trunkQuarantineLoading && !trunkQuarantine ? (
                            <LemonSkeleton className="h-32 w-full" />
                        ) : trunkQuarantineStatus === 'notConnected' || !trunkQuarantine?.available ? (
                            <div className="py-8 text-center text-sm text-secondary">
                                No Trunk source is connected. Connect the Trunk.io data warehouse source to see this
                                team's quarantined tests.
                            </div>
                        ) : !trunkQuarantine.ownersResolved ? (
                            <LemonBanner type="warning">
                                We could not read {trunkQuarantine.repository}'s ownership files, so quarantined tests
                                can't be matched to teams. Try again in a few minutes.
                            </LemonBanner>
                        ) : (
                            <>
                                <TeamQuarantinedTestsTable
                                    tests={quarantinedTests}
                                    ttlDays={trunkQuarantine.ttlDays}
                                    repository={trunkQuarantine.repository}
                                    loading={trunkQuarantineLoading}
                                />
                                {trunkQuarantine.truncated && (
                                    <div className="mt-2 text-xs text-tertiary">
                                        Showing quarantined tests from the oldest {trunkQuarantine.limit} in the
                                        repository. This team may have more.
                                    </div>
                                )}
                            </>
                        )}
                    </Section>
                </>
            )}
        </SceneContent>
    )
}

export default EngineeringAnalyticsTeamScene
