// One push as a set of workflow graphs: a node per job or matrix, an edge per `needs` dependency.
// ELK places the nodes and routes the edges.

import type { ELK, ElkNode } from 'elkjs'

import type { WorkflowJobApi } from '../generated/api.schemas'
import { JobGroupConclusion, collapseTemplates, groupJobs } from './jobGroups'
import { jobCacheKey } from './jobs'
import { WorkflowRun, isDecisiveFailure } from './lifecycle'

export type CIStatus = 'success' | 'failure' | 'running' | 'neutral'
export type CIJobKind = 'test' | 'check' | 'build' | 'setup' | 'report' | 'other'

export interface CIExplorerShard {
    id: string
    label: string
    status: CIStatus
    job: WorkflowJobApi
    /** Duration relative to the slowest shard of the matrix, 0 to 1. */
    durationShare: number
}

/** A node of a workflow's graph: one job, or one matrix job with its shards. */
export interface CIExplorerItem {
    id: string
    name: string
    kind: CIJobKind
    status: CIStatus
    startedAt: number
    endedAt: number
    /** Wall time: for a matrix, its slowest shard. Null while nothing has finished. */
    durationSeconds: number | null
    /** Duration relative to the slowest item of the workflow, 0 to 1. */
    durationShare: number
    /** Set for a single job. */
    job: WorkflowJobApi | null
    /** Set for a matrix, failed first and then slowest first. */
    shards: CIExplorerShard[]
}

export interface CIExplorerWorkflow {
    id: string
    run: WorkflowRun
    status: CIStatus
    /** Duration relative to the slowest workflow of the push, 0 to 1. */
    durationShare: number
    /** Null while the workflow's jobs are loading. */
    items: CIExplorerItem[] | null
    edges: [string, string][]
    columnOf: Record<string, number>
}

export interface CIExplorerLayout {
    at: Record<string, { x: number; y: number }>
    width: number
    height: number
    /** SVG path data, one per edge. */
    wires: string[]
    /** Both ends of every edge. */
    ends: { x: number; y: number }[]
}

export const NODE_WIDTH = 264
const NODE_PADDING = 24
export const INNER_WIDTH = 744
/** A matrix lays its shards out INNER_WIDTH wide, then scales them down to fit the node. */
export const INNER_SCALE = (NODE_WIDTH - NODE_PADDING) / INNER_WIDTH
export const SHARDS_PER_ROW = 3
export const SHARD_HEIGHT = 40
export const SHARD_GAP = 8
const TITLE_CHARS_PER_LINE = 21
const SAME_COLUMN_MS = 5000

// A job's kind is guessed from its name. The first rule that matches wins.
const KIND_RULES: [CIJobKind, RegExp][] = [
    ['report', /\bpass(es)?$|tests pass|checks pass/i],
    [
        'setup',
        /determine need|dynamic ci|discover|select|matrix|detect|get \w+ versions|hand off|wait for|prime|cancel|assign|token/i,
    ],
    ['report', /report|capture|calculate|coverage|summary|complete|snapshot changes|verdict|upload|comment/i],
    ['test', /test|jest|playwright|pytest|django|e2e|visual regression|flake verification/i],
    [
        'check',
        /lint|format|typecheck|type ?checking|validate|semgrep|shellcheck|migration|openapi|check|guard|quality|audit|clippy/i,
    ],
    ['build', /build|image|compile|bundle|deploy/i],
]

export function jobKind(name: string): CIJobKind {
    return KIND_RULES.find(([, pattern]) => pattern.test(name))?.[0] ?? 'other'
}

export function statusOf(conclusion: string | null): CIStatus {
    if (conclusion === null) {
        return 'running'
    }
    if (isDecisiveFailure(conclusion)) {
        return 'failure'
    }
    return conclusion === 'success' ? 'success' : 'neutral'
}

const STATUS_RANK: Record<CIStatus, number> = { failure: 0, running: 1, success: 2, neutral: 3 }

const GROUP_STATUS: Record<JobGroupConclusion, CIStatus> = {
    failure: 'failure',
    running: 'running',
    success: 'success',
    cancelled: 'neutral',
    skipped: 'neutral',
}

function share(seconds: number | null, longest: number): number {
    return longest > 0 && seconds ? Math.min(1, seconds / longest) : 0
}

function startOf(job: WorkflowJobApi): number {
    return job.started_at ? Date.parse(job.started_at) : Infinity
}

function endOf(job: WorkflowJobApi): number {
    return job.completed_at ? Date.parse(job.completed_at) : Infinity
}

/** What a shard's name adds to its matrix name: "Django tests – Core (3/23)" becomes "Core (3/23)". */
function shardLabel(jobName: string, base: string): string {
    const name = collapseTemplates(jobName)
    const rest = name.startsWith(base) ? name.slice(base.length).replace(/^[\s–-]+/, '') : name
    return rest.replace(/^\((\d+\/\d+)\)$/, '$1') || name
}

function itemsOf(workflowId: string, jobs: WorkflowJobApi[]): CIExplorerItem[] {
    const items = groupJobs(jobs).map((group): Omit<CIExplorerItem, 'durationShare'> => {
        const id = `${workflowId}/${group.base}`
        const slowest = Math.max(0, ...group.jobs.map((job) => job.duration_seconds ?? 0))
        const finished = group.jobs.some((job) => job.duration_seconds !== null)
        const single = group.jobs.length === 1 ? group.jobs[0] : null
        return {
            id,
            name: single ? collapseTemplates(single.name) : group.base,
            kind: jobKind(group.base),
            status: GROUP_STATUS[group.conclusion],
            startedAt: Math.min(...group.jobs.map(startOf)),
            endedAt: Math.max(...group.jobs.map(endOf)),
            durationSeconds: finished ? slowest : null,
            job: single,
            shards: single
                ? []
                : [...group.jobs]
                      .sort(
                          (a, b) =>
                              STATUS_RANK[statusOf(a.conclusion)] - STATUS_RANK[statusOf(b.conclusion)] ||
                              (b.duration_seconds ?? 0) - (a.duration_seconds ?? 0)
                      )
                      .map((job) => ({
                          id: `${id}/${job.id}`,
                          label: shardLabel(job.name, group.base),
                          status: statusOf(job.conclusion),
                          job,
                          durationShare: share(job.duration_seconds, slowest),
                      })),
        }
    })
    const longest = Math.max(0, ...items.map((item) => item.durationSeconds ?? 0))
    return items.map((item) => ({ ...item, durationShare: share(item.durationSeconds, longest) }))
}

// Jobs that started together share a column, and a job always sits to the right of a job it needs.
function columnsOf(items: CIExplorerItem[], edges: [string, string][]): Record<string, number> {
    const columnOf: Record<string, number> = {}
    const sorted = [...items].sort(
        (a, b) => a.startedAt - b.startedAt || (b.durationSeconds ?? 0) - (a.durationSeconds ?? 0)
    )
    if (!sorted.length) {
        return columnOf
    }
    const span = sorted[sorted.length - 1].startedAt - sorted[0].startedAt
    const tolerance = Math.max(SAME_COLUMN_MS, isFinite(span) ? span * 0.01 : 0)
    let column = 0
    sorted.forEach((item, index) => {
        if (index && item.startedAt - sorted[index - 1].startedAt > tolerance) {
            column++
        }
        const afterPrevious = edges
            .filter(([from, to]) => to === item.id && from in columnOf)
            .map(([from]) => columnOf[from] + 1)
        columnOf[item.id] = Math.max(column, ...afterPrevious)
    })
    return columnOf
}

export function workflowId(run: WorkflowRun): string {
    return run.runId === null ? run.workflow : jobCacheKey(run.runId, run.runAttempt, run.ciEngine)
}

/** The workflows of a push, failed first and then slowest first. */
export function buildWorkflows(runs: WorkflowRun[], jobsByRun: Record<string, WorkflowJobApi[]>): CIExplorerWorkflow[] {
    const longest = Math.max(0, ...runs.map((run) => run.durationSeconds ?? 0))
    return [...runs]
        .sort(
            (a, b) =>
                Number(statusOf(b.conclusion) === 'failure') - Number(statusOf(a.conclusion) === 'failure') ||
                (b.durationSeconds ?? 0) - (a.durationSeconds ?? 0)
        )
        .map((run): CIExplorerWorkflow => {
            const id = workflowId(run)
            const jobs = run.runId === null ? [] : jobsByRun[id]
            const items = jobs ? itemsOf(id, jobs) : null
            // An edge is a `needs` dependency from the workflow file, which is not synced yet.
            const edges: [string, string][] = []
            return {
                id,
                run,
                status: statusOf(run.conclusion),
                durationShare: share(run.durationSeconds, longest),
                items,
                edges,
                columnOf: items ? columnsOf(items, edges) : {},
            }
        })
}

/** The space a node takes, known before it is drawn so the layout can run first. */
export function itemSize(item: CIExplorerItem): { height: number; titleHeight: number; gridHeight: number } {
    const rows = Math.ceil(item.shards.length / SHARDS_PER_ROW)
    const gridHeight = (rows * SHARD_HEIGHT + Math.max(0, rows - 1) * SHARD_GAP) * INNER_SCALE
    const titleHeight = 20 + Math.min(3, Math.ceil(item.name.length / TITLE_CHARS_PER_LINE)) * 17
    return { gridHeight, titleHeight, height: titleHeight + 2 + 10 + (rows ? 12 + gridHeight : 0) }
}

// Partitioning pins each node to the column `columnsOf` chose for it.
const ELK_OPTIONS = {
    'elk.algorithm': 'layered',
    'elk.direction': 'RIGHT',
    'elk.edgeRouting': 'SPLINES',
    'elk.partitioning.activate': 'true',
    'elk.padding': '[top=0,left=0,bottom=0,right=0]',
    'elk.spacing.nodeNode': '14',
    'elk.spacing.edgeNode': '12',
    'elk.spacing.edgeEdge': '8',
    'elk.layered.spacing.nodeNodeBetweenLayers': '56',
    'elk.layered.spacing.edgeNodeBetweenLayers': '14',
}

interface Point {
    x: number
    y: number
}

// ELK's spline route as SVG path data.
function wirePath(points: Point[]): string {
    let d = `M${points[0].x},${points[0].y}`
    for (let i = 1; i < points.length; ) {
        const left = points.length - i
        if (left >= 3) {
            d += ` C${points[i].x},${points[i].y} ${points[i + 1].x},${points[i + 1].y} ${points[i + 2].x},${points[i + 2].y}`
        } else if (left === 2) {
            d += ` Q${points[i].x},${points[i].y} ${points[i + 1].x},${points[i + 1].y}`
        } else {
            d += ` L${points[i].x},${points[i].y}`
        }
        i += Math.min(left, 3)
    }
    return d
}

export async function layoutWorkflow(elk: ELK, workflow: CIExplorerWorkflow): Promise<CIExplorerLayout> {
    const items = workflow.items ?? []
    if (!items.length) {
        return { at: {}, width: NODE_WIDTH, height: 1, wires: [], ends: [] }
    }
    const graph: ElkNode = {
        id: 'root',
        layoutOptions: ELK_OPTIONS,
        children: items.map((item) => ({
            id: item.id,
            width: NODE_WIDTH,
            height: itemSize(item).height,
            layoutOptions: { 'elk.partitioning.partition': String(workflow.columnOf[item.id]) },
        })),
        edges: workflow.edges.map(([from, to], index) => ({ id: `e${index}`, sources: [from], targets: [to] })),
    }
    const placed = await elk.layout(graph)
    const routes = (placed.edges ?? [])
        .flatMap((edge) => edge.sections ?? [])
        .map((section) => [section.startPoint, ...(section.bendPoints ?? []), section.endPoint])
    return {
        at: Object.fromEntries(
            (placed.children ?? []).map((child) => [child.id, { x: child.x ?? 0, y: child.y ?? 0 }])
        ),
        width: placed.width ?? NODE_WIDTH,
        height: placed.height ?? 1,
        wires: routes.map(wirePath),
        ends: routes.flatMap((points) => [points[0], points[points.length - 1]]),
    }
}

export const TILE_WIDTH = 300
export const TILE_HEIGHT = 98
export const TILE_GAP = 16
export const TILE_COLUMN_GAP = 56
/** The tiles hang off a rail that runs along the top and drops down the left of each column. */
export const RAIL_LEFT = 32
export const RAIL_TOP = 72

export function tileGridSize(columns: number, rows: number): { width: number; height: number } {
    return {
        width: RAIL_LEFT + columns * TILE_WIDTH + (columns - 1) * TILE_COLUMN_GAP,
        height: RAIL_TOP + rows * (TILE_HEIGHT + TILE_GAP) - TILE_GAP,
    }
}

/** How many rows of tiles show largest on a stage of this size. Tiles fill a column before the next starts. */
export function tileRows(count: number, stageWidth: number, stageHeight: number): number {
    let best = { rows: Math.max(1, count), scale: 0 }
    for (let columns = 1; columns <= count; columns++) {
        const rows = Math.ceil(count / columns)
        const size = tileGridSize(columns, rows)
        const scale = Math.min(stageWidth / size.width, stageHeight / size.height)
        if (scale > best.scale + 1e-6) {
            best = { rows, scale }
        }
    }
    return best.rows
}

export interface CIExplorerFocusLevel {
    id: string
    name: string
    durationSeconds: number | null
}

/** The focused node and what contains it, outermost first. A node id starts with the id of its container. */
export function focusPath(workflows: CIExplorerWorkflow[], nodeId: string | null): CIExplorerFocusLevel[] {
    const workflow =
        nodeId === null ? undefined : workflows.find((w) => nodeId === w.id || nodeId.startsWith(`${w.id}/`))
    if (!workflow || nodeId === null) {
        return []
    }
    const path: CIExplorerFocusLevel[] = [
        { id: workflow.id, name: workflow.run.workflow, durationSeconds: workflow.run.durationSeconds },
    ]
    const item = workflow.items?.find((i) => nodeId === i.id || nodeId.startsWith(`${i.id}/`))
    if (item) {
        path.push({ id: item.id, name: item.name, durationSeconds: item.durationSeconds })
        const shard = item.shards.find((s) => s.id === nodeId)
        if (shard) {
            path.push({ id: shard.id, name: shard.label, durationSeconds: shard.job.duration_seconds })
        }
    }
    return path
}

/** The job a focused node stands for: a single job, or one shard of a matrix. */
export function focusedJob(
    workflows: CIExplorerWorkflow[],
    nodeId: string | null
): { job: WorkflowJobApi; run: WorkflowRun } | null {
    for (const workflow of workflows) {
        for (const item of workflow.items ?? []) {
            const job = item.id === nodeId ? item.job : item.shards.find((shard) => shard.id === nodeId)?.job
            if (job) {
                return { job, run: workflow.run }
            }
        }
    }
    return null
}
