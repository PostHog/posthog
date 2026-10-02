import { isObject, isString } from 'lib/utils/guards'

import type { HogFlowApi, HogFlowScheduleApi } from 'products/workflows/frontend/generated/api.schemas'

import {
    type LoopContextTargetDraft,
    type LoopFormValues,
    type LoopGithubTriggerConfig,
    type LoopGithubTriggerEvent,
    type LoopScheduleTriggerConfig,
    type LoopTriggerDraft,
    defaultLoopContextOutputs,
    emptyLoopFormValues,
} from './loopFormValues'
import {
    type HogFlowScheduleWrite,
    hogFlowScheduleToScheduleConfig,
    scheduleConfigToHogFlowSchedule,
} from './loopSchedule'

// Mirrors PostHog Desktop's `loopHogFlowMapping.ts`: a loop stored as a workflow is one trigger, one "Create AI
// task" step, an optional Slack or email step, and an exit.

// pinned: PostHog Desktop and the building-loops skill write these ids and event names into a loop's workflow.
export const CREATE_TASK_TEMPLATE_ID = 'template-posthog-create-task'
export const SLACK_TEMPLATE_ID = 'template-slack'
export const GITHUB_EVENT_RECEIVED_EVENT = '$github_event_received'
export const LOOPS_ORIGIN_PRODUCT = 'loops'

const TRIGGER_ACTION_ID = 'trigger'
const TASK_ACTION_ID = 'create_task'
const EXIT_ACTION_ID = 'exit'

const LOOP_GITHUB_EVENTS: ReadonlySet<string> = new Set<LoopGithubTriggerEvent>([
    'issues',
    'issue_comment',
    'pull_request',
    'push',
])

/** Task inputs the form owns. The form keeps any other input on the step as it is. */
const MANAGED_TASK_INPUTS: ReadonlySet<string> = new Set(['prompt', 'repository', 'model', 'skills', 'channel'])

type Json = Record<string, unknown>

/** The workflow fields the mapping reads. The detail response carries all of them. */
export interface LoopHogFlowSource {
    id: string
    name?: string | null
    description?: string
    updated_at?: string
    actions?: unknown
    edges?: unknown
    schedules?: readonly Pick<HogFlowScheduleApi, 'id' | 'rrule' | 'starts_at' | 'timezone'>[]
    /** Staged edits from the workflow editor that the live graph does not show yet. */
    draft?: unknown
}

export interface LoopHogFlowWrite {
    flow: {
        name: string
        description: string
        status: 'active' | 'draft'
        origin_product: string
        exit_condition: string
        actions: LoopAction[]
        edges: { from: string; to: string; type: 'continue' }[]
    }
    /** Null for a GitHub-triggered loop, which has no schedule row. */
    schedule: HogFlowScheduleWrite | null
}

/** Thrown when the form holds a trigger a workflow cannot carry. Form validation stops this first. */
export class UnsupportedLoopShapeError extends Error {
    constructor(message: string) {
        super(message)
        this.name = 'UnsupportedLoopShapeError'
    }
}

interface LoopAction {
    id: string
    name: string
    type: 'trigger' | 'function' | 'function_email' | 'exit'
    config: Json
    [key: string]: unknown
}

function inputValue(inputs: Json, key: string): unknown {
    const input = inputs[key]
    return isObject(input) ? input.value : undefined
}

function readString(value: unknown): string {
    return isString(value) ? value : ''
}

function exactFilter(key: string, value: string[]): Json {
    return { key, value, operator: 'exact', type: 'event' }
}

function githubTriggerConfig(config: LoopGithubTriggerConfig): Json {
    // Only people with write access can start a run: the event body reaches an AI task that acts with the
    // owner's access, so a drive-by issue or comment must not steer it. The loops webhook applied the same gate.
    const properties = [
        exactFilter('repository', [config.repository]),
        exactFilter('event_type', config.events),
        exactFilter('actor_access', ['write']),
    ]
    const actions = config.filters?.actions ?? []
    if (actions.length) {
        properties.push(exactFilter('action', actions))
    }
    return {
        type: 'internal-event',
        filters: {
            source: 'internal-events',
            events: [{ id: GITHUB_EVENT_RECEIVED_EVENT, type: 'events' }],
            properties,
        },
    }
}

function triggerFromForm(values: LoopFormValues): { config: Json; schedule: HogFlowScheduleWrite | null } {
    const enabledTriggers = values.triggers.filter((trigger) => trigger.enabled)
    if (enabledTriggers.length !== 1) {
        throw new UnsupportedLoopShapeError('A loop stored as a workflow has exactly one trigger.')
    }
    const [trigger] = enabledTriggers
    if (trigger.type === 'schedule') {
        const schedule = scheduleConfigToHogFlowSchedule(trigger.config as LoopScheduleTriggerConfig)
        if (!schedule) {
            throw new UnsupportedLoopShapeError('This schedule is not one of the supported presets.')
        }
        return { config: { type: 'schedule' }, schedule }
    }
    if (trigger.type === 'github') {
        return { config: githubTriggerConfig(trigger.config as LoopGithubTriggerConfig), schedule: null }
    }
    throw new UnsupportedLoopShapeError('A loop stored as a workflow cannot use an API trigger.')
}

/** The space as the task step holds it: the space id, then the name after a pipe. */
function spaceInputValue(contextTarget: LoopContextTargetDraft): string {
    return contextTarget.name ? `${contextTarget.spaceId}|${contextTarget.name}` : contextTarget.spaceId
}

function taskInputs(values: LoopFormValues): Json {
    const inputs: Json = { prompt: { value: values.instructions.trim() } }
    const repository = values.repositories[0]?.full_name
    if (repository) {
        inputs.repository = { value: repository }
    }
    const model = values.model.trim()
    if (model) {
        inputs.model = {
            value: { model, ...(values.reasoningEffort ? { reasoning_effort: values.reasoningEffort } : {}) },
        }
    }
    if (values.teamSkills.length) {
        inputs.skills = { value: [...values.teamSkills] }
    }
    if (values.contextTarget) {
        inputs.channel = { value: spaceInputValue(values.contextTarget) }
    }
    return inputs
}

function isLoopAction(value: unknown): value is LoopAction {
    return (
        isObject(value) &&
        isString(value.id) &&
        isString(value.name) &&
        isObject(value.config) &&
        (value.type === 'trigger' ||
            value.type === 'function' ||
            value.type === 'function_email' ||
            value.type === 'exit')
    )
}

function isNotifyAction(action: LoopAction): boolean {
    return action.type === 'function_email' || action.config.template_id === SLACK_TEMPLATE_ID
}

interface ParsedLoopActions {
    trigger: Json
    taskInputs: Json
    actions: { trigger: LoopAction; task: LoopAction; notify: LoopAction | null; exit: LoopAction | null }
}

/** The steps of a loop-shaped graph, or null when the graph holds a step the loop form did not put there. */
function parseLoopActions(actions: unknown): ParsedLoopActions | null {
    if (!Array.isArray(actions)) {
        return null
    }
    let trigger: LoopAction | null = null
    let task: LoopAction | null = null
    let notify: LoopAction | null = null
    let exit: LoopAction | null = null
    for (const action of actions) {
        if (!isLoopAction(action)) {
            return null
        }
        if (action.type === 'trigger') {
            if (trigger) {
                return null
            }
            trigger = action
        } else if (action.type === 'function' && action.config.template_id === CREATE_TASK_TEMPLATE_ID) {
            if (task) {
                return null
            }
            task = action
        } else if (action.type !== 'exit') {
            if (notify || !task || !isNotifyAction(action)) {
                return null
            }
            notify = action
        } else {
            if (exit) {
                return null
            }
            exit = action
        }
    }
    if (!trigger || !task) {
        return null
    }
    return {
        trigger: trigger.config,
        taskInputs: isObject(task.config.inputs) ? task.config.inputs : {},
        actions: { trigger, task, notify, exit },
    }
}

/** Whether the edges are the straight line the form draws. A branch would be lost when a save rewrites them. */
function hasLoopShapedEdges(edges: unknown, actions: ParsedLoopActions['actions']): boolean {
    if (edges === undefined || edges === null) {
        return true
    }
    if (!Array.isArray(edges)) {
        return false
    }
    const chain = [
        actions.trigger,
        actions.task,
        ...(actions.notify ? [actions.notify] : []),
        ...(actions.exit ? [actions.exit] : []),
    ]
    const expected = chain.slice(1).map((step, index) => `${chain[index].id}>${step.id}`)
    const actual = edges.map((edge) => (isObject(edge) && edge.type === 'continue' ? `${edge.from}>${edge.to}` : '?'))
    return actual.length === expected.length && expected.every((edge) => actual.includes(edge))
}

function filterValues(filter: Json): string[] | null {
    if (filter.operator !== 'exact') {
        return null
    }
    const raw = Array.isArray(filter.value) ? filter.value : [filter.value]
    return raw.every(isString) ? raw : null
}

function githubConfigFromTrigger(trigger: Json): LoopGithubTriggerConfig | null {
    if (!isObject(trigger.filters)) {
        return null
    }
    const { events, properties } = trigger.filters
    const subscribed =
        Array.isArray(events) &&
        events.length === 1 &&
        isObject(events[0]) &&
        events[0].id === GITHUB_EVENT_RECEIVED_EVENT
    if (!subscribed) {
        return null
    }
    let repository: string | null = null
    let eventTypes: string[] | null = null
    let actions: string[] = []
    let trustedActorsOnly = false
    for (const property of Array.isArray(properties) ? properties : []) {
        const values = isObject(property) ? filterValues(property) : null
        if (!isObject(property) || !values) {
            return null
        }
        switch (property.key) {
            case 'actor_access':
                if (values.length !== 1 || values[0] !== 'write') {
                    return null
                }
                trustedActorsOnly = true
                break
            case 'repository':
                if (values.length !== 1) {
                    return null
                }
                repository = values[0]
                break
            case 'event_type':
                if (!values.every((value) => LOOP_GITHUB_EVENTS.has(value))) {
                    return null
                }
                eventTypes = values
                break
            case 'action':
                actions = values
                break
            default:
                return null
        }
    }
    // A trigger open to anyone is outside what a loop offers. Editing it here would narrow it to write access.
    if (!repository || !eventTypes || eventTypes.length !== 1 || !trustedActorsOnly) {
        return null
    }
    return {
        github_integration_id: 0,
        repository,
        events: eventTypes as LoopGithubTriggerEvent[],
        ...(actions.length ? { filters: { actions } } : {}),
    }
}

function loopTrigger(flow: LoopHogFlowSource, parsed: ParsedLoopActions): LoopTriggerDraft | null {
    if (parsed.trigger.type === 'schedule') {
        const schedule = flow.schedules?.[0]
        // The list leaves schedules out. Only the detail decides whether the schedule fits the form.
        const config = schedule ? hogFlowScheduleToScheduleConfig(schedule) : {}
        return config
            ? { key: TRIGGER_ACTION_ID, id: TRIGGER_ACTION_ID, type: 'schedule', enabled: true, config }
            : null
    }
    if (parsed.trigger.type === 'internal-event') {
        const config = githubConfigFromTrigger(parsed.trigger)
        return config ? { key: TRIGGER_ACTION_ID, id: TRIGGER_ACTION_ID, type: 'github', enabled: true, config } : null
    }
    return null
}

/** Whether the form can edit this workflow without dropping something someone built in the workflow editor. */
export function isLoopShapedHogFlow(flow: LoopHogFlowSource): boolean {
    // A save from here would land under staged edits, and the next publish would overwrite it.
    if (flow.draft !== undefined && flow.draft !== null) {
        return false
    }
    const parsed = parseLoopActions(flow.actions)
    return parsed !== null && hasLoopShapedEdges(flow.edges, parsed.actions) && loopTrigger(flow, parsed) !== null
}

/** The workflow as form values. Call it only for a loop-shaped workflow. */
export function hogFlowToFormValues(flow: LoopHogFlowSource): LoopFormValues {
    const parsed = parseLoopActions(flow.actions)
    const trigger = parsed ? loopTrigger(flow, parsed) : null
    const inputs = parsed?.taskInputs ?? {}
    const model = inputValue(inputs, 'model')
    const repository = readString(inputValue(inputs, 'repository'))
    const reasoningEffort = isObject(model) ? readString(model.reasoning_effort) : ''
    const skills = inputValue(inputs, 'skills')
    const [spaceId, ...rest] = readString(inputValue(inputs, 'channel')).split('|')
    return {
        ...emptyLoopFormValues(),
        name: flow.name ?? '',
        description: flow.description ?? '',
        visibility: 'team',
        instructions: readString(inputValue(inputs, 'prompt')),
        model: isObject(model) ? readString(model.model) : '',
        reasoningEffort: (reasoningEffort || null) as LoopFormValues['reasoningEffort'],
        repositories: repository ? [{ github_integration_id: 0, full_name: repository }] : [],
        triggers: trigger ? [trigger] : [],
        contextTarget: spaceId ? { spaceId, name: rest.join('|'), outputs: defaultLoopContextOutputs() } : null,
        teamSkills: Array.isArray(skills) ? skills.filter(isString) : [],
    }
}

const DEFAULT_TRIGGER_ACTION: LoopAction = { id: TRIGGER_ACTION_ID, name: 'Trigger', type: 'trigger', config: {} }
const DEFAULT_TASK_ACTION: LoopAction = { id: TASK_ACTION_ID, name: 'Create AI task', type: 'function', config: {} }
const DEFAULT_EXIT_ACTION: LoopAction = {
    id: EXIT_ACTION_ID,
    name: 'Exit',
    type: 'exit',
    config: { reason: 'Task created' },
}

/**
 * The workflow a loop form saves as. On an edit, pass `existing`: the save then replaces only what the form owns
 * (the trigger config and the task inputs), so step names and settings from the workflow editor stay.
 */
export function formValuesToHogFlowWrite(
    values: LoopFormValues,
    options: { enabled: boolean; existing?: LoopHogFlowSource }
): LoopHogFlowWrite {
    const trigger = triggerFromForm(values)
    const existing = options.existing ? parseLoopActions(options.existing.actions) : null
    const triggerAction = existing?.actions.trigger ?? DEFAULT_TRIGGER_ACTION
    const taskAction = existing?.actions.task ?? DEFAULT_TASK_ACTION
    const notifyAction = existing?.actions.notify ?? null
    const exitAction = existing?.actions.exit ?? DEFAULT_EXIT_ACTION
    const preservedInputs = existing
        ? Object.fromEntries(Object.entries(existing.taskInputs).filter(([key]) => !MANAGED_TASK_INPUTS.has(key)))
        : {}
    const steps = [taskAction, ...(notifyAction ? [notifyAction] : []), exitAction]
    return {
        flow: {
            name: values.name.trim(),
            description: values.description.trim(),
            status: options.enabled ? 'active' : 'draft',
            origin_product: LOOPS_ORIGIN_PRODUCT,
            exit_condition: 'exit_only_at_end',
            actions: [
                { ...triggerAction, config: trigger.config },
                {
                    ...taskAction,
                    config: {
                        ...taskAction.config,
                        template_id: CREATE_TASK_TEMPLATE_ID,
                        inputs: { ...preservedInputs, ...taskInputs(values) },
                    },
                },
                ...(notifyAction ? [notifyAction] : []),
                exitAction,
            ],
            edges: [
                { from: triggerAction.id, to: taskAction.id, type: 'continue' },
                ...steps.slice(1).map((step, index) => ({
                    from: steps[index].id,
                    to: step.id,
                    type: 'continue' as const,
                })),
            ],
        },
        schedule: trigger.schedule,
    }
}

export type LoopHogFlowDetail = Pick<
    HogFlowApi,
    'id' | 'name' | 'description' | 'updated_at' | 'actions' | 'edges' | 'schedules' | 'draft' | 'status'
>
