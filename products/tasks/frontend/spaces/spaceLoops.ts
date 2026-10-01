import type { HogFlowMinimalApi } from 'products/workflows/frontend/generated/api.schemas'

import type { LoopDTOApi } from '../generated/api.schemas'

export type SpaceLoopStatusVariant = 'default' | 'destructive' | 'success'

export interface SpaceLoopStatus {
    label: string
    variant: SpaceLoopStatusVariant
}

/** One row of a space's Loops tab, the same for a loop from the loops API and a loop stored as a workflow. */
export interface SpaceLoop {
    id: string
    name: string
    description: string
    status: SpaceLoopStatus
    trigger: string
    lastRunAt: string | null
    lastRunFailed: boolean
}

// pinned: PostHog Desktop writes these ids into a loop's workflow, so they must match `loopHogFlowMapping.ts`.
const CREATE_TASK_TEMPLATE_ID = 'template-posthog-create-task'
const TASK_SPACE_INPUT = 'channel'

const TRIGGER_LABELS: Record<string, string> = {
    schedule: 'Schedule',
    github: 'GitHub event',
    api: 'API',
}

// pinned: the trigger shapes the building-loops skill creates. GitHub and Slack both arrive as internal events.
const HOG_FLOW_TRIGGER_LABELS: Record<string, string> = {
    schedule: 'Schedule',
    event: 'PostHog event',
    manual: 'Manual',
}
const HOG_FLOW_INTERNAL_EVENT_LABELS: Record<string, string> = {
    $github_event_received: 'GitHub event',
    $slack_message_received: 'Slack message',
}

function loopStatus(enabled: boolean, disabledReason: string | null, lastRunFailed: boolean): SpaceLoopStatus {
    if (!enabled) {
        if (disabledReason === 'usage_limited') {
            return { label: 'Paused: usage limit', variant: 'destructive' }
        }
        return disabledReason
            ? { label: 'Auto-paused', variant: 'destructive' }
            : { label: 'Paused', variant: 'default' }
    }
    return lastRunFailed ? { label: 'Failing', variant: 'destructive' } : { label: 'Active', variant: 'success' }
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function hogFlowActionConfigs(flow: HogFlowMinimalApi): { type: unknown; config: Record<string, unknown> }[] {
    if (!Array.isArray(flow.actions)) {
        return []
    }
    return flow.actions.filter(isRecord).map((action) => ({
        type: action.type,
        config: isRecord(action.config) ? action.config : {},
    }))
}

/** The space a loop workflow files its runs in. The task step holds it as `<space id>|<space name>`. */
function hogFlowSpaceId(flow: HogFlowMinimalApi): string | null {
    const task = hogFlowActionConfigs(flow).find(
        ({ type, config }) => type === 'function' && config.template_id === CREATE_TASK_TEMPLATE_ID
    )
    const inputs = task && isRecord(task.config.inputs) ? task.config.inputs : {}
    const input = inputs[TASK_SPACE_INPUT]
    const value = isRecord(input) && typeof input.value === 'string' ? input.value : ''
    return value.split('|')[0] || null
}

function hogFlowTrigger(flow: HogFlowMinimalApi): string {
    const config = hogFlowActionConfigs(flow).find(({ type }) => type === 'trigger')?.config
    if (!config) {
        return 'No trigger'
    }
    if (config.type === 'internal-event') {
        const filters = isRecord(config.filters) ? config.filters : {}
        const event = Array.isArray(filters.events) && isRecord(filters.events[0]) ? filters.events[0].id : null
        return (typeof event === 'string' && HOG_FLOW_INTERNAL_EVENT_LABELS[event]) || 'Internal event'
    }
    return (typeof config.type === 'string' && HOG_FLOW_TRIGGER_LABELS[config.type]) || 'Custom trigger'
}

function loopTrigger(loop: LoopDTOApi): string {
    const [first, ...rest] = loop.triggers
    if (!first) {
        return 'No trigger'
    }
    const label = TRIGGER_LABELS[first.type] ?? 'API'
    return rest.length ? `${label} +${rest.length} more` : label
}

export function spaceLoopsFromLoops(loops: LoopDTOApi[], spaceId: string): SpaceLoop[] {
    return loops
        .filter((loop) => loop.context_target?.channel_id === spaceId)
        .map((loop) => {
            const lastRunFailed = loop.consecutive_failures > 0 || loop.last_run_status === 'failed'
            return {
                id: loop.id,
                name: loop.name,
                description: loop.description.trim(),
                status: loopStatus(loop.enabled, loop.disabled_reason, lastRunFailed),
                trigger: loopTrigger(loop),
                lastRunAt: loop.last_run_at,
                lastRunFailed,
            }
        })
}

export function spaceLoopsFromHogFlows(flows: HogFlowMinimalApi[], spaceId: string): SpaceLoop[] {
    return (
        flows
            // Archived workflows come back from the list too, and PostHog Desktop hides them.
            .filter((flow) => flow.status !== 'archived' && hogFlowSpaceId(flow) === spaceId)
            .map((flow) => {
                const lastRunFailed = flow.last_run?.status === 'failed'
                return {
                    id: flow.id,
                    name: flow.name ?? '',
                    description: flow.description.trim(),
                    status: loopStatus(flow.status === 'active', null, lastRunFailed),
                    trigger: hogFlowTrigger(flow),
                    lastRunAt: flow.last_run?.ran_at ?? null,
                    lastRunFailed,
                }
            })
    )
}

/**
 * The first message of a session that builds a loop for this space. The agent creates the loop through the
 * PostHog MCP, so the message names the tools for the backend that stores loops for this project.
 */
export function spaceLoopBuilderPrompt(space: { id: string; name: string }, workflowBacked: boolean): string {
    const attach = workflowBacked
        ? `Read the building-loops skill and follow it. Set the \`channel\` input on the "Create AI task" step to ${JSON.stringify(`${space.id}|${space.name}`)}, so the runs show in this space's feed.`
        : `Build it with the PostHog MCP loops tools, and show it to me with \`loops-review\` before you create it. Make it a team loop and set \`context_target\` to ${JSON.stringify({ channel_id: space.id, name: space.name, outputs: { post_to_feed: true } })}, so the runs show in this space's feed.`
    return `Help me create a loop for this space. A loop runs an AI task each time its trigger fires. ${attach} Ask me before you create or enable anything.\n\n\nUser input:\n- What should the loop do:\n- When should it run (for example a schedule or a GitHub event):`
}
