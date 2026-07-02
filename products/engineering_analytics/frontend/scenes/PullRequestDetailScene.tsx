import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { Fragment, ReactNode } from 'react'

import { IconExternal } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSkeleton, LemonTableColumns, LemonTag, Link } from '@posthog/lemon-ui'

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

import { PullRequestStateTag } from '../components/PullRequestStateTag'
import { RunJobsTable, RunsTable, formatCost } from '../components/runTables'
import { StatTile } from '../components/StatTile'
import { WorkflowHealthTable } from '../components/WorkflowHealthTable'
import type { PRCostSummaryApi, PullRequestApi } from '../generated/api.schemas'
import { githubCommitUrl, githubPrUrl } from '../lib/github'
import { LifecycleSummary, WorkflowRun, isPassingConclusion } from '../lib/lifecycle'
import {
    PrCommitRuns,
    PrRunRow,
    PullRequestDetailLogicProps,
    jobCacheKey,
    pullRequestDetailLogic,
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
    /** Small caption under the dot — relative time, "pushed", "now", … */
    sublabel?: ReactNode
    /** Round nodes render the sha in mono. */
    mono?: boolean
    /** Color the label red — a failed round / closed PR. */
    danger?: boolean
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
const ROW_DOT = 'flex h-3 items-center'
const ROW_SUB = 'flex h-4 items-center'

// Cap push nodes so the strip fits on one line; older pushes collapse into a "+N earlier" node, and
// every round stays reachable in the list below.
const MAX_PUSH_NODES = 4

/**
 * Horizontal lifecycle timeline: dots are milestones, the pill above each connector is the gap between
 * them. Chronological — a PR's head-SHA runs can start (and finish) after the merge. Each push is its own
 * node, red when that round had a failure; clicking it jumps to that round's run table below.
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
    shownRounds.forEach((group, index) => {
        const at = roundStart(group)
        if (!at) {
            return
        }
        const hasFailure = group.runs.some((run) => run.conclusion != null && !isPassingConclusion(run.conclusion))
        nodes.push({
            key: `round-${group.headSha}`,
            label: group.headSha.slice(0, 7),
            at,
            dotClass: hasFailure ? 'bg-danger' : 'bg-muted',
            mono: true,
            danger: hasFailure,
            // index 0 is the latest push (newest-first).
            sublabel: index === 0 ? 'latest push' : 'pushed',
        })
    })
    if (hiddenRounds.length) {
        const at = roundStart(hiddenRounds[0])
        const anyFailure = hiddenRounds.some((group) =>
            group.runs.some((run) => run.conclusion != null && !isPassingConclusion(run.conclusion))
        )
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
    const endLabel = summary.mergedAt ? 'merged' : summary.closedAt ? 'closed' : 'still open'
    const subtitle = commitGroups.length ? `opened → latest push → ${endLabel}` : `opened → ${endLabel}`
    const connector = (dashed: boolean | undefined): string =>
        dashed ? 'w-full border-t border-dashed border-border-bold' : 'h-px w-full bg-border-bold'

    // Connector widths are proportional to elapsed time, so the strip reads as a timeline. Floor each
    // segment so a near-instant gap still draws a visible connector instead of collapsing to nothing.
    const totalSeconds = Math.max(1, dayjs(nodes[nodes.length - 1].at).diff(dayjs(nodes[0].at), 'second'))
    const minGrow = totalSeconds * 0.04

    return (
        <LemonCard hoverEffect={false} className="px-5 py-4">
            <div className="mb-3 flex items-baseline gap-2">
                <span className="text-xs font-semibold tracking-wide text-secondary uppercase">Lifecycle</span>
                <span className="text-xs text-tertiary">{subtitle}</span>
            </div>
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

function MetaRow({ pullRequest, sourceId }: { pullRequest: PullRequestApi; sourceId: string | null }): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
            <PullRequestStateTag state={pullRequest.state} isDraft={pullRequest.is_draft} />
            <span className="flex items-center gap-1.5">
                {pullRequest.author.avatar_url && (
                    <img src={pullRequest.author.avatar_url} alt="" className="h-5 w-5 shrink-0 rounded-full" />
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
            <span className="font-mono text-xs text-secondary">
                {pullRequest.repo.owner}/{pullRequest.repo.name} #{pullRequest.number}
            </span>
        </div>
    )
}

// Stable per-row key — re-runs share a runId, so start time disambiguates attempts. Used for rowKey and
// the expand-state set, so expanding one attempt doesn't open the others.
function runRowKey(run: WorkflowRun): string {
    return `${run.workflow}@${run.startedAt ?? run.finishedAt ?? run.runId ?? ''}`
}

function formatMinutes(minutes: number): string {
    return `${Math.round(minutes).toLocaleString()} min`
}

const VERDICT_LEGEND: { key: 'passed' | 'failed' | 'running'; dot: string; label: string }[] = [
    { key: 'passed', dot: 'bg-success', label: 'passed' },
    { key: 'failed', dot: 'bg-danger', label: 'failed' },
    { key: 'running', dot: 'bg-warning', label: 'running' },
]

// Stroke from the same CSS vars the verdict dots / LemonTags use, so the donut matches the legend dots
// and the run-table StatusDots exactly.
const DONUT_STROKE: Record<'passed' | 'failed' | 'running', string> = {
    passed: 'var(--success)',
    failed: 'var(--danger)',
    running: 'var(--warning)',
}

interface VerdictCounts {
    passed: number
    failed: number
    running: number
}

/** Donut of run verdicts with the pass rate (passed / settled) in the center. */
function VerdictDonut({ counts }: { counts: VerdictCounts }): JSX.Element {
    const total = counts.passed + counts.failed + counts.running
    const settled = counts.passed + counts.failed
    const passRate = settled > 0 ? Math.round((counts.passed / settled) * 100) : null
    const radius = 40
    const circumference = 2 * Math.PI * radius

    let offset = 0
    const arcs = VERDICT_LEGEND.flatMap(({ key }) => {
        const value = counts[key]
        if (value <= 0 || total <= 0) {
            return []
        }
        const length = (value / total) * circumference
        const arc = (
            <circle
                key={key}
                cx="50"
                cy="50"
                r={radius}
                fill="none"
                strokeWidth="10"
                stroke={DONUT_STROKE[key]}
                strokeDasharray={`${length} ${circumference - length}`}
                strokeDashoffset={-offset}
            />
        )
        offset += length
        return [arc]
    })

    return (
        <div className="relative h-24 w-24 shrink-0">
            <svg viewBox="0 0 100 100" className="h-full w-full -rotate-90">
                <circle cx="50" cy="50" r={radius} fill="none" strokeWidth="10" stroke="var(--border)" />
                {arcs}
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
                <span className="text-xl leading-none font-semibold tabular-nums">
                    {passRate == null ? '—' : `${passRate}%`}
                </span>
                <span className="text-xs text-tertiary">pass rate</span>
            </div>
        </div>
    )
}

interface PrSummaryCardsProps {
    cost: PRCostSummaryApi | null
    costLoading: boolean
    pushes: number
    rerunCycles: number
    counts: VerdictCounts
    runsTotal: number
    commits: number
    summary: LifecycleSummary | null
    openedAt: string
    // First load: three loaders (lifecycle / runs / cost) resolve at different times; without this the
    // cards pop in one at a time. Show a full skeleton row instead.
    loading: boolean
}

/**
 * Headline stats for a PR's CI: verdict donut over all commits, billable runner minutes + estimated cost
 * (when the job-level source is synced), CI triggers, and time open. Cost is an estimate — the chip spells
 * out the model (wall-clock × reference rate) and excludes unsettled jobs.
 */
function PrSummaryCards({
    cost,
    costLoading,
    pushes,
    rerunCycles,
    counts,
    runsTotal,
    commits,
    summary,
    openedAt,
    loading,
}: PrSummaryCardsProps): JSX.Element {
    if (loading) {
        // One skeleton per card (the verdict card is wider) so the whole row appears at once.
        return (
            <div className="flex flex-wrap items-stretch gap-3">
                <LemonSkeleton className="h-[104px] min-w-72 flex-1 rounded-lg" />
                <LemonSkeleton className="h-[104px] min-w-44 flex-1 rounded-lg" />
                <LemonSkeleton className="h-[104px] min-w-44 flex-1 rounded-lg" />
                <LemonSkeleton className="h-[104px] min-w-44 flex-1 rounded-lg" />
            </div>
        )
    }
    const showCost = cost?.jobs_available
    const openTo = summary?.mergedAt ?? summary?.closedAt ?? dayjs().toISOString()
    const openLabel = summary?.mergedAt ? 'Time to merge' : summary?.closedAt ? 'Time to close' : 'Open so far'
    return (
        <div className="flex flex-col gap-2">
            {showCost && (
                <div className="flex flex-wrap items-center gap-2">
                    <LemonTag type="warning">estimate · wall-clock × reference rate</LemonTag>
                    {cost.unsettled_jobs > 0 && (
                        <LemonTag type="muted">{pluralize(cost.unsettled_jobs, 'unsettled job')} excluded</LemonTag>
                    )}
                </div>
            )}
            <div className="flex flex-wrap items-stretch gap-3">
                {runsTotal > 0 && (
                    <LemonCard hoverEffect={false} className="flex min-w-72 flex-1 flex-col gap-2 px-5 py-4">
                        <span className="text-xs text-secondary">Run verdicts · all commits &amp; re-runs</span>
                        <div className="flex items-center gap-4">
                            <VerdictDonut counts={counts} />
                            <div className="flex flex-col gap-0.5 text-xs">
                                {VERDICT_LEGEND.map(({ key, dot, label }) => (
                                    <span key={key} className="flex items-center gap-1.5">
                                        <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', dot)} />
                                        <span className="font-medium tabular-nums">{counts[key]}</span>
                                        <span className="text-secondary">{label}</span>
                                    </span>
                                ))}
                            </div>
                        </div>
                        <span className="text-xs text-tertiary">
                            {pluralize(runsTotal, 'run')} · {pluralize(commits, 'commit')}
                        </span>
                    </LemonCard>
                )}
                {costLoading && !cost ? (
                    <LemonSkeleton className="h-24 w-44" />
                ) : showCost ? (
                    <StatTile
                        label="Billable CI minutes"
                        value={formatMinutes(cost.billable_minutes)}
                        sub={<>≈ {formatCost(cost.estimated_cost_usd)} estimated</>}
                    />
                ) : null}
                <StatTile
                    label="Pushes (CI triggers)"
                    value={pushes.toLocaleString()}
                    sub={rerunCycles > 0 ? pluralize(rerunCycles, 're-run cycle') : 'no re-runs'}
                />
                {openedAt && (
                    <StatTile
                        label={openLabel}
                        value={gapBetween(openedAt, openTo)}
                        sub={
                            <>
                                opened <TZLabel time={openedAt} />
                            </>
                        }
                    />
                )}
            </div>
        </div>
    )
}

/**
 * Lead columns for the PR runs table: the commit (which push) + re-run attempt. Re-runs share a runId,
 * so attempts are numbered by start order. The shared RunsTable appends verdict / duration / started / cost.
 */
function commitLeadColumns(runs: PrRunRow[], repoOwner: string, repoName: string): LemonTableColumns<PrRunRow> {
    const attemptIndexByKey = new Map<string, number>()
    const runsByRunId = new Map<number, PrRunRow[]>()
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
    return [
        {
            // The workflow is already the parent row, so lead with the commit (which push) + attempt.
            title: 'Commit',
            key: 'commit',
            // Tiebreak by start so a commit's re-run attempts stay in order.
            sorter: (a, b) => (a.startedAt ?? '').localeCompare(b.startedAt ?? ''),
            render: (_, run) => {
                const attempt = attemptIndexByKey.get(runRowKey(run))
                return (
                    <div className="flex items-center gap-2">
                        {run.headSha ? (
                            <Link
                                to={githubCommitUrl(repoOwner, repoName, run.headSha)}
                                target="_blank"
                                className="font-mono text-xs font-medium"
                                onClick={(e) => e.stopPropagation()}
                            >
                                {run.headSha.slice(0, 7)}
                            </Link>
                        ) : (
                            <span className="text-xs text-secondary">—</span>
                        )}
                        {attempt ? <span className="text-xs text-secondary">· attempt {attempt}</span> : null}
                    </div>
                )
            },
        },
    ]
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
        filteredWorkflowHealthRows,
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
        runJobs,
        runJobsLoading,
        expandedRunKeys,
        runCostByKey,
    } = useValues(pullRequestDetailLogic)
    const { loadLifecycle, loadPrRuns, loadJobs, setRunExpanded, setWorkflowFilter } =
        useActions(pullRequestDetailLogic)

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

            {pullRequest ? (
                <MetaRow pullRequest={pullRequest} sourceId={sourceId} />
            ) : (
                <LemonSkeleton className="h-5 w-96" />
            )}

            <div>
                <PrSummaryCards
                    cost={prCost}
                    costLoading={prCostLoading}
                    pushes={pushes}
                    rerunCycles={rerunCycles}
                    counts={{ passed, failed, running }}
                    runsTotal={runs.length}
                    commits={commitGroups.length}
                    summary={summary}
                    openedAt={summary?.openedAt ?? pullRequest?.created_at ?? ''}
                    // Skeleton the whole row until lifecycle + runs are in (covers the frame before
                    // afterMount fires). The cost card fills on its own once prCost resolves. loadFailed
                    // returns earlier, so !lifecycle can't hang here.
                    loading={!lifecycle || (prRunsLoading && runs.length === 0)}
                />
            </div>

            {summary && pullRequest ? (
                <div>
                    <LifecycleStrip
                        summary={summary}
                        openedAt={summary.openedAt ?? pullRequest.created_at}
                        commitGroups={commitGroups}
                    />
                </div>
            ) : (
                <LemonSkeleton className="h-12 w-full" />
            )}

            <div>
                <div className="mb-2 flex items-baseline gap-3">
                    <h3 className="mb-0">CI runs</h3>
                    {runs.length > 0 && (
                        <span className="text-xs text-secondary">
                            Cumulative · {pluralize(passed, 'run')} passed
                            {failed > 0 && <> · {failed} failed</>}
                            {running > 0 && <> · {running} still running</>}
                            {commitGroups.length > 1 && <> · {pluralize(commitGroups.length, 'commit')}</>}
                        </span>
                    )}
                </div>
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
                ) : filteredWorkflowHealthRows.length === 0 ? (
                    <div className="text-sm text-secondary">No workflows match “{workflowFilter}”.</div>
                ) : (
                    <WorkflowHealthTable
                        rows={filteredWorkflowHealthRows}
                        loading={prRunsLoading}
                        sourceId={sourceId}
                        showCost={prCost?.jobs_available ?? false}
                        dataAttr="engineering-analytics-pr-workflow-table"
                        emptyState="No CI runs match."
                        expandable={{
                            noIndent: true,
                            rowExpandable: (row) => filteredRuns.some((run) => run.workflow === row.workflowName),
                            // Single run on the PR → load its jobs straight away (we skip the runs layer below).
                            onRowExpand: (row) => {
                                const wfRuns = filteredRuns.filter((run) => run.workflow === row.workflowName)
                                const run = wfRuns.length === 1 ? wfRuns[0] : null
                                if (run?.runId != null && !(jobCacheKey(run.runId, run.runAttempt) in runJobs)) {
                                    loadJobs({ runId: run.runId, runAttempt: run.runAttempt })
                                }
                            },
                            expandedRowRender: (row) => {
                                const wfRuns = filteredRuns.filter((run) => run.workflow === row.workflowName)
                                // One run → no point in a one-row runs table; jump straight to its jobs.
                                if (wfRuns.length === 1) {
                                    const run = wfRuns[0]
                                    return (
                                        <RunJobsTable
                                            jobs={
                                                run.runId != null
                                                    ? runJobs[jobCacheKey(run.runId, run.runAttempt)]
                                                    : undefined
                                            }
                                            loading={runJobsLoading}
                                            embedded
                                            aligned
                                        />
                                    )
                                }
                                // Multiple runs (re-runs / multi-push) → list them, each expandable to jobs.
                                return (
                                    <RunsTable
                                        runs={wfRuns}
                                        rowKey={runRowKey}
                                        leadColumns={commitLeadColumns(wfRuns, repoOwner, repoName)}
                                        loading={prRunsLoading}
                                        runJobs={runJobs}
                                        runJobsLoading={runJobsLoading}
                                        expandedKeys={expandedRunKeys}
                                        setExpanded={setRunExpanded}
                                        runCostByKey={runCostByKey}
                                        showCost={prCost?.jobs_available ?? false}
                                        aligned
                                        // Oldest push first so rows read in the same order as the sparkline.
                                        defaultSorting={{ columnKey: 'started', order: 1 }}
                                        dataAttr="engineering-analytics-pr-runs-table"
                                    />
                                )
                            },
                        }}
                    />
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
