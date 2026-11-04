import { LemonDialog, LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

export function openWorkflowSavedViewDialog(onSubmit: (name: string) => Promise<void>, currentName?: string): void {
    let pendingSubmit: Promise<void> | null = null
    LemonDialog.openForm({
        title: currentName === undefined ? 'Save as new view' : 'Rename view',
        description:
            currentName === undefined
                ? 'The filters, search and columns become a new view that everyone in this project sees.'
                : undefined,
        initialValues: { name: currentName ?? '' },
        shouldAwaitSubmit: true,
        content: (
            <LemonField name="name">
                <LemonInput
                    maxLength={128}
                    placeholder={currentName === undefined ? 'For example: Webinar emails' : undefined}
                    autoFocus
                    onKeyDown={(event) => {
                        if (event.key === 'Enter' && event.nativeEvent.isComposing) {
                            event.stopPropagation()
                        }
                    }}
                    data-attr={currentName === undefined ? 'workflows-combined-view-name' : undefined}
                />
            </LemonField>
        ),
        errors: { name: (name: string) => (!name?.trim() ? 'Give the view a name' : undefined) },
        onSubmit: ({ name }) => {
            pendingSubmit ??= onSubmit(String(name).trim()).finally(() => {
                pendingSubmit = null
            })
            return pendingSubmit
        },
    })
}

export function openDeleteWorkflowSavedViewDialog(name: string, onDelete: () => Promise<void>): void {
    LemonDialog.open({
        title: `Delete ${name}?`,
        description: 'Everyone in this project loses this view.',
        shouldAwaitSubmit: true,
        primaryButton: { children: 'Delete view', status: 'danger', onClick: onDelete },
        secondaryButton: { children: 'Cancel' },
    })
}
