import { useActions, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import { ConnectGitHubSource } from '../components/ConnectGitHubSource'
import { ScopeBar, SourceScopeChip } from '../components/ScopeBar'
import { StatCard } from '../components/StatCard'
import { TeamQuarantinedTestsTable } from '../components/TeamQuarantinedTestsTable'
import { TrunkQuarantineTeamRow, engineeringAnalyticsLogic } from './engineeringAnalyticsLogic'

function teamLabel(ownerTeam: string): string {
    return ownerTeam.replace(/^team-/, '')
}

function TrunkQuarantineDebtBoard(): JSX.Element {
    const {
        trunkQuarantine,
        trunkQuarantineLoading,
        trunkQuarantineStatus,
        trunkQuarantineTestsByTeam,
        expandedTrunkQuarantineTeams,
    } = useValues(engineeringAnalyticsLogic)
    const { toggleTrunkQuarantineTeam } = useActions(engineeringAnalyticsLogic)

    const ttlDays = trunkQuarantine?.ttlDays ?? 15
    const overdueCount = trunkQuarantine ? trunkQuarantine.teams.reduce((n, t) => n + t.overdueCount, 0) : null
    const oldestAgeDays = trunkQuarantine?.tests.length ? trunkQuarantine.tests[0].ageDays : null

    const teamColumns: LemonTableColumns<TrunkQuarantineTeamRow> = [
        {
            title: 'Team',
            key: 'ownerTeam',
            render: (_, row) => <span className="font-semibold">{teamLabel(row.ownerTeam)}</span>,
        },
        {
            title: 'Quarantined',
            key: 'testCount',
            align: 'right',
            sorter: (a, b) => a.testCount - b.testCount,
            render: (_, row) => humanFriendlyNumber(row.testCount),
        },
        {
            title: 'Overdue',
            key: 'overdueCount',
            align: 'right',
            tooltip: `Quarantined longer than ${pluralize(ttlDays, 'day')}.`,
            sorter: (a, b) => a.overdueCount - b.overdueCount,
            render: (_, row) =>
                row.overdueCount > 0 ? (
                    <span className="font-semibold text-danger">{humanFriendlyNumber(row.overdueCount)}</span>
                ) : (
                    '0'
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
        return <LemonBanner type="warning">Couldn't load Trunk quarantine data. Try refreshing.</LemonBanner>
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
        <div className="flex flex-col gap-4">
            <div className="flex items-center justify-between gap-2">
                <h3 className="m-0 text-base font-semibold">Quarantine debt by team</h3>
                {trunkQuarantine?.trunkUrl && (
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
                )}
            </div>
            <div className="grid grid-cols-1 gap-3 @2xl/main-content:grid-cols-2 @5xl/main-content:grid-cols-4">
                <StatCard
                    label="Quarantined tests"
                    value={trunkQuarantine ? humanFriendlyNumber(trunkQuarantine.tests.length) : '—'}
                    caption="currently masked in CI"
                    loading={trunkQuarantineLoading}
                />
                <StatCard
                    label="Overdue"
                    value={overdueCount !== null ? humanFriendlyNumber(overdueCount) : '—'}
                    caption={`quarantined over ${ttlDays} days`}
                    loading={trunkQuarantineLoading}
                />
                <StatCard
                    label="Teams affected"
                    value={trunkQuarantine ? humanFriendlyNumber(trunkQuarantine.teams.length) : '—'}
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
                    onClick: () => toggleTrunkQuarantineTeam(row.ownerTeam),
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
    )
}

export function EngineeringAnalyticsTestHealth(): JSX.Element {
    const { quarantineLoadFailed } = useValues(engineeringAnalyticsLogic)

    // Production with no GitHub source and no local checkout: the endpoint 400s, same as the other tabs.
    if (quarantineLoadFailed) {
        return <ConnectGitHubSource />
    }

    return (
        <div className="flex flex-col gap-8">
            <ScopeBar repoSlot={<SourceScopeChip />} showDate={false} />
            <TrunkQuarantineDebtBoard />
        </div>
    )
}
