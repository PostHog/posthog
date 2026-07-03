import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconCheckCircle, IconExternal, IconHourglass, IconPause, IconXCircle } from '@posthog/icons'
import { LemonButton, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
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
import { formatCost, formatMinutes } from '../components/runTables'
import { RepoScopeChip, ScopeBar } from '../components/ScopeBar'
import { githubCommitUrl, githubRunUrl } from '../lib/github'
import { isDecisiveFailure } from '../lib/lifecycle'
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

export function WorkflowRunDetailScene(): JSX.Element {
    const {
        run,
        runLoading,
        loadFailed,
        sourceId,
        jobs,
        jobsLoading,
        runCost,
        isValidRunId,
        failureLogs,
        failureLogsLoading,
    } = useValues(workflowRunDetailLogic)
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
    // Run started → first job started: the runner-capacity wait before anything executed.
    const jobStarts = (jobs ?? []).map((job) => job.started_at).filter((at): at is string => !!at)
    const queueSeconds =
        run?.run_started_at && jobStarts.length
            ? Math.max(
                  0,
                  dayjs(jobStarts.reduce((min, at) => (at < min ? at : min))).diff(dayjs(run.run_started_at), 'second')
              )
            : null
    const jobRollupLabel = jobs?.length
        ? [
              `${jobs.filter((job) => job.conclusion === 'success').length} passed`,
              ...(jobs.some((job) => isDecisiveFailure(job.conclusion))
                  ? [`${jobs.filter((job) => isDecisiveFailure(job.conclusion)).length} failed`]
                  : []),
              ...(jobs.some((job) => job.conclusion === 'skipped')
                  ? [`${jobs.filter((job) => job.conclusion === 'skipped').length} skipped`]
                  : []),
          ].join(' · ')
        : null
    // The logs endpoint only carries job ids; the run's loaded jobs supply the names.
    const jobNamesById = Object.fromEntries((jobs ?? []).map((job) => [job.id, job.name]))

    if (loadFailed) {
        return (
            <SceneContent>
                <SceneTitleSection name="Workflow run" resourceType={{ type: 'health' }} />
                <div className="flex items-center gap-3">
                    <span className="text-secondary">
                        Couldn't load this workflow run. It may not exist in the connected GitHub source.
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
                    <ScopeBar
                        repoSlot={
                            <RepoScopeChip
                                label={`${run.repo.owner}/${run.repo.name}`}
                                to={combineUrl(urls.engineeringAnalytics(), sourceId ? { source: sourceId } : {}).url}
                            />
                        }
                        crumbs={[
                            {
                                label: run.workflow_name,
                                to: combineUrl(
                                    urls.engineeringAnalyticsWorkflowRuns(
                                        run.repo.owner,
                                        run.repo.name,
                                        run.workflow_name
                                    ),
                                    sourceId ? { source: sourceId } : {}
                                ).url,
                            },
                            { label: `run #${run.id}` },
                        ]}
                        showDate={false}
                    />
                    <EntityHeader
                        icon={
                            run.conclusion == null ? (
                                <IconHourglass className="text-muted" />
                            ) : isDecisiveFailure(run.conclusion) ? (
                                <IconXCircle className="text-danger" />
                            ) : run.conclusion === 'success' ? (
                                <IconCheckCircle className="text-success" />
                            ) : (
                                <IconPause className="text-muted" />
                            )
                        }
                        title={run.workflow_name}
                        titleSuffix={`#${run.id}`}
                        slug={
                            <>
                                {run.head_branch && <span>{run.head_branch}</span>}
                                {run.head_sha && (
                                    <>
                                        <span>· commit</span>
                                        <Link
                                            to={githubCommitUrl(run.repo.owner, run.repo.name, run.head_sha)}
                                            target="_blank"
                                        >
                                            {run.head_sha.slice(0, 7)}
                                        </Link>
                                    </>
                                )}
                                {prUrl && (
                                    <>
                                        <span>· pull request</span>
                                        <Link to={prUrl}>#{run.pr_number}</Link>
                                    </>
                                )}
                                {run.run_attempt > 1 && <span>· attempt {run.run_attempt}</span>}
                                {run.run_started_at && (
                                    <span>
                                        · started <TZLabel time={run.run_started_at} />
                                    </span>
                                )}
                            </>
                        }
                        right={
                            verdict ? (
                                <VerdictPill
                                    kind={
                                        run.conclusion == null
                                            ? 'warning'
                                            : isDecisiveFailure(run.conclusion)
                                              ? 'danger'
                                              : run.conclusion === 'success'
                                                ? 'success'
                                                : 'muted'
                                    }
                                >
                                    {verdict.label}
                                </VerdictPill>
                            ) : undefined
                        }
                    />

                    <div className="flex flex-wrap gap-2.5">
                        <MetricTile
                            label="Duration"
                            tooltip="Wall-clock time of the run."
                            value={run.duration_seconds == null ? '—' : humanFriendlyDuration(run.duration_seconds)}
                        />
                        <MetricTile
                            label="Queue time"
                            tooltip="From run started to the first job starting."
                            value={queueSeconds != null ? humanFriendlyDuration(queueSeconds) : '—'}
                        />
                        <MetricTile label="Jobs" tooltip={jobRollupLabel} value={jobs ? `${jobs.length}` : '—'} />
                        <MetricTile
                            label="Estimated cost"
                            tooltip={
                                runCost
                                    ? `${formatMinutes(runCost.billableMinutes)} billable × runner-tier rate${
                                          runCost.unsettledJobs > 0
                                              ? ` · ${pluralize(runCost.unsettledJobs, 'unsettled job')} excluded`
                                              : ''
                                      }.`
                                    : 'Available once the job-level source is synced.'
                            }
                            value={runCost ? formatCost(runCost.estimatedCostUsd) : '—'}
                        />
                    </div>

                    <div className="flex flex-col gap-2">
                        <h3 className="mb-0">Jobs</h3>
                        <GroupedJobsTable jobs={jobs} loading={jobsLoading} />
                    </div>

                    {isDecisiveFailure(run.conclusion) && (
                        <div className="flex flex-col gap-2">
                            <h3 className="mb-0">Failure logs</h3>
                            <FailureLogGroups
                                jobs={failureLogs === 'unavailable' ? [] : failureLogs?.jobs}
                                logsAvailable={failureLogs !== 'unavailable' && (failureLogs?.logs_available ?? false)}
                                loading={failureLogsLoading}
                                jobNames={jobNamesById}
                                emptyState={
                                    failureLogs === 'unavailable'
                                        ? 'Failure logs are unavailable for this run.'
                                        : undefined
                                }
                            />
                        </div>
                    )}
                </>
            ) : (
                <LemonSkeleton className="h-64 w-full" />
            )}
        </SceneContent>
    )
}

export default WorkflowRunDetailScene
