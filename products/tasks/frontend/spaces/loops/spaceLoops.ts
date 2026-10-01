import { describeCron as describeAnyCron } from 'lib/cron'
import { dayjs } from 'lib/dayjs'
import { isObject, isString } from 'lib/utils/guards'

import type { HogFlowMinimalApi, HogFlowScheduleApi } from 'products/workflows/frontend/generated/api.schemas'
import {
    buildSummary,
    parseRRuleToState,
} from 'products/workflows/frontend/Workflows/hogflows/steps/components/rrule-helpers'

import type { LoopDTOApi, LoopRunDTOApi, LoopTriggerDTOApi, TaskListItemApi } from '../../generated/api.schemas'
import { RUN_STATUSES, SpaceFeedStatus, spaceFeedStatus } from '../spaceFeedStatus'
import type { TaskAvatarUser } from '../TaskUserAvatar'

/** One loop of a space, the same for a loop from the loops API and a loop stored as a workflow. */
export interface SpaceLoop {
    id: string
    name: string
    description: string
    enabled: boolean
    status: SpaceFeedStatus
    /** The first trigger, short enough for a table cell. */
    trigger: string
    /** Every trigger, with its cadence where the source holds one. */
    triggers: string[]
    lastRunAt: string | null
    lastRunFailed: boolean
    instructions: string
    model: string
    reasoningEffort: string | null
    repositories: string[]
    createdBy: TaskAvatarUser | null
    notifications: string[]
    /** A run can start now. A workflow runs on demand only when a schedule or a manual trigger starts it. */
    canRunNow: boolean
}

export interface SpaceLoopRun {
    id: string
    taskId: string
    title: string | null
    /** Null while a local run is still going, the same as the space feed shows it. */
    status: SpaceFeedStatus | null
    startedAt: string
    error: string | null
}

/** The fields of a loop workflow the mapping reads. The list serves no schedules, the detail does. */
export interface SpaceLoopHogFlow {
    id: string
    name?: string | null
    description?: string
    status?: HogFlowMinimalApi['status']
    actions: unknown
    created_by?: HogFlowMinimalApi['created_by'] | null
    last_run?: HogFlowMinimalApi['last_run']
    schedules?: readonly HogFlowScheduleApi[]
}

// pinned: PostHog Desktop writes these ids into a loop's workflow, so they must match `loopHogFlowMapping.ts`.
const CREATE_TASK_TEMPLATE_ID = 'template-posthog-create-task'
const SLACK_TEMPLATE_ID = 'template-slack'

// pinned: the event names behind the trigger shapes the building-loops skill creates.
const GITHUB_EVENT = '$github_event_received'
const SLACK_EVENT = '$slack_message_received'

const WEEKDAYS: Record<string, string> = {
    SU: 'Sundays',
    MO: 'Mondays',
    TU: 'Tuesdays',
    WE: 'Wednesdays',
    TH: 'Thursdays',
    FR: 'Fridays',
    SA: 'Saturdays',
}
const CRON_WEEKDAYS = ['SU', 'MO', 'TU', 'WE', 'TH', 'FR', 'SA']

function loopStatus(enabled: boolean, disabledReason: string | null, lastRunFailed: boolean): SpaceFeedStatus {
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

function readString(value: unknown): string {
    return isString(value) ? value : ''
}

function inputValue(inputs: Record<string, unknown>, key: string): unknown {
    const input = inputs[key]
    return isObject(input) ? input.value : undefined
}

function clockTime(hour: number, minute: number): string {
    return dayjs().hour(hour).minute(minute).format('h:mm A')
}

/** The cadence of a loop API schedule, for the simple cron shapes Desktop's form writes. */
function describeCron(cron: string, timezone: string): string {
    const [minute, hour, dayOfMonth, month, dayOfWeek] = cron.trim().split(/\s+/)
    const zone = timezone ? ` (${timezone})` : ''
    const m = Number(minute)
    const h = Number(hour)
    if (dayOfMonth !== '*' || month !== '*' || !Number.isInteger(m)) {
        return `${describeAnyCron(cron) ?? cron}${zone}`
    }
    if (hour === '*' && dayOfWeek === '*') {
        return 'Every hour'
    }
    if (!Number.isInteger(h)) {
        return `${describeAnyCron(cron) ?? cron}${zone}`
    }
    const time = clockTime(h, m)
    if (dayOfWeek === '*') {
        return `Every day at ${time}${zone}`
    }
    if (dayOfWeek === '1-5') {
        return `Weekdays at ${time}${zone}`
    }
    const day = CRON_WEEKDAYS[Number(dayOfWeek)]
    return day ? `${WEEKDAYS[day]} at ${time}${zone}` : `${describeAnyCron(cron) ?? cron}${zone}`
}

/** The cadence of a workflow schedule, for the rrule presets the building-loops skill writes. */
function describeRRule(schedule: HogFlowScheduleApi): string {
    const parts = Object.fromEntries(schedule.rrule.split(';').map((part) => part.split('=') as [string, string]))
    const start = schedule.timezone ? dayjs(schedule.starts_at).tz(schedule.timezone) : dayjs(schedule.starts_at)
    const time = start.format(schedule.timezone ? 'h:mm A z' : 'h:mm A')
    if (parts.COUNT === '1') {
        return `Once · ${start.format('LLL')}`
    }
    if (parts.FREQ === 'HOURLY') {
        return 'Every hour'
    }
    if (parts.FREQ === 'DAILY') {
        return `Every day at ${time}`
    }
    if (parts.FREQ === 'WEEKLY' && parts.BYDAY === 'MO,TU,WE,TH,FR') {
        return `Weekdays at ${time}`
    }
    if (parts.FREQ === 'WEEKLY' && WEEKDAYS[parts.BYDAY]) {
        return `${WEEKDAYS[parts.BYDAY]} at ${time}`
    }
    return buildSummary(parseRRuleToState(schedule.rrule), schedule.starts_at, schedule.timezone)
}

function describeLoopTrigger(trigger: LoopTriggerDTOApi): string {
    const config = trigger.config
    if (trigger.type === 'schedule') {
        if (readString(config.run_at)) {
            return `Once · ${dayjs(readString(config.run_at)).format('LLL')}`
        }
        const cron = readString(config.cron_expression)
        return cron ? describeCron(cron, readString(config.timezone)) : 'No schedule set'
    }
    if (trigger.type === 'github') {
        const events = Array.isArray(config.events) ? config.events.filter((e) => typeof e === 'string') : []
        const repository = readString(config.repository) || 'a repository'
        return `GitHub · ${repository}${events.length ? ` (${events.join(', ')})` : ''}`
    }
    return 'API'
}

function hogFlowActions(flow: SpaceLoopHogFlow): { type: unknown; config: Record<string, unknown> }[] {
    if (!Array.isArray(flow.actions)) {
        return []
    }
    return flow.actions.filter(isObject).map((action) => ({
        type: action.type,
        config: isObject(action.config) ? action.config : {},
    }))
}

function hogFlowTaskInputs(flow: SpaceLoopHogFlow): Record<string, unknown> {
    const task = hogFlowActions(flow).find(
        ({ type, config }) => type === 'function' && config.template_id === CREATE_TASK_TEMPLATE_ID
    )
    return task && isObject(task.config.inputs) ? task.config.inputs : {}
}

/** The space a loop workflow files its runs in. The task step holds it as `<space id>|<space name>`. */
function hogFlowSpaceId(flow: SpaceLoopHogFlow): string | null {
    return readString(inputValue(hogFlowTaskInputs(flow), 'channel')).split('|')[0] || null
}

function propertyValue(filters: Record<string, unknown>, key: string): string {
    const properties = Array.isArray(filters.properties) ? filters.properties.filter(isObject) : []
    const value = properties.find((property) => property.key === key)?.value
    return Array.isArray(value) ? value.filter((item) => typeof item === 'string').join(', ') : readString(value)
}

/** What starts a loop workflow, and whether a person can start a run by hand. */
function hogFlowTrigger(flow: SpaceLoopHogFlow): { summary: string; detail: string; canRunNow: boolean } {
    const config = hogFlowActions(flow).find(({ type }) => type === 'trigger')?.config
    if (!config) {
        return { summary: 'No trigger', detail: 'No trigger', canRunNow: false }
    }
    if (config.type === 'schedule') {
        const schedule = flow.schedules?.[0]
        const detail = flow.schedules ? (schedule ? describeRRule(schedule) : 'No schedule set') : 'Schedule'
        return { summary: detail, detail, canRunNow: true }
    }
    if (config.type === 'manual') {
        return { summary: 'Manual', detail: 'Manual', canRunNow: true }
    }
    const filters = isObject(config.filters) ? config.filters : {}
    const event = Array.isArray(filters.events) && isObject(filters.events[0]) ? readString(filters.events[0].id) : ''
    if (config.type === 'internal-event' && event === GITHUB_EVENT) {
        const repository = propertyValue(filters, 'repository') || 'a repository'
        const eventType = propertyValue(filters, 'event_type')
        return {
            summary: 'GitHub event',
            detail: `GitHub · ${repository}${eventType ? ` (${eventType})` : ''}`,
            canRunNow: false,
        }
    }
    if (config.type === 'internal-event' && event === SLACK_EVENT) {
        return { summary: 'Slack message', detail: 'Slack message', canRunNow: false }
    }
    if (config.type === 'event') {
        return {
            summary: 'PostHog event',
            detail: event ? `PostHog event · ${event}` : 'PostHog event',
            canRunNow: false,
        }
    }
    return { summary: 'Custom trigger', detail: 'Custom trigger', canRunNow: false }
}

function hogFlowNotifications(flow: SpaceLoopHogFlow): string[] {
    const inputs = hogFlowTaskInputs(flow)
    const notifications = hogFlowActions(flow).flatMap(({ type, config }) =>
        type === 'function_email' ? ['Email'] : config.template_id === SLACK_TEMPLATE_ID ? ['Slack'] : []
    )
    return inputValue(inputs, 'reply_in_slack_thread') === true
        ? [...notifications, 'Slack thread reply']
        : notifications
}

export function spaceLoopFromLoop(loop: LoopDTOApi): SpaceLoop {
    const lastRunFailed = loop.consecutive_failures > 0 || loop.last_run_status === 'failed'
    const triggers = loop.triggers.map(
        (trigger) => `${describeLoopTrigger(trigger)}${trigger.enabled ? '' : ' (disabled)'}`
    )
    const [first, ...rest] = loop.triggers
    const summary = first
        ? first.type === 'schedule'
            ? describeLoopTrigger(first)
            : first.type === 'github'
              ? 'GitHub event'
              : 'API'
        : 'No trigger'
    return {
        id: loop.id,
        name: loop.name,
        description: loop.description.trim(),
        enabled: loop.enabled,
        status: loopStatus(loop.enabled, loop.disabled_reason, lastRunFailed),
        trigger: rest.length ? `${summary} +${rest.length} more` : summary,
        triggers,
        lastRunAt: loop.last_run_at,
        lastRunFailed,
        instructions: loop.instructions,
        model: loop.model,
        reasoningEffort: loop.reasoning_effort,
        repositories: loop.repositories.map((repository) => repository.full_name),
        createdBy: null,
        notifications: (['slack', 'email', 'push'] as const)
            .filter((channel) => loop.notifications[channel]?.enabled)
            .map((channel) => ({ slack: 'Slack', email: 'Email', push: 'Push' })[channel]),
        canRunNow: true,
    }
}

export function spaceLoopFromHogFlow(flow: SpaceLoopHogFlow): SpaceLoop {
    const inputs = hogFlowTaskInputs(flow)
    const model = inputValue(inputs, 'model')
    const repository = readString(inputValue(inputs, 'repository'))
    const trigger = hogFlowTrigger(flow)
    const enabled = flow.status === 'active'
    const lastRunFailed = flow.last_run?.status === 'failed'
    return {
        id: flow.id,
        name: flow.name ?? '',
        description: (flow.description ?? '').trim(),
        enabled,
        status: loopStatus(enabled, null, lastRunFailed),
        trigger: trigger.summary,
        triggers: [trigger.detail],
        lastRunAt: flow.last_run?.ran_at ?? null,
        lastRunFailed,
        instructions: readString(inputValue(inputs, 'prompt')),
        model: isObject(model) ? readString(model.model) : '',
        reasoningEffort: isObject(model) ? readString(model.reasoning_effort) || null : null,
        repositories: repository ? [repository] : [],
        createdBy: flow.created_by
            ? {
                  first_name: flow.created_by.first_name ?? '',
                  last_name: flow.created_by.last_name ?? '',
                  email: flow.created_by.email,
                  uuid: flow.created_by.uuid,
              }
            : null,
        notifications: hogFlowNotifications(flow),
        canRunNow: trigger.canRunNow,
    }
}

export function spaceLoopsFromLoops(loops: LoopDTOApi[], spaceId: string): SpaceLoop[] {
    return loops.filter((loop) => loop.context_target?.channel_id === spaceId).map(spaceLoopFromLoop)
}

export function spaceLoopsFromHogFlows(flows: SpaceLoopHogFlow[], spaceId: string): SpaceLoop[] {
    return (
        flows
            // Archived workflows come back from the list too, and PostHog Desktop hides them.
            .filter((flow) => flow.status !== 'archived' && hogFlowSpaceId(flow) === spaceId)
            .map(spaceLoopFromHogFlow)
    )
}

/** A loop after someone pauses or resumes it, before the next load. */
export function spaceLoopWithEnabled(loop: SpaceLoop, enabled: boolean): SpaceLoop {
    return { ...loop, enabled, status: loopStatus(enabled, null, loop.lastRunFailed) }
}

export function spaceLoopRunFromLoopRun(run: LoopRunDTOApi): SpaceLoopRun {
    return {
        id: run.id,
        taskId: run.task_id,
        title: null,
        status: RUN_STATUSES[run.status] ?? RUN_STATUSES.not_started,
        startedAt: run.created_at,
        error: run.error_message,
    }
}

/** A task a loop workflow created, as one run. A task with no run yet lists as not started. */
export function spaceLoopRunFromTask(task: TaskListItemApi): SpaceLoopRun {
    const run = task.latest_run ?? null
    return {
        id: run?.id ?? task.id,
        taskId: task.id,
        title: task.title || null,
        status: spaceFeedStatus(run),
        startedAt: run?.created_at ?? task.created_at ?? '',
        error: run?.error_message ?? null,
    }
}

const RUN_BLOCKED_MESSAGES: Record<string, string> = {
    deduped: 'An identical run was already started for this trigger.',
    overlap_skipped: 'The previous run is still in progress.',
    rate_capped: 'This loop reached its daily run cap.',
    team_rate_capped: 'Your team reached its daily loop run cap.',
    disabled: 'This loop or its trigger is paused.',
    gate_blocked: 'Your organization reached its usage limit.',
    owner_inactive: 'The loop owner’s account can no longer start runs.',
    owner_changed: 'The loop’s owner changed while the run was starting. Try again.',
}

/** Why the loops API did not start a run, in words a person can act on. */
export function spaceLoopRunBlockedMessage(reason: string): string {
    return RUN_BLOCKED_MESSAGES[reason] ?? 'The run didn’t start. Try again.'
}

/** The name a person sees for a loop. Search still matches the stored name. */
export function spaceLoopName(loop: Pick<SpaceLoop, 'name'>): string {
    return loop.name || 'Untitled loop'
}

export function filterSpaceLoops(loops: SpaceLoop[], search: string, hidePaused: boolean): SpaceLoop[] {
    const query = search.trim().toLowerCase()
    return loops.filter(
        (loop) =>
            (!hidePaused || loop.enabled) &&
            (!query || [loop.name, loop.description].some((value) => value.toLowerCase().includes(query)))
    )
}

/**
 * The first message of a session that builds a loop for this space. The agent creates the loop through the
 * PostHog MCP, so the message names the tools for the backend that stores loops for this project.
 */
export function spaceLoopBuilderPrompt(
    space: { id: string; name: string },
    workflowBacked: boolean,
    request: string
): string {
    const attach = workflowBacked
        ? `Read the building-loops skill and follow it. Set the \`channel\` input on the "Create AI task" step to ${JSON.stringify(`${space.id}|${space.name}`)}, so the runs show in this space's feed.`
        : `Build it with the PostHog MCP loops tools, and show it to me with \`loops-review\` before you create it. Make it a team loop and set \`context_target\` to ${JSON.stringify({ channel_id: space.id, name: space.name, outputs: { post_to_feed: true } })}, so the runs show in this space's feed.`
    return `Help me create a loop for this space: ${request.trim()}\n\nA loop runs an AI task each time its trigger fires. ${attach} Ask me about anything you cannot infer, and ask me before you create or enable anything.`
}
