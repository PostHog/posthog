import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { CyclotronJobInputType } from '~/types'

import { HogFlowTriggerSchema } from './hogflows/steps/types'
import type { HogFlow, HogFlowAction } from './hogflows/types'

export type WorkflowTriggerConfig = Extract<HogFlowAction, { type: 'trigger' }>['config']

export const TRIGGER_PREFILL_PARAM = 'trigger'
export const SCAFFOLD_PREFILL_PARAM = 'scaffold'

export type WorkflowScaffold = 'email'

export function urlForNewWorkflowWithTrigger(config: WorkflowTriggerConfig, scaffold?: WorkflowScaffold): string {
    return combineUrl(urls.workflowNew(), {
        [TRIGGER_PREFILL_PARAM]: JSON.stringify(config),
        ...(scaffold ? { [SCAFFOLD_PREFILL_PARAM]: scaffold } : {}),
    }).url
}

export function urlForWorkflowChooserWithTrigger(config: WorkflowTriggerConfig, scaffold?: WorkflowScaffold): string {
    return combineUrl(
        urls.workflows(),
        {
            [TRIGGER_PREFILL_PARAM]: JSON.stringify(config),
            ...(scaffold ? { [SCAFFOLD_PREFILL_PARAM]: scaffold } : {}),
        },
        { newWorkflow: 'modal' }
    ).url
}

export function parseWorkflowTriggerPrefill(raw: string | undefined): WorkflowTriggerConfig | null {
    if (!raw) {
        return null
    }
    try {
        const result = HogFlowTriggerSchema.safeParse(JSON.parse(raw))
        return result.success ? (result.data as WorkflowTriggerConfig) : null
    } catch {
        return null
    }
}

export function parseWorkflowScaffold(raw: string | undefined): WorkflowScaffold | null {
    return raw === 'email' ? 'email' : null
}

// The step panel snapshots its inputs on mount, so emailInputs must carry the template-email
// defaults up front (same reason the editor seeds them when a step is dragged in).
export function applyEmailScaffold(workflow: HogFlow, emailInputs: Record<string, CyclotronJobInputType>): HogFlow {
    const trigger = workflow.actions.find((action) => action.type === 'trigger')
    const exit = workflow.actions.find((action) => action.type === 'exit')
    if (!trigger || !exit) {
        return workflow
    }
    const emailAction: HogFlowAction = {
        id: 'action_function_email_prefill',
        type: 'function_email',
        name: 'Email',
        description: 'Send an email to the user.',
        config: { template_id: 'template-email', inputs: emailInputs },
        created_at: 0,
        updated_at: 0,
    }
    return {
        ...workflow,
        actions: workflow.actions.flatMap((action) => (action.id === exit.id ? [emailAction, action] : [action])),
        edges: workflow.edges.flatMap((edge) =>
            edge.from === trigger.id && edge.to === exit.id
                ? [
                      { from: trigger.id, to: emailAction.id, type: 'continue' as const },
                      { from: emailAction.id, to: exit.id, type: 'continue' as const },
                  ]
                : [edge]
        ),
    }
}
