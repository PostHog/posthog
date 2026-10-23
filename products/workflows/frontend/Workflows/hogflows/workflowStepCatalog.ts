// Registers the product-specific action nodes before any catalog reads them.
import './registry'

import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import type { HogFunctionTemplateType, TeamPublicType, TeamType } from '~/types'

import { PERSON_DEPENDENT_ACTION_TYPES } from '../workflowLogic'
import type { CreateActionType } from './hogFlowEditorLogic'
import { destinationPickerFilter } from './panel/destinationPickerFilter'
import { getRegisteredActionNodeCategories } from './registry/actions/actionNodeRegistry'
import { DEFAULT_DELAY_DURATION, getDelayDescription } from './steps/stepDelayLogic'
import type { HogFlowAction } from './types'

const ACTION_NODES_TO_SHOW: CreateActionType[] = [
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

const PUSH_NOTIFICATION_ACTION_NODE: CreateActionType = {
    type: 'function_push',
    name: 'Push',
    description: 'Send a push notification to the user.',
    config: { template_id: 'template-native-push', inputs: {} },
}

const AI_TASK_ACTION_NODE: CreateActionType = {
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

const RUN_SCOUT_ACTION_NODE: CreateActionType = {
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

const CLASSIFY_ACTION_NODE: CreateActionType = {
    type: 'function',
    name: 'Classify with AI',
    description: 'Ask an AI model to pick one category for the context. Branch on the result with a condition step.',
    config: { template_id: 'template-posthog-classify', inputs: {} },
    output_variable: [
        { key: 'category', result_path: 'category', label: 'Category' },
        { key: 'confidence', result_path: 'confidence', label: 'Confidence' },
    ],
}

const REPLAY_VISION_ACTION_NODE: CreateActionType = {
    type: 'function',
    name: 'Replay Vision',
    description: "Ask about, categorize, score or summarize the triggering event's session recording.",
    config: { template_id: 'template-posthog-replay-vision', inputs: {} },
    output_variable: { key: 'replay_vision', result_path: null, label: 'Replay Vision' },
}

const DELAY_NODES_TO_SHOW: CreateActionType[] = [
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

const LOGIC_NODES_TO_SHOW: CreateActionType[] = [
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

const POSTHOG_NODES_TO_SHOW: CreateActionType[] = [
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

const ADD_TO_STATIC_COHORT_ACTION_NODE: CreateActionType = {
    type: 'function',
    name: 'Add to static cohort',
    description: 'Add the person to a static cohort.',
    config: { template_id: 'template-posthog-add-to-static-cohort', inputs: {} },
}

const OPT_OUT_OF_MESSAGES_ACTION_NODE: CreateActionType = {
    type: 'function',
    name: 'Opt out of messages',
    description: 'Opt the recipient out of a message category, or of all marketing messages.',
    config: { template_id: 'template-posthog-opt-out-of-messages', inputs: {} },
    // The executor only stops on an explicit abort. A failed opt-out must not continue to a message step.
    on_error: 'abort',
}

export interface StepCatalogContext {
    featureFlags: FeatureFlagsSet
    currentTeam: Pick<TeamPublicType | TeamType, 'id' | 'project_id'> | null
    isRowScopedTrigger: boolean
}

export interface StepCatalogSection {
    key: string
    title: string
    steps: CreateActionType[]
}

/** Scouts and Replay Vision belong to the project's main environment, and the server refuses their steps
 * elsewhere. While the team is still loading, both sides of the id comparison are undefined, so the team must be
 * there first. */
function isMainEnvironment(currentTeam: StepCatalogContext['currentTeam']): boolean {
    return !!currentTeam && currentTeam.id === currentTeam.project_id
}

function dispatchSteps({ featureFlags }: StepCatalogContext): CreateActionType[] {
    return [
        ...ACTION_NODES_TO_SHOW,
        ...(featureFlags[FEATURE_FLAGS.WORKFLOWS_PUSH_NOTIFICATIONS] ? [PUSH_NOTIFICATION_ACTION_NODE] : []),
    ]
}

function aiSteps({ featureFlags, currentTeam }: StepCatalogContext): CreateActionType[] {
    const mainEnvironment = isMainEnvironment(currentTeam)
    return [
        ...(featureFlags[FEATURE_FLAGS.WORKFLOW_AI_TASK_ACTION] ? [AI_TASK_ACTION_NODE] : []),
        ...(mainEnvironment ? [RUN_SCOUT_ACTION_NODE] : []),
        ...(featureFlags[FEATURE_FLAGS.WORKFLOW_CLASSIFY_ACTION] ? [CLASSIFY_ACTION_NODE] : []),
        ...(mainEnvironment ? [REPLAY_VISION_ACTION_NODE] : []),
    ]
}

function posthogSteps({ featureFlags }: StepCatalogContext): CreateActionType[] {
    return [
        ...POSTHOG_NODES_TO_SHOW,
        ...(featureFlags[FEATURE_FLAGS.WORKFLOW_ADD_TO_STATIC_COHORT_ACTION] ? [ADD_TO_STATIC_COHORT_ACTION_NODE] : []),
        ...(featureFlags[FEATURE_FLAGS.WORKFLOW_OPT_OUT_OF_MESSAGES_ACTION] ? [OPT_OUT_OF_MESSAGES_ACTION_NODE] : []),
    ]
}

const BETA_TEMPLATE_IDS = new Set(['template-posthog-create-task'])

export function isBetaStep(step: CreateActionType): boolean {
    const templateId = templateIdOf(step)
    return !!templateId && BETA_TEMPLATE_IDS.has(templateId)
}

/** A warehouse-triggered workflow has no person, so it offers no step that needs one. */
function forTrigger(steps: CreateActionType[], isRowScopedTrigger: boolean): CreateActionType[] {
    return isRowScopedTrigger ? steps.filter((step) => !PERSON_DEPENDENT_ACTION_TYPES.has(step.type)) : steps
}

export function workflowStepSections(context: StepCatalogContext): StepCatalogSection[] {
    return [
        { key: 'dispatch', title: 'Dispatch', steps: dispatchSteps(context) },
        { key: 'ai', title: 'AI', steps: aiSteps(context) },
        { key: 'delays', title: 'Delays', steps: forTrigger(DELAY_NODES_TO_SHOW, context.isRowScopedTrigger) },
        { key: 'split', title: 'Audience split', steps: forTrigger(LOGIC_NODES_TO_SHOW, context.isRowScopedTrigger) },
        { key: 'posthog', title: 'PostHog actions', steps: posthogSteps(context) },
        ...getRegisteredActionNodeCategories(context.featureFlags).map((category) => ({
            key: category.label,
            title: category.label,
            steps: category.nodes,
        })),
    ].filter((section) => section.steps.length > 0)
}

function templateIdOf(step: CreateActionType): string | undefined {
    return 'template_id' in step.config ? step.config.template_id : undefined
}

const ALWAYS_LISTED_STEPS: CreateActionType[] = [
    ...ACTION_NODES_TO_SHOW,
    ...DELAY_NODES_TO_SHOW,
    ...LOGIC_NODES_TO_SHOW,
    ...POSTHOG_NODES_TO_SHOW,
    ...getRegisteredActionNodeCategories().flatMap((category) => category.nodes),
]

const ALL_CATALOG_STEPS: CreateActionType[] = [
    ...ALWAYS_LISTED_STEPS,
    PUSH_NOTIFICATION_ACTION_NODE,
    AI_TASK_ACTION_NODE,
    RUN_SCOUT_ACTION_NODE,
    CLASSIFY_ACTION_NODE,
    REPLAY_VISION_ACTION_NODE,
]

/** Destinations already offered as their own step stay out of the destination list. */
const TEMPLATE_IDS_AT_TOP_LEVEL = ALWAYS_LISTED_STEPS.flatMap((step) => templateIdOf(step) ?? [])

export const isPickableDestination = destinationPickerFilter(TEMPLATE_IDS_AT_TOP_LEVEL)

export function destinationStep(template: HogFunctionTemplateType): CreateActionType {
    return {
        type: 'function',
        name: template.name,
        description: typeof template.description === 'string' ? template.description : '',
        config: { template_id: template.id, inputs: {} },
    }
}

/** Destination templates that are not already a step of their own, as steps, by name. */
export function destinationSteps(templates: HogFunctionTemplateType[]): CreateActionType[] {
    return templates
        .filter(isPickableDestination)
        .sort((a, b) => a.name.localeCompare(b.name))
        .map(destinationStep)
}

const kindKey = (type: string, templateId: string | undefined): string => `${type}:${templateId ?? ''}`

const STEP_KIND_NAMES = new Map(ALL_CATALOG_STEPS.map((step) => [kindKey(step.type, templateIdOf(step)), step.name]))

/** The name the step picker gives this kind of step, so one kind of step has one name everywhere. */
export function stepKindName(action: HogFlowAction): string | undefined {
    const templateId = 'template_id' in action.config ? (action.config.template_id as string | undefined) : undefined
    return STEP_KIND_NAMES.get(kindKey(action.type, templateId)) ?? STEP_KIND_NAMES.get(kindKey(action.type, undefined))
}

/** The step's own name, unless it is still the name the step picker gave it or reads the same as a text shown beside it. */
export function customStepName(action: HogFlowAction, shownElsewhere: (string | undefined)[]): string | undefined {
    const name = action.name?.trim()
    return name && name !== stepKindName(action) && !shownElsewhere.includes(name) ? name : undefined
}
