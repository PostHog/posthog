import { useActions, useValues } from 'kea'

import { IconPeople } from '@posthog/icons'
import { LemonSegmentedButton, LemonTable, LemonTableColumns, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { EntityHeader } from '../components/EntityHeader'
import { DeltaBadge, percentChange } from '../components/MetricTile'
import { Section } from '../components/Section'
import { TeamDetailLogicProps, TeamTestSignalRow, teamDetailLogic } from './teamDetailLogic'
import { TeamsWindow, UNOWNED_TEAM } from './teamsLogic'

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

// The two merge-trend lines, defined once for the series and the static legend (identity is
// never color-alone). Both are the team's own merges: the median carries the accent, the
// average is the skew tell beside it.
const MERGE_SERIES = [
    { label: 'Median', color: 'data-color-1', colorVar: 'var(--data-color-1)' },
    { label: 'Average', color: 'muted', colorVar: 'var(--muted)' },
]

export function EngineeringAnalyticsTeamScene(): JSX.Element {
    const { activity, activityLoading, mergeTrend, mergeTrendLoading, filledMergePoints, window, ownerTeam } =
        useValues(teamDetailLogic)
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

            {!isUnowned && (
                <Section id="team-merge-trend" title="Time to merge" busy={mergeTrendLoading}>
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
                                            p.medianSeconds !== null ? p.medianSeconds / 3600 : NaN
                                        ),
                                    },
                                    {
                                        name: MERGE_SERIES[1].label,
                                        color: MERGE_SERIES[1].color,
                                        values: filledMergePoints.map((p) =>
                                            p.averageSeconds !== null ? p.averageSeconds / 3600 : NaN
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
