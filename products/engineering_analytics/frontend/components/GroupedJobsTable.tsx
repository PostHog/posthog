// A run's jobs with matrix shards rolled up (lib/jobGroups, the same rule as the backend's SQL
// de-shard); failing groups sort first and name their failed shards. Groups expand via the caret only —
// links inside rows must stay clickable.

import { LemonTable, LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils/durations'

import type { WorkflowJobApi } from '../generated/api.schemas'
import { JobGroup, JobGroupConclusion, failedShardsLabel, groupJobs } from '../lib/jobGroups'
import { BillableBadge } from './BillableBadge'
import { StatusDot } from './runTables'

type WorkflowJobGroup = JobGroup<WorkflowJobApi>

const GROUP_DOT_COLOR: Record<JobGroupConclusion, string> = {
    success: 'var(--success)',
    failure: 'var(--danger)',
    running: 'var(--brand-blue)',
    cancelled: 'var(--muted)',
    skipped: 'var(--muted)',
}

function GroupConclusionDot({ conclusion }: { conclusion: JobGroupConclusion }): JSX.Element {
    return (
        <span
            className="inline-block size-2 shrink-0 rounded-full"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ backgroundColor: GROUP_DOT_COLOR[conclusion], opacity: conclusion === 'skipped' ? 0.5 : 1 }}
        />
    )
}

/** One dot per matrix group. */
export function GroupDots({ groups }: { groups: WorkflowJobGroup[] }): JSX.Element {
    return (
        <span className="inline-flex items-center gap-[3px]">
            {groups.map((group) => (
                <span
                    key={group.base}
                    className="inline-block size-1.5 rounded-full"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        backgroundColor: GROUP_DOT_COLOR[group.conclusion],
                        opacity: group.conclusion === 'skipped' ? 0.5 : 0.9,
                    }}
                    title={`${group.base} · ${group.jobs.length > 1 ? `${group.jobs.length} jobs, ` : ''}${group.conclusion}`}
                />
            ))}
        </span>
    )
}

interface GroupSpan {
    startMs: number | null
    endMs: number | null
}

function groupSpan(group: WorkflowJobGroup): GroupSpan {
    const starts = group.jobs.map((j) => j.started_at).filter((at): at is string => !!at)
    const ends = group.jobs
        .map((j) => j.completed_at ?? (j.started_at ? dayjs().toISOString() : null))
        .filter((at): at is string => !!at)
    return {
        startMs: starts.length ? Math.min(...starts.map((at) => dayjs(at).valueOf())) : null,
        endMs: ends.length ? Math.max(...ends.map((at) => dayjs(at).valueOf())) : null,
    }
}

/** Earliest-start → latest-finish envelope of the group's shards on the run's shared time axis. */
function TimingEnvelope({
    span,
    conclusion,
    axisStart,
    axisEnd,
}: {
    span: GroupSpan
    conclusion: JobGroupConclusion
    axisStart: number
    axisEnd: number
}): JSX.Element {
    if (span.startMs == null || span.endMs == null) {
        return <span className="text-xs text-secondary">—</span>
    }
    const total = Math.max(1, axisEnd - axisStart)
    const left = Math.max(0, Math.min(100, ((span.startMs - axisStart) / total) * 100))
    const width = Math.max(1, Math.min(100 - left, ((span.endMs - span.startMs) / total) * 100))
    return (
        <span className="relative block h-2 w-full min-w-36">
            <span className="absolute top-[3px] h-0.5 w-full rounded-full bg-fill-secondary" />
            <span
                className="absolute top-0.5 h-1 rounded-full opacity-80"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ left: `${left}%`, width: `${width}%`, backgroundColor: GROUP_DOT_COLOR[conclusion] }}
            />
        </span>
    )
}

function durationRange(group: WorkflowJobGroup): JSX.Element {
    const durations = group.jobs
        .map((j) => j.duration_seconds)
        .filter((d): d is number => d != null)
        .sort((a, b) => a - b)
    if (!durations.length) {
        return <span className="text-xs text-secondary">—</span>
    }
    const min = durations[0]
    const max = durations[durations.length - 1]
    return (
        <span className="text-xs tabular-nums whitespace-nowrap">
            {durations.length > 1 && min !== max ? (
                <>
                    {humanFriendlyDuration(min)} <span className="text-tertiary">→ {humanFriendlyDuration(max)}</span>
                </>
            ) : (
                humanFriendlyDuration(max)
            )}
        </span>
    )
}

function runnerLabel(group: WorkflowJobGroup): JSX.Element {
    const labels = Array.from(new Set(group.jobs.map((j) => j.runner_label).filter(Boolean)))
    if (!labels.length) {
        return <span className="text-xs text-secondary">—</span>
    }
    return (
        <span className="font-mono text-[11px] text-tertiary whitespace-nowrap">
            {labels[0]}
            {labels.length > 1 && <span> +{labels.length - 1}</span>}
        </span>
    )
}

function groupCost(group: WorkflowJobGroup): JSX.Element {
    if (group.jobs.every((j) => j.runner_provider === 'github_hosted')) {
        return <span className="text-xs text-secondary">Free</span>
    }
    const billable = group.jobs.filter((j) => j.runner_provider === 'self_hosted' && j.duration_seconds != null)
    const minutes = billable.length ? billable.reduce((sum, j) => sum + (j.duration_seconds ?? 0), 0) / 60 : null
    const costed = group.jobs.filter((j) => j.estimated_cost_usd != null)
    const cost = costed.length ? costed.reduce((sum, j) => sum + (j.estimated_cost_usd ?? 0), 0) : null
    return <BillableBadge minutes={minutes} costUsd={cost} />
}

function resultTag(group: WorkflowJobGroup): JSX.Element {
    if (group.failed.length > 0 && group.jobs.length > 1) {
        return (
            <LemonTag type="danger">
                {group.failed.length}/{group.jobs.length} failed
            </LemonTag>
        )
    }
    const tag: Record<JobGroupConclusion, JSX.Element> = {
        failure: <LemonTag type="danger">Failed</LemonTag>,
        running: <LemonTag type="completion">Running</LemonTag>,
        cancelled: <LemonTag type="muted">Cancelled</LemonTag>,
        skipped: <LemonTag type="muted">Skipped</LemonTag>,
        success: <LemonTag type="success">Success</LemonTag>,
    }
    return tag[group.conclusion]
}

/**
 * Grouped jobs of one workflow-run attempt. ``jobs == null`` is the not-loaded state; ``[]`` means the
 * job-level source isn't synced for this team (mirrors RunJobsTable's contract).
 */
export function GroupedJobsTable({
    jobs,
    loading,
    embedded = false,
}: {
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
                No job data yet. The job-level source isn't synced for this team.
            </div>
        )
    }
    const groups = groupJobs(jobs).sort((a, b) => Number(b.failed.length > 0) - Number(a.failed.length > 0))
    const spans = new Map(groups.map((group) => [group.base, groupSpan(group)]))
    const startValues = Array.from(spans.values())
        .map((s) => s.startMs)
        .filter((v): v is number => v != null)
    const endValues = Array.from(spans.values())
        .map((s) => s.endMs)
        .filter((v): v is number => v != null)
    const axisStart = startValues.length ? Math.min(...startValues) : 0
    const axisEnd = endValues.length ? Math.max(...endValues) : 1

    return (
        <LemonTable<WorkflowJobGroup>
            dataSource={groups}
            size="small"
            embedded={embedded}
            loading={loading}
            rowKey={(group) => group.base}
            useURLForSorting={false}
            expandable={{
                noIndent: true,
                // Only matrix groups expand, straight to their individual shards.
                rowExpandable: (group) => group.jobs.length > 1,
                expandedRowRender: (group) => (
                    <div className="px-3 py-2">
                        {[...group.jobs]
                            .sort(
                                (a, b) =>
                                    Number(b.conclusion === 'failure' || b.conclusion === 'timed_out') -
                                    Number(a.conclusion === 'failure' || a.conclusion === 'timed_out')
                            )
                            .map((job) => (
                                <div key={job.id} className="flex items-center gap-2 py-0.5 text-[11px]">
                                    <StatusDot conclusion={job.conclusion} />
                                    <span className="truncate font-mono">{job.name}</span>
                                    <span className="ml-auto tabular-nums text-tertiary whitespace-nowrap">
                                        {job.duration_seconds != null
                                            ? humanFriendlyDuration(job.duration_seconds)
                                            : '—'}
                                    </span>
                                </div>
                            ))}
                    </div>
                ),
            }}
            columns={[
                {
                    title: 'Job',
                    key: 'job',
                    render: (_, group) => (
                        <span className="overflow-hidden">
                            <span className="flex items-center gap-1.5">
                                <GroupConclusionDot conclusion={group.conclusion} />
                                <span className="truncate font-mono text-[11px]">{group.base}</span>
                                {group.jobs.length > 1 && (
                                    <LemonTag type="muted">
                                        ×{group.jobs.length}
                                        {group.variants > 1 ? ` · ${group.variants} variants` : ''}
                                    </LemonTag>
                                )}
                            </span>
                            {group.failed.length > 0 && (
                                <span className="mt-0.5 block pl-3.5 font-mono text-[10.5px] text-danger">
                                    {failedShardsLabel(group)} failed
                                </span>
                            )}
                        </span>
                    ),
                },
                {
                    title: 'Timing',
                    key: 'timing',
                    width: 220,
                    render: (_, group) => (
                        <TimingEnvelope
                            span={spans.get(group.base) ?? { startMs: null, endMs: null }}
                            conclusion={group.conclusion}
                            axisStart={axisStart}
                            axisEnd={axisEnd}
                        />
                    ),
                },
                {
                    title: 'Duration',
                    key: 'duration',
                    align: 'right',
                    render: (_, group) => durationRange(group),
                },
                {
                    title: 'Runner',
                    key: 'runner',
                    render: (_, group) => runnerLabel(group),
                },
                {
                    title: 'Cost',
                    key: 'cost',
                    align: 'right',
                    render: (_, group) => groupCost(group),
                },
                {
                    title: 'Result',
                    key: 'result',
                    width: 110,
                    render: (_, group) => resultTag(group),
                },
            ]}
            emptyState="No jobs."
            nouns={['job group', 'job groups']}
        />
    )
}
