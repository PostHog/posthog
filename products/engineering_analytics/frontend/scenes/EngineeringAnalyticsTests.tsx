import { useActions, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTable, LemonTableColumns, Link } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { CIAnalyticsLoadError } from '../components/CIAnalyticsLoadError'
import { ScopeBar, SourceScopeChip } from '../components/ScopeBar'
import { Section } from '../components/Section'
import { StatCard } from '../components/StatCard'
import { TeamQuarantinedTestsTable } from '../components/TeamQuarantinedTestsTable'
import { withCurrentScope } from '../lib/scope'
import { TrunkQuarantineTeamRow, engineeringAnalyticsLogic } from './engineeringAnalyticsLogic'
import { teamLabel } from './teamsLogic'

function TrunkQuarantineDebtBoard(): JSX.Element {
    const {
        trunkQuarantine,
        trunkQuarantineLoading,
        trunkQuarantineStatus,
        trunkQuarantineTestsByTeam,
        expandedTrunkQuarantineTeams,
        sourceId,
    } = useValues(engineeringAnalyticsLogic)
    const { loadTrunkQuarantine, toggleTrunkQuarantineTeam } = useActions(engineeringAnalyticsLogic)

    const ttlDays = trunkQuarantine?.ttlDays ?? 15
    const overdueCount = trunkQuarantine ? trunkQuarantine.teams.reduce((n, t) => n + t.overdueCount, 0) : null
    const oldestAgeDays = trunkQuarantine?.tests.length ? trunkQuarantine.tests[0].ageDays : null
    const formatCappedCount = (count: number): string =>
        `${humanFriendlyNumber(count)}${trunkQuarantine?.truncated ? '+' : ''}`

    const teamColumns: LemonTableColumns<TrunkQuarantineTeamRow> = [
        {
            title: 'Team',
            key: 'ownerTeam',
            render: (_, row) => (
                <Link
                    to={withCurrentScope(urls.engineeringAnalyticsTeam(row.ownerTeam), sourceId)}
                    className="font-semibold"
                    data-attr="engineering-analytics-quarantine-team-link"
                >
                    {teamLabel(row.ownerTeam)}
                </Link>
            ),
        },
        {
            title: 'Quarantined',
            key: 'testCount',
            align: 'right',
            sorter: (a, b) => a.testCount - b.testCount,
            render: (_, row) => formatCappedCount(row.testCount),
        },
        {
            title: 'Overdue',
            key: 'overdueCount',
            align: 'right',
            tooltip: `Quarantined longer than ${pluralize(ttlDays, 'day')}.`,
            sorter: (a, b) => a.overdueCount - b.overdueCount,
            render: (_, row) =>
                row.overdueCount > 0 ? (
                    <span className="font-semibold text-danger">{formatCappedCount(row.overdueCount)}</span>
                ) : (
                    formatCappedCount(0)
                ),
        },
        {
            title: 'Oldest',
            key: 'oldestAgeDays',
            align: 'right',
            sorter: (a, b) => a.oldestAgeDays - b.oldestAgeDays,
            render: (_, row) => `${row.oldestAgeDays}d`,
        },
    ]

    if (trunkQuarantineStatus === 'error') {
        return (
            <CIAnalyticsLoadError
                onRetry={loadTrunkQuarantine}
                loading={trunkQuarantineLoading}
                title="Couldn't load Trunk quarantine data"
                description="Loading quarantined tests from Trunk failed. Retry, or check the Trunk source's sync status."
            />
        )
    }
    if (trunkQuarantineStatus === 'notConnected' || (trunkQuarantine && !trunkQuarantine.available)) {
        return (
            <LemonBanner type="info">
                No Trunk source is connected. Connect the Trunk.io data warehouse source with its quarantined tests
                endpoint to see which quarantined tests each team owns.
            </LemonBanner>
        )
    }

    return (
        <Section
            id="quarantine-debt"
            title="Quarantine debt by team"
            right={
                trunkQuarantine?.trunkUrl ? (
                    <LemonButton
                        size="small"
                        type="secondary"
                        to={trunkQuarantine.trunkUrl}
                        targetBlank
                        sideIcon={<IconExternal />}
                        data-attr="engineering-analytics-trunk-debt-open-trunk"
                    >
                        Open in Trunk
                    </LemonButton>
                ) : undefined
            }
        >
            <div className="flex flex-col gap-4">
                <div className="grid grid-cols-1 gap-3 @2xl/main-content:grid-cols-2 @5xl/main-content:grid-cols-4">
                    <StatCard
                        label="Quarantined tests"
                        value={trunkQuarantine ? formatCappedCount(trunkQuarantine.tests.length) : '—'}
                        caption="currently masked in CI"
                        loading={trunkQuarantineLoading}
                    />
                    <StatCard
                        label="Overdue"
                        value={overdueCount !== null ? formatCappedCount(overdueCount) : '—'}
                        caption={`quarantined over ${ttlDays} days`}
                        loading={trunkQuarantineLoading}
                    />
                    <StatCard
                        label="Teams affected"
                        value={trunkQuarantine ? formatCappedCount(trunkQuarantine.teams.length) : '—'}
                        caption="own at least one quarantined test"
                        loading={trunkQuarantineLoading}
                    />
                    <StatCard
                        label="Oldest quarantine"
                        value={oldestAgeDays !== null ? `${oldestAgeDays}d` : '—'}
                        caption="longest-standing masked test"
                        loading={trunkQuarantineLoading}
                    />
                </div>
                {trunkQuarantine?.truncated && (
                    <div className="text-xs text-tertiary">
                        Showing the oldest {humanFriendlyNumber(trunkQuarantine.limit)} quarantined tests. The counts
                        above are lower bounds.
                    </div>
                )}
                {trunkQuarantine && !trunkQuarantine.ownersResolved && (
                    <LemonBanner type="warning">
                        We could not read {trunkQuarantine.repository}'s ownership files, so every test below is listed
                        as unowned. Try again in a few minutes.
                    </LemonBanner>
                )}
                <LemonTable
                    data-attr="engineering-analytics-trunk-debt-teams-table"
                    size="small"
                    columns={teamColumns}
                    dataSource={trunkQuarantine?.teams ?? []}
                    rowKey={(row) => row.ownerTeam}
                    loading={trunkQuarantineLoading}
                    useURLForSorting={false}
                    emptyState="No tests are quarantined right now."
                    nouns={['team', 'teams']}
                    onRow={(row) => ({
                        className: 'cursor-pointer',
                        onClick: (event) => {
                            if (!(event.target as HTMLElement).closest('a, button')) {
                                toggleTrunkQuarantineTeam(row.ownerTeam)
                            }
                        },
                    })}
                    expandable={{
                        noIndent: true,
                        isRowExpanded: (row) => expandedTrunkQuarantineTeams.includes(row.ownerTeam),
                        expandedRowRender: (row) => (
                            <TeamQuarantinedTestsTable
                                tests={trunkQuarantineTestsByTeam[row.ownerTeam] ?? []}
                                ttlDays={ttlDays}
                                repository={trunkQuarantine?.repository ?? ''}
                            />
                        ),
                    }}
                />
            </div>
        </Section>
    )
}

export function EngineeringAnalyticsTests(): JSX.Element {
    return (
        <div className="flex flex-col gap-8">
            <ScopeBar repoSlot={<SourceScopeChip />} showDate={false} />
            <TrunkQuarantineDebtBoard />
        </div>
    )
}
