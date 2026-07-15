import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { Fragment, ReactNode } from 'react'

import { IconExternal, IconPullRequest } from '@posthog/icons'
import {
    LemonButton,
    LemonInput,
    LemonSkeleton,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
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
import { PullRequestStateTag } from '../components/PullRequestStateTag'
import { RunConclusionTag } from '../components/runTables'
import { RepoScopeChip, ScopeBar } from '../components/ScopeBar'
import { Section } from '../components/Section'
import type { WorkflowJobApi } from '../generated/api.schemas'
import { compactCount, compactUsd } from '../lib/format'
import { githubCommitUrl, githubPrUrl } from '../lib/github'
import { LifecycleSummary, WorkflowRun, isPassingConclusion } from '../lib/lifecycle'
import { PushRound, pushRoundColor, pushRoundOf, pushRoundVerdictLabel } from '../lib/pushRounds'
import {
    PrCommitRuns,
    PrRunRow,
    PrWorkflowRow,
    PullRequestDetailLogicProps,
    jobCacheKey,
    pullRequestDetailLogic,
    latestRunPerWorkflow,
} from './pullRequestDetailLogic'

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
    /** Small caption under the dot — relative time, the push's CI wall time, "now", … */
    sublabel?: ReactNode
    /** Round nodes render the sha in mono. */
    mono?: boolean
    /** Color the label red — a failed round / closed PR. */
    danger?: boolean
    /** Push nodes carry their CI round: a bar above the dot (height = wall time, color = verdict). */
    round?: PushRound
}

interface LifecycleStripProps {
    summary: LifecycleSummary
    openedAt: string
    // One node per push (CI round); each scrolls to its run table below.
    commitGroups: PrCommitRuns[]
}

/** The earliest run start in a round — where that push's CI begins on the timeline. */
function roundStart(group: PrCommitRuns): string | null {
    const starts = group.runs.map((run) => run.startedAt).filter((at): at is string => !!at)
    return starts.length ? starts.reduce((min, at) => (at < min ? at : min)) : group.latestStart
}

// Fixed row heights so dots and connectors line up across columns regardless of label/pill height.
const ROW_LABEL = 'flex h-5 items-center'
const ROW_BAR = 'flex h-10 items-end justify-center'
const ROW_DOT = 'flex h-3 items-center'
const ROW_SUB = 'flex h-4 items-center'
// Tallest push bar in px — must fit inside ROW_BAR's h-10 (40px) with a little headroom.
const BAR_MAX_PX = 34

/** Dot color matching the round's verdict, so the timeline and the bars tell one story. */
function roundDotClass(round: PushRound): string {
    return round.failed ? 'bg-danger' : round.pending ? 'bg-warning' : 'bg-success'
}

// Cap push nodes so the strip fits on one line; older pushes collapse into a "+N earlier" node, and
// every round stays reachable in the list below.
const MAX_PUSH_NODES = 4

/**
 * Horizontal lifecycle timeline crossed with a per-push bar chart: dots are milestones, the pill above
 * each connector is the gap between them, and each push node grows a bar — height is that push's
 * wall-clock CI time (shared scale), color its verdict. Chronological — a PR's head-SHA runs can start
 * (and finish) after the merge.
 */
function LifecycleStrip({ summary, openedAt, commitGroups }: LifecycleStripProps): JSX.Element {
    const nodes: TimelineNode[] = [
        {
            key: 'opened',
            label: 'Opened',
            at: openedAt,
            dotClass: 'bg-muted',
            sublabel: <TZLabel time={openedAt} />,
        },
    ]
    // Only recent pushes get their own node; the rest collapse into one summary node so the strip never
    // scrolls. commitGroups is newest-first. Don't collapse a single straggler — "+1 earlier" saves nothing.
    const collapseOlder = commitGroups.length > MAX_PUSH_NODES + 1
    const shownRounds = collapseOlder ? commitGroups.slice(0, MAX_PUSH_NODES) : commitGroups
    const hiddenRounds = collapseOlder ? commitGroups.slice(MAX_PUSH_NODES) : []
    shownRounds.forEach((group) => {
        const at = roundStart(group)
        if (!at) {
            return
        }
        const round = pushRoundOf(group.headSha, group.runs)
        nodes.push({
            key: `round-${group.headSha}`,
            label: group.headSha.slice(0, 7),
            at,
            dotClass: roundDotClass(round),
            mono: true,
            danger: round.failed,
            // The bar carries the verdict; the sublabel answers "how long did CI take on this push".
            sublabel:
                round.wallSeconds != null
                    ? humanFriendlyDuration(round.wallSeconds, { maxUnits: 1 })
                    : round.pending
                      ? 'running'
                      : undefined,
            round,
        })
    })
    if (hiddenRounds.length) {
        const at = roundStart(hiddenRounds[0])
        const anyFailure = hiddenRounds.some((group) => pushRoundOf(group.headSha, group.runs).failed)
        if (at) {
            nodes.push({
                key: 'earlier-pushes',
                label: `+${hiddenRounds.length} earlier`,
                at,
                dotClass: anyFailure ? 'bg-danger' : 'bg-muted',
                danger: anyFailure,
                sublabel: 'pushes',
            })
        }
    }
    if (summary.mergedAt) {
        nodes.push({
            key: 'merged',
            label: 'Merged',
            at: summary.mergedAt,
            dotClass: 'bg-success',
            sublabel: <TZLabel time={summary.mergedAt} />,
        })
    } else if (summary.closedAt) {
        nodes.push({
            key: 'closed',
            label: 'Closed',
            at: summary.closedAt,
            dotClass: 'bg-danger',
            danger: true,
            sublabel: <TZLabel time={summary.closedAt} />,
        })
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
            sublabel: 'now',
        })
    }

    // Not necessarily the last node's time: head-SHA runs can outlive the merge.
    const totalTo = summary.mergedAt ?? summary.closedAt ?? nodes[nodes.length - 1].at
    const connector = (dashed: boolean | undefined): string =>
        dashed ? 'w-full border-t border-dashed border-border-bold' : 'h-px w-full bg-border-bold'

    // Connector widths are proportional to elapsed time, so the strip reads as a timeline. Floor each
    // segment so a near-instant gap still draws a visible connector instead of collapsing to nothing.
    const totalSeconds = Math.max(1, dayjs(nodes[nodes.length - 1].at).diff(dayjs(nodes[0].at), 'second'))
    const minGrow = totalSeconds * 0.04

    // Shared scale across the push bars, so their heights compare push-to-push.
    const maxWall = Math.max(...nodes.map((node) => node.round?.wallSeconds ?? 0), 1)
    const barPx = (round: PushRound): number =>
        round.wallSeconds != null ? Math.max(6, Math.round((round.wallSeconds / maxWall) * BAR_MAX_PX)) : 6

    return (
        <LemonCard hoverEffect={false} className="px-5 py-4">
            <div className="flex items-center gap-6">
                <div className="flex min-w-0 flex-1 items-stretch">
                    {nodes.map((node, index) => (
                        <Fragment key={node.key}>
                            {index > 0 && (
                                <div
                                    className="flex min-w-12 flex-col"
                                    style={{
                                        flexGrow: Math.max(
                                            minGrow,
                                            dayjs(node.at).diff(dayjs(nodes[index - 1].at), 'second')
                                        ),
                                    }}
                                >
                                    <span className={cn(ROW_LABEL, 'justify-center')}>
                                        <span className="rounded-full border bg-surface-secondary px-2 text-xs leading-4 whitespace-nowrap text-secondary tabular-nums">
                                            {gapBetween(nodes[index - 1].at, node.at)}
                                        </span>
                                    </span>
                                    <span className={ROW_BAR} />
                                    <span className={ROW_DOT}>
                                        <span className={connector(node.dashedIncoming)} />
                                    </span>
                                    <span className={ROW_SUB} />
                                </div>
                            )}
                            <div className="flex shrink-0 flex-col items-center px-1">
                                <span className={ROW_LABEL}>
                                    <span
                                        className={cn(
                                            'text-xs font-medium whitespace-nowrap',
                                            node.mono && 'font-mono',
                                            node.danger && 'text-danger'
                                        )}
                                    >
                                        {node.label}
                                    </span>
                                </span>
                                <span className={cn(ROW_BAR, 'w-full')}>
                                    {node.round && (
                                        <Tooltip
                                            title={`${node.round.headSha.slice(0, 7)} · ${
                                                node.round.wallSeconds != null
                                                    ? humanFriendlyDuration(node.round.wallSeconds)
                                                    : 'no completed runs'
                                            } · ${pushRoundVerdictLabel(node.round)}`}
                                        >
                                            <span
                                                className={cn(
                                                    'w-2.5 rounded-t-sm',
                                                    node.round.pending && 'animate-pulse'
                                                )}
                                                // eslint-disable-next-line react/forbid-dom-props
                                                style={{
                                                    height: barPx(node.round),
                                                    backgroundColor: pushRoundColor(node.round),
                                                    opacity: node.round.failed ? 1 : node.round.pending ? 0.9 : 0.65,
                                                }}
                                            />
                                        </Tooltip>
                                    )}
                                </span>
                                <span className={cn(ROW_DOT, 'w-full')}>
                                    <span className={cn('flex-1', index > 0 && connector(node.dashedIncoming))} />
                                    <span className={cn('h-2.5 w-2.5 shrink-0 rounded-full', node.dotClass)} />
                                    <span
                                        className={cn(
                                            'flex-1',
                                            index < nodes.length - 1 && connector(nodes[index + 1].dashedIncoming)
                                        )}
                                    />
                                </span>
                                <span className={cn(ROW_SUB, 'text-xs whitespace-nowrap text-tertiary')}>
                                    {node.sublabel ?? <>&nbsp;</>}
                                </span>
                            </div>
                        </Fragment>
                    ))}
                </div>
                <div className="flex shrink-0 flex-col items-end self-center border-l border-primary pl-6">
                    <span className="text-lg font-semibold leading-6 tabular-nums">
                        {gapBetween(openedAt, totalTo)}
                    </span>
                    <span className="text-xs text-tertiary">
                        {summary.mergedAt ? 'open → merge' : summary.closedAt ? 'open → close' : 'open so far'}
                    </span>
                </div>
            </div>
        </LemonCard>
    )
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
                        to={
                            combineUrl(
                                urls.engineeringAnalyticsWorkflowRun(repoOwner, repoName, run.runId),
                                sourceId ? { source: sourceId } : {}
                            ).url
                        }
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
                            to={
                                combineUrl(
                                    urls.engineeringAnalyticsWorkflowRuns(repoOwner, repoName, row.workflowName),
                                    sourceId ? { source: sourceId } : {}
                                ).url
                            }
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
        summary,
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
    } = useValues(pullRequestDetailLogic)
    const { loadLifecycle, loadPrRuns, setWorkflowFilter, setRunExpanded } = useActions(pullRequestDetailLogic)

    const pullRequest = lifecycle?.pull_request
    const githubUrl = pullRequest
        ? githubPrUrl(pullRequest.repo.owner, pullRequest.repo.name, pullRequest.number)
        : null

    const passed = runs.filter((run) => run.conclusion !== null && isPassingConclusion(run.conclusion)).length
    const failed = runs.filter((run) => run.conclusion !== null && !isPassingConclusion(run.conclusion)).length
    const running = runs.filter((run) => run.conclusion === null).length
    // The newest push's CI round — the wall-time tile and the lifecycle strip's last bar agree by construction.
    const latestRound = commitGroups[0] ? pushRoundOf(commitGroups[0].headSha, commitGroups[0].runs) : null
    const tilesLoading = prRunsLoading && commitGroups.length === 0

    if (loadFailed) {
        return (
            <SceneContent>
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
        <SceneContent>
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
                        to={combineUrl(urls.engineeringAnalytics(), sourceId ? { source: sourceId } : {}).url}
                    />
                }
                lensFilter={{
                    label: `pr: #${pullRequest?.number ?? ''}`,
                    to: combineUrl(urls.engineeringAnalytics(), sourceId ? { source: sourceId } : {}).url,
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
                {summary && pullRequest ? (
                    <LifecycleStrip
                        summary={summary}
                        openedAt={summary.openedAt ?? pullRequest.created_at}
                        commitGroups={commitGroups}
                    />
                ) : (
                    <LemonSkeleton className="h-12 w-full" />
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
