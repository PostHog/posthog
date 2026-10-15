import { CreateActionType } from '../hogFlowEditorLogic'
import { DEFAULT_DELAY_DURATION, getDelayDescription } from '../steps/stepDelayLogic'

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
    description: 'Start a Signals scout run. The scout explores as it does on its schedule.',
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
