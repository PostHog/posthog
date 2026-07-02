// The repo hub — the landing page of the lens stack. One entity-page skeleton: scope bar → stat tiles
// with deltas → section jumper → fixed section rhythm (failing on master, master health, PRs needing
// attention, workflows, cost, authors). Facets are sections here, not tabs.

import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconBox } from '@posthog/icons'
import { LemonCard, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'
import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { CIAnalyticsLoadError } from '../components/CIAnalyticsLoadError'
import { ConnectGitHubSource } from '../components/ConnectGitHubSource'
import { EntityHeader, VerdictPill } from '../components/EntityHeader'
import { FailureLogGroups } from '../components/FailureLogs'
import { DeltaBadge, MetricTile, percentChange, pointChange } from '../components/MetricTile'
import { PullRequestTable } from '../components/PullRequestTable'
import { ScopeBar, SourceScopeChip } from '../components/ScopeBar'
import { Section, SectionNav } from '../components/Section'
import { ShareRow } from '../components/ShareRow'
import { WorkflowHealthTable } from '../components/WorkflowHealthTable'
import type { GitHubSourceApi, MasterFailureGroupApi } from '../generated/api.schemas'
import { compactCount, compactHours, compactHoursUnit, compactMinutes, compactUsd, percent } from '../lib/format'
import { engineeringAnalyticsLogic } from './engineeringAnalyticsLogic'
import { repoOverviewLogic } from './repoOverviewLogic'

const SHARE_COLORS = ['var(--brand-blue)', 'var(--success)', 'var(--warning)', 'var(--purple)', 'var(--danger)']

function withSource(url: string, sourceId: string | null): string {
    return combineUrl(url, sourceId ? { source: sourceId } : {}).url
}

function RepoEntityHeader({
    repoFullName,
    failingWorkflowCount,
    failuresLoading,
    defaultBranch,
}: {
    repoFullName: string
    failingWorkflowCount: number
    failuresLoading: boolean
    defaultBranch: string
}): JSX.Element {
    const name = repoFullName.split('/')[1] || repoFullName || 'Repository'
    return (
        <EntityHeader
            icon={<IconBox />}
            title={name}
            slug={
                <>
                    {repoFullName || 'connected GitHub source'}
                    {repoFullName && (
                        <>
                            {' · '}
                            <Link to={`https://github.com/${repoFullName}`} target="_blank" targetBlankIcon>
                                View on GitHub
                            </Link>
                        </>
                    )}
                </>
            }
            right={
                failuresLoading ? undefined : failingWorkflowCount > 0 ? (
                    <VerdictPill kind="danger">
                        {failingWorkflowCount === 1
                            ? `1 workflow failing on ${defaultBranch}`
                            : `${failingWorkflowCount} workflows failing on ${defaultBranch}`}
                    </VerdictPill>
                ) : (
                    <VerdictPill kind="success">Nothing failing on {defaultBranch}</VerdictPill>
                )
            }
        />
    )
}

function MasterFailuresSection(): JSX.Element {
    const { masterFailures, masterFailuresLoading, failureLogs, failureLogsLoading, defaultBranch } =
        useValues(repoOverviewLogic)
    const { loadLogsForRun } = useActions(repoOverviewLogic)
    const { sourceId } = useValues(engineeringAnalyticsLogic)

    return (
        <Section
            id="now"
            title={`Failing on ${defaultBranch}`}
            note="last 24 hours, grouped by workflow and failing job — expand a group for its failure logs"
        >
            <LemonCard hoverEffect={false} className="p-0">
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
                                    <FailureLogGroups
                                        jobs={logs === 'unavailable' ? [] : logs?.jobs}
                                        logsAvailable={logs !== 'unavailable' && (logs?.logs_available ?? false)}
                                        loading={failureLogsLoading}
                                        emptyState={
                                            logs === 'unavailable'
                                                ? 'Failure logs are unavailable for this run.'
                                                : undefined
                                        }
                                    />
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
                    PR-branch failures are deliberately not listed here — they surface on each pull request page and in
                    the attention slice below.
                </div>
            </LemonCard>
        </Section>
    )
}

export function RepoOverviewScene(): JSX.Element {
    const {
        overview,
        overviewLoading,
        masterHealth,
        attentionPrs,
        draftCount,
        costByWorkflow,
        otherCostWorkflowCount,
        authorsByActivity,
        authorsByCost,
        authorCount,
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
        githubSources,
    } = useValues(engineeringAnalyticsLogic)
    const { loadOverview, loadMasterFailures } = useActions(repoOverviewLogic)

    if (notConnected) {
        return <ConnectGitHubSource />
    }
    if (overviewFailed) {
        return (
            <CIAnalyticsLoadError
                onRetry={() => {
                    loadOverview()
                    loadMasterFailures()
                }}
            />
        )
    }

    return (
        <div className="flex flex-col gap-4">
            <ScopeBar
                repoSlot={<SourceScopeChip />}
                lensPickers={[
                    { label: 'pr', to: withSource(urls.engineeringAnalyticsPullRequestList(), sourceId) },
                    { label: 'author', to: withSource(urls.engineeringAnalyticsAuthors(), sourceId) },
                ]}
            />

            <RepoEntityHeader
                repoFullName={
                    (sourceId
                        ? githubSources.find((source: GitHubSourceApi) => source.id === sourceId)?.repo
                        : githubSources[0]?.repo) || ''
                }
                failingWorkflowCount={failingWorkflowCount}
                failuresLoading={masterFailuresLoading}
                defaultBranch={defaultBranch}
            />

            <div className="flex flex-wrap gap-2.5">
                <MetricTile
                    label="Pass rate"
                    value={percent(overview?.success_rate)}
                    delta={
                        <DeltaBadge
                            value={pointChange(overview?.success_rate, overview?.success_rate_prev)}
                            unit="pp"
                        />
                    }
                    sub="workflow-level, all branches"
                />
                <MetricTile
                    label="Runs"
                    value={compactCount(overview?.run_count)}
                    delta={<DeltaBadge value={percentChange(overview?.run_count, overview?.run_count_prev)} />}
                    sub="all branches and workflows"
                />
                <MetricTile
                    label="CI cost"
                    value={jobsAvailable ? compactUsd(overview?.estimated_cost_usd) : '—'}
                    delta={
                        jobsAvailable ? (
                            <DeltaBadge
                                value={percentChange(overview?.estimated_cost_usd, overview?.estimated_cost_usd_prev)}
                                goodWhenDown
                            />
                        ) : undefined
                    }
                    sub={
                        jobsAvailable
                            ? `${compactMinutes(overview?.billable_minutes)} billable × tier rate`
                            : 'job-level source not synced'
                    }
                />
                <MetricTile
                    label="Median PR open→merge"
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
                    sub="bots and drafts excluded"
                />
                <MetricTile
                    label="Re-run cycles"
                    value={compactCount(overview?.rerun_cycles)}
                    delta={
                        <DeltaBadge
                            value={percentChange(overview?.rerun_cycles, overview?.rerun_cycles_prev)}
                            goodWhenDown
                        />
                    }
                    sub="runs with attempt > 1"
                />
            </div>

            <SectionNav
                items={[
                    { id: 'now', label: 'Now' },
                    { id: 'master', label: `${defaultBranch === 'main' ? 'Main' : 'Master'} health` },
                    { id: 'prs', label: 'Pull requests' },
                    { id: 'workflows', label: 'Workflows' },
                    { id: 'cost', label: 'Cost' },
                    { id: 'authors', label: 'Authors' },
                ]}
            />

            <MasterFailuresSection />

            <Section
                id="master"
                title={`${defaultBranch === 'main' ? 'Main' : 'Master'} health`}
                note="the default branch gets its own trend — not buried in a filter"
            >
                {masterHealth ? (
                    <div className="grid gap-2.5 lg:grid-cols-2">
                        <LemonCard hoverEffect={false} className="p-4">
                            <h3 className="mb-2 text-xs font-semibold text-secondary">
                                Success rate on {defaultBranch}
                            </h3>
                            <Sparkline
                                type="line"
                                className="h-32 w-full"
                                data={[
                                    {
                                        name: 'Success rate (%)',
                                        values: masterHealth.successRate.map((v) => Math.round(v)),
                                        color: 'brand-blue',
                                    },
                                ]}
                                labels={masterHealth.labels}
                                maximumIndicator={false}
                            />
                        </LemonCard>
                        <LemonCard hoverEffect={false} className="p-4">
                            <h3 className="mb-2 text-xs font-semibold text-secondary">
                                Failed runs on {defaultBranch}
                            </h3>
                            <Sparkline
                                type="bar"
                                className="h-32 w-full"
                                data={[{ name: 'Failed runs', values: masterHealth.failures, color: 'danger' }]}
                                labels={masterHealth.labels}
                                maximumIndicator={false}
                            />
                            <div className="mt-2 border-t border-primary pt-2 text-[11px] text-tertiary">
                                Completed runs on {defaultBranch} whose conclusion wasn't success.
                            </div>
                        </LemonCard>
                    </div>
                ) : (
                    <LemonCard hoverEffect={false} className="p-4 text-xs text-secondary">
                        {overviewLoading ? 'Loading…' : `No completed runs on ${defaultBranch} in the window.`}
                    </LemonCard>
                )}
            </Section>

            <Section
                id="prs"
                title="Pull requests needing attention"
                note="the failing / stuck slice of the open backlog — never the full list"
            >
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
                <LemonCard hoverEffect={false} className="p-0">
                    <PullRequestTable
                        rows={attentionPrs}
                        loading={pullRequestsLoading}
                        sourceId={sourceId}
                        costLensEnabled={costLensEnabled}
                        emptyState="Nothing failing or stuck in the open backlog."
                        dataAttr="engineering-analytics-attention-prs"
                    />
                    <div className="border-t border-primary px-4 py-2 text-[11px] text-tertiary">
                        Showing {attentionPrs.length} of {cards ? humanFriendlyNumber(cards.openPrs) : '…'} open pull
                        requests —{' '}
                        <Link to={withSource(urls.engineeringAnalyticsPullRequestList(), sourceId)}>view all →</Link>
                    </div>
                </LemonCard>
            </Section>

            <Section
                id="workflows"
                title="Workflows"
                note="every row opens the workflow page — same skeleton, one level down"
            >
                <WorkflowHealthTable
                    rows={workflowHealth}
                    loading={workflowHealthLoading}
                    sourceId={sourceId}
                    showCost={jobsAvailable}
                    defaultSorting={{ columnKey: 'runCount', order: -1 }}
                    emptyState="No workflow runs in the window."
                />
            </Section>

            <Section id="cost" title="Cost" note="where the window's spend goes">
                {jobsAvailable && costByWorkflow.length > 0 ? (
                    <LemonCard hoverEffect={false} className="p-4 lg:max-w-xl">
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
                            : 'Cost needs the job-level source (github_workflow_jobs) — not synced for this team yet.'}
                    </LemonCard>
                )}
            </Section>

            <Section
                id="authors"
                title="Authors"
                note="who's shipping across the loaded pull requests — for finding your own work, not ranking people"
            >
                <div className="grid gap-2.5 lg:grid-cols-2">
                    <LemonCard hoverEffect={false} className="p-4">
                        <h3 className="mb-1 text-xs font-semibold text-secondary">Most active · by pull requests</h3>
                        {authorsByActivity.map((author, i) => (
                            <ShareRow
                                key={author.handle}
                                rank={i + 1}
                                avatar={author.handle}
                                label={author.handle}
                                sub={
                                    author.medianOpenToMergeSeconds != null
                                        ? `median open→merge ${humanFriendlyDuration(author.medianOpenToMergeSeconds, { maxUnits: 1 })}`
                                        : 'nothing merged yet'
                                }
                                value={`${author.prCount} PRs`}
                                to={withSource(urls.engineeringAnalyticsAuthor(author.handle), sourceId)}
                            />
                        ))}
                        {!authorsByActivity.length && (
                            <div className="py-2 text-xs text-secondary">
                                {pullRequestsLoading ? 'Loading…' : 'No pull requests loaded.'}
                            </div>
                        )}
                    </LemonCard>
                    <LemonCard hoverEffect={false} className="p-4">
                        <h3 className="mb-1 text-xs font-semibold text-secondary">CI cost attributed to their PRs</h3>
                        {authorsByCost.map((author, i) => (
                            <ShareRow
                                key={author.handle}
                                rank={i + 1}
                                avatar={author.handle}
                                label={author.handle}
                                sub={`${author.rerunCycles} re-run cycles`}
                                value={compactUsd(author.costUsd)}
                                to={withSource(urls.engineeringAnalyticsAuthor(author.handle), sourceId)}
                            />
                        ))}
                        {!authorsByCost.length && (
                            <div className="py-2 text-xs text-secondary">
                                {jobsAvailable ? 'No costed pull requests yet.' : 'Needs the job-level source.'}
                            </div>
                        )}
                        <div className="mt-2 border-t border-primary pt-2 text-[11px] text-tertiary">
                            <Link to={withSource(urls.engineeringAnalyticsAuthors(), sourceId)}>
                                All {humanFriendlyNumber(authorCount)} authors →
                            </Link>
                        </div>
                    </LemonCard>
                </div>
            </Section>
        </div>
    )
}
