// Registers the product-specific action nodes before any catalog reads them.
import './registry'

import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import type { HogFunctionTemplateType, TeamPublicType, TeamType } from '~/types'

import { PERSON_DEPENDENT_ACTION_TYPES } from '../workflowLogic'
import {
    ACTION_NODES_TO_SHOW,
    ADD_TO_STATIC_COHORT_ACTION_NODE,
    AI_TASK_ACTION_NODE,
    BUILT_IN_STEPS,
    CLASSIFY_ACTION_NODE,
    DELAY_NODES_TO_SHOW,
    LOGIC_NODES_TO_SHOW,
    OPT_OUT_OF_MESSAGES_ACTION_NODE,
    POSTHOG_NODES_TO_SHOW,
    PUSH_NOTIFICATION_ACTION_NODE,
    REPLAY_VISION_ACTION_NODE,
    RUN_SCOUT_ACTION_NODE,
    stepKindNamer,
    templateIdOf,
} from './builtInSteps'
import type { CreateActionType } from './hogFlowEditorLogic'
import { destinationPickerFilter } from './panel/destinationPickerFilter'
import { getRegisteredActionNodeCategories } from './registry/actions/actionNodeRegistry'

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

const ALWAYS_LISTED_STEPS: CreateActionType[] = [
    ...ACTION_NODES_TO_SHOW,
    ...DELAY_NODES_TO_SHOW,
    ...LOGIC_NODES_TO_SHOW,
    ...POSTHOG_NODES_TO_SHOW,
    ...getRegisteredActionNodeCategories().flatMap((category) => category.nodes),
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

export const stepKindName = stepKindNamer([
    ...BUILT_IN_STEPS,
    ...getRegisteredActionNodeCategories().flatMap((category) => category.nodes),
])
