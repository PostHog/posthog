import { randomBytes } from 'node:crypto'
import { z } from 'zod'

import { META_CLIENT_CAPABILITIES } from '@/lib/stateless-protocol'
import type { Context } from '@/tools/types'

import type { RedisLike } from './cache/RedisCache'

// MCP Tasks extension for the 2026-07-28 protocol (SEP-2663). A long-running `tools/call`
// answers with a task handle, and the client polls `tasks/get` until the job finishes. The
// model then sees one finished result instead of polling a status tool itself.
// Spec: https://tasks.extensions.modelcontextprotocol.io/specification/2026-07-28/tasks.html
export const TASKS_EXTENSION_ID = 'io.modelcontextprotocol/tasks'

const TASK_TTL_MS = 60 * 60 * 1000
const TASK_KEY_PREFIX = 'mcp:task:'

export function isTasksExtensionEnabled(): boolean {
    return process.env.MCP_TASKS_EXTENSION === 'true'
}

const RequestCapabilitiesSchema = z.object({
    _meta: z.object({
        [META_CLIENT_CAPABILITIES]: z.object({ extensions: z.record(z.string(), z.unknown()) }),
    }),
})

// The opt-in is per request: a client declares the extension in each request's `_meta`,
// and the server must never return a task to a request that did not declare it.
export function requestDeclaresTasks(params: unknown): boolean {
    const parsed = RequestCapabilitiesSchema.safeParse(params)
    return parsed.success && TASKS_EXTENSION_ID in parsed.data._meta[META_CLIENT_CAPABILITIES].extensions
}

export interface TaskToolSpec {
    /** The tool that reports the job's state. Its final result becomes the task's result. */
    statusTool: string
    pendingStatusArgs(startArgs: Record<string, unknown>, startResult: unknown): Record<string, unknown> | undefined
    isTerminal(statusResult: unknown): boolean
    statusMessage(statusResult: unknown): string | undefined
    pollIntervalMs: number
}

const RECALCULATION_TERMINAL_STATUSES = new Set(['completed', 'failed'])

const RecalculationRunSchema = z.object({
    id: z.string(),
    status: z.string(),
    completed_metrics: z.number().optional(),
    total_metrics: z.number().optional(),
    rows_read: z.number().nullish(),
})

function recalculationProgress(result: unknown): string | undefined {
    const run = RecalculationRunSchema.safeParse(result)
    if (!run.success || run.data.total_metrics === undefined) {
        return undefined
    }
    const rows = run.data.rows_read ? `, ${run.data.rows_read.toLocaleString('en-US')} rows read` : ''
    return `${run.data.completed_metrics ?? 0} of ${run.data.total_metrics} metrics done${rows}`
}

export const TASK_TOOLS: Readonly<Record<string, TaskToolSpec>> = {
    'experiment-metrics-recalculation-create': {
        statusTool: 'experiment-metrics-recalculation-retrieve',
        pendingStatusArgs: (startArgs, startResult) => {
            const run = RecalculationRunSchema.safeParse(startResult)
            if (!run.success || RECALCULATION_TERMINAL_STATUSES.has(run.data.status)) {
                return undefined
            }
            return { id: startArgs.id, recalculation_id: run.data.id }
        },
        isTerminal: (statusResult) => {
            const run = RecalculationRunSchema.safeParse(statusResult)
            return run.success && RECALCULATION_TERMINAL_STATUSES.has(run.data.status)
        },
        statusMessage: recalculationProgress,
        pollIntervalMs: 5_000,
    },
}

export interface StoredTask {
    toolName: string
    statusArgs: Record<string, unknown>
    distinctId: string
    projectId: string
    createdAt: string
    cancelled?: boolean
}

export type TaskStatus = 'working' | 'completed' | 'cancelled'

export class TaskNotFoundError extends Error {
    constructor() {
        super('Failed to retrieve task: Task not found')
    }
}

export class TaskStore {
    constructor(private readonly redis: RedisLike) {}

    async create(task: StoredTask): Promise<string> {
        // The ID works as a bearer handle for the task, so it must not be guessable.
        const taskId = randomBytes(24).toString('base64url')
        await this.redis.set(TASK_KEY_PREFIX + taskId, JSON.stringify(task), 'PX', TASK_TTL_MS)
        return taskId
    }

    // A task that belongs to another user reads as missing, so a leaked ID does not
    // confirm that the task exists.
    async get(taskId: string, distinctId: string): Promise<StoredTask> {
        const raw = taskId ? await this.redis.get(TASK_KEY_PREFIX + taskId) : null
        const task = raw ? (JSON.parse(raw) as StoredTask) : undefined
        if (!task || task.distinctId !== distinctId) {
            throw new TaskNotFoundError()
        }
        return task
    }

    async cancel(taskId: string, distinctId: string): Promise<void> {
        const task = await this.get(taskId, distinctId)
        await this.redis.set(TASK_KEY_PREFIX + taskId, JSON.stringify({ ...task, cancelled: true }), 'KEEPTTL')
    }
}

export function taskView(
    taskId: string,
    task: StoredTask,
    status: TaskStatus,
    statusMessage: string | undefined
): Record<string, unknown> {
    return {
        taskId,
        status,
        ...(statusMessage ? { statusMessage } : {}),
        createdAt: task.createdAt,
        lastUpdatedAt: new Date().toISOString(),
        ttlMs: TASK_TTL_MS,
        pollIntervalMs: TASK_TOOLS[task.toolName]?.pollIntervalMs,
    }
}

// Status checks run against the project the task started in. The conversation can switch
// project between two polls, and the job does not move with it.
export function contextForProject(context: Context, projectId: string): Context {
    const stateManager = Object.create(context.stateManager) as Context['stateManager']
    stateManager.getProjectId = async () => projectId
    return { ...context, stateManager }
}
