import { CyclotronJobInputType } from '~/types'

import { HogFlowTriggerSchema } from './hogflows/steps/types'
import type { HogFlow, HogFlowAction } from './hogflows/types'

export type WorkflowTriggerConfig = Extract<HogFlowAction, { type: 'trigger' }>['config']

export const TRIGGER_PREFILL_PARAM = 'trigger'
export const SCAFFOLD_PREFILL_PARAM = 'scaffold'
export const PREFILL_PARAMS = [TRIGGER_PREFILL_PARAM, SCAFFOLD_PREFILL_PARAM] as const

export type WorkflowScaffold = 'email'

export function serializeWorkflowTriggerPrefill(config: WorkflowTriggerConfig): string {
    return JSON.stringify(config)
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

export function applyTriggerPrefill<T extends Pick<HogFlow, 'actions'>>(workflow: T, config: WorkflowTriggerConfig): T {
    return {
        ...workflow,
        actions: workflow.actions.map((action) => (action.type === 'trigger' ? { ...action, config } : action)),
    }
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
