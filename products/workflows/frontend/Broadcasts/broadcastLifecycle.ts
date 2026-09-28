import { LemonDialog, lemonToast } from '@posthog/lemon-ui'

import { hogFlowsDestroy, hogFlowsPartialUpdate } from 'products/workflows/frontend/generated/api'

export interface ManagedBroadcast {
    id: string
    name?: string | null
}

const RUNNING_BATCH_JOB_STATUSES = ['waiting', 'queued', 'active']

/** Archiving only cancels a running send's people as they come up, so a send in flight is stopped first. */
export function archiveDisabledReason(batchJobStatuses: (string | null | undefined)[]): string | undefined {
    return batchJobStatuses.some((status) => RUNNING_BATCH_JOB_STATUSES.includes(status ?? ''))
        ? 'This broadcast is sending. Wait for it to finish before archiving it.'
        : undefined
}

function label(broadcast: ManagedBroadcast): string {
    return broadcast.name || 'Untitled broadcast'
}

function errorDetail(error: any): string {
    return error?.detail || error?.message || 'unknown error'
}

export function confirmArchiveBroadcast(projectId: string, broadcast: ManagedBroadcast, onDone: () => void): void {
    LemonDialog.open({
        width: 500,
        title: 'Archive broadcast?',
        description: `"${label(broadcast)}" moves to the archived list and any schedule stops sending. You can restore it later as a draft.`,
        primaryButton: {
            children: 'Archive',
            type: 'primary',
            status: 'danger',
            'data-attr': 'broadcast-archive-confirm',
            onClick: async () => {
                try {
                    await hogFlowsPartialUpdate(projectId, broadcast.id, { status: 'archived' })
                    lemonToast.success(`Archived "${label(broadcast)}"`)
                    onDone()
                } catch (error: any) {
                    lemonToast.error(`Couldn't archive the broadcast: ${errorDetail(error)}`)
                }
            },
        },
        secondaryButton: { children: 'Cancel' },
    })
}

export async function restoreBroadcast(
    projectId: string,
    broadcast: ManagedBroadcast,
    onDone: () => void
): Promise<void> {
    try {
        await hogFlowsPartialUpdate(projectId, broadcast.id, { status: 'draft' })
        lemonToast.success(`Restored "${label(broadcast)}" as a draft`)
        onDone()
    } catch (error: any) {
        lemonToast.error(`Couldn't restore the broadcast: ${errorDetail(error)}`)
    }
}

export function confirmDeleteBroadcast(projectId: string, broadcast: ManagedBroadcast, onDone: () => void): void {
    LemonDialog.open({
        width: 500,
        title: 'Delete broadcast?',
        description: `"${label(broadcast)}" and its settings are deleted for good. This can't be undone.`,
        primaryButton: {
            children: 'Delete',
            type: 'primary',
            status: 'danger',
            'data-attr': 'broadcast-delete-confirm',
            onClick: async () => {
                try {
                    await hogFlowsDestroy(projectId, broadcast.id)
                    lemonToast.success(`Deleted "${label(broadcast)}"`)
                    onDone()
                } catch (error: any) {
                    lemonToast.error(`Couldn't delete the broadcast: ${errorDetail(error)}`)
                }
            },
        },
        secondaryButton: { children: 'Cancel' },
    })
}
