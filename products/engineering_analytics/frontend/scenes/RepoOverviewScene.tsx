// The repo hub landing page: stat tiles with deltas, then master health, failing runs, PRs needing
// attention, workflows, and cost as sections on one page.

import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { ReactNode } from 'react'

import { IconBox } from '@posthog/icons'
import { LemonButton, LemonCard, LemonTable, LemonTag, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { CIAnalyticsLoadError } from '../components/CIAnalyticsLoadError'
import { ConnectGitHubSource } from '../components/ConnectGitHubSource'
import { EntityHeader } from '../components/EntityHeader'
import { FailureLogGroups } from '../components/FailureLogs'
import { PullRequestTable } from '../components/PullRequestTable'
import { formatAxisMinutes, hasEnoughRunActivity } from '../components/RunActivityChart'
import { RunActivityMiniBars } from '../components/RunActivityMiniBars'
import { ScopeDateFilter, SourceScopeChip } from '../components/ScopeBar'
import { Section, scrollToSection } from '../components/Section'
import { TrendCard } from '../components/TrendCard'
import { WorkflowHealthTable } from '../components/WorkflowHealthTable'
import type { MasterFailureGroupApi } from '../generated/api.schemas'
import { compactHoursLabel, compactMinutes, compactUsd, percent } from '../lib/format'
import { githubCommitUrl } from '../lib/github'
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

/** A right-now backlog count in the hero: number over a small label, colored only when it's a pressure. */
function HeroStat({
    label,
    value,
    tone = 'default',
}: {
    label: string
    value: number | null | undefined
    tone?: 'default' | 'danger' | 'warning'
}): JSX.Element {
    const pressing = value != null && value > 0
    const color =
        pressing && tone === 'danger'
            ? 'text-danger'
            : pressing && tone === 'warning'
              ? 'text-warning-dark'
              : 'text-primary'
    return (
        <div className="flex flex-col items-end">
            <span className={cn('text-xl font-semibold leading-none tabular-nums', color)}>
                {value == null ? '—' : humanFriendlyNumber(value)}
            </span>
            <span className="mt-1 text-[11px] text-tertiary whitespace-nowrap">{label}</span>
        </div>
    )
}

/** The page's thesis: is the pipeline healthy right now? Default-branch verdict plus open-PR backlog
 *  pressure, both current-state, so it sits above the date filter that scopes everything below. */
function PipelineVerdictHero({
    failingCount,
    failingWorkflows,
    loading,
    defaultBranch,
    backlog,
}: {
    failingCount: number
    failingWorkflows: string[]
    loading: boolean
    defaultBranch: string
    backlog: { open: number | null; failingCi: number | null; stuck: number | null }
}): JSX.Element {
    const failing = failingCount > 0
    const dotColor = loading ? 'var(--muted)' : failing ? 'var(--danger)' : 'var(--success)'
    const status = loading ? 'Checking' : failing ? `${failingCount} failing` : 'Passing'
    // Only the failing state earns a subline (which workflows broke). "Passing" already says the rest.
    const failingNames = failingWorkflows.slice(0, 3).join(', ') + (failingCount > 3 ? ` +${failingCount - 3}` : '')
    return (
        <LemonCard
            hoverEffect={failing}
            onClick={failing ? () => scrollToSection('now') : undefined}
            className={cn(
                'flex flex-wrap items-center justify-between gap-x-8 gap-y-4 px-6 py-5',
                failing && 'bg-fill-error-tertiary'
            )}
        >
            <div className="flex min-w-0 flex-col gap-1.5">
                <Tooltip title="Default-branch workflow runs failing in the last 24 hours.">
                    <span className="w-fit cursor-default font-mono text-xs text-tertiary">{defaultBranch}</span>
                </Tooltip>
                <span className="flex items-baseline gap-2.5">
                    <span
                        className="inline-block size-2.5 shrink-0 translate-y-[-0.15em] rounded-full"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ backgroundColor: dotColor }}
                    />
                    <span
                        className={cn(
                            'text-3xl font-bold leading-none tracking-tight',
                            loading ? 'text-tertiary' : failing ? 'text-danger' : 'text-primary'
                        )}
                    >
                        {status}
                    </span>
                    {failing && <span className="text-sm font-medium text-danger">View →</span>}
                </span>
                {failing && <span className="truncate text-xs text-secondary">{failingNames}</span>}
            </div>
            <div className="flex items-center gap-6">
                <HeroStat label="Open PRs" value={backlog.open} />
                <HeroStat label="Failing CI" value={backlog.failingCi} tone="danger" />
                <HeroStat label="Stuck >7d" value={backlog.stuck} tone="warning" />
            </div>
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
        costPerMergeSeries,
        timeToGreenSeries,
        passRateSeries,
        openToMergeSeries,
        jobsAvailable,
        defaultBranch,
        notConnected,
        overviewFailed,
        overviewLoading,
        failingWorkflowCount,
        masterFailures,
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

    // Window/source changes reload the overview, activity, and workflow health (the date-scoped surfaces);
    // the PR backlog is current-state, not windowed, so it stays put. Surface the reload so a window change
    // doesn't silently swap stale numbers.
    const hubReloading = overviewLoading || repoActivityLoading || workflowHealthLoading

    // The hub previews each table: a short, sorted slice with "Show more" to grow in place, and "View all"
    // to the dedicated full table. Workflows are sorted by run count here so the preview is the busiest few,
    // matching the table's default sort; attentionPrs is already ordered failing-first in the selector.
    // Distinct workflow names failing on the default branch — the hero's "what's broken" subline.
    const failingWorkflows = Array.from(new Set(masterFailures.map((group) => group.workflow_name)))
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
            {/* Repo identity. The scope controls used to dock here; they now sit below the verdict hero, so
                the date filter visibly governs only the windowed surfaces beneath it. */}
            <RepoEntityHeader repoFullName={activeSource?.repo || ''} />

            {/* The thesis: is the pipeline healthy right now? Current-state, above the date filter. */}
            <PipelineVerdictHero
                failingCount={failingWorkflowCount}
                failingWorkflows={failingWorkflows}
                loading={masterFailuresLoading}
                defaultBranch={defaultBranch}
                backlog={{
                    open: cards?.openPrs ?? null,
                    failingCi: cards?.failingCi ?? null,
                    stuck: cards?.stuck ?? null,
                }}
            />

            {/* Now zone: current-state surfaces above the filter. The hero owns the backlog summary, so this
                section is just the triage table. */}
            <MasterFailuresSection />

            <Section id="prs" title="Pull requests needing attention">
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

                    {/* Median time-to-green on PR runs (success-only, PR-scoped; see #67398). */}
                    <TrendCard
                        title="PR time to green"
                        series={timeToGreenSeries}
                        formatValue={formatAxisMinutes}
                        renderTooltipValue={formatAxisMinutes}
                        goodWhenDown
                        loading={overviewPending}
                        emptyText="Not enough successful PR CI runs in the window yet."
                        caption="Median time-to-green on pull requests: successful runs only, default branch excluded."
                    />

                    {/* PR throughput: coarse created→merged time, bots and drafts excluded. */}
                    <TrendCard
                        title="Median PR open→merge"
                        series={openToMergeSeries}
                        formatValue={compactHoursLabel}
                        renderTooltipValue={compactHoursLabel}
                        goodWhenDown
                        loading={overviewPending}
                        emptyText="No PRs merged in the window yet."
                        caption="Median created-to-merged time, bots and drafts excluded. Coarse: draft and ready time are fused."
                    />

                    {/* CI cost per merged PR. */}
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
                title={`${defaultBranch === 'main' ? 'Main' : 'Master'} health`}
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
                              ? `Couldn't load ${defaultBranch} activity. Refresh to retry.`
                              : `Not enough completed runs on ${defaultBranch} in the window to chart yet.`}
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
        </div>
    )
}
