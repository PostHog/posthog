export interface TemplateEditState {
    draftsEnabled: boolean
    hasDraft: boolean
    hasUnsavedChanges: boolean
    templateChanged: boolean
    isSavingSensitive: boolean
}

/** Why a workflow can't copy the template's email yet: it copies the saved, published email only. */
export function templateWorkflowDisabledReason(state: TemplateEditState): string | undefined {
    if (state.isSavingSensitive) {
        return 'Saving the setting'
    }
    if (state.draftsEnabled) {
        return state.hasDraft || state.hasUnsavedChanges ? 'Publish your changes first' : undefined
    }
    return state.templateChanged ? 'Save your changes first' : undefined
}
