// What the CI explorer says about a node besides drawing it: its status word, its share of the push's job time,
// its tooltip, and the excerpt of a failed job's log.

import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils/durations'

import type { CIFailureLogLineApi, WorkflowJobApi, WorkflowRunDetailApi } from '../generated/api.schemas'
import { CIExplorerItem, CIExplorerWorkflow, CIJobKind, jobsOf, resolveNode, workflowJobs } from './ciExplorerGraph'
import { compactUsd } from './format'

export type CIEngine = WorkflowRunDetailApi['ci_engine']

const KIND_NAME: Record<CIJobKind, string> = {
    test: 'Test',
    check: 'Check',
    build: 'Build',
    setup: 'Setup',
    report: 'Report',
    other: 'Job',
}

const STATUS_LABEL: Record<string, string> = {
    success: 'Passed',
    failure: 'Failed',
    startup_failure: 'Failed',
    timed_out: 'Timed out',
    cancelled: 'Cancelled',
    skipped: 'Skipped',
    neutral: 'Neutral',
    action_required: 'Action required',
    stale: 'Stale',
}

const LEVELS_SHOWN = 3
const EXCERPT_LINES = 12

/** One word for how a run, job, or step ended. A null conclusion means it has not ended. */
export function statusLabel(conclusion: string | null | undefined): string {
    return conclusion ? (STATUS_LABEL[conclusion] ?? conclusion) : 'Running'
}

/** The CI provider that ran the workflow. The runner hardware is a separate fact. */
export function providerName(engine: CIEngine | undefined): string {
    return engine === 'depot_ci' ? 'Depot CI' : engine === 'github_actions' ? 'GitHub Actions' : 'Unknown provider'
}

function duration(seconds: number | null): string {
    return seconds === null ? 'Running' : humanFriendlyDuration(seconds, { maxUnits: 2 })
}

function jobSeconds(jobs: WorkflowJobApi[]): number {
    return jobs.reduce((sum, job) => sum + (job.duration_seconds ?? 0), 0)
}

// Null when no job has a cost, so an unknown runner tier never reads as free.
function costUsd(jobs: WorkflowJobApi[]): number | null {
    const costs = jobs.map((job) => job.estimated_cost_usd).filter((cost): cost is number => cost !== null)
    return costs.length ? costs.reduce((sum, cost) => sum + cost, 0) : null
}

function ran(job: WorkflowJobApi): boolean {
    return job.conclusion !== 'skipped'
}

/** The older of the sync times that are known, because everything on screen is at least that fresh. */
export function oldestSync(...times: (string | null | undefined)[]): string | null {
    const known = times.filter((time): time is string => !!time)
    return known.length ? known.reduce((oldest, time) => (time < oldest ? time : oldest)) : null
}

/** The summed duration of every job of the push. Jobs run in parallel, so this is more than the elapsed time. */
export function totalJobSeconds(workflows: CIExplorerWorkflow[]): number {
    return jobSeconds(workflows.flatMap(workflowJobs))
}

export interface CIExplorerShareLevel {
    id: string
    name: string
    elapsedSeconds: number | null
    jobSeconds: number
    /** Percent of the push's job time, 0 to 100. */
    share: number
}

/** The focused node and what contains it, outermost first, each as a share of the push's job time. */
export function shareLevels(workflows: CIExplorerWorkflow[], nodeId: string | null): CIExplorerShareLevel[] {
    const total = Math.max(1, totalJobSeconds(workflows))
    const node = resolveNode(workflows, nodeId)
    if (!node) {
        return []
    }
    const { workflow, item, shard } = node
    const level = (id: string, name: string, elapsed: number | null, jobs: WorkflowJobApi[]): CIExplorerShareLevel => {
        const seconds = jobSeconds(jobs)
        return { id, name, elapsedSeconds: elapsed, jobSeconds: seconds, share: (seconds / total) * 100 }
    }
    const levels = [level(workflow.id, workflow.run.workflow, workflow.run.durationSeconds, workflowJobs(workflow))]
    if (item) {
        levels.push(level(item.id, item.name, item.durationSeconds, jobsOf(item)))
    }
    if (shard) {
        levels.push(level(shard.id, shard.label, shard.job.duration_seconds, [shard.job]))
    }
    return levels.slice(0, LEVELS_SHOWN)
}

export interface CIExplorerTip {
    name: string
    rows: [string, string][]
}

function costRow(jobs: WorkflowJobApi[]): [string, string][] {
    const cost = costUsd(jobs)
    return cost === null ? [] : [['Estimated cost', compactUsd(cost)]]
}

function jobTip(name: string, job: WorkflowJobApi, kind: CIJobKind, containerSeconds: number | null): CIExplorerTip {
    const ofContainer =
        containerSeconds && job.duration_seconds !== null
            ? ` · ${Math.round((job.duration_seconds / containerSeconds) * 100)}% of elapsed`
            : ''
    const rows: [string, string][] = [
        ['Kind', KIND_NAME[kind]],
        ['Status', statusLabel(job.conclusion)],
        ['Elapsed', duration(job.duration_seconds) + ofContainer],
        ['Provider', providerName(job.ci_engine)],
        ['Runner', job.runner_label || 'Unknown'],
        ...costRow([job]),
    ]
    if (job.started_at) {
        rows.push(['Started', dayjs(job.started_at).format('MMM D, HH:mm:ss')])
    }
    return { name, rows }
}

function matrixTip(item: CIExplorerItem): CIExplorerTip {
    const jobs = jobsOf(item)
    const durations = jobs.map((job) => job.duration_seconds).filter((d): d is number => d !== null)
    const failed = item.shards.filter((shard) => shard.status === 'failure').length
    const rows: [string, string][] = [
        ['Kind', `${KIND_NAME[item.kind]}, matrix`],
        ['Parallel jobs', String(item.shards.length)],
        ['Elapsed', duration(item.durationSeconds)],
        ['Job time', duration(jobSeconds(jobs))],
        ['Provider', providerName(jobs[0]?.ci_engine)],
        ...costRow(jobs),
    ]
    if (durations.length) {
        rows.push(['Slowest', duration(Math.max(...durations))], ['Fastest', duration(Math.min(...durations))])
    }
    if (failed) {
        rows.push(['Failed', String(failed)])
    }
    return { name: item.name, rows }
}

function workflowTip(workflow: CIExplorerWorkflow): CIExplorerTip {
    const jobs = workflowJobs(workflow)
    const executed = jobs.filter(ran)
    const rows: [string, string][] = [
        ['Provider', providerName(workflow.run.ciEngine)],
        ['Status', statusLabel(workflow.run.conclusion)],
        ['Attempt', String(workflow.run.runAttempt ?? 1)],
        ['Elapsed', duration(workflow.run.durationSeconds)],
        ['Job time', workflow.items === null ? 'Loading' : duration(jobSeconds(jobs))],
        [
            'Jobs',
            workflow.items === null ? 'Loading' : `${executed.length} ran, ${jobs.length - executed.length} skipped`,
        ],
        ...costRow(jobs),
    ]
    if (workflow.run.event) {
        rows.push(['Trigger', workflow.run.event])
    }
    return { name: workflow.run.workflow, rows }
}

/** What a tooltip says about the node with this id, or null when no node has it. */
export function nodeTip(workflows: CIExplorerWorkflow[], nodeId: string): CIExplorerTip | null {
    for (const workflow of workflows) {
        if (workflow.id === nodeId) {
            return workflowTip(workflow)
        }
        for (const item of workflow.items ?? []) {
            if (item.id === nodeId) {
                return item.job ? jobTip(item.name, item.job, item.kind, workflow.run.durationSeconds) : matrixTip(item)
            }
            const shard = item.shards.find((s) => s.id === nodeId)
            if (shard) {
                return jobTip(shard.job.name, shard.job, item.kind, item.durationSeconds)
            }
        }
    }
    return null
}

export interface CIExplorerSummary {
    passed: number
    failed: number
    running: number
    /** Cancelled, skipped, and every other ending that is neither a pass nor a failure. */
    other: number
}

/** How the workflows of a push ended, as counts. It is not a merge verdict, because required checks are not synced. */
export function summarize(workflows: CIExplorerWorkflow[]): CIExplorerSummary {
    const summary: CIExplorerSummary = { passed: 0, failed: 0, running: 0, other: 0 }
    for (const workflow of workflows) {
        if (workflow.status === 'success') {
            summary.passed++
        } else if (workflow.status === 'failure') {
            summary.failed++
        } else if (workflow.status === 'running') {
            summary.running++
        } else {
            summary.other++
        }
    }
    return summary
}

export interface CIFailureExcerpt {
    /** The last lines of the failure region, where the error usually is. */
    tail: string
    /** The whole stored region, or null when the tail already shows all of it. */
    context: string | null
}

export function failureExcerpt(lines: CIFailureLogLineApi[]): CIFailureExcerpt | null {
    if (!lines.length) {
        return null
    }
    const text = lines.map((line) => line.text)
    return {
        tail: text.slice(-EXCERPT_LINES).join('\n'),
        context: text.length > EXCERPT_LINES ? text.join('\n') : null,
    }
}
