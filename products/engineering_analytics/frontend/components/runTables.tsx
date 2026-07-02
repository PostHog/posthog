// Shared building blocks for the CI run/job tables (PR detail page and single workflow-run page) so the
// two surfaces read identically — a job row looks the same expanded under a run or on its own page.

import { ReactNode } from 'react'

import { LemonTable, LemonTableColumns, LemonTag, LemonTagType, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyDuration } from 'lib/utils/durations'

import type { WorkflowJobApi } from '../generated/api.schemas'
import { jobCacheKey } from '../lib/jobs'
import { verdictTag } from '../lib/runStatus'
import { BillableBadge } from './BillableBadge'

// A short item still shows next to a long one (durations span seconds → minutes).
const MIN_BAR_PCT = 4

const STATUS_DOT: Record<string, string> = {
    success: 'bg-success',
    danger: 'bg-danger',
    warning: 'bg-warning',
    muted: 'bg-muted',
}

/** Earliest start → latest finish (running items extend to now) over a set of start/finish pairs. */
export function timeAxis(items: { startedAt: string | null; finishedAt: string | null }[]): {
    axisStart: number | null
    axisEnd: number | null
} {
    const starts = items
        .map((i) => i.startedAt)
        .filter((at): at is string => !!at)
        .map((at) => dayjs(at).valueOf())
    const ends = items
        .map((i) => i.finishedAt ?? (i.startedAt ? dayjs().toISOString() : null))
        .filter((at): at is string => !!at)
        .map((at) => dayjs(at).valueOf())
    return { axisStart: starts.length ? Math.min(...starts) : null, axisEnd: ends.length ? Math.max(...ends) : null }
}

/** Compact status: a colored dot + label rather than a boxed tag — far less noise down a long list. */
export function StatusDot({ conclusion }: { conclusion: string | null }): JSX.Element {
    const tag = verdictTag(conclusion)
    return (
        <span className="flex items-center gap-1.5 text-xs whitespace-nowrap">
            <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', STATUS_DOT[tag.type] ?? 'bg-muted')} />
            <span className="text-secondary">{tag.label}</span>
        </span>
    )
}

/**
 * Gantt bar anchored to start time on a shared axis, sized by duration, red when failed. Running bars
 * extend to now; a min width keeps short items visible. The duration prints to the right.
 */
export function GanttBar({
    startedAt,
    finishedAt,
    durationSeconds,
    conclusion,
    axisStart,
    axisEnd,
    showDuration = true,
}: {
    startedAt: string | null
    finishedAt: string | null
    durationSeconds: number | null
    conclusion: string | null
    axisStart: number | null
    axisEnd: number | null
    // Hidden in the aligned grid, where duration has its own column under p50.
    showDuration?: boolean
}): JSX.Element {
    if (!startedAt || axisStart == null || axisEnd == null) {
        return <span className="text-xs text-secondary">—</span>
    }
    const start = dayjs(startedAt).valueOf()
    const end = finishedAt ? dayjs(finishedAt).valueOf() : dayjs().valueOf()
    const span = Math.max(1, axisEnd - axisStart)
    const left = Math.max(0, Math.min(100, ((start - axisStart) / span) * 100))
    const width = Math.max(MIN_BAR_PCT, Math.min(100 - left, ((end - start) / span) * 100))
    const isFailure = conclusion === 'failure' || conclusion === 'timed_out'
    return (
        <div className="flex items-center gap-2">
            <div className="relative h-1.5 flex-1 overflow-hidden rounded-sm bg-border">
                <div
                    className={cn('absolute top-0 h-1.5 rounded-sm', isFailure ? 'bg-danger' : 'bg-muted')}
                    style={{ left: `${left}%`, width: `${width}%` }}
                />
            </div>
            {showDuration && (
                <span className="w-14 shrink-0 text-right text-xs whitespace-nowrap tabular-nums text-secondary">
                    {durationSeconds == null ? '—' : humanFriendlyDuration(durationSeconds)}
                </span>
            )}
        </div>
    )
}

export function formatCost(usd: number | null): string {
    if (usd == null) {
        return '—'
    }
    // Sub-cent costs would round to "$0.00" and read as free (and jobs wouldn't sum to the run total),
    // so show positives under a cent as "<$0.01"; only a measured zero is "$0.00".
    if (usd > 0 && usd < 0.01) {
        return '<$0.01'
    }
    return `$${usd.toFixed(2)}`
}

export function formatMinutes(minutes: number | null): string {
    return minutes == null ? '—' : `${Math.round(minutes).toLocaleString()} min`
}

// Canonical CI grid: the L1 (workflow), L2 (run), and L3 (job) tables reuse these exact widths so every
// column lines up vertically as you drill in. Each level fills the slots it has an analog for, blanks the
// rest. Single source of truth shared by WorkflowHealthTable, RunsTable, RunJobsTable; change a width
// once, all levels move. Widths fit the widest header in each slot (fixed layout clips overflow).
export const CI_GRID = {
    status: 116, // L1 Passing/Failing tag · L3 runner tier
    runs: 80, // L1 run count · blank below
    successRate: 140, // L1 "Success rate" · L2/L3 verdict/status dot
    cost: 132, // shared "min · $" billable badge
    health: 220, // L1 failure sparkline · L3 job timeline
    p50: 108, // L1 p50 · L2/L3 "Duration"
    p95: 92, // L1 p95 · blank below
    lastFailure: 124, // L1 last-failure time · L2/L3 started
} as const

// Grey for GitHub-hosted (free), blue for self-hosted — off the green/red verdict palette so a runner
// badge never reads as a pass/fail status.
const RUNNER_BADGE: Record<string, { label: string; type: LemonTagType }> = {
    github_hosted: { label: 'GitHub', type: 'muted' },
    self_hosted: { label: 'Self-hosted', type: 'primary' },
    unknown: { label: 'Unknown', type: 'muted' },
}

/** Runner type badge: GitHub-hosted (free) vs self-hosted (billable), plus the tier (e.g. 16-core). */
export function RunnerBadge({ provider, label }: { provider: string; label: string }): JSX.Element {
    const badge = RUNNER_BADGE[provider] ?? RUNNER_BADGE.unknown
    return (
        <span className="flex items-center gap-1.5 whitespace-nowrap">
            <LemonTag type={badge.type} size="small">
                {badge.label}
            </LemonTag>
            {label && provider !== 'unknown' && <span className="font-mono text-xs text-secondary">{label}</span>}
        </span>
    )
}

/** GitHub-hosted runners are free; self-hosted shows the modeled estimate in the same "min · $" badge as
 *  the run/workflow rows. */
function jobCostCell(job: WorkflowJobApi): JSX.Element {
    if (job.runner_provider === 'github_hosted') {
        return <span className="text-xs text-secondary">Free</span>
    }
    const minutes = job.duration_seconds != null ? job.duration_seconds / 60 : null
    return <BillableBadge minutes={minutes} costUsd={job.estimated_cost_usd} />
}

function formatSeconds(seconds: number | null): string {
    return seconds == null ? '—' : humanFriendlyDuration(seconds)
}

/** Runner in the aligned grid: just the tier tag (full name on hover) — the verbose badge won't fit the
 *  Status slot. */
function compactRunnerCell(job: WorkflowJobApi): JSX.Element {
    const badge = RUNNER_BADGE[job.runner_provider] ?? RUNNER_BADGE.unknown
    if (job.runner_provider === 'unknown' && !job.runner_label) {
        return <span className="text-xs text-secondary">—</span>
    }
    return (
        <Tooltip title={`${badge.label}${job.runner_label ? ` · ${job.runner_label}` : ''}`}>
            <LemonTag type={badge.type} size="small">
                {job.runner_label || badge.label}
            </LemonTag>
        </Tooltip>
    )
}

/**
 * A workflow run's jobs: runner tier, Gantt timeline on the jobs' own axis, est. cost. Used as the
 * expanded-row content under a run (`embedded`) and as the single workflow-run page. `undefined`/`null`
 * jobs = not loaded; `[]` = the job-level source isn't synced for this team.
 */
export function RunJobsTable({
    jobs,
    loading,
    embedded = false,
    aligned = false,
}: {
    // null/undefined = not loaded (kea coerces an undefined loader default to null); [] = source unsynced.
    jobs: WorkflowJobApi[] | null | undefined
    loading: boolean
    embedded?: boolean
    // Render onto the canonical CI_GRID so columns line up under the run/workflow tables (PR detail).
    aligned?: boolean
}): JSX.Element {
    if (jobs == null) {
        return <div className="px-3 py-2 text-xs text-secondary">{loading ? 'Loading jobs…' : 'No job data yet.'}</div>
    }
    if (jobs.length === 0) {
        return (
            <div className="px-3 py-2 text-xs text-secondary">
                No job data yet — the job-level source isn't synced for this team.
            </div>
        )
    }
    // Jobs of one run share the run's window; anchor their bars to the jobs' own start→finish span.
    const { axisStart, axisEnd } = timeAxis(
        jobs.map((job) => ({ startedAt: job.started_at, finishedAt: job.completed_at }))
    )
    const nameColumn = {
        title: 'Job',
        key: 'name',
        sorter: (a: WorkflowJobApi, b: WorkflowJobApi) => a.name.localeCompare(b.name),
        render: (_: unknown, job: WorkflowJobApi) => <span className="font-medium">{job.name}</span>,
    }
    const timelineCell = (job: WorkflowJobApi): JSX.Element => (
        <GanttBar
            startedAt={job.started_at}
            finishedAt={job.completed_at}
            durationSeconds={job.duration_seconds}
            conclusion={job.conclusion}
            axisStart={axisStart}
            axisEnd={axisEnd}
            showDuration={!aligned}
        />
    )
    // Aligned: job data drops into the canonical L1 slots (Runner→Status, dot→Success rate, timeline→
    // Health, duration→p50, started→Last failure). Natural: the standalone run page's own layout.
    const jobColumns: LemonTableColumns<WorkflowJobApi> = aligned
        ? [
              nameColumn,
              { title: 'Runner', key: 'status', width: CI_GRID.status, render: (_, job) => compactRunnerCell(job) },
              { title: '', key: 'runs', width: CI_GRID.runs, render: () => null },
              {
                  title: 'Status',
                  key: 'successRate',
                  width: CI_GRID.successRate,
                  render: (_, job) => <StatusDot conclusion={job.conclusion} />,
              },
              {
                  title: 'Cost',
                  key: 'cost',
                  width: CI_GRID.cost,
                  align: 'right',
                  render: (_, job) => jobCostCell(job),
              },
              {
                  title: 'Timeline',
                  key: 'health',
                  width: CI_GRID.health,
                  sorter: (a, b) => (a.started_at ?? '').localeCompare(b.started_at ?? ''),
                  render: (_, job) => timelineCell(job),
              },
              {
                  title: 'Duration',
                  key: 'p50',
                  width: CI_GRID.p50,
                  align: 'right',
                  render: (_, job) => (
                      <span className="text-xs tabular-nums">{formatSeconds(job.duration_seconds)}</span>
                  ),
              },
              { title: '', key: 'p95', width: CI_GRID.p95, render: () => null },
              {
                  title: 'Started',
                  key: 'lastFailure',
                  width: CI_GRID.lastFailure,
                  align: 'right',
                  render: (_, job) =>
                      job.started_at ? (
                          <span className="text-xs whitespace-nowrap">
                              <TZLabel time={job.started_at} />
                          </span>
                      ) : (
                          <span className="text-xs text-secondary">—</span>
                      ),
              },
          ]
        : [
              nameColumn,
              {
                  title: 'Status',
                  key: 'status',
                  width: 110,
                  sorter: (a, b) => (a.conclusion ?? '').localeCompare(b.conclusion ?? ''),
                  render: (_, job) => <StatusDot conclusion={job.conclusion} />,
              },
              {
                  title: 'Runner',
                  key: 'runner',
                  width: 180,
                  sorter: (a, b) => a.runner_label.localeCompare(b.runner_label),
                  render: (_, job) => <RunnerBadge provider={job.runner_provider} label={job.runner_label} />,
              },
              {
                  title: 'Timeline',
                  key: 'timeline',
                  width: 200,
                  sorter: (a, b) => (a.started_at ?? '').localeCompare(b.started_at ?? ''),
                  render: (_, job) => timelineCell(job),
              },
              {
                  title: 'Cost',
                  key: 'cost',
                  width: 110,
                  align: 'right',
                  sorter: (a, b) => (a.estimated_cost_usd ?? -1) - (b.estimated_cost_usd ?? -1),
                  render: (_, job) => jobCostCell(job),
              },
          ]
    const table = (
        <LemonTable
            embedded={embedded}
            size="small"
            columns={jobColumns}
            dataSource={jobs}
            rowKey={(job) => job.id}
            useURLForSorting={false}
            // Sort by start (the timeline column, keyed 'health' when aligned) so bars read top-to-bottom.
            defaultSorting={{ columnKey: aligned ? 'health' : 'timeline', order: 1 }}
            nouns={['job', 'jobs']}
        />
    )
    // No indent: the job table has no expand toggle, so rows read flush-left under the parent run instead
    // of behind a stray gap.
    return table
}

// The minimum a run row needs to drive the shared columns + job expansion. Callers add their own lead
// columns (the PR page leads with the commit; the workflow page leads with run id / branch / PR).
export interface RunRowBase {
    runId: number | null
    runAttempt: number | null
    conclusion: string | null
    durationSeconds: number | null
    startedAt: string | null
}

export interface RunsTableProps<T extends RunRowBase> {
    runs: T[]
    rowKey: (row: T) => string
    /** Columns shown before the shared Verdict / Duration / Started / Cost columns. */
    leadColumns: LemonTableColumns<T>
    loading: boolean
    // null/undefined per key = that run's jobs aren't loaded yet; lazily fetched on first expand.
    runJobs: Record<string, WorkflowJobApi[]>
    runJobsLoading: boolean
    expandedKeys: string[]
    setExpanded: (rowKey: string, expanded: boolean, runId: number | null, runAttempt: number | null) => void
    /** Per-run cost keyed by jobCacheKey; pass with showCost to add the trailing Cost column. */
    runCostByKey?: Record<string, { minutes: number | null; cost: number | null }>
    showCost?: boolean
    /** Render onto the canonical CI_GRID so columns line up under the workflow table (PR detail). */
    aligned?: boolean
    defaultSorting?: { columnKey: string; order: 1 | -1 }
    emptyState?: ReactNode
    dataAttr?: string
}

/**
 * A list of workflow runs, each expandable to its jobs (RunJobsTable). Shared trailing columns (verdict,
 * duration, started, optional cost) and expand-to-jobs behavior; only the leading columns differ per caller.
 */
export function RunsTable<T extends RunRowBase>({
    runs,
    rowKey,
    leadColumns,
    loading,
    runJobs,
    runJobsLoading,
    expandedKeys,
    setExpanded,
    runCostByKey,
    showCost = false,
    aligned = false,
    defaultSorting = { columnKey: 'started', order: 1 },
    emptyState = 'No CI runs match.',
    dataAttr = 'engineering-analytics-runs-table',
}: RunsTableProps<T>): JSX.Element {
    const verdictColumn = {
        title: 'Verdict',
        key: 'verdict',
        sorter: (a: T, b: T) => verdictTag(a.conclusion).label.localeCompare(verdictTag(b.conclusion).label),
        render: (_: unknown, run: T) => <StatusDot conclusion={run.conclusion} />,
    }
    const durationCell = (run: T): JSX.Element => (
        <span className="text-xs tabular-nums whitespace-nowrap">
            {run.durationSeconds == null ? '—' : humanFriendlyDuration(run.durationSeconds)}
        </span>
    )
    const startedCell = (run: T): JSX.Element =>
        run.startedAt ? (
            <span className="text-xs whitespace-nowrap">
                <TZLabel time={run.startedAt} />
            </span>
        ) : (
            <span className="text-xs text-secondary">—</span>
        )
    const costCell = (run: T): JSX.Element => {
        const cost = run.runId != null ? runCostByKey?.[jobCacheKey(run.runId, run.runAttempt)] : null
        return <BillableBadge minutes={cost?.minutes ?? null} costUsd={cost?.cost ?? null} />
    }
    // Aligned: run data drops into the canonical L1 slots (verdict→Success rate, cost→Cost, duration→p50,
    // started→Last failure), with blank spacers under the slots a run has no analog for (Status, Runs,
    // Health, p95). Natural: the standalone workflow-runs page's own compact layout.
    const columns: LemonTableColumns<T> = aligned
        ? [
              ...leadColumns,
              { title: '', key: 'slotStatus', width: CI_GRID.status, render: () => null },
              { title: '', key: 'slotRuns', width: CI_GRID.runs, render: () => null },
              { ...verdictColumn, width: CI_GRID.successRate },
              { title: 'Cost', key: 'cost', width: CI_GRID.cost, align: 'right', render: (_, run) => costCell(run) },
              { title: '', key: 'slotHealth', width: CI_GRID.health, render: () => null },
              {
                  title: 'Duration',
                  key: 'duration',
                  width: CI_GRID.p50,
                  align: 'right',
                  sorter: (a, b) => (a.durationSeconds ?? -1) - (b.durationSeconds ?? -1),
                  render: (_, run) => durationCell(run),
              },
              { title: '', key: 'slotP95', width: CI_GRID.p95, render: () => null },
              {
                  title: 'Started',
                  key: 'started',
                  width: CI_GRID.lastFailure,
                  align: 'right',
                  sorter: (a, b) => (a.startedAt ?? '').localeCompare(b.startedAt ?? ''),
                  render: (_, run) => startedCell(run),
              },
          ]
        : [
              ...leadColumns,
              { ...verdictColumn, width: 110 },
              {
                  title: 'Duration',
                  key: 'duration',
                  width: 90,
                  align: 'right',
                  sorter: (a, b) => (a.durationSeconds ?? -1) - (b.durationSeconds ?? -1),
                  render: (_, run) => durationCell(run),
              },
              {
                  title: 'Started',
                  key: 'started',
                  width: 130,
                  align: 'right',
                  sorter: (a, b) => (a.startedAt ?? '').localeCompare(b.startedAt ?? ''),
                  render: (_, run) => startedCell(run),
              },
              ...((showCost
                  ? [
                        {
                            title: 'Cost',
                            key: 'cost',
                            width: 110,
                            align: 'right',
                            render: (_: unknown, run: T) => costCell(run),
                        },
                    ]
                  : []) as LemonTableColumns<T>),
          ]

    return (
        <LemonTable
            data-attr={dataAttr}
            size="small"
            columns={columns}
            dataSource={runs}
            rowKey={rowKey}
            loading={loading}
            useURLForSorting={false}
            defaultSorting={defaultSorting}
            // Whole-row click toggles the job breakdown (the logs-viewer pattern); in-row links
            // stopPropagation so they still navigate.
            onRow={(run) =>
                run.runId != null
                    ? {
                          className: 'cursor-pointer',
                          onClick: () =>
                              setExpanded(rowKey(run), !expandedKeys.includes(rowKey(run)), run.runId, run.runAttempt),
                      }
                    : {}
            }
            expandable={{
                // Compact chevron toggle + whole-row click; no onRowExpand/onRowCollapse so the toggle
                // bubbles to onRow — one toggle, not two.
                noIndent: true,
                rowExpandable: (run) => run.runId != null,
                isRowExpanded: (run) => expandedKeys.includes(rowKey(run)),
                expandedRowRender: (run) => (
                    <RunJobsTable
                        jobs={run.runId != null ? runJobs[jobCacheKey(run.runId, run.runAttempt)] : undefined}
                        loading={runJobsLoading}
                        embedded
                        aligned={aligned}
                    />
                ),
            }}
            emptyState={emptyState}
            nouns={['workflow run', 'workflow runs']}
        />
    )
}
