import { redactSecretHogFunctionInputs } from 'scenes/hog-functions/hog-function-utils'

import { CyclotronJobInputSchemaType, CyclotronJobInputType, HogFunctionTemplateType } from '~/types'

import { AttachedContextItem } from 'products/posthog_ai/frontend/api/types'

import { BUILDING_WORKFLOWS_SKILL, WORKFLOWS_MCP_TOOLS } from '../generated/agentContext'
import { isEmailAction, isFunctionAction, isTriggerFunction } from './hogflows/steps/types'
import type { HogFlow } from './hogflows/types'

// Each visible chip and the hidden payload items it stands for share a dismiss group, so closing
// the chip actually detaches the payload instead of only hiding the chip.
const SKILL_DISMISS_GROUP = 'workflow-scene-skill'
const EDITOR_STATE_DISMISS_GROUP = 'workflow-scene-state'

// All static strings below are build-time constants from our own repo (skill markdown + tool
// descriptions), which is what makes them safe to attach as trusted `instructions` items.
const PREAMBLE_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    dismissGroup: SKILL_DISMISS_GROUP,
    value:
        'The user has the PostHog workflow editor open. The full building-workflows skill and the complete ' +
        'workflows MCP tool catalog are included in this context - you already have everything needed to act. ' +
        'Do not spend turns discovering tools or reading skill files: call the listed tools directly, and use ' +
        'the exec `info <tool>` command only when you need a full input schema.',
}

const SKILL_CONTENT_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    dismissGroup: SKILL_DISMISS_GROUP,
    value:
        `Skill ${BUILDING_WORKFLOWS_SKILL.name} (embedded, including its graph-schema reference): ` +
        BUILDING_WORKFLOWS_SKILL.content,
}

const EDITOR_STATE_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    dismissGroup: EDITOR_STATE_DISMISS_GROUP,
    value:
        'The hog_flow_editor_state item is the current, possibly unsaved editor state of the workflow the user ' +
        'has open - prefer it over a fetched definition when reading. Use workflows-get only when you need the ' +
        'persisted state. Oversized email designs may be elided from this state; read them with workflows-get, ' +
        'or workflows-get-email-template for library templates.',
}

const TOOL_CONTEXT_ITEMS: AttachedContextItem[] = WORKFLOWS_MCP_TOOLS.map((tool) => ({
    type: 'instructions',
    hidden: true,
    dismissGroup: SKILL_DISMISS_GROUP,
    value: `MCP tool ${tool.name}: ${tool.description}`,
}))

const SKILL_CHIP_CONTEXT_ITEM: AttachedContextItem = {
    type: 'skill',
    key: BUILDING_WORKFLOWS_SKILL.name,
    label: 'Building workflows skill',
    dismissGroup: SKILL_DISMISS_GROUP,
}

export const WORKFLOW_AGENT_HEADLINES: string[] = [
    'How can I help with this workflow?',
    'What should this workflow do?',
]

function redactInputsRecord(
    inputs: Record<string, CyclotronJobInputType>,
    inputsSchema: CyclotronJobInputSchemaType[] | undefined
): Record<string, CyclotronJobInputType> {
    if (!inputsSchema) {
        // Without a schema (templates still loading, fetch failed, or the template was deleted) there
        // is no way to tell which inputs are secret, so fail closed and redact every value. The agent
        // can still read the persisted state with workflows-get, where secrets are masked server-side.
        return Object.fromEntries(
            Object.entries(inputs).map(([key, entry]) => [
                key,
                entry ? { ...entry, value: '[redacted]', bytecode: undefined } : entry,
            ])
        )
    }
    const redacted = redactSecretHogFunctionInputs(inputs, inputsSchema)
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

function emailValueOf(action: HogFlow['actions'][number]): Record<string, unknown> | null {
    if (!isEmailAction(action)) {
        return null
    }
    const value = (action.config as { inputs?: Record<string, CyclotronJobInputType> | null })?.inputs?.email?.value
    return value && typeof value === 'object' ? (value as Record<string, unknown>) : null
}

/** Serialized editor state beyond this budget gets its email designs elided (see `serializeWorkflowEditorState`). */
export const EDITOR_STATE_MAX_CHARS = 64_000

const DESIGN_ELIDED_MARKER =
    '[design elided for size: read it with workflows-get, or workflows-get-email-template for library templates]'

/**
 * Serialize the live workflow for agent context, bounding the payload that rides along with every
 * message: secrets are redacted (failing closed while template schemas are unavailable), the
 * rendered email html is dropped from steps that carry a design (the server re-renders html from
 * the design on every save, so it is derived weight), and if the result still exceeds
 * `EDITOR_STATE_MAX_CHARS` the email designs themselves are swapped for a fetch hint. Elision keeps
 * the JSON parseable, which blind truncation would not.
 */
export function serializeWorkflowEditorState(
    workflow: HogFlow,
    hogFunctionTemplatesById: Record<string, HogFunctionTemplateType>
): string {
    const prepared = redactWorkflowSecretInputs(workflow, hogFunctionTemplatesById)
    for (const action of prepared.actions ?? []) {
        const email = emailValueOf(action)
        // Steps without a design keep their html, because it is the only body they have.
        if (email?.design && email.html) {
            delete email.html
        }
    }
    const serialized = JSON.stringify(prepared)
    if (serialized.length <= EDITOR_STATE_MAX_CHARS) {
        return serialized
    }
    for (const action of prepared.actions ?? []) {
        const email = emailValueOf(action)
        if (email?.design) {
            email.design = DESIGN_ELIDED_MARKER
        }
    }
    return JSON.stringify(prepared)
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
        items.push({
            type: 'hog_flow',
            key: id,
            label: workflow?.name || 'Current workflow',
            dismissGroup: EDITOR_STATE_DISMISS_GROUP,
        })
    }
    if (workflow) {
        items.push({
            type: 'hog_flow_editor_state',
            hidden: true,
            dismissGroup: EDITOR_STATE_DISMISS_GROUP,
            value: serializeWorkflowEditorState(workflow, hogFunctionTemplatesById),
        })
    }
    return items
}
