import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'

import { IconCheckCircle, IconExternal, IconHourglass, IconPause, IconXCircle } from '@posthog/icons'
import { LemonButton, LemonSkeleton, Link } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { pluralize } from 'lib/utils/strings'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { CIAnalyticsLoadError } from '../components/CIAnalyticsLoadError'
import { CITimeline } from '../components/CITimeline'
import { EntityHeader, VerdictPill } from '../components/EntityHeader'
import { FailureLogGroups } from '../components/FailureLogs'
import { MetricTile } from '../components/MetricTile'
import { ProductNav } from '../components/ProductNav'
import { RepoSceneTitle } from '../components/RepoSceneTitle'
import { formatCost, formatMinutes, runPrNumber } from '../components/runTables'
import { ScopeBar } from '../components/ScopeBar'
import { Section } from '../components/Section'
import { buildRunTimeline } from '../lib/ciTimeline'
import { githubCommitUrl, githubRunUrl } from '../lib/github'
import { isDecisiveFailure } from '../lib/lifecycle'
import { verdictTag } from '../lib/runStatus'
import { withScope } from '../lib/scope'
import { repoScopeLogic } from './repoScopeLogic'
import { WorkflowRunDetailLogicProps, workflowRunDetailLogic } from './workflowRunDetailLogic'

export const scene: SceneExport<WorkflowRunDetailLogicProps> = {
    component: WorkflowRunDetailScene,
    logic: workflowRunDetailLogic,
    paramsToProps: ({ params: { repoOwner, repoName, runId }, searchParams: { source, ci_engine } }) => ({
        repoOwner: decodeURIComponent(repoOwner),
        repoName: decodeURIComponent(repoName),
        runId: parseInt(runId, 10),
        ciEngine: ci_engine as WorkflowRunDetailLogicProps['ciEngine'],
        sourceId: source ?? null,
    }),
}

export function WorkflowRunDetailScene(): JSX.Element {
    // Remembers this repository, so the product root reopens it.
    useMountedLogic(repoScopeLogic)
    const {
        run,
        runLoading,
        loadFailed,
        sourceId,
        jobs,
        jobsLoading,
        jobsFailed,
        runCost,
        isValidRunId,
        failureLogs,
        failureLogsLoading,
    } = useValues(workflowRunDetailLogic)
    const { repoOwner, repoName } = useMountedLogic(workflowRunDetailLogic).props
    const { loadRun, loadJobs, loadFailureLogs } = useActions(workflowRunDetailLogic)
    const { searchParams } = useValues(router)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!isValidRunId) {
        return (
            <SceneContent className="pb-16">
                <RepoSceneTitle repo={`${repoOwner}/${repoName}`} />
                <ProductNav activeTab="workflows" repo={`${repoOwner}/${repoName}`} sourceId={sourceId}>
                    <span className="text-secondary">That run id isn't valid.</span>
                </ProductNav>
            </SceneContent>
        )
    }

    const githubUrl = run?.ci_engine === 'github_actions' ? githubRunUrl(run.repo.owner, run.repo.name, run.id) : null
    const verdict = run ? verdictTag(run.conclusion) : null
    const prNumber = run ? runPrNumber(run.pr_number, run.commit_pr_number) : null
    const prUrl =
        prNumber != null && run
            ? withScope(
                  urls.engineeringAnalyticsPullRequest(run.repo.owner, run.repo.name, prNumber),
                  searchParams,
                  sourceId
              )
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
    const jobsPending = jobsLoading && !jobs

    if (loadFailed) {
        return (
            <SceneContent className="pb-16">
                <RepoSceneTitle repo={`${repoOwner}/${repoName}`} />
                <ProductNav activeTab="workflows" repo={`${repoOwner}/${repoName}`} sourceId={sourceId}>
                    <CIAnalyticsLoadError
                        title="Couldn't load this workflow run"
                        description="It may not exist in the connected GitHub source. Retry, or check the source's sync status."
                        onRetry={loadRun}
                        loading={runLoading}
                    />
                </ProductNav>
            </SceneContent>
        )
    }

    return (
        <SceneContent className="pb-16">
            <RepoSceneTitle
                repo={`${repoOwner}/${repoName}`}
                actions={
                    githubUrl ? (
                        todayRailNav ? (
                            <Button variant="outline" render={<LinkPrimitive to={githubUrl} target="_blank" />}>
                                View on GitHub
                                <IconExternal />
                            </Button>
                        ) : (
                            <LemonButton
                                type="secondary"
                                size="small"
                                to={githubUrl}
                                targetBlank
                                sideIcon={<IconExternal />}
                            >
                                View on GitHub
                            </LemonButton>
                        )
                    ) : undefined
                }
            />

            <ProductNav activeTab="workflows" repo={`${repoOwner}/${repoName}`} sourceId={sourceId}>
                <div className="flex flex-col gap-4">
                    {run ? (
                        <>
                            <ScopeBar
                                crumbs={[
                                    {
                                        label: 'Workflows',
                                        to: withScope(
                                            urls.engineeringAnalyticsWorkflows(`${repoOwner}/${repoName}`),
                                            searchParams,
                                            sourceId
                                        ),
                                    },
                                    {
                                        label: run.workflow_name,
                                        // Carries the window scope back so stepping up doesn't reset it.
                                        to: withScope(
                                            urls.engineeringAnalyticsWorkflowRuns(
                                                run.repo.owner,
                                                run.repo.name,
                                                run.workflow_name
                                            ),
                                            searchParams,
                                            sourceId
                                        ),
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
                                                <Link to={prUrl}>#{prNumber}</Link>
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
                                    value={
                                        run.duration_seconds == null ? '—' : humanFriendlyDuration(run.duration_seconds)
                                    }
                                />
                                <MetricTile
                                    label="Queue time"
                                    tooltip="From run started to the first job starting."
                                    value={queueSeconds != null ? humanFriendlyDuration(queueSeconds) : '—'}
                                    loading={jobsPending}
                                />
                                <MetricTile
                                    label="Jobs"
                                    tooltip={jobRollupLabel}
                                    value={jobs ? `${jobs.length}` : '—'}
                                    loading={jobsPending}
                                />
                                <MetricTile
                                    label="Estimated cost"
                                    tooltip={
                                        runCost
                                            ? `${formatMinutes(runCost.billableMinutes)} billable × runner-tier rate${
                                                  runCost.unsettledJobs > 0
                                                      ? ` · ${pluralize(runCost.unsettledJobs, 'unsettled job')} excluded`
                                                      : ''
                                              }.`
                                            : jobsFailed
                                              ? "Couldn't load this run's jobs."
                                              : 'Available once the job-level source is synced.'
                                    }
                                    value={runCost ? formatCost(runCost.estimatedCostUsd) : '—'}
                                    loading={jobsPending}
                                />
                            </div>

                            <Section id="jobs" title="Jobs">
                                {jobsFailed ? (
                                    <CIAnalyticsLoadError
                                        title="Couldn't load this run's jobs"
                                        onRetry={loadJobs}
                                        loading={jobsLoading}
                                    />
                                ) : jobs == null ? (
                                    <LemonSkeleton className="h-48 w-full" />
                                ) : jobs.length === 0 ? (
                                    <div className="text-sm text-secondary">
                                        No job data yet. The job-level source isn't synced for this team.
                                    </div>
                                ) : (
                                    <CITimeline
                                        timeline={buildRunTimeline(
                                            { owner: repoOwner, name: repoName },
                                            run.run_started_at,
                                            jobs,
                                            Date.now()
                                        )}
                                    />
                                )}
                            </Section>

                            {isDecisiveFailure(run.conclusion) && (
                                <Section id="failure-logs" title="Failure logs">
                                    <FailureLogGroups
                                        logs={failureLogs}
                                        loading={failureLogsLoading}
                                        onRetry={loadFailureLogs}
                                        jobNames={jobNamesById}
                                        logsOnGitHub={githubUrl !== null}
                                    />
                                </Section>
                            )}
                        </>
                    ) : (
                        <LemonSkeleton className="h-64 w-full" />
                    )}
                </div>
            </ProductNav>
        </SceneContent>
    )
}

export default WorkflowRunDetailScene
