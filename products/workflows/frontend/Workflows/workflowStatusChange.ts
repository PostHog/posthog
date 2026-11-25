import posthog from 'posthog-js'

import type { HogFlow } from './hogflows/types'
import { triggerEventNames, triggerLeadIn } from './overview/workflowOverviewSummary'

export type WorkflowStatusChangeSurface = 'editor' | 'list'
export type WorkflowStatusChangeTarget = 'active' | 'draft'

export function statusChangeTitle(status: WorkflowStatusChangeTarget): string {
    return `Are you sure you want to ${status === 'active' ? 'enable' : 'disable'} this workflow?`
}

export function statusChangeConsequence(status: WorkflowStatusChangeTarget): string {
    return status === 'active'
        ? 'From now on, new runs start each time this trigger fires.'
        : "From now on, this trigger doesn't start new runs. In-progress runs will be canceled and users within the workflow won't continue."
}

export function triggerRecap(trigger: HogFlow['trigger']): string {
    if (!trigger) {
        return triggerLeadIn(trigger)
    }
    const eventNames = triggerEventNames(trigger)
    return `${triggerLeadIn(trigger)}${eventNames.length > 0 ? `: ${eventNames.join(', ')}` : ''}.`
}

// pinned: analytics event names, property values and data-attr values
export const STATUS_CHANGE_CONFIRM_ATTR: Record<WorkflowStatusChangeTarget, string> = {
    active: 'workflow-confirm-enable',
    draft: 'workflow-confirm-disable',
}
export const STATUS_CHANGE_CANCEL_ATTR = 'workflow-cancel-status-change'

export function trackStatusChangeShown(
    workflowId: string,
    surface: WorkflowStatusChangeSurface,
    status: WorkflowStatusChangeTarget
): void {
    posthog.capture('workflows status change confirmation shown', { workflow_id: workflowId, surface, status })
}

export function trackStatusChangeConfirmed(
    workflowId: string,
    surface: WorkflowStatusChangeSurface,
    status: WorkflowStatusChangeTarget
): void {
    posthog.capture('workflows status change confirmed', { workflow_id: workflowId, surface, status })
}
