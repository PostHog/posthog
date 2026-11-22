export interface TemplateEditState {
    draftsEnabled: boolean
    hasDraft: boolean
    hasUnsavedChanges: boolean
    templateChanged: boolean
    isSavingSensitive: boolean
    sensitive: boolean
}

export const SENSITIVE_REASON =
    'A sensitive email sends from the API only. PostHog stores the events a workflow starts from.'

/**
 * Why a workflow can't copy the template's email: it copies the saved, published email only, and never a sensitive
 * one, whose values would have to come from a stored event.
 */
export function templateWorkflowDisabledReason(state: TemplateEditState): string | undefined {
    if (state.isSavingSensitive) {
        return 'Saving the setting'
    }
    if (state.sensitive) {
        return SENSITIVE_REASON
    }
    if (state.draftsEnabled) {
        return state.hasDraft || state.hasUnsavedChanges ? 'Publish your changes first' : undefined
    }
    return state.templateChanged ? 'Save your changes first' : undefined
}
