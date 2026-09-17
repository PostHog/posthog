import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconExternal, IconGear } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonSkeleton,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

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

import { CIAnalyticsLoadError } from '../components/CIAnalyticsLoadError'
import { EntityHeader, VerdictPill } from '../components/EntityHeader'
import { GroupedJobsTable } from '../components/GroupedJobsTable'
import { JobAggregatesTable } from '../components/JobAggregatesTable'
import { MetricTile } from '../components/MetricTile'
import { RunActivityChart, hasEnoughRunActivity } from '../components/RunActivityChart'
import { RunConclusionTag } from '../components/runTables'
import { RepoScopeChip, ScopeBar, WorkflowScopeChip, WorkflowScopeControls } from '../components/ScopeBar'
import { ScopePanel } from '../components/ScopePanel'
import { Section } from '../components/Section'
import { ShareRow } from '../components/ShareRow'
import type { WorkflowRunnerCostApi } from '../generated/api.schemas'
import { compactCount, compactMinutes, compactUsd, percent } from '../lib/format'
import { githubCommitUrl, githubWorkflowUrl } from '../lib/github'
import { jobCacheKey } from '../lib/jobs'
import { isDecisiveFailure } from '../lib/lifecycle'
import { withScope } from '../lib/scope'
import { WorkflowRunRow, WorkflowRunsLogicProps, workflowRunsLogic } from './workflowRunsLogic'

/** Spend by runner tier: tier, job count, cost (or 'free'), share bar scaled to billable spend. */
function RunnerTierCard({ costs }: { costs: WorkflowRunnerCostApi[] }): JSX.Element {
    const totalCost = costs.reduce((sum, cost) => sum + (cost.estimated_cost_usd ?? 0), 0)
    return (
        <LemonCard hoverEffect={false} className="p-4">
            <h3 className="mb-1 text-xs font-semibold text-secondary">
                <Tooltip title="Estimated: billable minutes × runner-tier rate. The tier comes from the job's runner labels. GitHub-hosted runners are free for open source.">
                    <span className="cursor-default">By runner tier</span>
                </Tooltip>
            </h3>
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
                    value={cost.estimated_cost_usd != null ? compactUsd(cost.estimated_cost_usd) : 'Free'}
                    valueSub={
                        cost.estimated_cost_usd != null
                            ? `${compactMinutes(cost.billable_minutes)} billable`
                            : undefined
                    }
                    share={totalCost > 0 ? (cost.estimated_cost_usd ?? 0) / totalCost : 0}
                    color={cost.estimated_cost_usd != null ? 'var(--brand-blue)' : 'var(--muted)'}
                />
            ))}
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

const refreshing = (loading: boolean, rows: unknown[]): boolean => loading && rows.length > 0

export function WorkflowRunsScene(): JSX.Element {
    const {
        runRows,
        runsLoading,
        runnerCosts,
        runnerCostsLoading,
        runnerCostsFailed,
        runActivityLoading,
        runActivityFailed,
        runJobs,
        runJobsLoading,
        expandedRunKeys,
        loadFailed,
        sourceId,
        repoOwner,
        repoName,
        workflowName,
        healthSummary,
        workflowHealthLoading,
        workflowHealthFailed,
        costSummary,
        runsTruncated,
        activityRuns,
        activityTruncated,
        jobAggregates,
        jobAggregatesLoading,
        jobAggregatesFailed,
        masterConclusion,
        queueP50Seconds,
    } = useValues(workflowRunsLogic)
    const { loadRuns, loadRunActivity, loadRunnerCosts, loadJobAggregates, setRunExpanded } =
        useActions(workflowRunsLogic)
    const { searchParams } = useValues(router)

    const githubUrl = githubWorkflowUrl(repoOwner, repoName, workflowName)
    // The rim spinner means "these numbers are updating", so each read only counts once it has data on
    // screen to update. A first load shows the sections' own skeletons instead.
    const healthBusy = refreshing(runActivityLoading, activityRuns)
    const costBusy = refreshing(runnerCostsLoading, runnerCosts)
    const panelBusy =
        refreshing(runsLoading, runRows) || healthBusy || costBusy || refreshing(jobAggregatesLoading, jobAggregates)
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

    // Lead columns for the runs table; rows expand (caret or row click) to the run's matrix-grouped jobs.
    const runColumns: LemonTableColumns<WorkflowRunRow> = [
        {
            title: 'Run',
            key: 'run',
            render: (_, run) => (
                <Link
                    to={withScope(
                        urls.engineeringAnalyticsWorkflowRun(run.repoOwner, run.repoName, run.id),
                        searchParams,
                        sourceId
                    )}
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
                run.prNumber != null ? (
                    <Link
                        to={withScope(
                            urls.engineeringAnalyticsPullRequest(run.repoOwner, run.repoName, run.prNumber),
                            searchParams,
                            sourceId
                        )}
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
            <SceneContent className="pb-16">
                <SceneTitleSection name="Workflow" resourceType={{ type: 'health' }} />
                <CIAnalyticsLoadError
                    title="Couldn't load this workflow's runs"
                    description="It may not exist in the connected GitHub source. Retry, or check the source's sync status."
                    onRetry={loadRuns}
                    loading={runsLoading}
                />
            </SceneContent>
        )
    }

    return (
        <SceneContent className="pb-16">
            {/* Scene chrome keeps the generic label; the EntityHeader below owns the title. */}
            <SceneTitleSection
                name="Workflow"
                resourceType={{ type: 'health' }}
                actions={
                    <LemonButton type="secondary" size="small" to={githubUrl} targetBlank sideIcon={<IconExternal />}>
                        View on GitHub
                    </LemonButton>
                }
            />
            <ScopeBar
                repoSlot={
                    <RepoScopeChip
                        label={`${repoOwner}/${repoName}`}
                        to={withScope(urls.engineeringAnalytics(), searchParams, sourceId)}
                    />
                }
                crumbs={[
                    {
                        label: workflowName,
                        node: (
                            <WorkflowScopeChip
                                repoOwner={repoOwner}
                                repoName={repoName}
                                workflowName={workflowName}
                                sourceId={sourceId}
                            />
                        ),
                    },
                ]}
                showDate={false}
            />
            <EntityHeader
                icon={<IconGear />}
                title={workflowName}
                slug={`${repoOwner}/${repoName}`}
                right={verdictPill}
            />
            {workflowHealthFailed && (
                <LemonBanner type="warning">
                    These figures could not load, so they cover only the runs in the table below rather than the whole
                    window. Refresh to try again.
                </LemonBanner>
            )}
            <ScopePanel busy={panelBusy} controls={<WorkflowScopeControls />}>
                <div className="flex flex-wrap gap-2.5">
                    <MetricTile
                        label="Pass rate"
                        tooltip={`${humanFriendlyNumber(healthSummary.passedRuns)} of ${humanFriendlyNumber(
                            healthSummary.conclusiveRuns
                        )} runs with a pass-or-fail result passed.`}
                        value={percent(healthSummary.passRate)}
                        loading={workflowHealthLoading}
                    />
                    <MetricTile
                        label="Runs"
                        tooltip={
                            healthSummary.reruns > 0
                                ? `Includes ${humanFriendlyNumber(healthSummary.reruns)} re-run cycles.`
                                : undefined
                        }
                        value={compactCount(healthSummary.totalRuns)}
                        sub={runsTruncated ? `table shows the most recent ${runRows.length}` : undefined}
                        loading={workflowHealthLoading}
                    />
                    <MetricTile
                        label="Duration p50"
                        tooltip="Median duration over successful runs. Runs under 10 seconds with no work are excluded when longer samples exist. All-fast workflows use every successful run."
                        value={
                            healthSummary.medianSeconds != null
                                ? humanFriendlyDuration(healthSummary.medianSeconds)
                                : '—'
                        }
                        sub={
                            healthSummary.p95Seconds != null
                                ? `→ ${humanFriendlyDuration(healthSummary.p95Seconds)} p95`
                                : undefined
                        }
                        loading={workflowHealthLoading}
                    />
                    <MetricTile
                        label="Estimated median queue time"
                        tooltip="Estimated median wait from job created to started: each job's median, weighted by how often the job ran."
                        value={queueP50Seconds != null ? humanFriendlyDuration(queueP50Seconds) : '—'}
                        sub={jobAggregatesFailed ? "Couldn't load" : undefined}
                        loading={jobAggregatesLoading}
                    />
                    <MetricTile
                        label="Cost"
                        tooltip={
                            costSummary?.estimatedCostUsd != null
                                ? `${compactMinutes(costSummary.billableMinutes)} billable · ${compactUsd(
                                      !workflowHealthFailed && healthSummary.totalRuns > 0
                                          ? costSummary.estimatedCostUsd / healthSummary.totalRuns
                                          : null
                                  )} per run.`
                                : runnerCostsFailed
                                  ? undefined
                                  : 'Available once the job-level source is synced.'
                        }
                        value={costSummary?.estimatedCostUsd != null ? compactUsd(costSummary.estimatedCostUsd) : '—'}
                        sub={
                            costSummary?.estimatedCostUsd != null
                                ? undefined
                                : runnerCostsFailed
                                  ? "Couldn't load"
                                  : 'Job-level source not synced'
                        }
                        loading={runnerCostsLoading || workflowHealthLoading}
                    />
                </div>
                <Section id="health" title="Health" busy={healthBusy}>
                    {runActivityFailed ? (
                        <CIAnalyticsLoadError
                            title="Couldn't load run activity"
                            onRetry={loadRunActivity}
                            loading={runActivityLoading}
                        />
                    ) : hasEnoughRunActivity(activityRuns) ? (
                        <RunActivityChart runs={activityRuns} truncated={activityTruncated} />
                    ) : runActivityLoading ? (
                        <LemonSkeleton className="h-80 w-full" />
                    ) : (
                        <LemonCard hoverEffect={false} className="p-4 text-xs text-secondary">
                            Not enough completed runs in the window to chart yet. Widen the date range or the run scope.
                        </LemonCard>
                    )}
                </Section>
                <Section id="jobs" title="Jobs">
                    {jobAggregatesFailed ? (
                        <CIAnalyticsLoadError
                            title="Couldn't load jobs"
                            onRetry={loadJobAggregates}
                            loading={jobAggregatesLoading}
                        />
                    ) : (
                        <JobAggregatesTable
                            aggregates={jobAggregates}
                            loading={jobAggregatesLoading}
                            totalCostUsd={costSummary?.estimatedCostUsd ?? null}
                        />
                    )}
                </Section>
                <Section id="cost" title="Cost" busy={costBusy}>
                    {runnerCostsFailed ? (
                        <CIAnalyticsLoadError
                            title="Couldn't load cost"
                            onRetry={loadRunnerCosts}
                            loading={runnerCostsLoading}
                        />
                    ) : runnerCosts.length > 0 ? (
                        <RunnerTierCard costs={runnerCosts} />
                    ) : runnerCostsLoading ? (
                        <LemonSkeleton className="h-40 w-full" />
                    ) : (
                        <LemonCard hoverEffect={false} className="p-4 text-xs text-secondary">
                            No cost data. The job-level source isn't synced, or nothing ran in the window. Widen the
                            date range, or check the source's sync status.
                        </LemonCard>
                    )}
                </Section>
                <Section id="runs" title="Runs">
                    <LemonCard hoverEffect={false} className="overflow-hidden p-0">
                        <LemonTable<WorkflowRunRow>
                            dataSource={runRows}
                            columns={runColumns}
                            size="small"
                            embedded
                            loading={runsLoading}
                            rowKey={(run) => `${run.id}-${run.runAttempt}`}
                            useURLForSorting={false}
                            defaultSorting={{ columnKey: 'started', order: -1 }}
                            pagination={{ pageSize: 25 }}
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
            </ScopePanel>
        </SceneContent>
    )
}

export default WorkflowRunsScene
