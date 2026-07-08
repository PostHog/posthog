// The repo hub landing page: stat tiles with deltas, then master health, failing runs, PRs needing
// attention, workflows, and cost as sections on one page.

import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { ReactNode } from 'react'

import { IconBox } from '@posthog/icons'
import { LemonButton, LemonCard, LemonSkeleton, LemonTable, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

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
import { hasEnoughRunActivity } from '../components/RunActivityChart'
import { RunActivityMiniBars } from '../components/RunActivityMiniBars'
import { ScopeDateFilter, SourceScopeChip } from '../components/ScopeBar'
import { Section, scrollToSection } from '../components/Section'
import { WorkflowHealthTable } from '../components/WorkflowHealthTable'
import type { MasterFailureGroupApi } from '../generated/api.schemas'
import { compactCount, compactHours, compactHoursUnit, compactMinutes, compactUsd, percent } from '../lib/format'
import { HUB_PREVIEW_MAX } from '../lib/preview'
import { engineeringAnalyticsLogic } from './engineeringAnalyticsLogic'
import { repoOverviewLogic } from './repoOverviewLogic'

function withSource(url: string, sourceId: string | null): string {
    return combineUrl(url, sourceId ? { source: sourceId } : {}).url
}

function RepoEntityHeader({ repoFullName, right }: { repoFullName: string; right?: ReactNode }): JSX.Element {
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
            right={right}
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
        costPerMergeSeries,
        jobsAvailable,
        defaultBranch,
        notConnected,
        overviewFailed,
        overviewLoading,
        failingWorkflowCount,
        masterFailuresLoading,
        prPreviewCount,
        workflowPreviewCount,
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
    const { loadOverview, loadMasterFailures, loadRepoActivity, showMorePrs, showMoreWorkflows } =
        useActions(repoOverviewLogic)
    const { searchParams } = useValues(router)

    // The hub previews each table: a short, sorted slice with "Show more" to grow in place, and "View all"
    // to the dedicated full table. Workflows are sorted by run count here so the preview is the busiest few,
    // matching the table's default sort; attentionPrs is already ordered failing-first in the selector.
    const shownPrs = attentionPrs.slice(0, prPreviewCount)
    const canShowMorePrs = shownPrs.length < attentionPrs.length && prPreviewCount < HUB_PREVIEW_MAX
    // Rank the leaderboard by spend when cost is known (where the money goes), else by run volume.
    const rankedWorkflows = jobsAvailable
        ? [...workflowHealth].sort((a, b) => (b.estimatedCostUsd ?? -1) - (a.estimatedCostUsd ?? -1))
        : [...workflowHealth].sort((a, b) => b.runCount - a.runCount)
    const shownWorkflows = rankedWorkflows.slice(0, workflowPreviewCount)
    const canShowMoreWorkflows = shownWorkflows.length < workflowHealth.length && workflowPreviewCount < HUB_PREVIEW_MAX

    // jobsAvailable reads false until the overview payload lands, so "not synced" messaging
    // during the initial fetch would misread as a broken setup — hold it back while loading.
    const overviewPending = overviewLoading && !overview

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
            {/* Repo identity, with the shared window picker (and source picker on multi-source teams) docked
                on its right — no separate scope-bar row above the tiles. */}
            <RepoEntityHeader
                repoFullName={activeSource?.repo || ''}
                right={
                    <>
                        <SourceScopeChip pickerOnly />
                        <ScopeDateFilter />
                    </>
                }
            />

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
                            : overviewPending
                              ? undefined
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
                    sub={jobsAvailable || overviewPending ? undefined : 'Job-level source not synced'}
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

            <Section id="master" title={`${defaultBranch === 'main' ? 'Main' : 'Master'} health`}>
                {/* Hub preview: one bar per default-branch commit, height = CI duration, color = verdict — the
                    at-a-glance "is master healthy and fast lately" read without the full chart's weight. The
                    full scatter (start-time axis, in-flight band, zoom) lives on the workflow page. */}
                {hasEnoughRunActivity(activityRuns) ? (
                    <RunActivityMiniBars
                        runs={activityRuns}
                        truncated={activityTruncated}
                        title="CI duration per commit"
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
                        rows={shownPrs}
                        loading={pullRequestsLoading}
                        sourceId={sourceId}
                        costLensEnabled={costLensEnabled}
                        embedded
                        pageSize={HUB_PREVIEW_MAX}
                        emptyState="Nothing failing or stuck in the open backlog."
                        dataAttr="engineering-analytics-attention-prs"
                    />
                    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-primary px-4 py-2 text-[11px] text-tertiary">
                        <span>
                            Showing {shownPrs.length} of {humanFriendlyNumber(attentionPrs.length)} needing attention
                        </span>
                        <div className="flex items-center gap-3">
                            {canShowMorePrs && (
                                <LemonButton size="xsmall" onClick={showMorePrs}>
                                    Show more
                                </LemonButton>
                            )}
                            <Link to={withSource(urls.engineeringAnalyticsPullRequestList(), sourceId)}>
                                View all →
                            </Link>
                        </div>
                    </div>
                </LemonCard>
            </Section>

            <Section id="workflows" title="Workflows">
                <LemonCard hoverEffect={false} className="overflow-hidden p-0">
                    <WorkflowHealthTable
                        rows={shownWorkflows}
                        loading={workflowHealthLoading}
                        sourceId={sourceId}
                        showCost={jobsAvailable}
                        embedded
                        compact
                        pageSize={HUB_PREVIEW_MAX}
                        emptyState="No workflow runs in the window."
                    />
                    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-primary px-4 py-2 text-[11px] text-tertiary">
                        <span>
                            Showing top {shownWorkflows.length} of {workflowHealth.length} workflows
                        </span>
                        <div className="flex items-center gap-3">
                            {canShowMoreWorkflows && (
                                <LemonButton size="xsmall" onClick={showMoreWorkflows}>
                                    Show more
                                </LemonButton>
                            )}
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
                                View all →
                            </Link>
                        </div>
                    </div>
                </LemonCard>
            </Section>

            <Section id="cost" title="Cost">
                {overviewPending ? (
                    <LemonCard hoverEffect={false} className="p-4">
                        <LemonSkeleton className="mb-3 h-4 w-40" />
                        <LemonSkeleton className="h-24 w-full" />
                    </LemonCard>
                ) : jobsAvailable && costPerMergeSeries ? (
                    <LemonCard hoverEffect={false} className="p-4">
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
                            depot tooling uses. Per-workflow spend is in the Workflows leaderboard above.
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
