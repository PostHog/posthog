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
    LemonSkeleton,
    LemonSwitch,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    LemonTagType,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'
import { dayjs } from 'lib/dayjs'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import { BrokenTestStateTag } from '../components/BrokenTestStateTag'
import { ConnectGitHubSource } from '../components/ConnectGitHubSource'
import { QuarantineTestModal } from '../components/QuarantineTestModal'
import { ScopeBar, SourceScopeChip } from '../components/ScopeBar'
import { StatCard } from '../components/StatCard'
import {
    BrokenTestRow,
    FlakyTestClassification,
    FlakyTestRow,
    FlakyTestWindow,
    QuarantineEntryRow,
    QuarantineLifecycle,
    QuarantineLifecycleFilter,
    QuarantineModeFilter,
    engineeringAnalyticsLogic,
    flakyEvidenceReason,
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

function RelativeTime({ iso }: { iso: string }): JSX.Element {
    return (
        <Tooltip title={dayjs(iso).format('YYYY-MM-DD HH:mm:ss')}>
            <span className="text-xs whitespace-nowrap text-secondary">{dayjs(iso).fromNow()}</span>
        </Tooltip>
    )
}

// Reads the `broken_tests` product endpoint: the failure fingerprints, the classifier that ranks
// them, and the two cluster reads it merges all run server-side. The row expansion lazy-loads the
// failing log lines for the row's latest run via run_failure_logs.
function BrokenTestDrilldown({ row }: { row: BrokenTestRow }): JSX.Element {
    const { runFailureLogsByRun, runFailureLogsByRunLoading, brokenTestsWindowDays } =
        useValues(engineeringAnalyticsLogic)
    const logs = row.latestRunId ? runFailureLogsByRun[row.latestRunId] : undefined
    const runUrl = row.repo && row.latestRunId ? `https://github.com/${row.repo}/actions/runs/${row.latestRunId}` : null

    return (
        <div className="flex flex-col gap-2 p-2">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-secondary">
                <span>
                    Latest failing run on <span className="font-mono">{row.latestBranch || 'unknown branch'}</span>
                </span>
                <span>·</span>
                <span>
                    {pluralize(row.occurrences, 'failure')} across {pluralize(row.branches, 'branch', 'branches')} in
                    the last {brokenTestsWindowDays} days
                </span>
                {runUrl && (
                    <Link to={runUrl} target="_blank" className="inline-flex items-center gap-1">
                        View run on GitHub <IconExternal />
                    </Link>
                )}
            </div>
            {!row.latestRunId ? (
                <span className="text-xs text-tertiary">No run id recorded for this failure — can't fetch logs.</span>
            ) : runFailureLogsByRunLoading && !logs ? (
                <LemonSkeleton className="h-24 w-full" />
            ) : !logs || !logs.logs_available || logs.jobs.length === 0 ? (
                <span className="text-xs text-tertiary">
                    No failure logs for this run — it didn't fail, or the logs aged out of the short Logs retention.
                </span>
            ) : (
                <div className="flex flex-col gap-3">
                    {logs.jobs.map((job) => (
                        <div key={job.job_id} className="flex flex-col gap-1">
                            <div className="font-mono text-xs font-semibold text-secondary">
                                {job.branch || 'unknown'} · job {job.job_id} · {job.conclusion}
                                {job.truncated && ' · truncated'}
                            </div>
                            <pre className="m-0 overflow-x-auto rounded border bg-bg-3000 p-2 font-mono text-xs leading-snug">
                                {job.lines.map((line, idx) => (
                                    <div
                                        key={idx}
                                        className={cn(line.original_line === null && 'italic text-tertiary')}
                                    >
                                        <span className="mr-3 inline-block w-12 select-none text-right text-tertiary">
                                            {line.original_line ?? ''}
                                        </span>
                                        {line.text}
                                    </div>
                                ))}
                            </pre>
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}

function BrokenTestsPanel(): JSX.Element {
    const {
        visibleBrokenTests,
        brokenTestsData,
        brokenTestsDataLoading,
        brokenTestsError,
        brokenTestsWindowDays,
        breakingMasterJobs,
        hiddenBrokenTestCount,
        showPrOnlyBrokenTests,
    } = useValues(engineeringAnalyticsLogic)
    const { setShowPrOnlyBrokenTests, loadRunFailureLogs } = useActions(engineeringAnalyticsLogic)

    const columns: LemonTableColumns<BrokenTestRow> = [
        {
            title: 'State',
            key: 'state',
            width: 160,
            render: (_, row) => <BrokenTestStateTag state={row.state} />,
        },
        {
            title: 'Test',
            key: 'testId',
            width: 320,
            render: (_, row) => (
                <Tooltip title={row.testId}>
                    <span className="block max-w-[20rem] truncate font-mono text-xs">{row.testId}</span>
                </Tooltip>
            ),
        },
        {
            title: 'Error',
            key: 'errorSignature',
            render: (_, row) =>
                row.errorSignature ? (
                    <Tooltip title={row.errorSignature}>
                        <span className="line-clamp-2 max-w-[22rem] text-xs text-secondary">{row.errorSignature}</span>
                    </Tooltip>
                ) : (
                    <span className="text-tertiary">—</span>
                ),
        },
        {
            title: 'Occurrences',
            key: 'occurrences',
            width: 110,
            align: 'right',
            sorter: (a, b) => a.occurrences - b.occurrences,
            render: (_, row) => <span className="tabular-nums">{humanFriendlyNumber(row.occurrences)}</span>,
        },
        {
            title: 'Branches',
            key: 'branches',
            width: 100,
            align: 'right',
            sorter: (a, b) => a.branches - b.branches,
            render: (_, row) => <span className="tabular-nums">{humanFriendlyNumber(row.branches)}</span>,
        },
        {
            title: 'Master hits',
            key: 'masterHits',
            width: 110,
            align: 'right',
            sorter: (a, b) => a.masterHits - b.masterHits,
            render: (_, row) =>
                row.masterHits > 0 ? (
                    <span className="tabular-nums font-semibold text-danger">
                        {humanFriendlyNumber(row.masterHits)}
                    </span>
                ) : (
                    <span className="tabular-nums text-tertiary">0</span>
                ),
        },
        {
            title: 'First seen',
            key: 'firstSeen',
            width: 110,
            align: 'right',
            sorter: (a, b) => a.firstSeen.localeCompare(b.firstSeen),
            render: (_, row) => <RelativeTime iso={row.firstSeen} />,
        },
        {
            title: 'Last seen',
            key: 'lastSeen',
            width: 110,
            align: 'right',
            sorter: (a, b) => a.lastSeen.localeCompare(b.lastSeen),
            render: (_, row) => <RelativeTime iso={row.lastSeen} />,
        },
        {
            title: 'Trend (24h)',
            key: 'trend',
            width: 140,
            tooltip: 'Failures per hour over the last 24 hours — a climbing bar means it is escalating right now.',
            render: (_, row) => {
                const series = row.trend
                return series && series.some((n) => n > 0) ? (
                    <Sparkline data={series} type="bar" color="danger" maximumIndicator={false} className="h-8 w-28" />
                ) : (
                    <span className="text-tertiary">—</span>
                )
            },
        },
    ]

    return (
        <div className="flex flex-col gap-4">
            <div className="flex items-start justify-between gap-2">
                <div className="flex flex-col gap-0.5">
                    <h3 className="m-0 text-base font-semibold">Currently broken tests</h3>
                    <p className="m-0 max-w-2xl text-xs text-tertiary">
                        Failures over the last {brokenTestsWindowDays} days, grouped by whether they're breaking trunk
                        right now, resolving, or just flaky — inferred from CI logs + master job history. Expand a row
                        for the latest failing run's logs.
                    </p>
                </div>
                <LemonSwitch
                    label="Show PR-only failures"
                    checked={showPrOnlyBrokenTests}
                    onChange={setShowPrOnlyBrokenTests}
                    size="small"
                    bordered
                />
            </div>
            {brokenTestsError ? (
                <LemonBanner type="error">Couldn't load broken tests: {brokenTestsError}</LemonBanner>
            ) : brokenTestsDataLoading && !brokenTestsData ? (
                <LemonSkeleton className="h-48 w-full" />
            ) : (
                <>
                    {breakingMasterJobs.length > 0 ? (
                        <LemonBanner type="error">
                            Breaking master: {pluralize(breakingMasterJobs.length, 'job group')} —{' '}
                            {breakingMasterJobs.join(', ')}
                        </LemonBanner>
                    ) : (
                        <LemonBanner type="success">
                            Nothing is flagged as breaking master right now. Failures that hit trunk only show here once
                            their job's latest master run is known to be red, so this needs the job-level source synced.
                        </LemonBanner>
                    )}
                    <LemonTable
                        data-attr="engineering-analytics-broken-tests-table"
                        size="small"
                        columns={columns}
                        dataSource={visibleBrokenTests}
                        rowKey={(row) => row.fingerprint}
                        loading={brokenTestsDataLoading}
                        pagination={{ pageSize: 10 }}
                        useURLForSorting={false}
                        emptyState="No broken tests to show. Nothing is breaking trunk right now."
                        nouns={['broken test', 'broken tests']}
                        expandable={{
                            noIndent: true,
                            onRowExpand: (row) => {
                                if (row.latestRunId) {
                                    loadRunFailureLogs({ runId: row.latestRunId })
                                }
                            },
                            expandedRowRender: (row) => <BrokenTestDrilldown row={row} />,
                        }}
                    />
                    {brokenTestsData?.truncated && (
                        <div className="text-xs text-tertiary">
                            Showing the top {brokenTestsData.limit} by urgency — more distinct failures matched than
                            fit.
                        </div>
                    )}
                    {hiddenBrokenTestCount > 0 && !showPrOnlyBrokenTests && (
                        <div className="text-xs text-tertiary">
                            {pluralize(hiddenBrokenTestCount, 'PR-only failure')} hidden — toggle "Show PR-only
                            failures" to include them.
                        </div>
                    )}
                </>
            )}
        </div>
    )
}

const FLAKY_CLASSIFICATION: Record<FlakyTestClassification, { label: string; type: LemonTagType; tooltip: string }> = {
    confirmed_flake: {
        label: 'Confirmed flake',
        type: 'warning',
        tooltip:
            'A retry recovered this test in the same run, so the failure is nondeterministic. Fix it, or quarantine it while you do.',
    },
    suspected_regression: {
        label: 'Suspected regression',
        type: 'danger',
        tooltip:
            'Only failures recorded, so nothing here proves the test is flaky. Treat it as a real break, and check Trunk if you think it flakes.',
    },
    quarantined: {
        label: 'Quarantined, still failing',
        type: 'muted',
        tooltip: 'Already masked as xfail in CI and still failing. Fix it, then remove the quarantine.',
    },
}

function ActiveTestHealthQueue(): JSX.Element {
    const { flakyTests, flakyTestsLoading, flakyTestsStatus, flakyTestWindow } = useValues(engineeringAnalyticsLogic)
    const { setFlakyTestWindow, openQuarantineModal } = useActions(engineeringAnalyticsLogic)

    const columns: LemonTableColumns<FlakyTestRow> = [
        {
            title: 'Test',
            key: 'nodeid',
            width: 360,
            render: (_, row) => {
                const { label, type, tooltip } = FLAKY_CLASSIFICATION[row.classification]
                return (
                    <div className="flex max-w-[22rem] flex-col gap-0.5">
                        <Tooltip title={row.nodeid}>
                            <span className="truncate font-mono text-xs">{row.nodeid}</span>
                        </Tooltip>
                        <div>
                            <Tooltip title={tooltip}>
                                <LemonTag type={type} size="small">
                                    {label}
                                </LemonTag>
                            </Tooltip>
                        </div>
                    </div>
                )
            },
        },
        {
            title: 'Evidence',
            key: 'failedRunCount',
            tooltip: 'Absolute counts, never a rate: fast passing runs are not recorded, so there is no denominator.',
            sorter: (a, b) => a.failedRunCount - b.failedRunCount,
            render: (_, row) => (
                <div className="flex flex-col gap-0.5 text-xs">
                    {row.failedRunCount > 0 && (
                        <span>
                            {pluralize(row.failedRunCount, 'failed run')} · {pluralize(row.failedPrCount, 'PR')}
                        </span>
                    )}
                    {row.quarantinedFailedRunCount > 0 && (
                        <span>Failed in {pluralize(row.quarantinedFailedRunCount, 'quarantined run')} (xfail)</span>
                    )}
                    {/* An xfail row has no recovery question to answer: it is masked, not racing. */}
                    {row.classification !== 'quarantined' && (
                        <span className="text-secondary">
                            {row.sameCommitRecoveryRunCount > 0
                                ? `Failed then passed on the same commit in ${pluralize(row.sameCommitRecoveryRunCount, 'run')}`
                                : 'No recovery recorded'}
                        </span>
                    )}
                    {row.masterFailedRunCount > 0 && (
                        <span className="font-semibold text-danger">
                            {pluralize(row.masterFailedRunCount, 'master failure')}
                        </span>
                    )}
                </div>
            ),
        },
        {
            title: 'Last signal',
            key: 'lastSignalAt',
            width: 120,
            align: 'right',
            sorter: (a, b) => a.lastSignalAt.localeCompare(b.lastSignalAt),
            render: (_, row) => <RelativeTime iso={row.lastSignalAt} />,
        },
        {
            title: '',
            key: 'actions',
            width: 130,
            align: 'right',
            render: (_, row) =>
                row.classification === 'confirmed_flake' ? (
                    <LemonButton
                        size="small"
                        type="tertiary"
                        icon={<IconShieldLock />}
                        tooltip="Review the evidence and owner before opening a tracking issue and quarantine PR."
                        aria-label={`Quarantine ${row.nodeid}`}
                        onClick={() =>
                            openQuarantineModal({
                                action: 'quarantine',
                                selector: row.selector,
                                // The evidence is the reason; the cause is the tracking issue's job to find.
                                reason: flakyEvidenceReason(row, flakyTestWindow),
                                owner: '',
                                issue: '',
                                mode: 'run',
                                confirm: true,
                            })
                        }
                        data-attr="eng-analytics-flaky-quarantine"
                    >
                        Quarantine…
                    </LemonButton>
                ) : null,
        },
    ]

    return (
        <div className="flex flex-col gap-4">
            <div className="flex items-start justify-between gap-2">
                <div className="flex flex-col gap-0.5">
                    <h3 className="m-0 text-base font-semibold">Active test health queue</h3>
                    <p className="m-0 text-xs text-tertiary">
                        Backend tests worth acting on now, ranked by blast radius: how many PRs they broke and how often
                        they broke master. For flake detection across every suite, see{' '}
                        <Link to="https://app.trunk.io/posthog-inc/flaky-tests" target="_blank">
                            Trunk
                        </Link>
                        .
                    </p>
                </div>
                <LemonSegmentedButton
                    size="small"
                    value={flakyTestWindow}
                    onChange={(value) => setFlakyTestWindow(value as FlakyTestWindow)}
                    options={[
                        { value: '-7d', label: '7d' },
                        { value: '-14d', label: '14d' },
                        { value: '-30d', label: '30d' },
                    ]}
                />
            </div>
            {flakyTestsStatus === 'error' ? (
                <LemonBanner type="warning">Couldn't load flaky test data. Try refreshing.</LemonBanner>
            ) : (
                <>
                    <LemonTable
                        data-attr="engineering-analytics-flaky-tests-table"
                        size="small"
                        columns={columns}
                        dataSource={flakyTests?.rows ?? []}
                        rowKey={(row) => row.nodeid}
                        loading={flakyTestsLoading}
                        pagination={{ pageSize: 10 }}
                        useURLForSorting={false}
                        emptyState="No tests need attention in this window."
                        nouns={['test', 'tests']}
                    />
                    {flakyTests?.truncated && (
                        <div className="text-xs text-tertiary">
                            Showing the top {flakyTests.limit} by blast radius. More tests qualified in this window.
                        </div>
                    )}
                </>
            )}
        </div>
    )
}

export function EngineeringAnalyticsTestHealth(): JSX.Element {
    const { quarantineLoadFailed, quarantineModal, quarantineOwnerOptions, quarantineSubmitLoading } =
        useValues(engineeringAnalyticsLogic)
    const { closeQuarantineModal, submitQuarantine } = useActions(engineeringAnalyticsLogic)

    // Production with no GitHub source and no local checkout: the endpoint 400s, same as the other tabs.
    if (quarantineLoadFailed) {
        return <ConnectGitHubSource />
    }

    return (
        <div className="flex flex-col gap-8">
            {/* Tab-level: both sections read the same source, so the picker scopes them together. */}
            <ScopeBar repoSlot={<SourceScopeChip />} showDate={false} />
            <BrokenTestsPanel />
            <ActiveTestHealthQueue />
            <QuarantineRegister />
            {/* Rendered once for the whole tab: the leaderboard rows, the register rows, and the
                register's no-file empty state all open it. */}
            <QuarantineTestModal
                modal={quarantineModal}
                ownerOptions={quarantineOwnerOptions}
                submitting={quarantineSubmitLoading}
                onClose={closeQuarantineModal}
                onSubmit={(input) => submitQuarantine({ input })}
            />
        </div>
    )
}

function QuarantineRegister(): JSX.Element {
    const {
        quarantine,
        quarantineLoading,
        filteredQuarantineEntries,
        quarantineCounts,
        quarantineOwnerOptions,
        quarantineSearch,
        quarantineLifecycleFilter,
        quarantineModeFilter,
        quarantineOwner,
        activeQuarantineCard,
        hasActiveQuarantineFilters,
    } = useValues(engineeringAnalyticsLogic)
    const {
        setQuarantineSearch,
        setQuarantineLifecycleFilter,
        setQuarantineModeFilter,
        setQuarantineOwner,
        applyQuarantineCard,
        resetQuarantineFilters,
        openQuarantineModal,
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

    // A fetch failure (timeout, 5xx, unsafe repo) also comes back as available:false, but with
    // parse_errors set — surface those instead of the "no file" explainer, which only fits a true 404.
    if (quarantine && !quarantine.available && quarantine.parseErrors.length > 0) {
        return (
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
        )
    }

    // A file that does not exist is a normal state, not an error — offer to start one.
    if (quarantine && !quarantine.available) {
        return (
            <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-primary p-10 text-center">
                <IconShieldLock className="size-8 text-tertiary" />
                <div className="text-lg font-semibold">No test quarantine yet</div>
                <p className="max-w-xl text-sm text-secondary">
                    {quarantine.repoFullName
                        ? `${quarantine.repoFullName} has no .test_quarantine.json. `
                        : 'This repo has no .test_quarantine.json. '}
                    Quarantine masks a flaky test in CI with a hard expiry, so it stops blocking merges while its owner
                    fixes it. The first quarantine opens a PR that creates the file.
                </p>
                <LemonButton type="primary" onClick={openNewQuarantine} data-attr="eng-analytics-quarantine-open">
                    Quarantine a test
                </LemonButton>
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
                pagination={{ pageSize: 25 }}
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
        </div>
    )
}
