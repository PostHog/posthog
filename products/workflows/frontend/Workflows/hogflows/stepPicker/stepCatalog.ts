// Side-effect import: registers the product-specific action nodes read below
import '../registry'

import { FEATURE_FLAGS, FeatureFlagKey } from 'lib/constants'
import { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import { HogFunctionTemplateType } from '~/types'

import { PERSON_DEPENDENT_ACTION_TYPES } from '../../workflowLogic'
import { CreateActionType } from '../hogFlowEditorLogic'
import { destinationPickerFilter } from '../panel/destinationPickerFilter'
import { getRegisteredActionNodeCategories } from '../registry/actions/actionNodeRegistry'
import {
    STEP_ATTRIBUTION,
    StepAttribution,
    StepCategory,
    StepProduct,
    unclassifiedDestinationAttribution,
} from './stepAttribution'
import { stepCatalogIdOf, templateIdOf } from './stepCatalogId'
import {
    ACTION_NODES_TO_SHOW,
    AI_TASK_ACTION_NODE,
    CLASSIFY_ACTION_NODE,
    DELAY_NODES_TO_SHOW,
    LOGIC_NODES_TO_SHOW,
    POSTHOG_NODES_TO_SHOW,
    PUSH_NOTIFICATION_ACTION_NODE,
    RUN_SCOUT_ACTION_NODE,
} from './stepDefinitions'

export type StepCatalogInput = {
    featureFlags: FeatureFlagsSet
    isMainEnvironment: boolean
    isRowScopedTrigger: boolean
    destinationTemplates: HogFunctionTemplateType[] | null
}

export type StepCatalogEntry = {
    id: string
    action: CreateActionType
    name: string
    operation: string | null
    description: string
    origin: 'posthog' | 'third_party'
    product: StepProduct | null
    vendor: string | null
    category: StepCategory | null
    tags: string[]
    status: 'alpha' | 'beta' | null
}

type BuiltInStep = {
    action: CreateActionType
    isEligible?: (input: StepCatalogInput) => boolean
}

const isFlagOn =
    (flag: FeatureFlagKey) =>
    ({ featureFlags }: StepCatalogInput): boolean =>
        !!featureFlags[flag]

const BUILT_IN_STEPS: BuiltInStep[] = [
    ...ACTION_NODES_TO_SHOW.map((action) => ({ action })),
    { action: PUSH_NOTIFICATION_ACTION_NODE, isEligible: isFlagOn(FEATURE_FLAGS.WORKFLOWS_PUSH_NOTIFICATIONS) },
    { action: AI_TASK_ACTION_NODE, isEligible: isFlagOn(FEATURE_FLAGS.WORKFLOW_AI_TASK_ACTION) },
    {
        action: RUN_SCOUT_ACTION_NODE,
        isEligible: (input) => isFlagOn(FEATURE_FLAGS.WORKFLOW_RUN_SCOUT_ACTION)(input) && input.isMainEnvironment,
    },
    { action: CLASSIFY_ACTION_NODE, isEligible: isFlagOn(FEATURE_FLAGS.WORKFLOW_CLASSIFY_ACTION) },
    ...[...DELAY_NODES_TO_SHOW, ...LOGIC_NODES_TO_SHOW, ...POSTHOG_NODES_TO_SHOW].map((action) => ({ action })),
]

function toEntry(
    action: CreateActionType,
    attribution: StepAttribution,
    { tags, status }: Pick<StepCatalogEntry, 'tags' | 'status'>
): StepCatalogEntry {
    return {
        id: stepCatalogIdOf(action),
        action,
        name: action.name,
        operation: attribution.operation,
        description: action.description ?? '',
        origin: attribution.product ? 'posthog' : 'third_party',
        product: attribution.product,
        vendor: attribution.vendor,
        category: attribution.category,
        tags,
        status,
    }
}

function stepEntry(action: CreateActionType, templates: HogFunctionTemplateType[]): StepCatalogEntry {
    const attribution = STEP_ATTRIBUTION[stepCatalogIdOf(action)] ?? unclassifiedDestinationAttribution(action.name, [])
    const template = templates.find((candidate) => candidate.id === templateIdOf(action))
    return toEntry(action, attribution, { tags: template?.category ?? [], status: null })
}

function destinationEntry(template: HogFunctionTemplateType): StepCatalogEntry {
    const tags = template.category ?? []
    const action: CreateActionType = {
        type: 'function',
        name: template.name,
        description: typeof template.description === 'string' ? template.description : '',
        config: { template_id: template.id, inputs: {} },
    }
    const attribution = STEP_ATTRIBUTION[template.id] ?? unclassifiedDestinationAttribution(template.name, tags)
    const status = template.status === 'alpha' || template.status === 'beta' ? template.status : null
    return toEntry(action, attribution, { tags, status })
}

function destinationEntries(templates: HogFunctionTemplateType[]): StepCatalogEntry[] {
    const stepTemplateIds = [
        ...BUILT_IN_STEPS.map(({ action }) => action),
        ...getRegisteredActionNodeCategories().flatMap((category) => category.nodes),
    ]
        .map(templateIdOf)
        .filter((templateId): templateId is string => !!templateId)
    const isOffered = destinationPickerFilter(stepTemplateIds)

    return templates
        .filter(isOffered)
        .sort((a, b) => a.name.localeCompare(b.name))
        .map(destinationEntry)
}

export function buildStepCatalog(input: StepCatalogInput): StepCatalogEntry[] {
    const builtInActions = BUILT_IN_STEPS.filter(({ isEligible }) => !isEligible || isEligible(input)).map(
        ({ action }) => action
    )
    const registeredActions = getRegisteredActionNodeCategories(input.featureFlags).flatMap(
        (category) => category.nodes
    )
    const templates = input.destinationTemplates ?? []
    const entries = [
        ...[...builtInActions, ...registeredActions].map((action) => stepEntry(action, templates)),
        ...destinationEntries(templates),
    ]

    return input.isRowScopedTrigger
        ? entries.filter((entry) => !PERSON_DEPENDENT_ACTION_TYPES.has(entry.action.type))
        : entries
}
