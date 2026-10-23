import { humanFriendlyDuration } from 'lib/utils/durations'

import type { WorkflowJobApi } from '../generated/api.schemas'
import { statusOf } from './ciExplorerGraph'
import { githubJobUrl } from './github'
import { groupJobs } from './jobGroups'
import { WorkflowRun } from './lifecycle'

export type TimelineStatus = 'success' | 'failure' | 'running' | 'neutral' | 'skipped'

export interface TimelineNode {
    id: string
    kind: 'workflow' | 'group' | 'job' | 'step'
    name: string
    /** A job's runner label. null on every other kind. */
    runner: string | null
    /** A job's estimated cost in USD. null when the runner tier is unknown or the job hasn't finished. */
    costUsd?: number | null
    /** The workflow's run page, or the GitHub log page of a job or step. */
    url?: string
    /** null when it never started, as for a skipped job. */
    startMs: number | null
    /** The build time while it runs. null when it never started or stopped reporting. */
    endMs: number | null
    status: TimelineStatus
    children: TimelineNode[]
}

export interface TimelineData {
    startMs: number
    endMs: number
    nodes: TimelineNode[]
}

export interface TimelineRow {
    node: TimelineNode
    /** Entry i is true when the row's ancestor at depth i + 1 is its parent's last child. The last entry is the row itself. */
    lastAtLevel: boolean[]
}

function timelineStatus(conclusion: string | null): TimelineStatus {
    return conclusion === 'skipped' ? 'skipped' : statusOf(conclusion)
}

function toMs(at: string | null): number | null {
    return at ? Date.parse(at) : null
}

// The webhook sync can miss a run's final event, so an unfinished item with no update for a day stopped reporting.
const STOPPED_REPORTING_MS = 24 * 60 * 60 * 1000

type Timing = Pick<TimelineNode, 'startMs' | 'endMs' | 'status'>

export interface TimelineRepo {
    owner: string
    name: string
}

/**
 * An unfinished item ends at `nowMs`. One that stopped reporting gets no end and no outcome.
 * Jobs and steps carry no update time, so their start stands in for it.
 */
function timing(
    startedAt: string | null,
    finishedAt: string | null,
    conclusion: string | null,
    nowMs: number,
    updatedAt: string | null = null
): Timing {
    const startMs = toMs(startedAt)
    const status = timelineStatus(conclusion)
    if (startMs == null) {
        return { startMs, endMs: null, status }
    }
    const endMs = toMs(finishedAt)
    if (endMs != null) {
        return { startMs, endMs, status }
    }
    return nowMs - (toMs(updatedAt) ?? startMs) < STOPPED_REPORTING_MS
        ? { startMs, endMs: nowMs, status }
        : { startMs, endMs: null, status: 'neutral' }
}

function combinedStatus(statuses: TimelineStatus[]): TimelineStatus {
    if (statuses.includes('failure')) {
        return 'failure'
    }
    if (statuses.includes('running')) {
        return 'running'
    }
    if (statuses.every((status) => status === 'skipped')) {
        return 'skipped'
    }
    return statuses.every((status) => status === 'success' || status === 'skipped') ? 'success' : 'neutral'
}

function minOf(values: (number | null)[]): number | null {
    const known = values.filter((v): v is number => v != null)
    return known.length ? Math.min(...known) : null
}

function maxOf(values: (number | null)[]): number | null {
    const known = values.filter((v): v is number => v != null)
    return known.length ? Math.max(...known) : null
}

const byStart = (a: TimelineNode, b: TimelineNode): number =>
    (a.startMs ?? Number.MAX_SAFE_INTEGER) - (b.startMs ?? Number.MAX_SAFE_INTEGER)

function jobId(job: WorkflowJobApi): string {
    return `job-${job.ci_engine ?? ''}-${job.id}`
}

function jobNode(job: WorkflowJobApi, repo: TimelineRepo, nowMs: number): TimelineNode {
    const id = jobId(job)
    // Depot CI jobs have no page on GitHub.
    const logUrl = (stepNumber?: number): string | undefined =>
        job.ci_engine === 'depot_ci' ? undefined : githubJobUrl(repo.owner, repo.name, job.run_id, job.id, stepNumber)
    return {
        id,
        kind: 'job',
        name: job.name,
        runner: job.runner_label || null,
        costUsd: job.estimated_cost_usd,
        url: logUrl(),
        ...timing(job.started_at, job.completed_at, job.conclusion, nowMs),
        children: job.steps.map(
            (step): TimelineNode => ({
                id: `${id}-step-${step.number}`,
                kind: 'step',
                name: step.name,
                runner: null,
                url: logUrl(step.number),
                ...timing(step.started_at, step.completed_at, step.conclusion, nowMs),
                children: [],
            })
        ),
    }
}

/** A run's jobs with matrix shards nested under their group, in start order. */
function jobNodes(jobs: WorkflowJobApi[], repo: TimelineRepo, nowMs: number): TimelineNode[] {
    return groupJobs(jobs)
        .map((group): TimelineNode => {
            if (group.jobs.length === 1) {
                return jobNode(group.jobs[0], repo, nowMs)
            }
            const shards = group.jobs.map((job) => jobNode(job, repo, nowMs)).sort(byStart)
            return {
                id: `${jobId(group.jobs[0])}-group`,
                kind: 'group',
                name: group.base,
                runner: null,
                startMs: minOf(shards.map((s) => s.startMs)),
                endMs: maxOf(shards.map((s) => s.endMs)),
                status: combinedStatus(shards.map((s) => s.status)),
                children: shards,
            }
        })
        .sort(byStart)
}

function flatten(nodes: TimelineNode[]): TimelineNode[] {
    return nodes.flatMap((node) => [node, ...flatten(node.children)])
}

/**
 * The end spans every descendant, since a child outlasts a parent whose finish the sync missed.
 * The start doesn't: a re-run lists jobs from an earlier attempt, and those started long before it.
 */
function withBounds(nodes: TimelineNode[], anchorMs: number | null, nowMs: number): TimelineData {
    const startMs = minOf([anchorMs, ...nodes.map((n) => n.startMs)]) ?? nowMs
    const endMs = maxOf(flatten(nodes).map((n) => n.endMs)) ?? startMs
    return { startMs, endMs: Math.max(endMs, startMs + 1000), nodes }
}

export function buildRunTimeline(
    repo: TimelineRepo,
    runStartedAt: string | null,
    jobs: WorkflowJobApi[],
    nowMs: number
): TimelineData {
    return withBounds(jobNodes(jobs, repo, nowMs), toMs(runStartedAt), nowMs)
}

export function buildPushTimeline(
    repo: TimelineRepo,
    runs: { id: string; run: WorkflowRun; jobs: WorkflowJobApi[]; url?: string }[],
    nowMs: number
): TimelineData {
    const nodes = runs
        .map(({ id, run, jobs, url }): TimelineNode => {
            const children = jobNodes(jobs, repo, nowMs)
            const own = timing(run.startedAt, run.finishedAt, run.conclusion, nowMs, run.updatedAt)
            // Only a run with no start of its own spans its jobs, so one that stopped reporting keeps its missing end.
            const span =
                own.startMs == null
                    ? { startMs: minOf(children.map((c) => c.startMs)), endMs: maxOf(children.map((c) => c.endMs)) }
                    : own
            return {
                id: `workflow-${id}`,
                kind: 'workflow',
                name: run.workflow,
                runner: null,
                url,
                startMs: span.startMs,
                endMs: span.endMs,
                status: own.status,
                children,
            }
        })
        .sort(byStart)
    return withBounds(nodes, null, nowMs)
}

export function visibleTimelineRows(nodes: TimelineNode[], isExpanded: (node: TimelineNode) => boolean): TimelineRow[] {
    const rows: TimelineRow[] = []
    const walk = (siblings: TimelineNode[], lastAtLevel: boolean[]): void => {
        siblings.forEach((node, index) => {
            const levels = [...lastAtLevel, index === siblings.length - 1]
            rows.push({ node, lastAtLevel: levels })
            if (isExpanded(node)) {
                walk(node.children, levels)
            }
        })
    }
    walk(nodes, [])
    return rows
}

export function timelineDuration(node: TimelineNode): string | null {
    return node.startMs != null && node.endMs != null ? humanFriendlyDuration((node.endMs - node.startMs) / 1000) : null
}

export function parentNodes(nodes: TimelineNode[]): TimelineNode[] {
    return nodes.flatMap((node) => (node.children.length ? [node, ...parentNodes(node.children)] : []))
}

const TICK_STEPS_SECONDS = [5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200]

/** Elapsed-second ticks from 0, at a round step that fits within maxTicks. */
export function timelineTicks(durationSeconds: number, maxTicks: number): number[] {
    const step =
        TICK_STEPS_SECONDS.find((s) => durationSeconds / s <= Math.max(1, maxTicks)) ??
        Math.ceil(durationSeconds / maxTicks / 3600) * 3600
    const ticks: number[] = []
    for (let t = 0; t <= durationSeconds; t += step) {
        ticks.push(t)
    }
    return ticks
}
