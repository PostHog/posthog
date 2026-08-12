// The repo hub landing page: PRs needing attention, then windowed trends, master health, and
// workflows as sections on one page.

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
import { TrendCard } from '../components/TrendCard'
import { WorkflowHealthTable } from '../components/WorkflowHealthTable'
import { compactHoursLabel, compactMinutes, compactUsd, percent } from '../lib/format'
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
        costPerMergeSeries,
        timeToGreenSeries,
        passRateSeries,
        openToMergeSeries,
        readyToMergeSeries,
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

    // Cycle time is ready→merge wherever the backend can observe the draft/ready transitions. Without
    // them it falls back to the coarse created→merged span and says so, rather than labelling one
    // measure with the other's name.
    const cycleTime = readyToMergeSeries
        ? {
              title: 'Median PR ready→merge',
              series: readyToMergeSeries,
              caption:
                  'Median ready-for-review to merged time, bots and drafts excluded. Time as a draft is not counted.',
          }
        : {
              title: 'Median PR open→merge',
              series: openToMergeSeries,
              caption:
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
            {/* Repo identity. The scope controls dock below the PR table, so the date filter visibly
                governs only the windowed surfaces beneath it. */}
            <RepoEntityHeader repoFullName={activeSource?.repo || ''} />

            <Section id="prs" title="Pull requests needing attention">
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

            {/* The filter is the seam: everything above is current-state, everything below reflects its window. */}
            <div className="mt-1 flex flex-wrap items-center justify-end gap-2 border-t border-primary pt-4">
                {hubReloading && <Spinner className="text-secondary" />}
                <SourceScopeChip pickerOnly />
                <ScopeDateFilter />
            </div>

            {/* The windowed headline metrics, each a value + colored delta over a sentiment-colored sparkline.
                CI cost is a window total, not a rate, so its number lives on the Workflows section below. */}
            <Section id="trends" title="Trends" busy={overviewLoading}>
                <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                    {/* CI health: share of completed runs that passed, all branches. */}
                    <TrendCard
                        title="Pass rate"
                        series={passRateSeries}
                        formatValue={(value) => percent(value)}
                        renderTooltipValue={(value) => percent(value, 1)}
                        loading={overviewPending}
                        emptyText="Not enough completed CI runs in the window yet."
                        caption="Share of completed CI runs that passed, all branches."
                    />

                    <TrendCard
                        title="PR time to green"
                        series={timeToGreenSeries}
                        formatValue={formatAxisMinutes}
                        renderTooltipValue={formatAxisMinutes}
                        goodWhenDown
                        loading={overviewPending}
                        emptyText="No fully green PR pushes in the window yet."
                        caption="Median time from a push until every workflow on it is green. Only fully green pushes count."
                    />

                    <TrendCard
                        title={cycleTime.title}
                        series={cycleTime.series}
                        formatValue={compactHoursLabel}
                        renderTooltipValue={compactHoursLabel}
                        goodWhenDown
                        loading={overviewPending}
                        emptyText="No PRs merged in the window yet."
                        caption={cycleTime.caption}
                    />

                    <TrendCard
                        title="Cost per merged PR"
                        series={jobsAvailable ? costPerMergeSeries : null}
                        formatValue={compactUsd}
                        renderTooltipValue={compactUsd}
                        goodWhenDown
                        loading={overviewPending}
                        emptyText={
                            jobsAvailable
                                ? 'No costable jobs in the window.'
                                : 'Cost appears once the job-level source is synced.'
                        }
                        caption="Estimated Depot CI cost per merged PR, trailing-window ratio. Per-workflow spend is in Workflows below."
                    />
                </div>
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
                            window.open(githubCommitUrl(owner, repoName, run.headSha), '_blank', 'noopener,noreferrer')
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
    )
}
