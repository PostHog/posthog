import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { HogFlowTriggerSchema } from './hogflows/steps/types'
import type { HogFlowAction } from './hogflows/types'

export type WorkflowTriggerConfig = Extract<HogFlowAction, { type: 'trigger' }>['config']

export const TRIGGER_PREFILL_PARAM = 'trigger'

export function urlForNewWorkflowWithTrigger(config: WorkflowTriggerConfig): string {
    return combineUrl(urls.workflowNew(), { [TRIGGER_PREFILL_PARAM]: JSON.stringify(config) }).url
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
