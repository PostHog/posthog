import { uuid } from 'lib/utils/dom'

import { CyclotronJobInputType, HogFunctionTemplateType } from '~/types'

import { HogFlow, HogFlowAction } from '../hogflows/types'
import { EXIT_NODE_ID, NEW_WORKFLOW, TRIGGER_NODE_ID } from '../workflowLogic'
import type { WorkflowTriggerConfig } from '../workflowTriggerPrefill'

export type EventTriggerFilters = Extract<WorkflowTriggerConfig, { type: 'event' }>['filters']

export interface BuildHogFlowFromDestinationArgs {
    template: HogFunctionTemplateType
    name: string
    triggerFilters: EventTriggerFilters
    inputs: Record<string, CyclotronJobInputType>
}

export interface HogFlowFromDestination {
    workflow: Partial<HogFlow>
    functionActionId: string
}

/**
 * The graph a destination maps onto: the event trigger, one function step that runs the
 * destination's template, and the exit. Server-owned fields are left out so the result can go
 * straight to the create endpoint.
 */
export function buildHogFlowFromDestination({
    template,
    name,
    triggerFilters,
    inputs,
}: BuildHogFlowFromDestinationArgs): HogFlowFromDestination {
    const triggerAction = NEW_WORKFLOW.actions.find((action) => action.id === TRIGGER_NODE_ID)
    const exitAction = NEW_WORKFLOW.actions.find((action) => action.id === EXIT_NODE_ID)
    if (!triggerAction || !exitAction) {
        throw new Error('The blank workflow must contain the trigger and exit nodes')
    }

    const functionActionId = `action_function_${uuid()}`
    const now = Date.now()

    const actions: HogFlowAction[] = [
        {
            ...triggerAction,
            config: { type: 'event', filters: triggerFilters },
            created_at: now,
            updated_at: now,
        } as HogFlowAction,
        {
            id: functionActionId,
            type: 'function',
            name: template.name,
            description: typeof template.description === 'string' ? template.description : '',
            config: { template_id: template.id, inputs },
            created_at: now,
            updated_at: now,
        },
        { ...exitAction, created_at: now, updated_at: now } as HogFlowAction,
    ]

    const workflow: Partial<HogFlow> = {
        name,
        status: 'draft',
        version: 1,
        conversion: NEW_WORKFLOW.conversion,
        exit_condition: NEW_WORKFLOW.exit_condition,
        actions,
        edges: [
            { from: TRIGGER_NODE_ID, to: functionActionId, type: 'continue' },
            { from: functionActionId, to: EXIT_NODE_ID, type: 'continue' },
        ],
    }

    return { workflow, functionActionId }
}
