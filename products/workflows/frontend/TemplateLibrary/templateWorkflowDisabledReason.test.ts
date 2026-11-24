import { SENSITIVE_REASON, TemplateEditState, templateWorkflowDisabledReason } from './templateWorkflowDisabledReason'

const saved: TemplateEditState = {
    draftsEnabled: true,
    hasDraft: false,
    hasUnsavedChanges: false,
    templateChanged: false,
    isSavingSensitive: false,
    sensitive: false,
}

describe('templateWorkflowDisabledReason', () => {
    test.each<[string, Partial<TemplateEditState>, string | undefined]>([
        ['a published template', {}, undefined],
        ['a sensitive setting still saving', { isSavingSensitive: true }, 'Saving the setting'],
        ['a sensitive template, whose values an event would store', { sensitive: true }, SENSITIVE_REASON],
        ['an unpublished draft', { hasDraft: true }, 'Publish your changes first'],
        ['unsaved edits with drafts on', { hasUnsavedChanges: true }, 'Publish your changes first'],
        ['unsaved edits with drafts off', { draftsEnabled: false, templateChanged: true }, 'Save your changes first'],
    ])('for %s', (_, state, reason) => {
        expect(templateWorkflowDisabledReason({ ...saved, ...state })).toBe(reason)
    })
})
