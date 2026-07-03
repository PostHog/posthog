import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconExternal } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { pluralize } from 'lib/utils/strings'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { RunJobsTable, formatCost, formatMinutes } from '../components/runTables'
import { StatTile } from '../components/StatTile'
import { githubCommitUrl, githubRunUrl } from '../lib/github'
import { verdictTag } from '../lib/runStatus'
import { WorkflowRunDetailLogicProps, workflowRunDetailLogic } from './workflowRunDetailLogic'

export const scene: SceneExport<WorkflowRunDetailLogicProps> = {
    component: WorkflowRunDetailScene,
    logic: workflowRunDetailLogic,
    paramsToProps: ({ params: { repoOwner, repoName, runId }, searchParams: { source } }) => ({
        repoOwner: decodeURIComponent(repoOwner),
        repoName: decodeURIComponent(repoName),
        runId: parseInt(runId, 10),
        sourceId: source ?? null,
    }),
}

function DetailRow({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex items-baseline gap-4 px-4 py-2.5">
            <span className="w-32 shrink-0 text-xs text-secondary">{label}</span>
            <span className="min-w-0 text-sm">{children}</span>
        </div>
    )
}

export function WorkflowRunDetailScene(): JSX.Element {
    const { run, runLoading, loadFailed, sourceId, jobs, jobsLoading, runCost, isValidRunId } =
        useValues(workflowRunDetailLogic)
    const { loadRun } = useActions(workflowRunDetailLogic)

    if (!isValidRunId) {
        return (
            <SceneContent>
                <SceneTitleSection name="Workflow run" resourceType={{ type: 'health' }} />
                <span className="text-secondary">That run id isn't valid.</span>
            </SceneContent>
        )
    }

    const githubUrl = run ? githubRunUrl(run.repo.owner, run.repo.name, run.id) : null
    const verdict = run ? verdictTag(run.conclusion) : null
    const prUrl =
        run && run.pr_number > 0
            ? combineUrl(
                  urls.engineeringAnalyticsPullRequest(run.repo.owner, run.repo.name, run.pr_number),
                  sourceId ? { source: sourceId } : {}
              ).url
            : null

    if (loadFailed) {
        return (
            <SceneContent>
                <SceneTitleSection name="Workflow run" resourceType={{ type: 'health' }} />
                <div className="flex items-center gap-3">
                    <span className="text-secondary">
                        Couldn't load this workflow run — it may not exist in the connected GitHub source.
                    </span>
                    <LemonButton type="secondary" size="small" onClick={loadRun} loading={runLoading}>
                        Retry
                    </LemonButton>
                </div>
            </SceneContent>
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={run?.workflow_name ?? 'Workflow run'}
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

            {run ? (
                <>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                        {verdict && <LemonTag type={verdict.type}>{verdict.label}</LemonTag>}
                        {run.run_attempt > 1 && <LemonTag type="muted">attempt {run.run_attempt}</LemonTag>}
                        <span className="font-mono text-xs text-secondary">
                            {run.repo.owner}/{run.repo.name} · run #{run.id}
                        </span>
                    </div>

                    {runCost && (
                        <div className="flex flex-col gap-2">
                            <div className="flex flex-wrap items-center gap-2">
                                <LemonTag type="warning">estimate · wall-clock × reference rate</LemonTag>
                                {runCost.unsettledJobs > 0 && (
                                    <LemonTag type="muted">
                                        {pluralize(runCost.unsettledJobs, 'unsettled job')} excluded
                                    </LemonTag>
                                )}
                            </div>
                            <StatTile
                                label="Billable CI minutes"
                                value={formatMinutes(runCost.billableMinutes)}
                                sub={<>≈ {formatCost(runCost.estimatedCostUsd)} estimated</>}
                                className="max-w-72"
                            />
                        </div>
                    )}

                    <LemonCard hoverEffect={false} className="divide-y p-0">
                        <DetailRow label="Status">
                            <span className="capitalize">{run.status || '—'}</span>
                        </DetailRow>
                        <DetailRow label="Duration">
                            <span className="tabular-nums">
                                {run.duration_seconds == null ? '—' : humanFriendlyDuration(run.duration_seconds)}
                            </span>
                        </DetailRow>
                        <DetailRow label="Started">
                            {run.run_started_at ? (
                                <TZLabel time={run.run_started_at} />
                            ) : (
                                <span className="text-secondary">—</span>
                            )}
                        </DetailRow>
                        <DetailRow label="Updated">
                            {run.updated_at ? (
                                <TZLabel time={run.updated_at} />
                            ) : (
                                <span className="text-secondary">—</span>
                            )}
                        </DetailRow>
                        <DetailRow label="Branch">
                            {run.head_branch ? (
                                <span className="font-mono text-xs">{run.head_branch}</span>
                            ) : (
                                <span className="text-secondary">—</span>
                            )}
                        </DetailRow>
                        <DetailRow label="Commit">
                            {run.head_sha ? (
                                <Link
                                    to={githubCommitUrl(run.repo.owner, run.repo.name, run.head_sha)}
                                    target="_blank"
                                    className="font-mono text-xs"
                                >
                                    {run.head_sha.slice(0, 7)}
                                </Link>
                            ) : (
                                <span className="text-secondary">—</span>
                            )}
                        </DetailRow>
                        <DetailRow label="Pull request">
                            {prUrl ? (
                                <Link to={prUrl} className="font-medium">
                                    #{run.pr_number}
                                </Link>
                            ) : (
                                <span className="text-secondary">—</span>
                            )}
                        </DetailRow>
                    </LemonCard>

                    <div className="flex flex-col gap-2">
                        <h3 className="mb-0">Jobs</h3>
                        <RunJobsTable jobs={jobs} loading={jobsLoading} />
                    </div>
                </>
            ) : (
                <LemonSkeleton className="h-64 w-full" />
            )}
        </SceneContent>
    )
}

export default WorkflowRunDetailScene
