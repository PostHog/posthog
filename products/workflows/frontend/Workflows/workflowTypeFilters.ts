import type { HogFlowAction } from './hogflows/types'
import type { WorkflowTypeFilter } from './workflowsLogic'

// Keep in sync with MESSAGING_ACTION_TYPES in products/workflows/backend/models/hog_flow/hog_flow.py,
// which the list API's `type` filter uses - the tag, the template filter, and the list filter must
// agree on what "Messaging" is.
const MESSAGING_ACTION_TYPES: string[] = ['function_email', 'function_sms', 'function_push']

export type WorkflowTemplateTypeFilter = 'all' | 'messaging' | 'automation'

export function hasMessagingAction(actions: Pick<HogFlowAction, 'type'>[]): boolean {
    return actions.some((action) => MESSAGING_ACTION_TYPES.includes(action.type))
}

export function matchesTemplateType(
    actions: Pick<HogFlowAction, 'type'>[],
    typeFilter: WorkflowTemplateTypeFilter
): boolean {
    if (typeFilter === 'all') {
        return true
    }
    return hasMessagingAction(actions) === (typeFilter === 'messaging')
}

/** The template filter that matches a type tab on the workflows list. Loops have no templates, so they show all. */
export function templateTypeForListType(listType: WorkflowTypeFilter): WorkflowTemplateTypeFilter {
    return listType === 'messaging' || listType === 'automation' ? listType : 'all'
}
