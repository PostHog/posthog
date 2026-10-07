import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { HogFlowTriggerSchema } from './hogflows/steps/types'
import type { HogFlowAction } from './hogflows/types'

export type WorkflowTriggerConfig = Extract<HogFlowAction, { type: 'trigger' }>['config']

export const TRIGGER_PREFILL_PARAM = 'trigger'

export function urlForNewWorkflowWithTrigger(config: WorkflowTriggerConfig): string {
    return combineUrl(urls.workflowNew(), { [TRIGGER_PREFILL_PARAM]: JSON.stringify(config) }).url
}

// kea-router hands over JSON-looking search params already parsed, so accept an object too.
export function parseWorkflowTriggerPrefill(raw: unknown): WorkflowTriggerConfig | null {
    if (!raw) {
        return null
    }
    try {
        const result = HogFlowTriggerSchema.safeParse(typeof raw === 'string' ? JSON.parse(raw) : raw)
        return result.success ? (result.data as WorkflowTriggerConfig) : null
    } catch {
        return null
    }
}
