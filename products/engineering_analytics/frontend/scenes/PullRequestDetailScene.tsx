import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconExternal, IconPullRequest } from '@posthog/icons'
import {
    LemonButton,
    LemonInput,
    LemonSkeleton,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    Link,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { pluralize } from 'lib/utils/strings'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { EntityHeader, VerdictPill } from '../components/EntityHeader'
import { FailureLogGroups } from '../components/FailureLogs'
import { GroupedJobsTable } from '../components/GroupedJobsTable'
import { MetricTile } from '../components/MetricTile'
import { PullRequestDeliveryTimeline } from '../components/PullRequestDeliveryTimeline'
import { PullRequestStateTag } from '../components/PullRequestStateTag'
import { RunConclusionTag } from '../components/runTables'
import { RepoScopeChip, ScopeBar } from '../components/ScopeBar'
import { Section } from '../components/Section'
import type { WorkflowJobApi } from '../generated/api.schemas'
import { compactCount, compactUsd } from '../lib/format'
import { githubCommitUrl, githubPrUrl } from '../lib/github'
import { WorkflowRun, isPassingConclusion } from '../lib/lifecycle'
import { pushRoundOf } from '../lib/pushRounds'
import { withCurrentScope } from '../lib/scope'
import {
    PrRunRow,
    PrWorkflowRow,
    PullRequestDetailLogicProps,
    jobCacheKey,
    pullRequestDetailLogic,
    latestRunPerWorkflow,
} from './pullRequestDetailLogic'
import { pullRequestTimelinesLogic } from './pullRequestTimelinesLogic'

export const scene: SceneExport<PullRequestDetailLogicProps> = {
    component: PullRequestDetailScene,
    logic: pullRequestDetailLogic,
    paramsToProps: ({ params: { repoOwner, repoName, number }, searchParams: { source } }) => ({
        repoOwner: decodeURIComponent(repoOwner),
        repoName: decodeURIComponent(repoName),
        number: parseInt(number, 10),
        sourceId: source ?? null,
    }),
}

// Stable per-row key — re-runs share a runId, so start time disambiguates attempts. Used for rowKey and
// the expand-state set, so expanding one attempt doesn't open the others.
function runRowKey(run: WorkflowRun): string {
    return `${run.workflow}@${run.startedAt ?? run.finishedAt ?? run.runId ?? ''}`
}

/** The runs of one workflow on this PR, one row per push × attempt — jobs live on the run page. */
function PerPushRunsTable({
    runs,
    runCostByKey,
    showCost,
    repoOwner,
    repoName,
    sourceId,
    runJobs,
    runJobsLoading,
    expandedRunKeys,
    setRunExpanded,
}: {
    runs: PrRunRow[]
    runCostByKey: Record<string, { minutes: number | null; cost: number | null }>
    showCost: boolean
    repoOwner: string
    repoName: string
    sourceId: string | null
    runJobs: Record<string, WorkflowJobApi[]>
    runJobsLoading: boolean
    expandedRunKeys: string[]
    setRunExpanded: (rowKey: string, expanded: boolean, runId: number | null, runAttempt: number | null) => void
}): JSX.Element {
    // Oldest push first so rows read in the same order as the timeline strip.
    const ordered = [...runs].sort((a, b) => (a.startedAt ?? '').localeCompare(b.startedAt ?? ''))
    const columns: LemonTableColumns<PrRunRow> = [
        {
            title: 'Push',
            key: 'push',
            render: (_, run) =>
                run.headSha ? (
                    <Link
                        to={githubCommitUrl(repoOwner, repoName, run.headSha)}
                        target="_blank"
                        className="font-mono text-xs"
                    >
                        {run.headSha.slice(0, 7)}
                    </Link>
                ) : (
                    <span className="text-xs text-secondary">—</span>
                ),
        },
        {
            title: 'Run',
            key: 'run',
            render: (_, run) =>
                run.runId != null ? (
                    <Link
                        to={withCurrentScope(
                            urls.engineeringAnalyticsWorkflowRun(repoOwner, repoName, run.runId),
                            sourceId
                        )}
                        className="font-mono text-xs"
                    >
                        #{run.runId}
                    </Link>
                ) : (
                    <span className="text-xs text-secondary">—</span>
                ),
        },
        {
            title: 'Attempt',
            key: 'attempt',
            align: 'right',
            render: (_, run) =>
                (run.runAttempt ?? 1) > 1 ? (
                    <LemonTag type="warning">{run.runAttempt}</LemonTag>
                ) : (
                    <span className="text-xs tabular-nums text-tertiary">{run.runAttempt ?? 1}</span>
                ),
        },
        {
            title: 'Conclusion',
            key: 'conclusion',
            render: (_, run) => <RunConclusionTag conclusion={run.conclusion} />,
        },
        {
            title: 'Duration',
            key: 'duration',
            align: 'right',
            render: (_, run) => (
                <span className="text-xs tabular-nums whitespace-nowrap">
                    {run.durationSeconds == null ? '—' : humanFriendlyDuration(run.durationSeconds)}
                </span>
            ),
        },
        ...((showCost
            ? [
                  {
                      title: 'Cost',
                      key: 'cost',
                      align: 'right',
                      render: (_: unknown, run: PrRunRow) => {
                          const cost = run.runId != null ? runCostByKey[jobCacheKey(run.runId, run.runAttempt)] : null
                          return (
                              <span className="text-xs tabular-nums whitespace-nowrap">
                                  {cost?.cost != null ? compactUsd(cost.cost) : '—'}
                              </span>
                          )
                      },
                  },
              ]
            : []) as LemonTableColumns<PrRunRow>),
        {
            title: 'Started',
            key: 'started',
            align: 'right',
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
    return (
        <LemonTable
            dataSource={ordered}
            columns={columns}
            size="small"
            embedded
            rowKey={runRowKey}
            useURLForSorting={false}
            onRow={(run) =>
                run.runId != null
                    ? {
                          className: 'cursor-pointer',
                          onClick: () =>
                              setRunExpanded(
                                  runRowKey(run),
                                  !expandedRunKeys.includes(runRowKey(run)),
                                  run.runId,
                                  run.runAttempt
                              ),
                      }
                    : {}
            }
            expandable={{
                noIndent: true,
                rowExpandable: (run) => run.runId != null,
                isRowExpanded: (run) => expandedRunKeys.includes(runRowKey(run)),
                expandedRowRender: (run) => (
                    <GroupedJobsTable
                        jobs={run.runId != null ? runJobs[jobCacheKey(run.runId, run.runAttempt)] : undefined}
                        loading={runJobsLoading}
                        embedded
                    />
                ),
            }}
            nouns={['run', 'runs']}
        />
    )
}

/** The PR's CI rolled up per workflow: latest state, what failed (by job name), runs / p50 / cost.
 *  Expands (caret only) to the per-push runs. */
function PrWorkflowsTable({
    rows,
    filteredRuns,
    failingJobLabelByWorkflow,
    runCostByKey,
    showCost,
    loading,
    repoOwner,
    repoName,
    sourceId,
    runJobs,
    runJobsLoading,
    expandedRunKeys,
    setRunExpanded,
}: {
    rows: PrWorkflowRow[]
    filteredRuns: PrRunRow[]
    failingJobLabelByWorkflow: Record<string, string>
    runCostByKey: Record<string, { minutes: number | null; cost: number | null }>
    showCost: boolean
    loading: boolean
    repoOwner: string
    repoName: string
    sourceId: string | null
    runJobs: Record<string, WorkflowJobApi[]>
    runJobsLoading: boolean
    expandedRunKeys: string[]
    setRunExpanded: (rowKey: string, expanded: boolean, runId: number | null, runAttempt: number | null) => void
}): JSX.Element {
    const latestByWorkflow = latestRunPerWorkflow(filteredRuns)
    const isWorkflowFailing = (workflowName: string): boolean => {
        const latest = latestByWorkflow.get(workflowName)
        return latest?.conclusion != null && !isPassingConclusion(latest.conclusion)
    }
    // Failing workflows first — the order a reviewer triages in — then alphabetical.
    const orderedRows = [...rows].sort(
        (a, b) =>
            Number(isWorkflowFailing(b.workflowName)) - Number(isWorkflowFailing(a.workflowName)) ||
            a.workflowName.localeCompare(b.workflowName)
    )
    const columns: LemonTableColumns<PrWorkflowRow> = [
        {
            title: 'Workflow',
            key: 'workflow',
            sorter: (a, b) => a.workflowName.localeCompare(b.workflowName),
            render: (_, row) => {
                const latest = latestByWorkflow.get(row.workflowName)
                const failing = latest?.conclusion != null && !isPassingConclusion(latest.conclusion)
                return (
                    <span className="flex items-center gap-2 font-medium">
                        <span
                            className={cn(
                                'inline-block size-2 shrink-0 rounded-full',
                                failing ? 'bg-danger' : latest?.conclusion == null ? 'bg-brand-blue' : 'bg-success'
                            )}
                        />
                        <Link
                            to={withCurrentScope(
                                urls.engineeringAnalyticsWorkflowRuns(repoOwner, repoName, row.workflowName),
                                sourceId
                            )}
                        >
                            {row.workflowName}
                        </Link>
                    </span>
                )
            },
        },
        {
            title: 'Latest conclusion',
            key: 'latest',
            width: 130,
            render: (_, row) => (
                <RunConclusionTag conclusion={latestByWorkflow.get(row.workflowName)?.conclusion ?? null} />
            ),
        },
        {
            title: 'What failed',
            key: 'failedJob',
            render: (_, row) => {
                const latest = latestByWorkflow.get(row.workflowName)
                if (latest?.conclusion == null || isPassingConclusion(latest.conclusion)) {
                    return <span className="text-xs text-tertiary">—</span>
                }
                const label = failingJobLabelByWorkflow[row.workflowName]
                return label ? (
                    <span className="font-mono text-[10.5px] text-secondary">{label}</span>
                ) : (
                    <span className="text-xs text-tertiary">looking up the failing job…</span>
                )
            },
        },
        {
            title: 'Runs',
            key: 'runCount',
            align: 'right',
            sorter: (a, b) => a.runCount - b.runCount,
            render: (_, row) => <span className="text-xs tabular-nums">{row.runCount}</span>,
        },
        {
            title: 'P50',
            key: 'p50',
            align: 'right',
            sorter: (a, b) => (a.p50Seconds ?? -1) - (b.p50Seconds ?? -1),
            render: (_, row) => (
                <span className="text-xs tabular-nums whitespace-nowrap">
                    {row.p50Seconds == null ? '—' : humanFriendlyDuration(row.p50Seconds)}
                </span>
            ),
        },
        ...((showCost
            ? [
                  {
                      title: 'Cost',
                      key: 'cost',
                      align: 'right',
                      sorter: (a: PrWorkflowRow, b: PrWorkflowRow) =>
                          (a.estimatedCostUsd ?? -1) - (b.estimatedCostUsd ?? -1),
                      render: (_: unknown, row: PrWorkflowRow) => (
                          <span className="text-xs tabular-nums whitespace-nowrap">
                              {row.estimatedCostUsd != null ? compactUsd(row.estimatedCostUsd) : '—'}
                          </span>
                      ),
                  },
              ]
            : []) as LemonTableColumns<PrWorkflowRow>),
    ]
    return (
        <LemonTable
            // Namespaces the page search param so paging can't move other tables sharing this URL.
            id="pr-workflows"
            dataSource={orderedRows}
            columns={columns}
            size="small"
            loading={loading}
            rowKey={(row) => row.workflowName}
            useURLForSorting={false}
            expandable={{
                noIndent: true,
                rowExpandable: (row) => filteredRuns.some((run) => run.workflow === row.workflowName),
                expandedRowRender: (row) => (
                    <PerPushRunsTable
                        runs={filteredRuns.filter((run) => run.workflow === row.workflowName)}
                        runCostByKey={runCostByKey}
                        showCost={showCost}
                        repoOwner={repoOwner}
                        repoName={repoName}
                        sourceId={sourceId}
                        runJobs={runJobs}
                        runJobsLoading={runJobsLoading}
                        expandedRunKeys={expandedRunKeys}
                        setRunExpanded={setRunExpanded}
                    />
                ),
            }}
            pagination={{ pageSize: 10 }}
            emptyState="No CI runs match."
            nouns={['workflow', 'workflows']}
        />
    )
}

export function PullRequestDetailScene(): JSX.Element {
    const {
        lifecycle,
        lifecycleLoading,
        loadFailed,
        runs,
        commitGroups,
        filteredRuns,
        filteredPrWorkflowRows,
        prRunsLoading,
        prRunsFailed,
        prCost,
        prCostLoading,
        pushes,
        rerunCycles,
        workflowFilter,
        repoOwner,
        repoName,
        sourceId,
        runCostByKey,
        failureLogs,
        failureLogsLoading,
        latestPushStats,
        failingJobLabelByWorkflow,
        runJobs,
        runJobsLoading,
        expandedRunKeys,
        deliveryScope,
        timelinePushes,
    } = useValues(pullRequestDetailLogic)
    const { loadLifecycle, loadPrRuns, setWorkflowFilter, setRunExpanded } = useActions(pullRequestDetailLogic)
    const timelinesLogic = pullRequestTimelinesLogic({ scope: deliveryScope, sourceId })
    const { timelines, timelinesLoading, timelinesFailed } = useValues(timelinesLogic)
    const { loadTimelines } = useActions(timelinesLogic)

    const pullRequest = lifecycle?.pull_request
    const githubUrl = pullRequest
        ? githubPrUrl(pullRequest.repo.owner, pullRequest.repo.name, pullRequest.number)
        : null

    const passed = runs.filter((run) => run.conclusion !== null && isPassingConclusion(run.conclusion)).length
    const failed = runs.filter((run) => run.conclusion !== null && !isPassingConclusion(run.conclusion)).length
    const running = runs.filter((run) => run.conclusion === null).length
    const latestRound = commitGroups[0] ? pushRoundOf(commitGroups[0].headSha, commitGroups[0].runs) : null
    const tilesLoading = prRunsLoading && commitGroups.length === 0
    // The pull request scope returns this pull request alone.
    const timeline = timelines?.items.find((item) => item.segments.length > 0) ?? null

    if (loadFailed) {
        return (
            <SceneContent className="pb-16">
                <SceneTitleSection name="Pull request" resourceType={{ type: 'health' }} />
                <div className="flex items-center gap-3">
                    <span className="text-secondary">
                        Couldn't load this pull request. It may not exist in the connected GitHub source.
                    </span>
                    <LemonButton type="secondary" size="small" onClick={loadLifecycle} loading={lifecycleLoading}>
                        Retry
                    </LemonButton>
                </div>
            </SceneContent>
        )
    }

    return (
        <SceneContent className="pb-16">
            <SceneTitleSection
                name="Pull request"
                resourceType={{ type: 'health' }}
                actions={
                    githubUrl ? (
                        <LemonButton
                            type="secondary"
                            size="small"
                            to={githubUrl}
                            targetBlank
                            sideIcon={<IconExternal />}
                        >
                            View on GitHub
                        </LemonButton>
                    ) : undefined
                }
            />

            <ScopeBar
                repoSlot={
                    <RepoScopeChip
                        label={`${repoOwner}/${repoName}`}
                        to={withCurrentScope(urls.engineeringAnalytics(), sourceId)}
                    />
                }
                lensFilter={{
                    label: `pr: #${pullRequest?.number ?? ''}`,
                    to: withCurrentScope(urls.engineeringAnalytics(), sourceId),
                }}
                showDate={false}
            />

            {pullRequest ? (
                <>
                    <EntityHeader
                        icon={<IconPullRequest />}
                        title={pullRequest.title}
                        slug={
                            <>
                                <PullRequestStateTag state={pullRequest.state} isDraft={pullRequest.is_draft} />
                                <span>
                                    {pullRequest.repo.owner}/{pullRequest.repo.name} #{pullRequest.number}
                                </span>
                                <span>·</span>
                                <span className="flex items-center gap-1.5">
                                    {pullRequest.author.avatar_url && (
                                        <img
                                            src={pullRequest.author.avatar_url}
                                            alt=""
                                            className="size-4 shrink-0 rounded-full"
                                        />
                                    )}
                                    <Link
                                        to={
                                            combineUrl(
                                                urls.engineeringAnalyticsAuthor(pullRequest.author.handle),
                                                sourceId ? { source: sourceId } : {}
                                            ).url
                                        }
                                    >
                                        {pullRequest.author.handle}
                                    </Link>
                                    {pullRequest.author.is_bot && <LemonTag type="muted">bot</LemonTag>}
                                </span>
                                <span>
                                    · opened <TZLabel time={pullRequest.created_at} />
                                </span>
                            </>
                        }
                        right={
                            pullRequest.state === 'merged' ? (
                                <VerdictPill kind="muted">Merged</VerdictPill>
                            ) : latestPushStats && latestPushStats.failingWorkflows.length > 0 ? (
                                <VerdictPill kind="danger">CI failing</VerdictPill>
                            ) : latestPushStats && latestPushStats.running > 0 ? (
                                <VerdictPill kind="warning">CI running</VerdictPill>
                            ) : latestPushStats ? (
                                <VerdictPill kind="success">CI passing</VerdictPill>
                            ) : undefined
                        }
                    />
                    <div className="flex flex-wrap gap-2.5">
                        <MetricTile
                            label="Latest push"
                            tooltip="Workflows green on the newest commit, one verdict per workflow."
                            value={latestPushStats ? `${latestPushStats.green} / ${latestPushStats.total}` : '—'}
                            sub={
                                latestPushStats && latestPushStats.failingWorkflows.length > 0
                                    ? `${latestPushStats.failingWorkflows.slice(0, 3).join(', ')} failing`
                                    : latestPushStats && latestPushStats.running > 0
                                      ? `${latestPushStats.running} still running`
                                      : latestPushStats
                                        ? 'passing'
                                        : undefined
                            }
                            loading={tilesLoading}
                        />
                        <MetricTile
                            label="CI wall time"
                            tooltip="On the newest commit: earliest run start to latest completed run end."
                            value={
                                latestRound?.wallSeconds != null
                                    ? humanFriendlyDuration(latestRound.wallSeconds, { maxUnits: 2 })
                                    : '—'
                            }
                            sub={latestRound?.pending ? 'still running' : undefined}
                            loading={tilesLoading}
                        />
                        <MetricTile
                            label="Pushes"
                            tooltip="Commits that triggered CI on this pull request."
                            value={`${pushes}`}
                            sub={
                                rerunCycles > 0 ? (
                                    <span className="font-semibold text-warning-dark">+{rerunCycles} re-runs</span>
                                ) : undefined
                            }
                            loading={tilesLoading}
                        />
                        <MetricTile
                            label="CI cost"
                            tooltip={
                                prCost?.jobs_available
                                    ? `${compactUsd(
                                          (prCost.estimated_cost_usd ?? 0) / Math.max(1, pushes)
                                      )} per push${prCost.unsettled_jobs > 0 ? ` · ${pluralize(prCost.unsettled_jobs, 'unsettled job')} excluded` : ''}.`
                                    : 'Available once the job-level source is synced.'
                            }
                            value={prCost?.jobs_available ? compactUsd(prCost.estimated_cost_usd) : '—'}
                            sub={prCost?.jobs_available ? undefined : 'Job-level source not synced'}
                            loading={prCostLoading && !prCost}
                        />
                        {prCost?.llm_spend && (
                            <MetricTile
                                label="LLM spend"
                                tooltip="Token spend from AI coding/review sessions on this PR's branch, including spend from the same session before the branch was created."
                                value={compactUsd(prCost.llm_spend.cost_usd)}
                                sub={`${compactCount(
                                    prCost.llm_spend.input_tokens + prCost.llm_spend.output_tokens
                                )} tokens · ${pluralize(prCost.llm_spend.generations, 'generation')}`}
                            />
                        )}
                    </div>
                </>
            ) : (
                <LemonSkeleton className="h-24 w-full" />
            )}

            <Section id="pr-timeline" title="Lifecycle">
                {timelinesFailed ? (
                    <div className="flex items-center gap-3">
                        <span className="text-sm text-secondary">
                            Couldn't load the timeline for this pull request.
                        </span>
                        <LemonButton type="secondary" size="small" onClick={loadTimelines} loading={timelinesLoading}>
                            Retry
                        </LemonButton>
                    </div>
                ) : !timelines ? (
                    <LemonSkeleton className="h-40 w-full" />
                ) : timeline ? (
                    <PullRequestDeliveryTimeline
                        pr={timeline}
                        pushes={tilesLoading || prRunsFailed ? null : timelinePushes}
                    />
                ) : (
                    <div className="text-sm text-secondary">
                        No timeline for this pull request yet. If it stays empty, check the GitHub source's sync status.
                    </div>
                )}
            </Section>

            <Section
                id="pr-runs"
                title="CI runs"
                right={
                    runs.length > 0 ? (
                        <span className="text-xs text-secondary">
                            Cumulative · {pluralize(passed, 'run')} passed
                            {failed > 0 && <> · {failed} failed</>}
                            {running > 0 && <> · {running} still running</>}
                        </span>
                    ) : undefined
                }
            >
                {commitGroups.length > 0 && (
                    <LemonInput
                        type="search"
                        placeholder="Filter workflows…"
                        value={workflowFilter}
                        onChange={setWorkflowFilter}
                        className="mb-3 max-w-md"
                    />
                )}
                {prRunsLoading && commitGroups.length === 0 ? (
                    <LemonSkeleton className="h-24 w-full" />
                ) : prRunsFailed ? (
                    <div className="flex items-center gap-3">
                        <span className="text-sm text-secondary">Couldn't load CI runs for this pull request.</span>
                        <LemonButton type="secondary" size="small" onClick={loadPrRuns} loading={prRunsLoading}>
                            Retry
                        </LemonButton>
                    </div>
                ) : commitGroups.length === 0 ? (
                    <div className="text-sm text-secondary">No CI runs attributed to this pull request yet.</div>
                ) : filteredPrWorkflowRows.length === 0 ? (
                    <div className="text-sm text-secondary">No workflows match “{workflowFilter}”.</div>
                ) : (
                    <PrWorkflowsTable
                        rows={filteredPrWorkflowRows}
                        filteredRuns={filteredRuns}
                        failingJobLabelByWorkflow={failingJobLabelByWorkflow}
                        runCostByKey={runCostByKey}
                        showCost={prCost?.jobs_available ?? false}
                        loading={prRunsLoading}
                        repoOwner={repoOwner}
                        repoName={repoName}
                        sourceId={sourceId}
                        runJobs={runJobs}
                        runJobsLoading={runJobsLoading}
                        expandedRunKeys={expandedRunKeys}
                        setRunExpanded={setRunExpanded}
                    />
                )}
            </Section>

            {failed > 0 && (
                <Section id="pr-failures" title="Failures">
                    <FailureLogGroups logs={failureLogs} loading={failureLogsLoading} />
                </Section>
            )}

            <div className="text-xs text-tertiary">Review and comment activity isn't tracked yet.</div>
        </SceneContent>
    )
}

export default PullRequestDetailScene
