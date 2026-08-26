// The repo hub landing page: the window-scoped sections (CI health, merge queue, master health,
// workflows) inside a panel whose rim carries the date filter, then the current-state PR backlog
// below it.

import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton, LemonCard, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { CIAnalyticsLoadError } from '../components/CIAnalyticsLoadError'
import { ConnectGitHubSource } from '../components/ConnectGitHubSource'
import { RepoEntityHeader } from '../components/EntityHeader'
import { PullRequestTable } from '../components/PullRequestTable'
import { formatAxisMinutes, hasEnoughRunActivity } from '../components/RunActivityChart'
import { RunActivityMiniBars } from '../components/RunActivityMiniBars'
import { ScopeDateFilter, SourceScopeChip } from '../components/ScopeBar'
import { Section } from '../components/Section'
import { WindowComparisonCard } from '../components/WindowComparisonCard'
import { WorkflowHealthTable } from '../components/WorkflowHealthTable'
import { compactAgeLabel, compactHoursLabel, compactMinutes, compactUsd, percent } from '../lib/format'
import { githubCommitUrl } from '../lib/github'
import { HUB_PREVIEW_MAX } from '../lib/preview'
import { withCurrentScope, withScope } from '../lib/scope'
import { engineeringAnalyticsLogic } from './engineeringAnalyticsLogic'
import { repoOverviewLogic } from './repoOverviewLogic'

export function RepoOverviewScene(): JSX.Element {
    const {
        overview,
        activityRuns,
        activityTruncated,
        repoActivityLoading,
        repoActivityFailed,
        attentionPrs,
        jobsAvailable,
        overviewDefaultBranch,
        notConnected,
        overviewFailed,
        overviewLoading,
        prPreviewCount,
        workflowPreviewCount,
    } = useValues(repoOverviewLogic)
    const { pullRequestsLoading, workflowHealth, workflowHealthLoading, sourceId, activeSource } =
        useValues(engineeringAnalyticsLogic)
    const { loadOverview, loadRepoActivity, showMorePrs, showMoreWorkflows } = useActions(repoOverviewLogic)
    const { searchParams } = useValues(router)

    // Window/source changes reload the overview, activity, and workflow health (the date-scoped
    // surfaces); the PR backlog is current-state, not windowed, so it stays put. Surface the reload
    // so a window change doesn't silently swap stale numbers.
    const hubReloading = overviewLoading || repoActivityLoading || workflowHealthLoading

    // The hub previews each table: a short, sorted slice with "Show more" to grow in place, and "View all"
    // to the dedicated full table. Workflows are ranked by cost (or run count) to pick the top few; the
    // table then displays them failing-first-then-name. attentionPrs is already ordered failing-first.
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

    const asMinutes = (seconds: number | null | undefined): number | null => (seconds != null ? seconds / 60 : null)

    // Cycle time is ready→merge wherever the backend can observe the draft/ready transitions. Without
    // them it falls back to the coarse created→merged span and says so, rather than labelling one
    // measure with the other's name.
    const cycleTime =
        overview?.median_ready_to_merge_seconds != null
            ? {
                  title: 'Median time from ready for review to merge',
                  value: overview.median_ready_to_merge_seconds,
                  previousValue: overview.median_ready_to_merge_seconds_prev,
                  tooltip:
                      'Median ready-for-review to merged time, bots and drafts excluded. Time as a draft is not counted.',
              }
            : {
                  title: 'Median time from open to merge',
                  value: overview?.median_open_to_merge_seconds,
                  previousValue: overview?.median_open_to_merge_seconds_prev,
                  tooltip:
                      'Median created-to-merged time, bots and drafts excluded. Coarse: draft and ready time are fused.',
              }

    if (notConnected) {
        return <ConnectGitHubSource />
    }
    if (overviewFailed) {
        return (
            <CIAnalyticsLoadError
                onRetry={() => {
                    loadOverview()
                    loadRepoActivity()
                }}
            />
        )
    }

    return (
        <div className="flex flex-col gap-4">
            <RepoEntityHeader repoFullName={activeSource?.repo || ''} />

            {/* The panel is the scope: the controls sit on its rim, and everything inside reflects
                their window. The PR backlog below the panel is current-state, not windowed. */}
            <div className="relative mt-4 rounded-lg border border-primary p-4">
                <div className="absolute -top-4 right-3 flex flex-wrap items-center justify-end gap-2 bg-primary px-2">
                    {hubReloading && <Spinner className="text-secondary" />}
                    <SourceScopeChip pickerOnly />
                    <ScopeDateFilter />
                </div>
                <div className="flex flex-col gap-4 pt-2">
                    {/* The windowed headline metrics: each card compares this window against the previous
                        one directly (two values), not as a time series. CI cost is a window total, not a
                        rate, so its number lives on the Workflows section below. */}
                    <Section id="ci-health" title="CI health" busy={overviewLoading}>
                        <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                            <WindowComparisonCard
                                title="CI runs that passed"
                                value={overview?.success_rate}
                                previousValue={overview?.success_rate_prev}
                                formatValue={percent}
                                share
                                deltaUnit="pt"
                                loading={overviewPending}
                                tooltip="Share of completed CI runs that passed, all branches."
                                emptyText="Not enough completed CI runs in the window yet."
                            />

                            <WindowComparisonCard
                                title="Median time from push to all checks green"
                                value={asMinutes(overview?.median_time_to_green_seconds)}
                                previousValue={asMinutes(overview?.median_time_to_green_seconds_prev)}
                                formatValue={formatAxisMinutes}
                                goodWhenDown
                                loading={overviewPending}
                                tooltip="Median time from a push until every workflow on it is green. Only fully green pushes count."
                                emptyText="No fully green PR pushes in the window yet."
                            />

                            <WindowComparisonCard
                                title={cycleTime.title}
                                value={cycleTime.value}
                                previousValue={cycleTime.previousValue}
                                formatValue={compactHoursLabel}
                                goodWhenDown
                                loading={overviewPending}
                                tooltip={cycleTime.tooltip}
                                emptyText="No PRs merged in the window yet."
                            />

                            <WindowComparisonCard
                                title="CI cost per merged PR"
                                value={overview?.cost_per_merge_usd}
                                previousValue={overview?.cost_per_merge_usd_prev}
                                formatValue={compactUsd}
                                goodWhenDown
                                loading={overviewPending}
                                emptyText={
                                    !jobsAvailable
                                        ? 'Cost appears once the job-level source is synced.'
                                        : overview?.merged_pr_count === 0
                                          ? 'Nothing merged in the window.'
                                          : 'No costable jobs in the window.'
                                }
                                tooltip="Estimated Depot CI cost per merged PR. Per-workflow spend is in Workflows below."
                            />
                        </div>
                    </Section>

                    <Section id="merge-queue" title="Merge queue" busy={overviewLoading}>
                        {overview &&
                        overview.merge_queue_merged_pr_count === 0 &&
                        overview.merge_queue_failed_or_cancelled_share == null ? (
                            <LemonCard hoverEffect={false} className="p-4 text-xs text-secondary">
                                No merge queue activity in the window.
                            </LemonCard>
                        ) : (
                            <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
                                <WindowComparisonCard
                                    title="Median time in the merge queue"
                                    tooltip="From a PR's first merge queue gate run starting to the PR merging. Waiting before gate testing starts is not included. The tick marks the p90."
                                    value={overview?.merge_queue_median_first_gate_to_merge_seconds}
                                    previousValue={overview?.merge_queue_median_first_gate_to_merge_seconds_prev}
                                    formatValue={compactAgeLabel}
                                    goodWhenDown
                                    marker={overview?.merge_queue_p90_first_gate_to_merge_seconds}
                                    markerPrevious={overview?.merge_queue_p90_first_gate_to_merge_seconds_prev}
                                    markerLabel="p90"
                                    loading={overviewPending}
                                    emptyText="No queue-landed merges in the window."
                                />
                                <WindowComparisonCard
                                    title="Merges retried in the queue"
                                    tooltip="Share of queue-landed merges that needed more than one gate attempt. Bisection branches count toward the attempt they investigate."
                                    value={overview?.merge_queue_multi_attempt_merge_share}
                                    previousValue={overview?.merge_queue_multi_attempt_merge_share_prev}
                                    formatValue={percent}
                                    deltaUnit="pt"
                                    goodWhenDown
                                    loading={overviewPending}
                                    emptyText="No queue-landed merges in the window."
                                />
                                {overview?.merge_queue_trunk_available ? (
                                    <WindowComparisonCard
                                        title="Left the queue unmerged"
                                        tooltip="Share of concluded merge queue entries that ended failed or cancelled, from the queue's own records."
                                        value={overview?.merge_queue_failed_or_cancelled_share}
                                        previousValue={overview?.merge_queue_failed_or_cancelled_share_prev}
                                        formatValue={(v) => percent(v, 1)}
                                        deltaUnit="pt"
                                        goodWhenDown
                                        loading={overviewPending}
                                        emptyText="No concluded queue entries in the window."
                                    />
                                ) : (
                                    <WindowComparisonCard
                                        title="Merges with a failed queue run"
                                        tooltip="Share of queue-landed merges where at least one gate run failed before the merge. Derived from CI run conclusions, not the queue's own eviction records."
                                        value={overview?.merge_queue_failed_gate_merge_share}
                                        previousValue={overview?.merge_queue_failed_gate_merge_share_prev}
                                        formatValue={percent}
                                        deltaUnit="pt"
                                        goodWhenDown
                                        loading={overviewPending}
                                        emptyText="No queue-landed merges in the window."
                                    />
                                )}
                            </div>
                        )}
                    </Section>

                    <Section
                        id="master"
                        title={`${overviewDefaultBranch === 'main' ? 'Main' : 'Master'} health`}
                        busy={repoActivityLoading}
                    >
                        {/* Hub preview: one bar per default-branch commit, height = CI duration, color = verdict — the
                    at-a-glance "is master healthy and fast lately" read without the full chart's weight. The
                    full scatter (start-time axis, in-flight band, zoom) lives on the workflow page. */}
                        {hasEnoughRunActivity(activityRuns) ? (
                            <RunActivityMiniBars
                                runs={activityRuns}
                                truncated={activityTruncated}
                                title="CI duration per commit"
                                noun="commit"
                                onBarClick={(run) => {
                                    // Each bar is a whole commit (its workflows collapsed), so open the commit on
                                    // GitHub — all its checks — rather than one arbitrary workflow run.
                                    const [owner, repoName] = (activeSource?.repo || '').split('/')
                                    if (!run.headSha || !owner || !repoName) {
                                        return
                                    }
                                    window.open(
                                        githubCommitUrl(owner, repoName, run.headSha),
                                        '_blank',
                                        'noopener,noreferrer'
                                    )
                                }}
                            />
                        ) : (
                            <LemonCard hoverEffect={false} className="p-4 text-xs text-secondary">
                                {repoActivityLoading
                                    ? 'Loading…'
                                    : repoActivityFailed
                                      ? `Couldn't load ${overviewDefaultBranch} activity. Refresh to retry.`
                                      : `Not enough completed runs on ${overviewDefaultBranch} in the window to chart yet.`}
                            </LemonCard>
                        )}
                    </Section>

                    <Section
                        id="workflows"
                        title={jobsAvailable ? 'Top workflows by cost' : 'Busiest workflows'}
                        right={
                            jobsAvailable && overview?.estimated_cost_usd != null ? (
                                <Tooltip
                                    title={`Estimated: ${compactMinutes(overview?.billable_minutes)} billable × runner-tier rate, across all workflows in the window.`}
                                >
                                    <span className="cursor-default text-tertiary">
                                        {compactUsd(overview.estimated_cost_usd)} total CI spend
                                    </span>
                                </Tooltip>
                            ) : undefined
                        }
                    >
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
                                            // A bare link would reset the shared window / branch / repo scope (the filters
                                            // logic re-hydrates from the URL on every route) — carry it, plus the source.
                                            withScope(urls.engineeringAnalyticsWorkflows(), searchParams, sourceId)
                                        }
                                    >
                                        View all →
                                    </Link>
                                </div>
                            </div>
                        </LemonCard>
                    </Section>
                </div>
            </div>

            <Section
                id="prs"
                title="Pull requests needing attention"
                note="Current open backlog. Not affected by the date range."
            >
                <LemonCard hoverEffect={false} className="overflow-hidden p-0">
                    <PullRequestTable
                        rows={shownPrs}
                        loading={pullRequestsLoading}
                        sourceId={sourceId}
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
                            <Link to={withCurrentScope(urls.engineeringAnalyticsPullRequestList(), sourceId)}>
                                View all →
                            </Link>
                        </div>
                    </div>
                </LemonCard>
            </Section>
        </div>
    )
}
