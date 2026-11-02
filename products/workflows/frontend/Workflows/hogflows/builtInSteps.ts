import type { CreateActionType } from './hogFlowEditorLogic'
import { DEFAULT_DELAY_DURATION, getDelayDescription } from './steps/delayConfig'
import type { HogFlowAction } from './types'

export const ACTION_NODES_TO_SHOW: CreateActionType[] = [
    {
        type: 'function_email',
        name: 'Email',
        description: 'Send an email to the user.',
        config: {
            template_id: 'template-email',
            inputs: {},
        },
    },
    {
        type: 'function_sms',
        name: 'SMS',
        description: 'Send an SMS to the user.',
        config: {
            template_id: 'template-twilio',
            inputs: {},
        },
    },
    {
        type: 'function',
        name: 'Slack',
        description: 'Send a Slack message to the user.',
        config: { template_id: 'template-slack', inputs: {} },
    },
    {
        type: 'function',
        name: 'Webhook',
        description: 'Send a Webhook to the user.',
        config: { template_id: 'template-webhook', inputs: {} },
    },
]

export const PUSH_NOTIFICATION_ACTION_NODE: CreateActionType = {
    type: 'function_push',
    name: 'Push',
    description: 'Send a push notification to the user.',
    config: { template_id: 'template-native-push', inputs: {} },
}

export const AI_TASK_ACTION_NODE: CreateActionType = {
    type: 'function',
    name: 'Create AI task',
    description: 'Start an AI agent task with instructions from this workflow.',
    config: {
        template_id: 'template-posthog-create-task',
        // Pinned rather than relying on the template default: the engine only reads
        // action.config.inputs at execution time, and this value is what turns a 409
        // "task limit reached" reply into a graceful skip instead of a failed step.
        inputs: { non_failure_status_codes: { value: [409] } },
    },
    output_variable: { key: 'task', result_path: null, label: 'Task' },
}

export const RUN_SCOUT_ACTION_NODE: CreateActionType = {
    type: 'function',
    name: 'Run scout',
    description: 'Start a Signals scout run. With a note, the scout handles what the note names first.',
    config: {
        template_id: 'template-posthog-run-scout',
        // Same reason as the AI-task node above: 409 (run in flight, scout paused, cooldown,
        // budget, or quota) is backpressure the step should skip on, not fail.
        inputs: { non_failure_status_codes: { value: [409] } },
    },
    output_variable: { key: 'scout_run', result_path: null, label: 'Scout run' },
}

export const CLASSIFY_ACTION_NODE: CreateActionType = {
    type: 'function',
    name: 'Classify with AI',
    description: 'Ask an AI model to pick one category for the context. Branch on the result with a condition step.',
    config: { template_id: 'template-posthog-classify', inputs: {} },
    output_variable: [
        { key: 'category', result_path: 'category', label: 'Category' },
        { key: 'confidence', result_path: 'confidence', label: 'Confidence' },
    ],
}

export const REPLAY_VISION_ACTION_NODE: CreateActionType = {
    type: 'function',
    name: 'Replay Vision',
    description: "Ask about, categorize, score or summarize the triggering event's session recording.",
    config: { template_id: 'template-posthog-replay-vision', inputs: {} },
    output_variable: { key: 'replay_vision', result_path: null, label: 'Replay Vision' },
}

export const DELAY_NODES_TO_SHOW: CreateActionType[] = [
    {
        type: 'delay',
        name: 'Delay',
        description: getDelayDescription({ delay_duration: DEFAULT_DELAY_DURATION }),
        config: { delay_duration: DEFAULT_DELAY_DURATION },
    },
    {
        type: 'wait_until_time_window',
        name: 'Time window',
        description: 'Wait for the next allowed time window before continuing.',
        config: {
            timezone: null,
            day: 'any',
            time: 'any',
        },
    },
    {
        type: 'wait_until_condition',
        name: 'Wait until',
        description: 'Wait until a matching event fires or a condition is met, up to a maximum duration.',
        branchEdges: 1,
        config: {
            condition: { filters: null },
            max_wait_duration: '5m',
        },
    },
]

export const LOGIC_NODES_TO_SHOW: CreateActionType[] = [
    {
        type: 'conditional_branch',
        name: 'Conditional branch',
        description: 'Branch using conditions on event or person properties.',
        branchEdges: 1,
        config: {
            conditions: [
                {
                    filters: {},
                },
            ],
        },
    },
    {
        type: 'random_cohort_branch',
        name: 'Cohort branch',
        description: 'Randomly branch off based on cohort percentages.',
        branchEdges: 1,
        config: {
            cohorts: [
                {
                    percentage: 50,
                },
            ],
        },
    },
]

export const POSTHOG_NODES_TO_SHOW: CreateActionType[] = [
    {
        type: 'function',
        name: 'Set variable',
        description: 'Set a workflow variable.',
        config: { template_id: 'template-posthog-set-variable', inputs: {} },
    },
    {
        type: 'function',
        name: 'Capture event',
        description: 'Capture an event to PostHog.',
        config: { template_id: 'template-posthog-capture', inputs: {} },
    },
    {
        type: 'function',
        name: 'Update person property',
        description: 'Set properties of a person in PostHog.',
        config: { template_id: 'template-posthog-update-person-properties', inputs: {} },
    },
    {
        type: 'function',
        name: 'Set group property',
        description: 'Set properties of a group in PostHog.',
        config: { template_id: 'template-posthog-group-identify', inputs: {} },
    },
]

export const ADD_TO_STATIC_COHORT_ACTION_NODE: CreateActionType = {
    type: 'function',
    name: 'Add to static cohort',
    description: 'Add the person to a static cohort.',
    config: { template_id: 'template-posthog-add-to-static-cohort', inputs: {} },
}

export const OPT_OUT_OF_MESSAGES_ACTION_NODE: CreateActionType = {
    type: 'function',
    name: 'Opt out of messages',
    description: 'Opt the recipient out of a message category, or of all marketing messages.',
    config: { template_id: 'template-posthog-opt-out-of-messages', inputs: {} },
    // The executor only stops on an explicit abort. A failed opt-out must not continue to a message step.
    on_error: 'abort',
}

export function templateIdOf(step: CreateActionType): string | undefined {
    return 'template_id' in step.config ? step.config.template_id : undefined
}

const kindKey = (type: string, templateId: string | undefined): string => `${type}:${templateId ?? ''}`

/** Names each kind of step the way the step picker does, so one kind of step has one name everywhere. */
export function stepKindNamer(steps: CreateActionType[]): (action: HogFlowAction) => string | undefined {
    const names = new Map(steps.map((step) => [kindKey(step.type, templateIdOf(step)), step.name]))
    return (action) => {
        const templateId =
            'template_id' in action.config ? (action.config.template_id as string | undefined) : undefined
        return names.get(kindKey(action.type, templateId)) ?? names.get(kindKey(action.type, undefined))
    }
}

export const SUPPORT_TICKET_NODES: CreateActionType[] = [
    {
        type: 'function',
        name: 'Get ticket',
        description: 'Fetch current ticket data into a workflow variable.',
        config: { template_id: 'template-posthog-get-ticket', inputs: {} },
        output_variable: { key: 'ticket', result_path: null, spread: true },
    },
    {
        type: 'function',
        name: 'Update ticket',
        description: 'Update a conversation ticket status or priority.',
        config: { template_id: 'template-posthog-update-ticket', inputs: {} },
    },
    {
        type: 'function',
        name: 'Send message',
        description: 'Post a reply on a ticket, or save it as a private note.',
        config: { template_id: 'template-posthog-send-ticket-message', inputs: {} },
    },
]

export const BUILT_IN_STEPS: CreateActionType[] = [
    ...ACTION_NODES_TO_SHOW,
    ...DELAY_NODES_TO_SHOW,
    ...LOGIC_NODES_TO_SHOW,
    ...POSTHOG_NODES_TO_SHOW,
    PUSH_NOTIFICATION_ACTION_NODE,
    AI_TASK_ACTION_NODE,
    RUN_SCOUT_ACTION_NODE,
    CLASSIFY_ACTION_NODE,
    REPLAY_VISION_ACTION_NODE,
    ADD_TO_STATIC_COHORT_ACTION_NODE,
    OPT_OUT_OF_MESSAGES_ACTION_NODE,
    ...SUPPORT_TICKET_NODES,
]

export const builtInStepKindName = stepKindNamer(BUILT_IN_STEPS)
