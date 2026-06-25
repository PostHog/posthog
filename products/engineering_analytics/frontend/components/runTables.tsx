// Shared building blocks for the CI run/job tables, used by both the PR detail page (a PR's workflow
// runs, expandable to jobs) and the single workflow-run page (that run's jobs). Keeping them here means
// the two surfaces read identically — a job row looks the same whether it's expanded under a run or
// shown on the run's own page.

import { LemonTable, LemonTableColumns, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyDuration } from 'lib/utils/durations'

import type { WorkflowJobApi } from '../generated/api.schemas'
import { verdictTag } from '../lib/runStatus'

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
 * A Gantt bar anchored to the real start time on a shared axis, sized by duration and colored by
 * verdict (failures tint red, everything else stays calm). A still-running bar extends to "now"; a
 * min width keeps short items visible next to long ones. The duration prints to the right.
 */
export function GanttBar({
    startedAt,
    finishedAt,
    durationSeconds,
    conclusion,
    axisStart,
    axisEnd,
}: {
    startedAt: string | null
    finishedAt: string | null
    durationSeconds: number | null
    conclusion: string | null
    axisStart: number | null
    axisEnd: number | null
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
            <span className="w-14 shrink-0 text-right text-xs whitespace-nowrap tabular-nums text-secondary">
                {durationSeconds == null ? '—' : humanFriendlyDuration(durationSeconds)}
            </span>
        </div>
    )
}

export function formatCost(usd: number | null): string {
    return usd == null ? '—' : `$${usd.toFixed(2)}`
}

export function formatMinutes(minutes: number | null): string {
    return minutes == null ? '—' : `${Math.round(minutes).toLocaleString()} min`
}

// Muted grey for GitHub-hosted (free), blue for billable self-hosted — kept off the green/red verdict
// palette so a runner badge never reads as a pass/fail status.
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

/** GitHub-hosted runners are free (open source); self-hosted shows the modeled estimate. */
function jobCostCell(job: WorkflowJobApi): JSX.Element {
    if (job.runner_provider === 'github_hosted') {
        return <span className="text-xs text-secondary">Free</span>
    }
    return <span className="text-xs tabular-nums">{formatCost(job.estimated_cost_usd)}</span>
}

/**
 * A workflow run's jobs: runner tier, Gantt timeline on the jobs' own axis, and est. cost. Used both
 * as the expanded-row content under a run in the PR view (`embedded`) and as the main content of the
 * single workflow-run page. ``jobs === undefined`` is the not-loaded state; ``[]`` means the job-level
 * source isn't synced for this team.
 */
export function RunJobsTable({
    jobs,
    loading,
    embedded = false,
}: {
    // null/undefined = not loaded (kea coerces an undefined loader default to null); [] = source unsynced.
    jobs: WorkflowJobApi[] | null | undefined
    loading: boolean
    embedded?: boolean
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
    const jobColumns: LemonTableColumns<WorkflowJobApi> = [
        { title: 'Job', key: 'name', render: (_, job) => <span className="font-medium">{job.name}</span> },
        {
            title: 'Status',
            key: 'status',
            width: 110,
            render: (_, job) => <StatusDot conclusion={job.conclusion} />,
        },
        {
            title: 'Runner',
            key: 'runner',
            width: 180,
            render: (_, job) => <RunnerBadge provider={job.runner_provider} label={job.runner_label} />,
        },
        {
            title: 'Timeline',
            key: 'timeline',
            width: 200,
            render: (_, job) => (
                <GanttBar
                    startedAt={job.started_at}
                    finishedAt={job.completed_at}
                    durationSeconds={job.duration_seconds}
                    conclusion={job.conclusion}
                    axisStart={axisStart}
                    axisEnd={axisEnd}
                />
            ),
        },
        {
            title: 'Est. cost',
            key: 'cost',
            width: 90,
            align: 'right',
            render: (_, job) => jobCostCell(job),
        },
    ]
    return (
        <LemonTable
            embedded={embedded}
            size="small"
            columns={jobColumns}
            dataSource={jobs}
            rowKey={(job) => job.id}
            nouns={['job', 'jobs']}
        />
    )
}
