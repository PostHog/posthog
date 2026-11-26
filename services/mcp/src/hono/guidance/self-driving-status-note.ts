import { createHash } from 'node:crypto'

import type { EvaluatedFlags } from '@/lib/posthog/flags'
import type { Context, Tool, ZodObjectAny } from '@/tools/types'

import type { RedisLike } from '../cache/RedisCache'
import { MCP_GUIDANCE_SELF_DRIVING_ACTIVATION_FLAG } from './rules'
import { fetchSelfDrivingSetupNotStarted } from './self-driving-activation'

const STATUS_TOOL = 'self-driving-status-get'
const STATUS_TTL_SECONDS = 60
const LOOKUP_BUDGET_MS = 1000

function statusNote(subject: string): string {
    return `Self-driving can hold automatic investigation reports from agents on ${subject}. Call \`${STATUS_TOOL}\` once; when it is not active, tell the user and link them to the activation page.`
}

const STATUS_NOTES: ReadonlyMap<string, string> = new Map([
    ['query-error-tracking-issues-list', statusNote('these issues')],
    ['query-error-tracking-issue', statusNote('this issue')],
])

export function isSelfDrivingStatusNoteEnabled(flags: EvaluatedFlags | undefined): boolean {
    return (
        (process.env.NODE_ENV === 'development' || process.env.NODE_ENV === 'test') &&
        flags?.[MCP_GUIDANCE_SELF_DRIVING_ACTIVATION_FLAG] === true
    )
}

// The key holds the credential so that a caller who pins a project ID it cannot read gets no status from another caller's lookup.
function statusKey(context: Context, projectId: string): string {
    const identity = createHash('sha256')
        .update(JSON.stringify([context.api.config.baseUrl, projectId, context.api.config.apiToken]))
        .digest('base64url')
    return `mcp:sd-status-note:{${identity}}`
}

async function lookupNotStarted(redis: RedisLike, context: Context, signal: AbortSignal): Promise<boolean | undefined> {
    try {
        const projectId = String(await context.stateManager.getProjectId())
        const key = statusKey(context, projectId)
        const cached = await redis.get(key)
        if (cached === 'not_started' || cached === 'other') {
            return cached === 'not_started'
        }
        const notStarted = await fetchSelfDrivingSetupNotStarted(context, projectId, signal)
        if (notStarted === undefined) {
            return undefined
        }
        await redis.set(key, notStarted ? 'not_started' : 'other', 'EX', STATUS_TTL_SECONDS)
        return notStarted
    } catch {
        return undefined
    }
}

async function lookupNotStartedWithinBudget(redis: RedisLike, context: Context): Promise<boolean | undefined> {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    const timeout = new Promise<undefined>((resolve) => {
        timer = setTimeout(() => {
            controller.abort()
            resolve(undefined)
        }, LOOKUP_BUDGET_MS)
    })
    try {
        return await Promise.race([lookupNotStarted(redis, context, controller.signal), timeout])
    } finally {
        clearTimeout(timer)
    }
}

function withDescription(tool: Tool<ZodObjectAny>, description: string): Tool<ZodObjectAny> {
    // Copy property descriptors rather than spread, because a spread runs the lazy `schema` getter and builds the schema.
    return Object.create(Object.getPrototypeOf(tool), {
        ...Object.getOwnPropertyDescriptors(tool),
        description: { value: description, enumerable: true, writable: true, configurable: true },
    })
}

/**
 * Appends the Self-driving status note to the error tracking tool descriptions when the project has not started Self-driving setup.
 * The tools stay unchanged when the status is unknown, so a failed or slow lookup never adds the note.
 */
export async function withSelfDrivingStatusNotes(
    redis: RedisLike,
    context: Context,
    flags: EvaluatedFlags | undefined,
    tools: Tool<ZodObjectAny>[]
): Promise<Tool<ZodObjectAny>[]> {
    if (
        !isSelfDrivingStatusNoteEnabled(flags) ||
        !tools.some(({ name }) => name === STATUS_TOOL) ||
        !tools.some(({ name }) => STATUS_NOTES.has(name))
    ) {
        return tools
    }
    if ((await lookupNotStartedWithinBudget(redis, context)) !== true) {
        return tools
    }
    return tools.map((tool) => {
        const note = STATUS_NOTES.get(tool.name)
        return note ? withDescription(tool, `${tool.description}\n\n${note}`) : tool
    })
}
