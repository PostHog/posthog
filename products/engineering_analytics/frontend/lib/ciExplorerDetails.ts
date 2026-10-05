// What the CI explorer says about a node besides drawing it: its share of the push's CI time, and its tooltip.

import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils/durations'

import type { WorkflowJobApi } from '../generated/api.schemas'
import type { CIExplorerItem, CIExplorerWorkflow, CIJobKind } from './ciExplorerGraph'

const KIND_NAME: Record<CIJobKind, string> = {
    test: 'Test',
    check: 'Check',
    build: 'Build',
    setup: 'Setup',
    report: 'Report',
    other: 'Job',
}

const LEVELS_SHOWN = 3

function duration(seconds: number | null): string {
    return seconds === null ? 'Running' : humanFriendlyDuration(seconds, { maxUnits: 2 })
}

function jobsOf(item: CIExplorerItem): WorkflowJobApi[] {
    return item.job ? [item.job] : item.shards.map((shard) => shard.job)
}

function computeSeconds(jobs: WorkflowJobApi[]): number {
    return jobs.reduce((sum, job) => sum + (job.duration_seconds ?? 0), 0)
}

function workflowJobs(workflow: CIExplorerWorkflow): WorkflowJobApi[] {
    return (workflow.items ?? []).flatMap(jobsOf)
}

/** Runner time of every job of the push. A matrix counts each shard, so this is more than the wall time. */
export function totalComputeSeconds(workflows: CIExplorerWorkflow[]): number {
    return computeSeconds(workflows.flatMap(workflowJobs))
}

export interface CIExplorerShareLevel {
    id: string
    name: string
    wallSeconds: number | null
    computeSeconds: number
    /** Percent of the push's CI time, 0 to 100. */
    share: number
}

/** The focused node and what contains it, outermost first, each as a share of the push's CI time. */
export function shareLevels(workflows: CIExplorerWorkflow[], nodeId: string | null): CIExplorerShareLevel[] {
    const total = Math.max(1, totalComputeSeconds(workflows))
    const workflow =
        nodeId === null ? undefined : workflows.find((w) => nodeId === w.id || nodeId.startsWith(`${w.id}/`))
    if (!workflow || nodeId === null) {
        return []
    }
    const level = (
        id: string,
        name: string,
        wallSeconds: number | null,
        jobs: WorkflowJobApi[]
    ): CIExplorerShareLevel => {
        const compute = computeSeconds(jobs)
        return { id, name, wallSeconds, computeSeconds: compute, share: (compute / total) * 100 }
    }
    const levels = [level(workflow.id, workflow.run.workflow, workflow.run.durationSeconds, workflowJobs(workflow))]
    const item = workflow.items?.find((i) => nodeId === i.id || nodeId.startsWith(`${i.id}/`))
    if (item) {
        levels.push(level(item.id, item.name, item.durationSeconds, jobsOf(item)))
        const shard = item.shards.find((s) => s.id === nodeId)
        if (shard) {
            levels.push(level(shard.id, shard.label, shard.job.duration_seconds, [shard.job]))
        }
    }
    return levels.slice(0, LEVELS_SHOWN)
}

export interface CIExplorerTip {
    name: string
    rows: [string, string][]
}

function jobTip(name: string, job: WorkflowJobApi, kind: CIJobKind, wallSeconds: number | null): CIExplorerTip {
    const ofWall =
        wallSeconds && job.duration_seconds !== null
            ? ` · ${Math.round((job.duration_seconds / wallSeconds) * 100)}% of wall`
            : ''
    const rows: [string, string][] = [
        ['Kind', KIND_NAME[kind]],
        ['Duration', duration(job.duration_seconds) + ofWall],
        ['Runner', job.runner_label || 'Unknown'],
    ]
    if (job.estimated_cost_usd !== null) {
        rows.push(['Estimated cost', `$${job.estimated_cost_usd.toFixed(2)}`])
    }
    if (job.started_at) {
        rows.push(['Started', dayjs(job.started_at).format('MMM D, HH:mm:ss')])
    }
    return { name, rows }
}

function matrixTip(item: CIExplorerItem): CIExplorerTip {
    const durations = item.shards.map((shard) => shard.job.duration_seconds).filter((d): d is number => d !== null)
    const failed = item.shards.filter((shard) => shard.status === 'failure').length
    const rows: [string, string][] = [
        ['Kind', `${KIND_NAME[item.kind]}, matrix`],
        ['Parallel jobs', String(item.shards.length)],
        ['Wall', duration(item.durationSeconds)],
        ['Compute', duration(computeSeconds(jobsOf(item)))],
    ]
    if (durations.length) {
        rows.push(['Slowest', duration(Math.max(...durations))], ['Fastest', duration(Math.min(...durations))])
    }
    if (failed) {
        rows.push(['Failed', String(failed)])
    }
    return { name: item.name, rows }
}

/** What a tooltip says about the node with this id, or null when no node has it. */
export function nodeTip(workflows: CIExplorerWorkflow[], nodeId: string): CIExplorerTip | null {
    for (const workflow of workflows) {
        if (workflow.id === nodeId) {
            const jobs = workflowJobs(workflow)
            return {
                name: workflow.run.workflow,
                rows: [
                    ['Duration', duration(workflow.run.durationSeconds)],
                    ['Compute', duration(computeSeconds(jobs))],
                    ['Jobs', workflow.items === null ? 'Loading' : String(jobs.length)],
                ],
            }
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
