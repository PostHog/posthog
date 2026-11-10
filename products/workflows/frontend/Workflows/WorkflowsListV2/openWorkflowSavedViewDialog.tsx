import { useSyncExternalStore } from 'react'

import { LemonDialog, LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

type PendingSubmit = {
    isPending: () => boolean
    subscribe: (listener: () => void) => () => void
}

function ViewNameField({ isNew, pending }: { isNew: boolean; pending: PendingSubmit }): JSX.Element {
    const isPending = useSyncExternalStore(pending.subscribe, pending.isPending)
    return (
        <LemonField name="name" help={isPending ? (isNew ? 'Saving the view...' : 'Renaming the view...') : undefined}>
            <LemonInput
                maxLength={128}
                placeholder={isNew ? 'For example: Webinar emails' : undefined}
                autoFocus
                data-attr={isNew ? 'workflows-combined-view-name' : undefined}
            />
        </LemonField>
    )
}

export function openWorkflowSavedViewDialog(onSubmit: (name: string) => Promise<void>, currentName?: string): void {
    let pendingSubmit: Promise<void> | null = null
    const listeners = new Set<() => void>()
    const pending: PendingSubmit = {
        isPending: () => pendingSubmit !== null,
        subscribe: (listener) => {
            listeners.add(listener)
            return () => listeners.delete(listener)
        },
    }
    const notify = (): void => listeners.forEach((listener) => listener())
    LemonDialog.openForm({
        title: currentName === undefined ? 'Save as new view' : 'Rename view',
        description:
            currentName === undefined
                ? 'The filters, search and columns become a new view that everyone in this project sees.'
                : undefined,
        initialValues: { name: currentName ?? '' },
        shouldAwaitSubmit: true,
        primaryButtonProps: { children: currentName === undefined ? 'Save view' : 'Rename view' },
        content: <ViewNameField isNew={currentName === undefined} pending={pending} />,
        errors: { name: (name: string) => (!name?.trim() ? 'Give the view a name' : undefined) },
        onSubmit: ({ name }) => {
            if (!pendingSubmit) {
                pendingSubmit = onSubmit(String(name).trim()).finally(() => {
                    pendingSubmit = null
                    notify()
                })
                notify()
            }
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
