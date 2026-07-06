// The repo hub landing page: stat tiles with deltas, then master health, failing runs, PRs needing
// attention, workflows, and cost as sections on one page.

import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconBox } from '@posthog/icons'
import { LemonCard, LemonTable, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'
import { TZLabel } from 'lib/components/TZLabel'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { CIAnalyticsLoadError } from '../components/CIAnalyticsLoadError'
import { ConnectGitHubSource } from '../components/ConnectGitHubSource'
import { EntityHeader } from '../components/EntityHeader'
import { FailureLogGroups } from '../components/FailureLogs'
import { DeltaBadge, MetricTile, percentChange, pointChange } from '../components/MetricTile'
import { PullRequestTable } from '../components/PullRequestTable'
import { RunActivityChart, hasEnoughRunActivity } from '../components/RunActivityChart'
import { ScopeBar, SourceScopeChip } from '../components/ScopeBar'
import { Section, SectionNav, scrollToSection } from '../components/Section'
import { ShareRow } from '../components/ShareRow'
import { WorkflowHealthTable } from '../components/WorkflowHealthTable'
import type { MasterFailureGroupApi } from '../generated/api.schemas'
import { compactCount, compactHours, compactHoursUnit, compactMinutes, compactUsd, percent } from '../lib/format'
import { engineeringAnalyticsLogic } from './engineeringAnalyticsLogic'
import { repoOverviewLogic } from './repoOverviewLogic'

const SHARE_COLORS = [
    'var(--data-color-1)',
    'var(--data-color-2)',
    'var(--data-color-3)',
    'var(--data-color-4)',
    'var(--data-color-5)',
]

// The hub shows capped tables; the dedicated list pages keep the full 50-per-page tables.
const HUB_TABLE_PAGE_SIZE = 8

function withSource(url: string, sourceId: string | null): string {
    return combineUrl(url, sourceId ? { source: sourceId } : {}).url
}

function RepoEntityHeader({ repoFullName }: { repoFullName: string }): JSX.Element {
    const name = repoFullName.split('/')[1] || repoFullName || 'GitHub repository'
    return (
        <EntityHeader
            icon={<IconBox />}
            title={name}
            // No slug line when the source hasn't reported a repo name yet.
            slug={
                repoFullName ? (
                    <>
                        {repoFullName}
                        {' · '}
                        <Link to={`https://github.com/${repoFullName}`} target="_blank" targetBlankIcon>
                            View on GitHub
                        </Link>
                    </>
                ) : undefined
            }
        />
    )
}

/** Default-branch verdict tile: a calm dot when clean, a red "N failing" that jumps to the triage table. */
function MasterStatusTile({
    failingCount,
    loading,
    defaultBranch,
}: {
    failingCount: number
    loading: boolean
    defaultBranch: string
}): JSX.Element {
    const failing = failingCount > 0
    const dotColor = loading ? 'var(--muted)' : failing ? 'var(--danger)' : 'var(--success)'
    const status = loading ? 'Checking…' : failing ? `${failingCount} failing` : 'Passing'
    return (
        <LemonCard
            hoverEffect={failing}
            onClick={failing ? () => scrollToSection('now') : undefined}
            className="flex min-w-44 flex-1 flex-col justify-center gap-1 px-5 py-4"
        >
            <Tooltip title="Workflows failing on the default branch in the last 24 hours.">
                <span className="self-start cursor-default text-xs text-secondary">
                    {defaultBranch === 'main' ? 'Main' : 'Master'}
                </span>
            </Tooltip>
            <span className="flex items-center gap-2">
                <span
                    className="inline-block size-2.5 shrink-0 rounded-full"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ backgroundColor: dotColor }}
                />
                <span
                    className={cn(
                        'text-2xl font-semibold leading-none',
                        loading ? 'text-tertiary' : failing ? 'text-danger' : 'text-primary'
                    )}
                >
                    {status}
                </span>
            </span>
        </LemonCard>
    )
}

function MasterFailuresSection(): JSX.Element {
    const { masterFailures, masterFailuresLoading, failureLogs, failureLogsLoading, defaultBranch } =
        useValues(repoOverviewLogic)
    const { loadLogsForRun } = useActions(repoOverviewLogic)
    const { sourceId } = useValues(engineeringAnalyticsLogic)

    return (
        <Section id="now" title={`Failing on ${defaultBranch}`} note="Last 24 hours">
            <LemonCard hoverEffect={false} className="overflow-hidden p-0">
                <LemonTable<MasterFailureGroupApi>
                    dataSource={masterFailures}
                    loading={masterFailuresLoading}
                    embedded
                    rowKey={(group) => `${group.workflow_name}:${group.failed_job}`}
                    expandable={{
                        noIndent: true,
                        onRowExpand: (group) => loadLogsForRun(group.latest_run_id),
                        expandedRowRender: (group) => {
                            const logs = failureLogs[group.latest_run_id]
                            return (
                                <div className="p-2">
                                    <div className="mb-1.5 flex items-center gap-2 text-xs font-semibold">
                                        Failure excerpt
                                        <span className="font-mono font-normal text-tertiary">
                                            latest run #{group.latest_run_id}
                                        </span>
                                        <span className="ml-auto font-normal">
                                            <Link
                                                to={withSource(
                                                    urls.engineeringAnalyticsWorkflowRun(
                                                        group.repo.owner,
                                                        group.repo.name,
                                                        group.latest_run_id
                                                    ),
                                                    sourceId
                                                )}
                                            >
                                                Open run →
                                            </Link>
                                        </span>
                                    </div>
                                    <FailureLogGroups logs={logs} loading={failureLogsLoading} />
                                </div>
                            )
                        },
                    }}
                    columns={[
                        {
                            title: 'Workflow',
                            key: 'workflow',
                            render: (_, group) => (
                                <span className="flex items-center gap-2 font-medium">
                                    <span className="inline-block size-2 shrink-0 rounded-full bg-danger" />
                                    <Link
                                        to={withSource(
                                            urls.engineeringAnalyticsWorkflowRuns(
                                                group.repo.owner,
                                                group.repo.name,
                                                group.workflow_name
                                            ),
                                            sourceId
                                        )}
                                    >
                                        {group.workflow_name}
                                    </Link>
                                </span>
                            ),
                        },
                        {
                            title: 'What failed',
                            key: 'failedJob',
                            render: (_, group) =>
                                group.failed_job ? (
                                    <span className="font-mono text-[11px] text-secondary">{group.failed_job}</span>
                                ) : (
                                    <span className="text-xs text-tertiary">workflow-level (jobs not synced)</span>
                                ),
                        },
                        {
                            title: 'Runs',
                            key: 'runs',
                            align: 'right',
                            render: (_, group) =>
                                group.run_count > 1 ? (
                                    <LemonTag type="danger">×{group.run_count}</LemonTag>
                                ) : (
                                    <span className="tabular-nums text-tertiary">1</span>
                                ),
                        },
                        {
                            title: 'First seen',
                            key: 'firstSeen',
                            align: 'right',
                            render: (_, group) => (
                                <span className="text-xs text-tertiary whitespace-nowrap">
                                    <TZLabel time={group.first_seen} />
                                </span>
                            ),
                        },
                        {
                            title: 'Last seen',
                            key: 'lastSeen',
                            align: 'right',
                            render: (_, group) => (
                                <span className="text-xs text-tertiary whitespace-nowrap">
                                    <TZLabel time={group.last_seen} />
                                </span>
                            ),
                        },
                    ]}
                    emptyState={`Nothing failing on ${defaultBranch} in the last 24 hours.`}
                    nouns={['failure group', 'failure groups']}
                />
                <div className="border-t border-primary px-4 py-2 text-[11px] text-tertiary">
                    PR-branch failures appear on each pull request's page.
                </div>
            </LemonCard>
        </Section>
    )
}

export function RepoOverviewScene(): JSX.Element {
    const {
        overview,
        activityRuns,
        activityTruncated,
        repoActivityLoading,
        repoActivityFailed,
        attentionPrs,
        draftCount,
        costByWorkflow,
        otherCostWorkflowCount,
        costPerMergeSeries,
        jobsAvailable,
        defaultBranch,
        notConnected,
        overviewFailed,
        failingWorkflowCount,
        masterFailuresLoading,
    } = useValues(repoOverviewLogic)
    const {
        cards,
        pullRequestsLoading,
        workflowHealth,
        workflowHealthLoading,
        sourceId,
        costLensEnabled,
        activeSource,
    } = useValues(engineeringAnalyticsLogic)
    const { loadOverview, loadMasterFailures, loadRepoActivity } = useActions(repoOverviewLogic)
    const { searchParams } = useValues(router)

    if (notConnected) {
        return <ConnectGitHubSource />
    }
    if (overviewFailed) {
        return (
            <CIAnalyticsLoadError
                onRetry={() => {
                    loadOverview()
                    loadMasterFailures()
                    loadRepoActivity()
                }}
            />
        )
    }

    return (
        <div className="flex flex-col gap-4">
            {/* The entity header below is the repo identity — the scope bar only adds the source
                picker (multi-source teams) so the repo name isn't stated twice on one screen. */}
            <ScopeBar repoSlot={<SourceScopeChip pickerOnly />} />

            <RepoEntityHeader repoFullName={activeSource?.repo || ''} />

            <div className="flex flex-wrap gap-2.5">
                <MasterStatusTile
                    failingCount={failingWorkflowCount}
                    loading={masterFailuresLoading}
                    defaultBranch={defaultBranch}
                />
                <MetricTile
                    label="Pass rate"
                    tooltip="Workflow-level, across all branches."
                    value={percent(overview?.success_rate)}
                    delta={
                        <DeltaBadge
                            value={pointChange(overview?.success_rate, overview?.success_rate_prev)}
                            unit="pp"
                        />
                    }
                />
                <MetricTile
                    label="Runs"
                    value={compactCount(overview?.run_count)}
                    delta={<DeltaBadge value={percentChange(overview?.run_count, overview?.run_count_prev)} />}
                />
                <MetricTile
                    label="CI cost"
                    tooltip={
                        jobsAvailable
                            ? `Estimated: ${compactMinutes(overview?.billable_minutes)} billable × runner-tier rate.`
                            : 'Available once the job-level source is synced.'
                    }
                    value={jobsAvailable ? compactUsd(overview?.estimated_cost_usd) : '—'}
                    delta={
                        jobsAvailable ? (
                            <DeltaBadge
                                value={percentChange(overview?.estimated_cost_usd, overview?.estimated_cost_usd_prev)}
                                goodWhenDown
                            />
                        ) : undefined
                    }
                    sub={jobsAvailable ? undefined : 'Job-level source not synced'}
                />
                <MetricTile
                    label="Median PR open→merge"
                    tooltip="Created to merged, over PRs merged in the window. Bots and drafts excluded."
                    value={compactHours(overview?.median_open_to_merge_seconds)}
                    valueSuffix={compactHoursUnit(overview?.median_open_to_merge_seconds)}
                    delta={
                        <DeltaBadge
                            value={
                                overview?.median_open_to_merge_seconds != null &&
                                overview?.median_open_to_merge_seconds_prev != null
                                    ? (overview.median_open_to_merge_seconds -
                                          overview.median_open_to_merge_seconds_prev) /
                                      3600
                                    : null
                            }
                            unit="h"
                            goodWhenDown
                        />
                    }
                />
                <MetricTile
                    label="Re-run cycles"
                    tooltip="Runs with attempt > 1 in the window."
                    value={compactCount(overview?.rerun_cycles)}
                    delta={
                        <DeltaBadge
                            value={percentChange(overview?.rerun_cycles, overview?.rerun_cycles_prev)}
                            goodWhenDown
                        />
                    }
                />
            </div>

            <SectionNav
                items={[
                    { id: 'master', label: `${defaultBranch === 'main' ? 'Main' : 'Master'} health` },
                    { id: 'now', label: `Failing on ${defaultBranch}` },
                    { id: 'prs', label: 'Pull requests' },
                    { id: 'workflows', label: 'Workflows' },
                    { id: 'cost', label: 'Cost' },
                ]}
            />

            <Section id="master" title={`${defaultBranch === 'main' ? 'Main' : 'Master'} health`}>
                {/* One dot per commit to the default branch: X = when its CI started, Y = wall-clock CI
                    duration, color = the commit's overall verdict (red if any workflow failed). Replaces the
                    old success-rate line + failed-runs bar — the scatter says time, outcome, and cost at once. */}
                {hasEnoughRunActivity(activityRuns) ? (
                    <RunActivityChart
                        runs={activityRuns}
                        truncated={activityTruncated}
                        title={`Every ${defaultBranch} commit`}
                        noun="commit"
                    />
                ) : (
                    <LemonCard hoverEffect={false} className="p-4 text-xs text-secondary">
                        {repoActivityLoading
                            ? 'Loading…'
                            : repoActivityFailed
                              ? `Couldn't load ${defaultBranch} activity. Refresh to retry.`
                              : `Not enough completed runs on ${defaultBranch} in the window to chart yet.`}
                    </LemonCard>
                )}
            </Section>

            <MasterFailuresSection />

            <Section id="prs" title="Pull requests needing attention">
                <div className="mb-2 flex flex-wrap gap-2 text-xs text-secondary">
                    <span>
                        <strong className="text-primary">{cards ? humanFriendlyNumber(cards.openPrs) : '…'}</strong>{' '}
                        open
                    </span>
                    <span>·</span>
                    <span>
                        <strong className="text-primary">{humanFriendlyNumber(draftCount)}</strong> drafts
                    </span>
                    <span>·</span>
                    <span>
                        <strong className="text-danger">{cards ? humanFriendlyNumber(cards.failingCi) : '…'}</strong>{' '}
                        failing CI
                    </span>
                    <span>·</span>
                    <span>
                        <strong className="text-warning-dark">{cards ? humanFriendlyNumber(cards.stuck) : '…'}</strong>{' '}
                        stuck &gt;7d
                    </span>
                </div>
                <LemonCard hoverEffect={false} className="overflow-hidden p-0">
                    <PullRequestTable
                        rows={attentionPrs}
                        loading={pullRequestsLoading}
                        sourceId={sourceId}
                        costLensEnabled={costLensEnabled}
                        embedded
                        pageSize={HUB_TABLE_PAGE_SIZE}
                        emptyState="Nothing failing or stuck in the open backlog."
                        dataAttr="engineering-analytics-attention-prs"
                    />
                    <div className="border-t border-primary px-4 py-2 text-[11px] text-tertiary">
                        Showing {attentionPrs.length} of {cards ? humanFriendlyNumber(cards.openPrs) : '…'} open pull
                        requests ·{' '}
                        <Link to={withSource(urls.engineeringAnalyticsPullRequestList(), sourceId)}>View all</Link>
                    </div>
                </LemonCard>
            </Section>

            <Section id="workflows" title="Workflows">
                <LemonCard hoverEffect={false} className="overflow-hidden p-0">
                    <WorkflowHealthTable
                        rows={workflowHealth}
                        loading={workflowHealthLoading}
                        sourceId={sourceId}
                        showCost={jobsAvailable}
                        embedded
                        defaultSorting={{ columnKey: 'runCount', order: -1 }}
                        pageSize={HUB_TABLE_PAGE_SIZE}
                        emptyState="No workflow runs in the window."
                    />
                    <div className="border-t border-primary px-4 py-2 text-[11px] text-tertiary">
                        Showing top {Math.min(HUB_TABLE_PAGE_SIZE, workflowHealth.length)} of {workflowHealth.length}{' '}
                        workflows ·{' '}
                        <Link
                            to={
                                // A bare link would reset the shared window/branch scope (the filters logic
                                // re-hydrates from the URL on every route) — carry it, plus the source.
                                combineUrl(urls.engineeringAnalyticsWorkflows(), {
                                    ...(searchParams.date_from ? { date_from: searchParams.date_from } : {}),
                                    ...(searchParams.date_to ? { date_to: searchParams.date_to } : {}),
                                    ...(searchParams.q ? { q: searchParams.q } : {}),
                                    ...(sourceId ? { source: sourceId } : {}),
                                }).url
                            }
                        >
                            View all
                        </Link>
                    </div>
                </LemonCard>
            </Section>

            <Section id="cost" title="Cost">
                {jobsAvailable && costPerMergeSeries ? (
                    <LemonCard hoverEffect={false} className="mb-2 p-4">
                        <h3 className="mb-1 text-xs font-semibold text-secondary">Cost per merged PR</h3>
                        <Sparkline
                            data={costPerMergeSeries.values}
                            labels={costPerMergeSeries.labels}
                            name="Cost per merged PR"
                            type="line"
                            className="h-24 w-full"
                            renderLabel={(label) => label}
                            renderTooltipValue={(value) => compactUsd(value)}
                        />
                        <div className="mt-2 border-t border-primary pt-2 text-[11px] text-tertiary">
                            Estimated Depot CI cost per PR merged. Each point divides a trailing window's CI cost by its
                            merges (24 h, 7 d, or 4 w to match the grain), so quiet buckets don't punch holes in the
                            trend. Cost counts by run start, merges by merge time — the same coarse split the daily
                            depot tooling uses.
                        </div>
                    </LemonCard>
                ) : null}
                {jobsAvailable && costByWorkflow.length > 0 ? (
                    <LemonCard hoverEffect={false} className="p-4">
                        <h3 className="mb-1 text-xs font-semibold text-secondary">By workflow</h3>
                        {costByWorkflow.map((row, i) => (
                            <ShareRow
                                key={row.workflowName ?? 'other'}
                                label={row.workflowName ?? `Other (${otherCostWorkflowCount} workflows)`}
                                value={compactUsd(row.costUsd)}
                                valueSub={`${Math.round(row.share * 100)}% of total`}
                                share={row.share}
                                color={row.workflowName ? SHARE_COLORS[i % SHARE_COLORS.length] : 'var(--muted)'}
                                to={
                                    row.workflowName && workflowHealth.length
                                        ? withSource(
                                              urls.engineeringAnalyticsWorkflowRuns(
                                                  workflowHealth[0].repoOwner,
                                                  workflowHealth[0].repoName,
                                                  row.workflowName
                                              ),
                                              sourceId
                                          )
                                        : undefined
                                }
                            />
                        ))}
                        <div className="mt-2 border-t border-primary pt-2 text-[11px] text-tertiary">
                            Estimated from billable job minutes × runner-tier rate. GitHub-hosted runners are free for
                            open source.
                        </div>
                    </LemonCard>
                ) : (
                    <LemonCard hoverEffect={false} className="p-4 text-xs text-secondary">
                        {jobsAvailable
                            ? 'No costable jobs in the window.'
                            : 'Cost data will appear once the job-level source (github_workflow_jobs) is synced.'}
                    </LemonCard>
                )}
            </Section>
        </div>
    )
}
