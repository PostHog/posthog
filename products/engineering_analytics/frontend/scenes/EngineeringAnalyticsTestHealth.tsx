import { useActions, useValues } from 'kea'

import { IconEllipsis, IconExternal, IconShieldLock } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonInput,
    LemonInputSelect,
    LemonMenu,
    LemonSegmentedButton,
    LemonSelect,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import { ConnectGitHubSource } from '../components/ConnectGitHubSource'
import { QuarantineTestModal } from '../components/QuarantineTestModal'
import { ScopeBar, SourceScopeChip } from '../components/ScopeBar'
import { StatCard } from '../components/StatCard'
import {
    QuarantineEntryRow,
    QuarantineLifecycle,
    QuarantineLifecycleFilter,
    QuarantineModeFilter,
    engineeringAnalyticsLogic,
} from './engineeringAnalyticsLogic'

function relativeExpiry(daysUntilExpiry: number): string {
    if (daysUntilExpiry === 0) {
        return 'today'
    }
    return daysUntilExpiry > 0 ? `in ${pluralize(daysUntilExpiry, 'day')}` : `${pluralize(-daysUntilExpiry, 'day')} ago`
}

function LifecycleTag({ lifecycle }: { lifecycle: QuarantineLifecycle }): JSX.Element {
    switch (lifecycle) {
        case 'active':
            return <LemonTag type="success">Active</LemonTag>
        case 'expiring_soon':
            return <LemonTag type="warning">Expiring soon</LemonTag>
        case 'in_grace':
            return (
                <Tooltip title="Expired, but inside the 7-day grace period. The quarantine check only warns for now.">
                    <LemonTag type="warning">In grace</LemonTag>
                </Tooltip>
            )
        default:
            return (
                <Tooltip title="Expired beyond the grace period. The quarantine check workflow fails until the entry is removed or re-triaged.">
                    <LemonTag type="danger">Overdue · blocks CI</LemonTag>
                </Tooltip>
            )
    }
}

function ModeTag({ mode }: { mode: QuarantineEntryRow['mode'] }): JSX.Element {
    if (mode === 'skip') {
        return (
            <Tooltip title="Skipped: the test is not collected at all (for hangs, import-time flakes, and state-polluters).">
                <LemonTag type="danger">Skipped</LemonTag>
            </Tooltip>
        )
    }
    return (
        <Tooltip title="Runs as xfail: the test still executes but cannot fail the suite.">
            <LemonTag type="muted">Runs, can't fail</LemonTag>
        </Tooltip>
    )
}

export function EngineeringAnalyticsTestHealth(): JSX.Element {
    const {
        quarantine,
        quarantineLoading,
        quarantineLoadFailed,
        filteredQuarantineEntries,
        quarantineCounts,
        quarantineOwnerOptions,
        quarantineSearch,
        quarantineLifecycleFilter,
        quarantineModeFilter,
        quarantineOwner,
        activeQuarantineCard,
        hasActiveQuarantineFilters,
        quarantineModal,
        quarantineSubmitLoading,
    } = useValues(engineeringAnalyticsLogic)
    const {
        setQuarantineSearch,
        setQuarantineLifecycleFilter,
        setQuarantineModeFilter,
        setQuarantineOwner,
        applyQuarantineCard,
        resetQuarantineFilters,
        openQuarantineModal,
        closeQuarantineModal,
        submitQuarantine,
    } = useActions(engineeringAnalyticsLogic)

    const openNewQuarantine = (): void =>
        openQuarantineModal({ action: 'quarantine', selector: '', reason: '', owner: '', issue: '', mode: 'run' })

    const openExtend = (row: QuarantineEntryRow): void =>
        openQuarantineModal({
            action: 'extend',
            selector: row.id,
            reason: row.reason,
            owner: row.owner,
            issue: row.issue,
            mode: row.mode,
        })

    const confirmRemove = (row: QuarantineEntryRow): void => {
        LemonDialog.open({
            title: 'Remove from quarantine?',
            description: `Opens a PR that removes ${row.id} from .test_quarantine.json so it gates CI normally again. It takes effect once the PR merges.`,
            primaryButton: {
                children: 'Open removal PR',
                status: 'danger',
                onClick: () =>
                    submitQuarantine({
                        input: {
                            action: 'remove',
                            selector: row.id,
                            reason: '',
                            owner: '',
                            issue: row.issue,
                            expires: null,
                            mode: row.mode,
                        },
                    }),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    // Rendered alongside every branch that can open it, so the modal survives the no-file empty state.
    const modalElement = (
        <QuarantineTestModal
            modal={quarantineModal}
            ownerOptions={quarantineOwnerOptions}
            submitting={quarantineSubmitLoading}
            onClose={closeQuarantineModal}
            onSubmit={(input) => submitQuarantine({ input })}
        />
    )

    // Rendered on every data-bearing branch: the quarantine file is per-repo, so multi-source teams
    // need the source picker here too — including on the wrong-repo empty states.
    const scopeBar = <ScopeBar repoSlot={<SourceScopeChip />} showDate={false} />

    // Production with no GitHub source and no local checkout: the endpoint 400s, same as the other tabs.
    if (quarantineLoadFailed) {
        return <ConnectGitHubSource />
    }

    // A fetch failure (timeout, 5xx, unsafe repo) also comes back as available:false, but with
    // parse_errors set — surface those instead of the "no file" explainer, which only fits a true 404.
    if (quarantine && !quarantine.available && quarantine.parseErrors.length > 0) {
        return (
            <div className="flex flex-col gap-4">
                {scopeBar}
                <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-primary p-10 text-center">
                    <IconShieldLock className="size-8 text-tertiary" />
                    <div className="text-lg font-semibold">Couldn't read the quarantine file</div>
                    <div className="w-full max-w-xl">
                        <LemonBanner type="warning">
                            <ul className="ml-4 list-disc text-left">
                                {quarantine.parseErrors.map((error, index) => (
                                    <li key={index} className="font-mono text-xs">
                                        {error}
                                    </li>
                                ))}
                            </ul>
                        </LemonBanner>
                    </div>
                    {quarantine.repoFullName && (
                        <p className="text-sm text-secondary">
                            Repository: <span className="font-mono">{quarantine.repoFullName}</span>
                        </p>
                    )}
                </div>
            </div>
        )
    }

    // A file that does not exist is a normal state, not an error — offer to start one.
    if (quarantine && !quarantine.available) {
        return (
            <div className="flex flex-col gap-4">
                {scopeBar}
                <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-primary p-10 text-center">
                    <IconShieldLock className="size-8 text-tertiary" />
                    <div className="text-lg font-semibold">No test quarantine yet</div>
                    <p className="max-w-xl text-sm text-secondary">
                        {quarantine.repoFullName
                            ? `${quarantine.repoFullName} has no .test_quarantine.json. `
                            : 'This repo has no .test_quarantine.json. '}
                        Quarantine masks a flaky test in CI with a hard expiry, so it stops blocking merges while its
                        owner fixes it. The first quarantine opens a PR that creates the file.
                    </p>
                    <LemonButton type="primary" onClick={openNewQuarantine} data-attr="eng-analytics-quarantine-open">
                        Quarantine a test
                    </LemonButton>
                    {modalElement}
                </div>
            </div>
        )
    }

    const columns: LemonTableColumns<QuarantineEntryRow> = [
        {
            title: 'Selector',
            key: 'id',
            render: (_, row) => (
                <div className="flex max-w-[28rem] flex-col gap-0.5">
                    <Tooltip title={row.id}>
                        <span className="truncate font-mono text-xs">{row.id}</span>
                    </Tooltip>
                    <div className="flex items-center gap-1.5">
                        <LemonTag type="option" size="small">
                            {row.selectorKind}
                        </LemonTag>
                        {row.runner !== 'pytest' && (
                            <Tooltip title="No enforcement adapter yet. This entry is informational.">
                                <LemonTag type="muted" size="small">
                                    {row.runner}
                                </LemonTag>
                            </Tooltip>
                        )}
                    </div>
                </div>
            ),
        },
        {
            title: 'Mode',
            key: 'mode',
            width: 130,
            render: (_, row) => <ModeTag mode={row.mode} />,
        },
        {
            title: 'Status',
            key: 'lifecycle',
            width: 150,
            render: (_, row) => <LifecycleTag lifecycle={row.lifecycle} />,
        },
        {
            title: 'Owner',
            key: 'owner',
            width: 200,
            render: (_, row) => <span className="font-mono text-xs">{row.owner || '—'}</span>,
        },
        {
            title: 'Reason',
            key: 'reason',
            render: (_, row) => (
                <Tooltip title={row.reason}>
                    <span className="line-clamp-2 max-w-[20rem] text-xs text-secondary">{row.reason || '—'}</span>
                </Tooltip>
            ),
        },
        {
            title: 'Issue',
            key: 'issue',
            width: 70,
            align: 'center',
            render: (_, row) =>
                row.issue ? (
                    <Link to={row.issue} target="_blank">
                        <IconExternal className="text-base" />
                    </Link>
                ) : (
                    <span className="text-tertiary">—</span>
                ),
        },
        {
            title: 'Added',
            key: 'added',
            width: 110,
            align: 'right',
            sorter: (a, b) => a.added.localeCompare(b.added),
            render: (_, row) => (
                <span className="text-xs whitespace-nowrap tabular-nums text-secondary">{row.added}</span>
            ),
        },
        {
            title: 'Expires',
            key: 'expires',
            width: 150,
            align: 'right',
            sorter: (a, b) => a.daysUntilExpiry - b.daysUntilExpiry,
            render: (_, row) => (
                <div className="flex flex-col items-end gap-0.5">
                    <span className="text-xs whitespace-nowrap tabular-nums">{row.expires}</span>
                    <span
                        className={cn(
                            'text-xs whitespace-nowrap tabular-nums',
                            row.daysUntilExpiry < 0 ? 'text-danger' : 'text-tertiary'
                        )}
                    >
                        {relativeExpiry(row.daysUntilExpiry)}
                    </span>
                </div>
            ),
        },
        {
            title: '',
            key: 'actions',
            width: 40,
            render: (_, row) => (
                <LemonMenu
                    items={[
                        { label: 'Extend…', onClick: () => openExtend(row) },
                        { label: 'Remove…', status: 'danger', onClick: () => confirmRemove(row) },
                        ...(row.issue ? [{ label: 'Open issue', to: row.issue, targetBlank: true }] : []),
                    ]}
                >
                    <LemonButton size="small" icon={<IconEllipsis />} aria-label="More actions" />
                </LemonMenu>
            ),
        },
    ]

    return (
        <div className="flex flex-col gap-4">
            {scopeBar}
            <div className="flex items-start justify-between gap-2">
                <div className="flex flex-col gap-0.5">
                    <h3 className="m-0 text-base font-semibold">Quarantine register</h3>
                    <p className="m-0 text-xs text-tertiary">
                        Flaky tests currently masked in CI via the checked-in quarantine file.
                    </p>
                </div>
                <LemonButton type="primary" onClick={openNewQuarantine} data-attr="eng-analytics-quarantine-open">
                    Quarantine a test
                </LemonButton>
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <StatCard
                    label="Active"
                    value={quarantine ? humanFriendlyNumber(quarantineCounts.active) : '—'}
                    caption="more than 7 days of runway"
                    loading={quarantineLoading}
                    onClick={() => applyQuarantineCard('active')}
                    active={activeQuarantineCard === 'active'}
                    filterHint="Filter to entries with runway left"
                />
                <StatCard
                    label="Expiring soon"
                    value={quarantine ? humanFriendlyNumber(quarantineCounts.expiringSoon) : '—'}
                    caption="7 days or fewer left"
                    loading={quarantineLoading}
                    onClick={() => applyQuarantineCard('expiring_soon')}
                    active={activeQuarantineCard === 'expiring_soon'}
                    filterHint="Filter to entries expiring within 7 days"
                />
                <StatCard
                    label="Past expiry"
                    value={quarantine ? humanFriendlyNumber(quarantineCounts.pastExpiry) : '—'}
                    caption="fails the quarantine check after 7 days"
                    loading={quarantineLoading}
                    onClick={() => applyQuarantineCard('past_expiry')}
                    active={activeQuarantineCard === 'past_expiry'}
                    filterHint="Filter to expired entries (in grace or overdue)"
                />
                <StatCard
                    label="Skipped entirely"
                    value={quarantine ? humanFriendlyNumber(quarantineCounts.skipped) : '—'}
                    caption="dropped from CI, not just masked"
                    loading={quarantineLoading}
                    onClick={() => applyQuarantineCard('skipped')}
                    active={activeQuarantineCard === 'skipped'}
                    filterHint="Filter to entries skipped entirely (mode: skip)"
                />
            </div>

            {quarantine && quarantine.parseErrors.length > 0 && (
                <LemonBanner type="warning">
                    <div className="font-semibold">The quarantine file has problems</div>
                    <ul className="ml-4 list-disc">
                        {quarantine.parseErrors.map((error, index) => (
                            <li key={index} className="font-mono text-xs">
                                {error}
                            </li>
                        ))}
                    </ul>
                </LemonBanner>
            )}
            {quarantine && quarantine.parseWarnings.length > 0 && (
                <LemonBanner type="info">
                    <ul className="ml-4 list-disc">
                        {quarantine.parseWarnings.map((warning, index) => (
                            <li key={index} className="font-mono text-xs">
                                {warning}
                            </li>
                        ))}
                    </ul>
                </LemonBanner>
            )}

            <div className="flex flex-wrap items-center gap-2">
                <LemonInput
                    type="search"
                    placeholder="Search selector, reason, owner…"
                    value={quarantineSearch}
                    onChange={setQuarantineSearch}
                    className="w-64"
                />
                <LemonSegmentedButton
                    size="small"
                    value={quarantineLifecycleFilter}
                    onChange={(value) => setQuarantineLifecycleFilter(value as QuarantineLifecycleFilter)}
                    options={[
                        { value: 'all', label: 'All' },
                        { value: 'active', label: 'Active' },
                        { value: 'expiring_soon', label: 'Expiring' },
                        { value: 'past_expiry', label: 'Past expiry' },
                    ]}
                />
                <LemonSelect
                    size="small"
                    value={quarantineModeFilter}
                    onChange={(value) => setQuarantineModeFilter(value as QuarantineModeFilter)}
                    options={[
                        { value: 'all', label: 'Mode: any', labelInMenu: 'Any' },
                        { value: 'run', label: 'Mode: runs', labelInMenu: "Runs, can't fail" },
                        { value: 'skip', label: 'Mode: skipped', labelInMenu: 'Skipped' },
                    ]}
                />
                <div className="w-56">
                    <LemonInputSelect
                        mode="single"
                        size="small"
                        placeholder="Owner: anyone"
                        value={quarantineOwner ? [quarantineOwner] : []}
                        onChange={(values) => setQuarantineOwner(values[0] ?? null)}
                        options={quarantineOwnerOptions.map((owner) => ({ key: owner, label: owner }))}
                        data-attr="engineering-analytics-quarantine-owner-filter"
                    />
                </div>
                {hasActiveQuarantineFilters && (
                    <LemonButton type="secondary" size="small" onClick={resetQuarantineFilters}>
                        Reset
                    </LemonButton>
                )}
                {quarantine?.sourceUrl && (
                    <Link to={quarantine.sourceUrl} target="_blank" className="ml-auto text-xs">
                        View .test_quarantine.json
                    </Link>
                )}
            </div>

            <LemonTable
                data-attr="engineering-analytics-quarantine-table"
                size="small"
                columns={columns}
                dataSource={filteredQuarantineEntries}
                rowKey={(row) => `${row.runner}:${row.id}`}
                loading={quarantineLoading}
                pagination={{ pageSize: 50 }}
                useURLForSorting={false}
                emptyState={
                    hasActiveQuarantineFilters ? (
                        <div className="flex flex-col items-center gap-2">
                            <span>No entries match these filters.</span>
                            <LemonButton type="secondary" size="small" onClick={resetQuarantineFilters}>
                                Clear filters
                            </LemonButton>
                        </div>
                    ) : (
                        'No quarantined tests. Nothing is masked right now.'
                    )
                }
                nouns={['quarantined test', 'quarantined tests']}
            />

            <div className="text-xs text-tertiary">
                Quarantine is checked into <span className="font-mono">.test_quarantine.json</span> and enforced by CI.
                Quarantining, extending, or removing opens a pull request, so the file stays the source of truth. A
                merged edit only affects CI runs that start after it lands.
            </div>
            {modalElement}
        </div>
    )
}
