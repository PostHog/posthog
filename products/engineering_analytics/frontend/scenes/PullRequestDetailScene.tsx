import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { Fragment } from 'react'

import { IconExternal } from '@posthog/icons'
import {
    LemonButton,
    LemonSkeleton,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    LemonTagType,
    Link,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { pluralize } from 'lib/utils/strings'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import type { PullRequestApi, WorkflowJobApi } from '../generated/api.schemas'
import { githubCommitUrl, githubPrUrl, githubWorkflowUrl } from '../lib/github'
import { LifecycleSummary, WorkflowRun, isPassingConclusion } from '../lib/lifecycle'
import { verdictTag } from '../lib/runStatus'
import { PullRequestDetailLogicProps, pullRequestDetailLogic } from './pullRequestDetailLogic'

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

const STATE_TAG: Record<string, { label: string; type: LemonTagType }> = {
    open: { label: 'Open', type: 'primary' },
    merged: { label: 'Merged', type: 'success' },
    closed: { label: 'Closed', type: 'danger' },
}

function gapBetween(from: string, to: string): string {
    const seconds = dayjs(to).diff(dayjs(from), 'second')
    return seconds <= 0 ? '<1s' : humanFriendlyDuration(seconds, { maxUnits: 2 })
}

interface TimelineNode {
    key: string
    label: string
    at: string
    dotClass: string
    /** The connector leading into this node — dashed when the time span is still running. */
    dashedIncoming?: boolean
    showTime?: boolean
}

/**
 * Horizontal timeline: dots are milestones, the duration above each connector is the
 * gap between them — where the hours actually went. Chronological — a PR's head-SHA
 * runs can start (and finish) after the merge.
 */
function LifecycleStrip({ summary, openedAt }: { summary: LifecycleSummary; openedAt: string }): JSX.Element {
    const nodes: TimelineNode[] = [
        { key: 'opened', label: 'Opened', at: openedAt, dotClass: 'bg-muted', showTime: true },
    ]
    if (summary.firstCiStartedAt) {
        nodes.push({
            key: 'ci-start',
            label: 'First CI run',
            at: summary.firstCiStartedAt,
            dotClass: 'bg-muted',
        })
    }
    if (summary.lastCiFinishedAt) {
        nodes.push({
            key: 'ci-end',
            label: 'Last CI verdict',
            at: summary.lastCiFinishedAt,
            dotClass: 'bg-muted',
        })
    }
    if (summary.mergedAt) {
        nodes.push({ key: 'merged', label: 'Merged', at: summary.mergedAt, dotClass: 'bg-success', showTime: true })
    } else if (summary.closedAt) {
        nodes.push({ key: 'closed', label: 'Closed', at: summary.closedAt, dotClass: 'bg-danger', showTime: true })
    }
    nodes.sort((a, b) => (a.at < b.at ? -1 : a.at > b.at ? 1 : 0))

    const stillOpen = !summary.mergedAt && !summary.closedAt
    if (stillOpen) {
        nodes.push({
            key: 'now',
            label: 'Still open',
            at: dayjs().toISOString(),
            dotClass: 'animate-pulse border-2 border-warning bg-transparent',
            dashedIncoming: true,
        })
    }

    // Not necessarily the last node's time: head-SHA runs can outlive the merge.
    const totalTo = summary.mergedAt ?? summary.closedAt ?? nodes[nodes.length - 1].at
    const connector = (dashed: boolean | undefined): string =>
        dashed ? 'w-full border-t border-dashed border-border-bold' : 'h-px w-full bg-border-bold'

    // Connector widths are proportional to real elapsed time, so the strip reads as a timeline —
    // a long review wait visibly dominates a quick queue. Floor each segment so a near-instant gap
    // still draws a visible connector instead of collapsing to nothing.
    const totalSeconds = Math.max(1, dayjs(nodes[nodes.length - 1].at).diff(dayjs(nodes[0].at), 'second'))
    const minGrow = totalSeconds * 0.04

    return (
        <div className="flex items-center gap-6 rounded-lg border bg-surface-primary px-5 py-3">
            <div className="flex min-w-0 flex-1 items-stretch overflow-x-auto">
                {nodes.map((node, index) => (
                    <Fragment key={node.key}>
                        {index > 0 && (
                            <div
                                className="flex min-w-10 flex-col gap-1"
                                style={{
                                    flexGrow: Math.max(
                                        minGrow,
                                        dayjs(node.at).diff(dayjs(nodes[index - 1].at), 'second')
                                    ),
                                }}
                            >
                                <span className="text-center text-xs leading-4 whitespace-nowrap text-secondary tabular-nums">
                                    {gapBetween(nodes[index - 1].at, node.at)}
                                </span>
                                <span className="flex h-2.5 items-center">
                                    <span className={connector(node.dashedIncoming)} />
                                </span>
                                <span className="text-xs leading-4">&nbsp;</span>
                            </div>
                        )}
                        <div className="flex shrink-0 flex-col items-center gap-1 px-1">
                            <span className="text-xs font-medium leading-4 whitespace-nowrap">{node.label}</span>
                            <span className="flex h-2.5 w-full items-center">
                                <span className={cn('flex-1', index > 0 && connector(node.dashedIncoming))} />
                                <span className={cn('h-2.5 w-2.5 shrink-0 rounded-full', node.dotClass)} />
                                <span
                                    className={cn(
                                        'flex-1',
                                        index < nodes.length - 1 && connector(nodes[index + 1].dashedIncoming)
                                    )}
                                />
                            </span>
                            <span className="text-xs leading-4 whitespace-nowrap text-tertiary">
                                {node.showTime ? <TZLabel time={node.at} /> : <>&nbsp;</>}
                            </span>
                        </div>
                    </Fragment>
                ))}
            </div>
            <div className="flex shrink-0 flex-col items-end self-center border-l border-primary pl-6">
                <span className="text-lg font-semibold leading-6 tabular-nums">{gapBetween(openedAt, totalTo)}</span>
                <span className="text-xs text-tertiary">
                    {summary.mergedAt ? 'open → merge' : summary.closedAt ? 'open → close' : 'open so far'}
                </span>
            </div>
        </div>
    )
}

function MetaRow({ pullRequest }: { pullRequest: PullRequestApi }): JSX.Element {
    const stateTag = STATE_TAG[pullRequest.state] ?? { label: pullRequest.state, type: 'muted' as LemonTagType }
    return (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
            <LemonTag type={stateTag.type}>{stateTag.label}</LemonTag>
            {pullRequest.is_draft && <LemonTag type="muted">draft</LemonTag>}
            <span className="flex items-center gap-1.5">
                {pullRequest.author.avatar_url && (
                    <img src={pullRequest.author.avatar_url} alt="" className="h-5 w-5 shrink-0 rounded-full" />
                )}
                <span>{pullRequest.author.handle}</span>
                {pullRequest.author.is_bot && <LemonTag type="muted">bot</LemonTag>}
            </span>
            <span className="font-mono text-xs text-secondary">
                {pullRequest.repo.owner}/{pullRequest.repo.name} #{pullRequest.number}
            </span>
        </div>
    )
}

// Verdict tag type → bar fill, so the Gantt bars match the Verdict column's colors.
const BAR_BG: Record<string, string> = {
    success: 'bg-success',
    danger: 'bg-danger',
    warning: 'bg-warning',
    muted: 'bg-muted',
}

/**
 * One run as a Gantt bar on the shared CI timeline (earliest start → latest finish across the PR's
 * runs), so overlap and stragglers are visible at a glance. A still-running bar extends to "now".
 */
function RunGanttBar({
    run,
    axisStart,
    axisEnd,
}: {
    run: WorkflowRun
    axisStart: number
    axisEnd: number
}): JSX.Element {
    if (!run.startedAt) {
        return <span className="text-xs text-secondary">—</span>
    }
    const start = dayjs(run.startedAt).valueOf()
    const end = run.finishedAt ? dayjs(run.finishedAt).valueOf() : dayjs().valueOf()
    const span = Math.max(1, axisEnd - axisStart)
    const left = Math.max(0, Math.min(100, ((start - axisStart) / span) * 100))
    const width = Math.max(2, Math.min(100 - left, ((end - start) / span) * 100))
    const tag = verdictTag(run.conclusion)
    const finishedLabel = run.finishedAt ? dayjs(run.finishedAt).format('HH:mm:ss') : 'now'
    const durationLabel = run.durationSeconds == null ? '' : ` · ${humanFriendlyDuration(run.durationSeconds)}`
    return (
        <div
            className="relative h-3 w-full"
            title={`${dayjs(run.startedAt).format('HH:mm:ss')} → ${finishedLabel}${durationLabel}`}
        >
            <div
                className={cn(
                    'absolute top-0 h-3 rounded-sm',
                    BAR_BG[tag.type] ?? 'bg-muted',
                    run.conclusion === null && 'animate-pulse'
                )}
                style={{ left: `${left}%`, width: `${width}%` }}
            />
        </div>
    )
}

// Stable per-row key — re-runs share a runId, so the start time disambiguates attempt rows. Used for
// both LemonTable's rowKey and the expand-state set, so expanding one attempt doesn't open the others.
function runRowKey(run: WorkflowRun): string {
    return `${run.workflow}@${run.startedAt ?? run.finishedAt ?? run.runId ?? ''}`
}

function formatCost(usd: number | null): string {
    return usd == null ? '—' : `$${usd.toFixed(2)}`
}

/** Expanded-row content for a run: its jobs (runner tier, duration, est. cost). Lazy-loaded on expand. */
function RunJobs({ jobs, loading }: { jobs: WorkflowJobApi[] | undefined; loading: boolean }): JSX.Element {
    if (jobs === undefined) {
        return <div className="px-3 py-2 text-xs text-secondary">{loading ? 'Loading jobs…' : 'No job data yet.'}</div>
    }
    if (jobs.length === 0) {
        return (
            <div className="px-3 py-2 text-xs text-secondary">
                No job data yet — the job-level source isn't synced for this team.
            </div>
        )
    }
    const jobColumns: LemonTableColumns<WorkflowJobApi> = [
        { title: 'Job', key: 'name', render: (_, job) => <span className="font-medium">{job.name}</span> },
        {
            title: 'Status',
            key: 'status',
            width: 120,
            render: (_, job) => {
                const tag = verdictTag(job.conclusion)
                return <LemonTag type={tag.type}>{tag.label}</LemonTag>
            },
        },
        {
            title: 'Runner',
            key: 'runner',
            width: 120,
            render: (_, job) => <span className="font-mono text-xs">{job.runner_label || '—'}</span>,
        },
        {
            title: 'Duration',
            key: 'duration',
            width: 110,
            align: 'right',
            render: (_, job) => (
                <span className="text-xs whitespace-nowrap tabular-nums">
                    {job.duration_seconds == null ? '—' : humanFriendlyDuration(job.duration_seconds)}
                </span>
            ),
        },
        {
            title: 'Est. cost',
            key: 'cost',
            width: 100,
            align: 'right',
            render: (_, job) => <span className="text-xs tabular-nums">{formatCost(job.estimated_cost_usd)}</span>,
        },
    ]
    return <LemonTable embedded size="small" columns={jobColumns} dataSource={jobs} rowKey={(job) => job.id} />
}

interface RunsTableProps {
    runs: WorkflowRun[]
    repoOwner: string
    repoName: string
    sourceId: string | null
    loading: boolean
    runJobs: Record<number, WorkflowJobApi[]>
    runJobsLoading: boolean
    expandedRunKeys: string[]
    setRunExpanded: (rowKey: string, expanded: boolean, runId: number | null) => void
}

/** One commit's CI runs: Gantt on a shared axis, attempts labeled, expand a row for its jobs. */
function RunsTable({
    runs,
    repoOwner,
    repoName,
    sourceId,
    loading,
    runJobs,
    runJobsLoading,
    expandedRunKeys,
    setRunExpanded,
}: RunsTableProps): JSX.Element {
    // Shared Gantt axis for this commit's runs: earliest start → latest finish (running extends to now).
    const startMs = runs
        .map((run) => run.startedAt)
        .filter((at): at is string => !!at)
        .map((at) => dayjs(at).valueOf())
    const endMs = runs
        .map((run) => run.finishedAt ?? (run.startedAt ? dayjs().toISOString() : null))
        .filter((at): at is string => !!at)
        .map((at) => dayjs(at).valueOf())
    const axisStart = startMs.length ? Math.min(...startMs) : null
    const axisEnd = endMs.length ? Math.max(...endMs) : null

    // Re-runs share a runId; number each multi-attempt run by start order to label "attempt N".
    const attemptIndexByKey = new Map<string, number>()
    const runsByRunId = new Map<number, WorkflowRun[]>()
    runs.forEach((run) => {
        if (run.runId != null) {
            const group = runsByRunId.get(run.runId) ?? []
            group.push(run)
            runsByRunId.set(run.runId, group)
        }
    })
    runsByRunId.forEach((group) => {
        if (group.length > 1) {
            ;[...group]
                .sort((a, b) => (a.startedAt ?? '').localeCompare(b.startedAt ?? ''))
                .forEach((run, index) => attemptIndexByKey.set(runRowKey(run), index + 1))
        }
    })

    const columns: LemonTableColumns<WorkflowRun> = [
        {
            title: 'Workflow',
            key: 'workflow',
            // Tiebreak by start so a workflow's re-run attempts stay in order under it.
            sorter: (a, b) =>
                a.workflow.localeCompare(b.workflow) || (a.startedAt ?? '').localeCompare(b.startedAt ?? ''),
            render: (_, run) => {
                const attempt = attemptIndexByKey.get(runRowKey(run))
                const attemptTag = attempt ? <LemonTag type="muted">attempt {attempt}</LemonTag> : null
                // A run with an id links to its detail page; without one, fall back to the workflow's
                // GitHub Actions list (we have no run to point at).
                const label =
                    run.runId != null ? (
                        <Link
                            to={
                                combineUrl(
                                    urls.engineeringAnalyticsWorkflowRun(repoOwner, repoName, run.runId),
                                    sourceId ? { source: sourceId } : {}
                                ).url
                            }
                            className="font-medium"
                            onClick={(e) => e.stopPropagation()}
                        >
                            {run.workflow}
                        </Link>
                    ) : (
                        <Link
                            to={githubWorkflowUrl(repoOwner, repoName, run.workflow)}
                            target="_blank"
                            className="font-medium"
                            onClick={(e) => e.stopPropagation()}
                        >
                            {run.workflow}
                        </Link>
                    )
                return (
                    <div className="flex items-center gap-2">
                        {label}
                        {attemptTag}
                    </div>
                )
            },
        },
        {
            title: 'Verdict',
            key: 'verdict',
            width: 140,
            sorter: (a, b) => verdictTag(a.conclusion).label.localeCompare(verdictTag(b.conclusion).label),
            render: (_, run) => {
                const tag = verdictTag(run.conclusion)
                return <LemonTag type={tag.type}>{tag.label}</LemonTag>
            },
        },
        {
            title: 'Timeline',
            key: 'timeline',
            width: 240,
            sorter: (a, b) => (a.startedAt ?? '').localeCompare(b.startedAt ?? ''),
            render: (_, run) =>
                axisStart != null && axisEnd != null ? (
                    <RunGanttBar run={run} axisStart={axisStart} axisEnd={axisEnd} />
                ) : (
                    <span className="text-xs text-secondary">—</span>
                ),
        },
        {
            title: 'Duration',
            key: 'duration',
            width: 130,
            align: 'right',
            sorter: (a, b) => (a.durationSeconds ?? -1) - (b.durationSeconds ?? -1),
            render: (_, run) => (
                <span className="text-xs whitespace-nowrap tabular-nums">
                    {run.durationSeconds == null ? '—' : humanFriendlyDuration(run.durationSeconds)}
                </span>
            ),
        },
        {
            title: 'Finished',
            key: 'finished',
            width: 140,
            align: 'right',
            render: (_, run) =>
                run.finishedAt ? (
                    <span className="text-xs whitespace-nowrap">
                        <TZLabel time={run.finishedAt} />
                    </span>
                ) : (
                    <span className="text-xs text-secondary">—</span>
                ),
        },
    ]

    return (
        <LemonTable
            data-attr="engineering-analytics-pr-runs-table"
            size="small"
            columns={columns}
            dataSource={runs}
            rowKey={runRowKey}
            loading={loading}
            useURLForSorting={false}
            // Group by workflow by default (runs on one commit share a start, so chronological ties and
            // looks scrambled); the Gantt column carries the timing. Headers re-sort.
            defaultSorting={{ columnKey: 'workflow', order: 1 }}
            // Whole-row click toggles the job breakdown (the logs-viewer pattern); in-row links
            // stopPropagation so they still navigate.
            onRow={(run) =>
                run.runId != null
                    ? {
                          className: 'cursor-pointer',
                          onClick: () =>
                              setRunExpanded(runRowKey(run), !expandedRunKeys.includes(runRowKey(run)), run.runId),
                      }
                    : {}
            }
            expandable={{
                showRowExpansionToggle: false,
                rowExpandable: (run) => run.runId != null,
                isRowExpanded: (run) => expandedRunKeys.includes(runRowKey(run)),
                expandedRowRender: (run) => (
                    <RunJobs jobs={run.runId != null ? runJobs[run.runId] : undefined} loading={runJobsLoading} />
                ),
            }}
            emptyState="No CI runs for this commit."
            nouns={['workflow run', 'workflow runs']}
        />
    )
}

export function PullRequestDetailScene(): JSX.Element {
    const {
        lifecycle,
        lifecycleLoading,
        loadFailed,
        summary,
        runs,
        commitGroups,
        prRunsLoading,
        repoOwner,
        repoName,
        sourceId,
        runJobs,
        runJobsLoading,
        expandedRunKeys,
    } = useValues(pullRequestDetailLogic)
    const { loadLifecycle, setRunExpanded } = useActions(pullRequestDetailLogic)

    const pullRequest = lifecycle?.pull_request
    const githubUrl = pullRequest
        ? githubPrUrl(pullRequest.repo.owner, pullRequest.repo.name, pullRequest.number)
        : null

    const passed = runs.filter((run) => run.conclusion !== null && isPassingConclusion(run.conclusion)).length
    const failed = runs.filter((run) => run.conclusion !== null && !isPassingConclusion(run.conclusion)).length
    const running = runs.filter((run) => run.conclusion === null).length

    if (loadFailed) {
        return (
            <SceneContent>
                <SceneTitleSection name="Pull request" resourceType={{ type: 'health' }} />
                <div className="flex items-center gap-3">
                    <span className="text-secondary">
                        Couldn't load this pull request — it may not exist in the connected GitHub source.
                    </span>
                    <LemonButton type="secondary" size="small" onClick={loadLifecycle} loading={lifecycleLoading}>
                        Retry
                    </LemonButton>
                </div>
            </SceneContent>
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={pullRequest?.title ?? 'Pull request'}
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

            {pullRequest ? <MetaRow pullRequest={pullRequest} /> : <LemonSkeleton className="h-5 w-96" />}

            {summary && pullRequest ? (
                <LifecycleStrip summary={summary} openedAt={summary.openedAt ?? pullRequest.created_at} />
            ) : (
                <LemonSkeleton className="h-12 w-full" />
            )}

            <div>
                <div className="mb-2 flex items-baseline justify-between">
                    <h3 className="mb-0">CI runs</h3>
                    {runs.length > 0 && (
                        <span className="text-xs text-secondary">
                            {pluralize(passed, 'run')} passed
                            {failed > 0 && <> · {failed} failed</>}
                            {running > 0 && <> · {running} still running</>}
                            {commitGroups.length > 1 && <> · {pluralize(commitGroups.length, 'commit')}</>}
                        </span>
                    )}
                </div>
                {prRunsLoading && commitGroups.length === 0 ? (
                    <LemonSkeleton className="h-24 w-full" />
                ) : commitGroups.length === 0 ? (
                    <div className="text-sm text-secondary">No CI runs attributed to this pull request yet.</div>
                ) : (
                    <div className="flex flex-col gap-4">
                        {commitGroups.map((group) => (
                            <div key={group.headSha} className="flex flex-col gap-1">
                                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
                                    <Link
                                        to={githubCommitUrl(repoOwner, repoName, group.headSha)}
                                        target="_blank"
                                        className="font-mono text-xs font-medium"
                                    >
                                        {group.headSha.slice(0, 7)}
                                    </Link>
                                    {group.headBranch && (
                                        <span className="font-mono text-xs text-secondary">{group.headBranch}</span>
                                    )}
                                    <span className="text-xs text-tertiary">{pluralize(group.runs.length, 'run')}</span>
                                    {group.latestStart && (
                                        <span className="text-xs text-tertiary">
                                            · <TZLabel time={group.latestStart} />
                                        </span>
                                    )}
                                </div>
                                <RunsTable
                                    runs={group.runs}
                                    repoOwner={repoOwner}
                                    repoName={repoName}
                                    sourceId={sourceId}
                                    loading={prRunsLoading}
                                    runJobs={runJobs}
                                    runJobsLoading={runJobsLoading}
                                    expandedRunKeys={expandedRunKeys}
                                    setRunExpanded={setRunExpanded}
                                />
                            </div>
                        ))}
                    </div>
                )}
            </div>

            <div className="text-xs text-tertiary">
                CI runs attributed to this pull request across all its commits — review and comment activity isn't
                tracked yet.
            </div>
        </SceneContent>
    )
}

export default PullRequestDetailScene
