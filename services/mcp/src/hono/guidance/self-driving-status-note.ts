import { createHash } from 'node:crypto'

import type { EvaluatedFlags } from '@/lib/posthog/flags'
import type { Context, Tool, ZodObjectAny } from '@/tools/types'

import type { RedisLike } from '../cache/RedisCache'
import { MCP_GUIDANCE_SELF_DRIVING_ACTIVATION_FLAG } from './rules'
import { fetchInboxOnboarding, isSelfDrivingActivated } from './self-driving-activation'

const STATUS_TOOL = 'self-driving-status-get'
const STATUS_TTL_SECONDS = 60
const LOOKUP_BUDGET_MS = 1000

function statusNote(subject: string): string {
    return `Self-driving can hold automatic investigation reports from agents on ${subject}. Call \`${STATUS_TOOL}\` once; when it is not active, tell the user and give them the activation link from that result.`
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

async function lookupActivated(redis: RedisLike, context: Context, signal: AbortSignal): Promise<boolean | undefined> {
    try {
        const projectId = String(await context.stateManager.getProjectId())
        const key = statusKey(context, projectId)
        const cached = await redis.get(key)
        if (cached === 'active' || cached === 'inactive') {
            return cached === 'active'
        }
        const onboarding = await fetchInboxOnboarding(context, projectId, signal)
        if (!onboarding) {
            return undefined
        }
        const activated = isSelfDrivingActivated(onboarding)
        await redis.set(key, activated ? 'active' : 'inactive', 'EX', STATUS_TTL_SECONDS)
        return activated
    } catch {
        return undefined
    }
}

async function lookupActivatedWithinBudget(redis: RedisLike, context: Context): Promise<boolean | undefined> {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    const timeout = new Promise<undefined>((resolve) => {
        timer = setTimeout(() => {
            controller.abort()
            resolve(undefined)
        }, LOOKUP_BUDGET_MS)
    })
    try {
        return await Promise.race([lookupActivated(redis, context, controller.signal), timeout])
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
 * Appends the Self-driving status note to the error tracking tool descriptions when the project has not activated Self-driving.
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
    if ((await lookupActivatedWithinBudget(redis, context)) !== false) {
        return tools
    }
    return tools.map((tool) => {
        const note = STATUS_NOTES.get(tool.name)
        return note ? withDescription(tool, `${tool.description}\n\n${note}`) : tool
    })
}
