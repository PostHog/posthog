import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconExternal } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumns, LemonTag, Link } from '@posthog/lemon-ui'

import { getSeriesColor } from 'lib/colors'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { BillableBadge } from '../components/BillableBadge'
import { DistributionBar } from '../components/DistributionBar'
import { EntityHeader, VerdictPill } from '../components/EntityHeader'
import { GroupedJobsTable } from '../components/GroupedJobsTable'
import { JobAggregatesTable } from '../components/JobAggregatesTable'
import { MetricTile } from '../components/MetricTile'
import { RunActivityChart } from '../components/RunActivityChart'
import { RunnerBadge, RunsTable, formatCost } from '../components/runTables'
import { RepoScopeChip, ScopeBar } from '../components/ScopeBar'
import { Section, SectionNav } from '../components/Section'
import type { WorkflowRunnerCostApi } from '../generated/api.schemas'
import { compactCount, compactMinutes, compactUsd, percent } from '../lib/format'
import { githubCommitUrl, githubWorkflowUrl } from '../lib/github'
import { isDecisiveFailure } from '../lib/lifecycle'
import { WorkflowRunRow, WorkflowRunsLogicProps, workflowRunsLogic } from './workflowRunsLogic'

/** Where a workflow's CI spend goes, split by runner tier — a small table (not bespoke chips) so it reads
 *  like every other table in the product. */
function RunnerCostTable({ costs }: { costs: WorkflowRunnerCostApi[] }): JSX.Element {
    const columns: LemonTableColumns<WorkflowRunnerCostApi> = [
        {
            title: 'Runner',
            key: 'runner',
            render: (_, cost) => <RunnerBadge provider={cost.provider} label={cost.runner_label} />,
        },
        {
            title: 'Jobs',
            key: 'jobs',
            width: 90,
            align: 'right',
            render: (_, cost) => <span className="text-xs tabular-nums">{cost.job_count}</span>,
        },
        {
            title: 'Cost',
            key: 'cost',
            width: 140,
            align: 'right',
            render: (_, cost) => <BillableBadge minutes={cost.billable_minutes} costUsd={cost.estimated_cost_usd} />,
        },
    ]
    // Where the money goes — one stacked bar over the table, a segment per tier sized by its $ share.
    // Free (GitHub-hosted) runners are $0, so they don't take a slice; the bar reads as "billable spend".
    const costSegments = costs.map((cost, i) => ({
        key: `${cost.provider}:${cost.runner_label}`,
        label: cost.runner_label || cost.provider,
        value: cost.estimated_cost_usd ?? 0,
        color: getSeriesColor(i),
        caption: formatCost(cost.estimated_cost_usd ?? null),
    }))
    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-baseline gap-2">
                <h3 className="mb-0">Cost by runner</h3>
                <LemonTag type="warning">estimate · wall-clock × reference rate</LemonTag>
            </div>
            <DistributionBar segments={costSegments} />
            <LemonTable
                data-attr="engineering-analytics-workflow-runner-costs"
                size="small"
                columns={columns}
                dataSource={costs}
                rowKey={(cost) => `${cost.provider}:${cost.runner_label}`}
                nouns={['runner tier', 'runner tiers']}
            />
        </div>
    )
}

export const scene: SceneExport<WorkflowRunsLogicProps> = {
    component: WorkflowRunsScene,
    logic: workflowRunsLogic,
    paramsToProps: ({ params: { repoOwner, repoName, workflowName }, searchParams: { source } }) => ({
        repoOwner: decodeURIComponent(repoOwner),
        repoName: decodeURIComponent(repoName),
        workflowName: decodeURIComponent(workflowName),
        sourceId: source ?? null,
    }),
}

export function WorkflowRunsScene(): JSX.Element {
    const {
        runRows,
        runsLoading,
        runnerCosts,
        runJobs,
        runJobsLoading,
        expandedRunKeys,
        loadFailed,
        sourceId,
        repoOwner,
        repoName,
        workflowName,
        healthSummary,
        costSummary,
        runsTruncated,
        activityRuns,
        activityTruncated,
        jobAggregates,
        jobAggregatesLoading,
        masterConclusion,
        queueP50Seconds,
    } = useValues(workflowRunsLogic)
    const { loadRuns, setRunExpanded } = useActions(workflowRunsLogic)

    const githubUrl = githubWorkflowUrl(repoOwner, repoName, workflowName)
    // Master's own verdict when the window has master runs; the overall fleet state otherwise.
    const verdictPill =
        masterConclusion != null ? (
            isDecisiveFailure(masterConclusion) ? (
                <VerdictPill kind="danger">Failing on master</VerdictPill>
            ) : masterConclusion === 'success' ? (
                <VerdictPill kind="success">Passing on master</VerdictPill>
            ) : (
                <VerdictPill kind="muted">
                    {capitalizeFirstLetter(masterConclusion.replace('_', ' '))} on master
                </VerdictPill>
            )
        ) : healthSummary.state === 'failing' ? (
            <VerdictPill kind="danger">Failing</VerdictPill>
        ) : healthSummary.state === 'degraded' ? (
            <VerdictPill kind="warning">Degraded</VerdictPill>
        ) : healthSummary.state === 'healthy' ? (
            <VerdictPill kind="success">Passing</VerdictPill>
        ) : undefined

    // Run id (→ the single-run page) + attempt, branch, attributed PR. The shared RunsTable appends
    // verdict / duration / started and the expand-to-jobs behavior.
    const leadColumns: LemonTableColumns<WorkflowRunRow> = [
        {
            title: 'Run',
            key: 'run',
            render: (_, run) => (
                <Link
                    to={
                        combineUrl(
                            urls.engineeringAnalyticsWorkflowRun(run.repoOwner, run.repoName, run.id),
                            sourceId ? { source: sourceId } : {}
                        ).url
                    }
                    className="font-medium tabular-nums"
                    onClick={(e) => e.stopPropagation()}
                >
                    #{run.id}
                </Link>
            ),
        },
        {
            title: 'Branch',
            key: 'branch',
            render: (_, run) =>
                run.headBranch ? (
                    <span className="flex items-center gap-1.5 font-mono text-xs">
                        {(run.headBranch === 'master' || run.headBranch === 'main') && (
                            <span
                                className={cn(
                                    'inline-block size-1.5 shrink-0 rounded-full',
                                    isDecisiveFailure(run.conclusion) ? 'bg-danger' : 'bg-success'
                                )}
                            />
                        )}
                        {run.headBranch}
                    </span>
                ) : (
                    <span className="text-xs text-secondary">—</span>
                ),
        },
        {
            title: 'Commit',
            key: 'commit',
            width: 90,
            render: (_, run) =>
                run.headSha ? (
                    <Link
                        to={githubCommitUrl(run.repoOwner, run.repoName, run.headSha)}
                        target="_blank"
                        className="font-mono text-xs text-tertiary"
                        onClick={(e) => e.stopPropagation()}
                    >
                        {run.headSha.slice(0, 7)}
                    </Link>
                ) : (
                    <span className="text-xs text-secondary">—</span>
                ),
        },
        {
            title: 'Attempt',
            key: 'attempt',
            width: 80,
            align: 'right',
            render: (_, run) =>
                (run.runAttempt ?? 1) > 1 ? (
                    <LemonTag type="warning">{run.runAttempt}</LemonTag>
                ) : (
                    <span className="text-xs tabular-nums text-tertiary">{run.runAttempt ?? 1}</span>
                ),
        },
        {
            title: 'PR',
            key: 'pr',
            width: 80,
            render: (_, run) =>
                run.prNumber > 0 ? (
                    <Link
                        to={
                            combineUrl(
                                urls.engineeringAnalyticsPullRequest(run.repoOwner, run.repoName, run.prNumber),
                                sourceId ? { source: sourceId } : {}
                            ).url
                        }
                        onClick={(e) => e.stopPropagation()}
                    >
                        #{run.prNumber}
                    </Link>
                ) : (
                    <span className="text-xs text-secondary">—</span>
                ),
        },
    ]

    if (loadFailed) {
        return (
            <SceneContent>
                <SceneTitleSection name="Workflow" resourceType={{ type: 'health' }} />
                <div className="flex items-center gap-3">
                    <span className="text-secondary">
                        Couldn't load this workflow's runs — it may not exist in the connected GitHub source.
                    </span>
                    <LemonButton type="secondary" size="small" onClick={loadRuns} loading={runsLoading}>
                        Retry
                    </LemonButton>
                </div>
            </SceneContent>
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={workflowName}
                resourceType={{ type: 'health' }}
                actions={
                    <LemonButton type="secondary" size="small" to={githubUrl} targetBlank sideIcon={<IconExternal />}>
                        View on GitHub
                    </LemonButton>
                }
            />
            {/* One shared window + branch scope every section below — the same scope as the repo hub, so
                numbers match after drilling in (a missing branch filter here read as more runs than the
                hub showed). */}
            <ScopeBar
                repoSlot={
                    <RepoScopeChip
                        label={`${repoOwner}/${repoName}`}
                        to={combineUrl(urls.engineeringAnalytics(), sourceId ? { source: sourceId } : {}).url}
                    />
                }
                crumbs={[{ label: workflowName }]}
                showBranch
            />
            <EntityHeader
                icon="⚙️"
                title={workflowName}
                slug={
                    <>
                        {repoOwner}/{repoName} ·{' '}
                        <Link to={githubUrl} target="_blank" targetBlankIcon>
                            View on GitHub
                        </Link>
                        {runsTruncated && <span> · run stats cover the most recent {runRows.length} runs</span>}
                    </>
                }
                right={verdictPill}
            />
            <div className="flex flex-wrap gap-2.5">
                <MetricTile
                    label="Pass rate"
                    value={percent(healthSummary.passRate)}
                    sub={
                        healthSummary.completedRuns > 0
                            ? `${humanFriendlyNumber(healthSummary.passedRuns)} of ${humanFriendlyNumber(
                                  healthSummary.completedRuns
                              )} completed runs passed`
                            : 'no completed runs in the window'
                    }
                />
                <MetricTile
                    label="Runs"
                    value={compactCount(healthSummary.totalRuns)}
                    sub={
                        healthSummary.reruns > 0
                            ? `${humanFriendlyNumber(healthSummary.reruns)} re-run cycles`
                            : 'no re-runs'
                    }
                />
                <MetricTile
                    label="Duration p50"
                    value={
                        healthSummary.medianSeconds != null ? humanFriendlyDuration(healthSummary.medianSeconds) : '—'
                    }
                    valueSuffix={
                        healthSummary.p95Seconds != null
                            ? `→ ${humanFriendlyDuration(healthSummary.p95Seconds)} p95`
                            : undefined
                    }
                    sub="wall-clock, completed runs"
                />
                <MetricTile
                    label="Queue time p50"
                    value={queueP50Seconds != null ? humanFriendlyDuration(queueP50Seconds) : '—'}
                    sub={queueP50Seconds != null ? 'created → started, across jobs' : 'needs the job-level source'}
                />
                <MetricTile
                    label="Cost"
                    value={costSummary?.estimatedCostUsd != null ? compactUsd(costSummary.estimatedCostUsd) : '—'}
                    sub={
                        costSummary?.estimatedCostUsd != null
                            ? `${compactMinutes(costSummary.billableMinutes)} billable · ${compactUsd(
                                  healthSummary.totalRuns > 0
                                      ? costSummary.estimatedCostUsd / healthSummary.totalRuns
                                      : null
                              )} per run`
                            : 'needs the job-level source'
                    }
                />
            </div>
            <SectionNav
                items={[
                    { id: 'health', label: 'Health' },
                    { id: 'jobs', label: 'Jobs' },
                    { id: 'cost', label: 'Cost' },
                    { id: 'runs', label: 'Runs' },
                ]}
            />
            <Section
                id="health"
                title="Health"
                note="every run in the window — duration, verdict, and in-flight load in one plot"
            >
                <RunActivityChart runs={activityRuns} truncated={activityTruncated} />
            </Section>
            <Section
                id="jobs"
                title="Jobs"
                note="matrix shards roll up into one row; a job always needs its run as context, so expand a run below instead of looking for a job page"
            >
                <JobAggregatesTable
                    aggregates={jobAggregates}
                    loading={jobAggregatesLoading}
                    totalCostUsd={costSummary?.estimatedCostUsd ?? null}
                />
            </Section>
            <Section id="cost" title="Cost" note="where this workflow's spend goes">
                {runnerCosts.length > 0 ? (
                    <RunnerCostTable costs={runnerCosts} />
                ) : (
                    <span className="text-xs text-secondary">
                        No cost data — the job-level source isn't synced, or nothing ran in the window.
                    </span>
                )}
            </Section>
            <Section id="runs" title="Runs" note="latest first — expand a run for its jobs, grouped by matrix">
                <RunsTable
                    runs={runRows}
                    rowKey={(run) => `${run.id}-${run.runAttempt}`}
                    leadColumns={leadColumns}
                    loading={runsLoading}
                    runJobs={runJobs}
                    runJobsLoading={runJobsLoading}
                    expandedKeys={expandedRunKeys}
                    setExpanded={setRunExpanded}
                    renderJobs={(jobs, loading) => <GroupedJobsTable jobs={jobs} loading={loading} embedded />}
                    // Newest run first on the workflow page.
                    defaultSorting={{ columnKey: 'started', order: -1 }}
                    dataAttr="engineering-analytics-workflow-runs-table"
                    emptyState="No runs for this workflow in the connected source."
                />
            </Section>
        </SceneContent>
    )
}

export default WorkflowRunsScene
