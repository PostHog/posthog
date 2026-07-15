import { useActions, useValues } from 'kea'

import { IconPeople } from '@posthog/icons'
import {
    LemonBanner,
    LemonSegmentedButton,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { EntityHeader } from '../components/EntityHeader'
import { DeltaBadge, MetricTile, percentChange } from '../components/MetricTile'
import { Section } from '../components/Section'
import { TeamTestSlopeChart } from '../components/TeamTestSlopeChart'
import { TeamDailyPoint, TeamDetailLogicProps, TeamTestSignalRow, teamDetailLogic } from './teamDetailLogic'
import { TeamsWindow, UNOWNED_TEAM } from './teamsLogic'

// The two merge-trend lines, defined once for the series and the static legend (identity is
// never color-alone). The team line carries the accent; the repo baseline stays muted context.
const MERGE_SERIES = [
    { label: 'This team', color: 'data-color-1', colorVar: 'var(--data-color-1)' },
    { label: 'Repo baseline', color: 'muted', colorVar: 'var(--muted)' },
]

export const scene: SceneExport<TeamDetailLogicProps> = {
    component: EngineeringAnalyticsTeamScene,
    logic: teamDetailLogic,
    paramsToProps: ({ params: { ownerTeam } }) => ({ ownerTeam: decodeURIComponent(ownerTeam ?? '') }),
}

const WINDOW_LABELS: Record<TeamsWindow, { prior: string; current: string }> = {
    '-24h': { prior: 'Previous 24 hours', current: 'Last 24 hours' },
    '-7d': { prior: 'Previous 7 days', current: 'Last 7 days' },
    '-14d': { prior: 'Previous 14 days', current: 'Last 14 days' },
    '-30d': { prior: 'Previous 30 days', current: 'Last 30 days' },
}

// One definition for the daily chart's series and its static legend, so they can't drift.
// These are status colors used as status (a failure IS danger), not categorical identity.
const DAILY_SERIES: {
    label: string
    color: string
    colorVar: string
    pick: (d: TeamDailyPoint) => number
}[] = [
    { label: 'Failures', color: 'danger', colorVar: 'var(--danger)', pick: (d) => d.failedCount },
    { label: 'Pass on retry', color: 'warning', colorVar: 'var(--warning)', pick: (d) => d.rerunPassedCount },
    { label: 'Quarantined, still failing', color: 'muted', colorVar: 'var(--muted)', pick: (d) => d.xfailedCount },
]

export function EngineeringAnalyticsTeamScene(): JSX.Element {
    const {
        activity,
        activityLoading,
        rosterRow,
        rosterRowLoading,
        mergeTrend,
        mergeTrendLoading,
        filledMergePoints,
        filledDays,
        window,
        ownerTeam,
    } = useValues(teamDetailLogic)
    const { setWindow } = useActions(teamDetailLogic)

    const labels = WINDOW_LABELS[window]
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
            render: (_, row) => (
                <div className="flex items-baseline justify-end gap-1.5">
                    <span className="font-semibold tabular-nums">{humanFriendlyNumber(row.signalCount)}</span>
                    <DeltaBadge value={percentChange(row.signalCount, row.signalCountPrior)} goodWhenDown />
                </div>
            ),
        },
        {
            title: 'Last seen',
            key: 'lastSeenAt',
            width: 110,
            align: 'right',
            render: (_, row) => (
                <Tooltip title={dayjs(row.lastSeenAt).format('YYYY-MM-DD HH:mm:ss')}>
                    <span className="text-xs whitespace-nowrap text-secondary">{dayjs(row.lastSeenAt).fromNow()}</span>
                </Tooltip>
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
                <LemonSegmentedButton
                    size="small"
                    value={window}
                    onChange={(value) => setWindow(value as TeamsWindow)}
                    options={[
                        { value: '-24h', label: '1d' },
                        { value: '-7d', label: '7d' },
                        { value: '-14d', label: '14d' },
                        { value: '-30d', label: '30d' },
                    ]}
                />
            </div>

            <div className="flex flex-wrap gap-3">
                <MetricTile
                    label="Flaky tests"
                    tooltip="Owned tests meeting the flaky-leaderboard bar in this window: passed on retry, or failed on 3+ distinct PRs."
                    value={rosterRow ? humanFriendlyNumber(rosterRow.flakyTestCount) : '—'}
                    delta={
                        rosterRow
                            ? {
                                  value: percentChange(rosterRow.flakyTestCount, rosterRow.flakyTestCountPrior),
                                  goodWhenDown: true,
                              }
                            : undefined
                    }
                    loading={rosterRowLoading}
                />
                <MetricTile
                    label="Failures"
                    tooltip="Failed or errored runs on owned tests. Absolute counts: passing runs are mostly not recorded."
                    value={rosterRow ? humanFriendlyNumber(rosterRow.failedCount) : '—'}
                    delta={
                        rosterRow
                            ? {
                                  value: percentChange(rosterRow.failedCount, rosterRow.failedCountPrior),
                                  goodWhenDown: true,
                              }
                            : undefined
                    }
                    loading={rosterRowLoading}
                />
                <MetricTile
                    label="Pass on retry"
                    tooltip="Failed, then passed on an automatic retry. The strongest flaky signal."
                    value={rosterRow ? humanFriendlyNumber(rosterRow.rerunPassedCount) : '—'}
                    delta={
                        rosterRow
                            ? {
                                  value: percentChange(rosterRow.rerunPassedCount, rosterRow.rerunPassedCountPrior),
                                  goodWhenDown: true,
                              }
                            : undefined
                    }
                    loading={rosterRowLoading}
                />
                <MetricTile
                    label="Quarantined, still failing"
                    tooltip="Runs where an owned test failed while quarantined (xfail). Masked in CI, still flaky."
                    value={rosterRow ? humanFriendlyNumber(rosterRow.xfailedCount) : '—'}
                    delta={
                        rosterRow
                            ? {
                                  value: percentChange(rosterRow.xfailedCount, rosterRow.xfailedCountPrior),
                                  goodWhenDown: true,
                              }
                            : undefined
                    }
                    loading={rosterRowLoading}
                />
            </div>

            {!isUnowned && (
                <Section
                    id="team-merge-trend"
                    title="Time to merge"
                    note="Median open→merge of PRs merged by this team's members each day, beside the repo-wide median. Coarse timing (draft + review combined); bots excluded; team-level medians only."
                    busy={mergeTrendLoading}
                >
                    {filledMergePoints.length ? (
                        <div className="flex flex-col gap-2">
                            <div className="flex items-center gap-4 text-xs text-secondary">
                                {MERGE_SERIES.map(({ label, colorVar }) => (
                                    <span key={label} className="flex items-center gap-1.5">
                                        <span
                                            className="inline-block size-2 rounded-full"
                                            // eslint-disable-next-line react/forbid-dom-props
                                            style={{ backgroundColor: colorVar }}
                                        />
                                        {label}
                                    </span>
                                ))}
                            </div>
                            <Sparkline
                                className="h-32 w-full"
                                type="line"
                                data={[
                                    {
                                        name: MERGE_SERIES[0].label,
                                        color: MERGE_SERIES[0].color,
                                        // NaN gaps the line on days the team merged nothing — zero would read as instant merges.
                                        values: filledMergePoints.map((p) =>
                                            p.teamMedianSeconds !== null ? p.teamMedianSeconds / 3600 : NaN
                                        ),
                                    },
                                    {
                                        name: MERGE_SERIES[1].label,
                                        color: MERGE_SERIES[1].color,
                                        values: filledMergePoints.map((p) =>
                                            p.repoMedianSeconds !== null ? p.repoMedianSeconds / 3600 : NaN
                                        ),
                                    },
                                ]}
                                labels={filledMergePoints.map((p) => dayjs(p.day).format('MMM D'))}
                                renderLabel={(label) => label}
                                renderTooltipValue={(value) =>
                                    Number.isNaN(value) ? 'no merges' : `${humanFriendlyNumber(value, 1)} h`
                                }
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

            <Section
                id="team-trend"
                title="Daily signal"
                note={`Signal runs per day on owned tests over the ${labels.current.toLowerCase()}.`}
                busy={activityLoading}
            >
                {filledDays.length ? (
                    <div className="flex flex-col gap-2">
                        {/* Identity must never be color-alone: name the three stacked series statically,
                            not only in the hover tooltip. */}
                        <div className="flex items-center gap-4 text-xs text-secondary">
                            {DAILY_SERIES.map(({ label, colorVar }) => (
                                <span key={label} className="flex items-center gap-1.5">
                                    <span
                                        className="inline-block size-2 rounded-full"
                                        // eslint-disable-next-line react/forbid-dom-props
                                        style={{ backgroundColor: colorVar }}
                                    />
                                    {label}
                                </span>
                            ))}
                        </div>
                        <Sparkline
                            className="h-32 w-full"
                            data={DAILY_SERIES.map(({ label, color, pick }) => ({
                                name: label,
                                color,
                                values: filledDays.map(pick),
                            }))}
                            labels={filledDays.map((d) => dayjs(d.day).format('MMM D'))}
                            renderLabel={(label) => label}
                        />
                    </div>
                ) : (
                    <div className="flex h-32 items-center text-xs text-secondary">
                        No signal in this window. Nothing owned by this team flaked or failed.
                    </div>
                )}
            </Section>

            <Section
                id="team-slope"
                title="Before vs after, per test"
                note="Each line is one owned test's signal count, prior window → current window. Red slopes got worse."
                busy={activityLoading}
            >
                {activity?.tests.length ? (
                    <>
                        <TeamTestSlopeChart
                            items={activity.tests.map((t) => ({
                                label: t.nodeid,
                                tooltip: t.selector,
                                prior: t.signalCountPrior,
                                current: t.signalCount,
                            }))}
                            priorLabel={labels.prior}
                            currentLabel={labels.current}
                        />
                        {activity.truncatedTests && (
                            <div className="mt-2 text-xs text-tertiary">
                                Showing the strongest signals. More owned tests had signal in this window.
                            </div>
                        )}
                    </>
                ) : (
                    <div className="flex h-24 items-center text-xs text-secondary">
                        No owned tests with signal in either window.
                    </div>
                )}
            </Section>

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
            </Section>

            <LemonBanner type="info" dismissKey="engineering-analytics-team-detail-scope">
                Counts are absolute signal (failures and retries), never rates: fast passing runs are not recorded, so
                there is no honest denominator. Ownership is stamped at CI time from the repo's ownership map.
            </LemonBanner>
        </SceneContent>
    )
}

export default EngineeringAnalyticsTeamScene
