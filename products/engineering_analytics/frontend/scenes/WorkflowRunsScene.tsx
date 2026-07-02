import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconExternal, IconGear } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumns, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { EntityHeader, VerdictPill } from '../components/EntityHeader'
import { GroupedJobsTable } from '../components/GroupedJobsTable'
import { JobAggregatesTable } from '../components/JobAggregatesTable'
import { MetricTile } from '../components/MetricTile'
import { RunActivityChart } from '../components/RunActivityChart'
import { RunConclusionTag } from '../components/runTables'
import { RepoScopeChip, ScopeBar } from '../components/ScopeBar'
import { Section, SectionNav } from '../components/Section'
import { ShareRow } from '../components/ShareRow'
import type { WorkflowRunnerCostApi } from '../generated/api.schemas'
import { compactCount, compactMinutes, compactUsd, percent } from '../lib/format'
import { githubCommitUrl, githubWorkflowUrl } from '../lib/github'
import { jobCacheKey } from '../lib/jobs'
import { isDecisiveFailure } from '../lib/lifecycle'
import { WorkflowRunRow, WorkflowRunsLogicProps, workflowRunsLogic } from './workflowRunsLogic'

/** Where this workflow's spend goes, split by runner tier — the mock's leaderboard rows: tier in
 *  mono, jobs count under it, cost (or 'free') on the right, share bar scaled to billable spend. */
function RunnerTierCard({ costs }: { costs: WorkflowRunnerCostApi[] }): JSX.Element {
    const totalCost = costs.reduce((sum, cost) => sum + (cost.estimated_cost_usd ?? 0), 0)
    return (
        <LemonCard hoverEffect={false} className="p-4 lg:max-w-xl">
            <div className="mb-1 flex items-baseline gap-2">
                <h3 className="mb-0 text-xs font-semibold text-secondary">By runner tier</h3>
                <LemonTag type="warning">estimate · wall-clock × reference rate</LemonTag>
            </div>
            {costs.map((cost) => (
                <ShareRow
                    key={`${cost.provider}:${cost.runner_label}`}
                    label={
                        <span className="font-mono text-xs">
                            {cost.runner_label || cost.provider}
                            {cost.provider === 'github_hosted' ? ' (GitHub-hosted)' : ''}
                        </span>
                    }
                    sub={`${humanFriendlyNumber(cost.job_count)} jobs`}
                    value={cost.estimated_cost_usd != null ? compactUsd(cost.estimated_cost_usd) : 'free'}
                    valueSub={
                        cost.estimated_cost_usd != null
                            ? `${compactMinutes(cost.billable_minutes)} billable`
                            : undefined
                    }
                    share={totalCost > 0 ? (cost.estimated_cost_usd ?? 0) / totalCost : 0}
                    color={cost.estimated_cost_usd != null ? 'var(--brand-blue)' : 'var(--muted)'}
                />
            ))}
            <div className="mt-2 border-t border-primary pt-2 text-[11px] text-tertiary">
                Tier parsed from job labels; rate ladder in the cost model. GitHub-hosted runners are free for open
                source.
            </div>
        </LemonCard>
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

    // The mock's runs-table column set, with what the runs snapshot actually carries (no author or
    // per-run queue/cost yet). Rows expand (caret or row click) to the run's matrix-grouped jobs.
    const runColumns: LemonTableColumns<WorkflowRunRow> = [
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
                    className="font-mono text-xs font-medium tabular-nums"
                    onClick={(e) => e.stopPropagation()}
                >
                    #{run.id}
                </Link>
            ),
        },
        {
            title: 'Conclusion',
            key: 'conclusion',
            width: 110,
            render: (_, run) => <RunConclusionTag conclusion={run.conclusion} />,
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
            title: 'Duration',
            key: 'duration',
            width: 90,
            align: 'right',
            sorter: (a, b) => (a.durationSeconds ?? -1) - (b.durationSeconds ?? -1),
            render: (_, run) => (
                <span className="text-xs tabular-nums whitespace-nowrap">
                    {run.durationSeconds == null ? '—' : humanFriendlyDuration(run.durationSeconds)}
                </span>
            ),
        },
        {
            title: 'Started',
            key: 'started',
            width: 130,
            align: 'right',
            sorter: (a, b) => (a.startedAt ?? '').localeCompare(b.startedAt ?? ''),
            render: (_, run) =>
                run.startedAt ? (
                    <span className="text-xs whitespace-nowrap text-tertiary">
                        <TZLabel time={run.startedAt} />
                    </span>
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
                icon={<IconGear />}
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
                    <RunnerTierCard costs={runnerCosts} />
                ) : (
                    <span className="text-xs text-secondary">
                        No cost data — the job-level source isn't synced, or nothing ran in the window.
                    </span>
                )}
            </Section>
            <Section id="runs" title="Runs" note="latest first — expand a run for its jobs, grouped by matrix">
                <LemonCard hoverEffect={false} className="p-0">
                    <LemonTable<WorkflowRunRow>
                        dataSource={runRows}
                        columns={runColumns}
                        size="small"
                        embedded
                        loading={runsLoading}
                        rowKey={(run) => `${run.id}-${run.runAttempt}`}
                        useURLForSorting={false}
                        defaultSorting={{ columnKey: 'started', order: -1 }}
                        onRow={(run) => ({
                            className: 'cursor-pointer',
                            onClick: () =>
                                setRunExpanded(
                                    `${run.id}-${run.runAttempt}`,
                                    !expandedRunKeys.includes(`${run.id}-${run.runAttempt}`),
                                    run.runId,
                                    run.runAttempt
                                ),
                        })}
                        expandable={{
                            noIndent: true,
                            isRowExpanded: (run) => expandedRunKeys.includes(`${run.id}-${run.runAttempt}`),
                            expandedRowRender: (run) => (
                                <GroupedJobsTable
                                    jobs={runJobs[jobCacheKey(run.id, run.runAttempt)]}
                                    loading={runJobsLoading}
                                    embedded
                                />
                            ),
                        }}
                        emptyState="No runs for this workflow in the connected source."
                        nouns={['run', 'runs']}
                        data-attr="engineering-analytics-workflow-runs-table"
                    />
                    <div className="border-t border-primary px-4 py-2 text-[11px] text-tertiary">
                        {runsTruncated
                            ? `Showing the most recent ${runRows.length} runs in the window.`
                            : `${runRows.length} runs in the window.`}
                    </div>
                </LemonCard>
            </Section>
        </SceneContent>
    )
}

export default WorkflowRunsScene
