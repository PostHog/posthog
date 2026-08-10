import { redactSecretHogFunctionInputs } from 'scenes/hog-functions/hog-function-utils'

import { CyclotronJobInputSchemaType, CyclotronJobInputType, HogFunctionTemplateType } from '~/types'

import { AttachedContextItem } from 'products/posthog_ai/frontend/api/types'

import { BUILDING_WORKFLOWS_SKILL, WORKFLOWS_MCP_TOOLS } from '../agentContext.generated'
import { isFunctionAction, isTriggerFunction } from './hogflows/steps/types'
import type { HogFlow } from './hogflows/types'

// All static strings below are build-time constants from our own repo (skill markdown + tool
// descriptions), which is what makes them safe to attach as trusted `instructions` items.
const PREAMBLE_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    value:
        'The user has the PostHog workflow editor open. The full building-workflows skill and the complete ' +
        'workflows MCP tool catalog are included in this context - you already have everything needed to act. ' +
        'Do not spend turns discovering tools or reading skill files: call the listed tools directly, and use ' +
        'the exec `info <tool>` command only when you need a full input schema.',
}

const SKILL_CONTENT_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    value:
        `Skill ${BUILDING_WORKFLOWS_SKILL.name} (embedded, including its graph-schema reference): ` +
        BUILDING_WORKFLOWS_SKILL.content,
}

const EDITOR_STATE_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    value:
        'The hog_flow_editor_state item is the current, possibly unsaved editor state of the workflow the user ' +
        'has open - prefer it over a fetched definition when reading. Use workflows-get only when you need the ' +
        'persisted state.',
}

const TOOL_CONTEXT_ITEMS: AttachedContextItem[] = WORKFLOWS_MCP_TOOLS.map((tool) => ({
    type: 'instructions',
    hidden: true,
    value: `MCP tool ${tool.name}: ${tool.description}`,
}))

const SKILL_CHIP_CONTEXT_ITEM: AttachedContextItem = {
    type: 'skill',
    key: BUILDING_WORKFLOWS_SKILL.name,
    label: 'Building workflows skill',
}

export const WORKFLOW_AGENT_HEADLINES: string[] = [
    'How can I help with this workflow?',
    'What should this workflow do?',
]

function redactInputsRecord(
    inputs: Record<string, CyclotronJobInputType>,
    inputsSchema: CyclotronJobInputSchemaType[] | undefined
): Record<string, CyclotronJobInputType> {
    const redacted = redactSecretHogFunctionInputs(inputs, inputsSchema ?? [])
    // Compiled bytecode of a redacted entry can embed the literal value, so it must not survive either.
    return Object.fromEntries(
        Object.entries(redacted).map(([key, entry]) =>
            entry?.value === '[secret]' && inputs[key]?.value !== '[secret]'
                ? [key, { ...entry, bytecode: undefined }]
                : [key, entry]
        )
    )
}

/**
 * Strip secret input values from a workflow before it is serialized into agent context. Saved
 * secrets never reach the frontend, but a secret typed into the editor and not yet saved sits in
 * cleartext in the live form state - and function steps carry only a `template_id`, so the secret
 * fields are only identifiable through the loaded template schemas.
 */
export function redactWorkflowSecretInputs(
    workflow: HogFlow,
    hogFunctionTemplatesById: Record<string, HogFunctionTemplateType>
): HogFlow {
    const clone: HogFlow = structuredClone(workflow)
    for (const action of clone.actions ?? []) {
        if (!isFunctionAction(action) && !isTriggerFunction(action)) {
            continue
        }
        const config = action.config as {
            template_id?: string
            inputs?: Record<string, CyclotronJobInputType> | null
            mappings?: {
                inputs?: Record<string, CyclotronJobInputType> | null
                inputs_schema?: CyclotronJobInputSchemaType[]
            }[]
        }
        const template = config.template_id ? hogFunctionTemplatesById[config.template_id] : undefined
        if (config.inputs) {
            config.inputs = redactInputsRecord(config.inputs, template?.inputs_schema ?? undefined)
        }
        for (const mapping of config.mappings ?? []) {
            if (mapping.inputs) {
                mapping.inputs = redactInputsRecord(mapping.inputs, mapping.inputs_schema)
            }
        }
    }
    const trigger = clone.trigger as
        | { template_id?: string; inputs?: Record<string, CyclotronJobInputType> | null }
        | undefined
    if (trigger?.inputs) {
        const template = trigger.template_id ? hogFunctionTemplatesById[trigger.template_id] : undefined
        trigger.inputs = redactInputsRecord(trigger.inputs, template?.inputs_schema ?? undefined)
    }
    return clone
}

/**
 * The default agent context for the workflow editor scene: the embedded building-workflows skill,
 * the workflows MCP tool catalog, and the current workflow (a visible ref for saved workflows plus
 * the live editor state so unsaved edits are visible to the agent).
 */
export function buildWorkflowAgentContext(
    workflow: HogFlow | null,
    id: string,
    hogFunctionTemplatesById: Record<string, HogFunctionTemplateType>
): AttachedContextItem[] {
    const items: AttachedContextItem[] = [
        PREAMBLE_CONTEXT_ITEM,
        SKILL_CHIP_CONTEXT_ITEM,
        SKILL_CONTENT_CONTEXT_ITEM,
        ...TOOL_CONTEXT_ITEMS,
        EDITOR_STATE_CONTEXT_ITEM,
    ]
    if (id !== 'new') {
        items.push({ type: 'hog_flow', key: id, label: workflow?.name || 'Current workflow' })
    }
    if (workflow) {
        items.push({
            type: 'hog_flow_editor_state',
            hidden: true,
            value: JSON.stringify(redactWorkflowSecretInputs(workflow, hogFunctionTemplatesById)),
        })
    }
    return items
}
