import { LemonDialog, lemonToast } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import {
    hogFlowsBatchJobsList,
    hogFlowsDestroy,
    hogFlowsPartialUpdate,
} from 'products/workflows/frontend/generated/api'

export interface ManagedBroadcast {
    id: string
    name?: string | null
}

/** Archive, restore and delete need editor access to the broadcast, as they do for a workflow. */
export function manageDisabledReason(userAccessLevel: string | null | undefined): string | undefined {
    return (
        getAccessControlDisabledReason(
            AccessControlResourceType.Workflow,
            AccessControlLevel.Editor,
            (userAccessLevel as AccessControlLevel | null) ?? undefined
        ) ?? undefined
    )
}

const RUNNING_BATCH_JOB_STATUSES = ['waiting', 'queued', 'active']

/**
 * Archiving only cancels a running send's people as they come up, so a send in flight is stopped first.
 * Null means the runs haven't loaded, and a send could be running.
 */
export function archiveDisabledReason(batchJobStatuses: (string | null | undefined)[] | null): string | undefined {
    if (batchJobStatuses === null) {
        return 'Checking whether a send is running'
    }
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

export interface ManageBroadcastCallbacks {
    onDone: () => void
    /** Marks the broadcast busy while its request runs, so its controls can't send a second, overlapping request. */
    setPending: (pending: boolean) => void
}

/** Wait text for the controls of a broadcast that has a request in flight. */
export const PENDING_DISABLED_REASON = 'Wait for the current change to finish'

async function runPending(
    { onDone, setPending }: ManageBroadcastCallbacks,
    request: () => Promise<boolean>
): Promise<void> {
    setPending(true)
    let succeeded = false
    try {
        succeeded = await request()
    } finally {
        setPending(false)
    }
    // After the pending flag clears, as onDone can leave the page and unmount the logic.
    if (succeeded) {
        onDone()
    }
}

/** A confirm button handler that ignores clicks while its request runs, before the dialog re-renders as loading. */
function confirmHandler(callbacks: ManageBroadcastCallbacks, request: () => Promise<boolean>): () => Promise<void> {
    let inFlight = false
    return async () => {
        if (inFlight) {
            return
        }
        inFlight = true
        try {
            await runPending(callbacks, request)
        } finally {
            inFlight = false
        }
    }
}

export function confirmArchiveBroadcast(
    projectId: string,
    broadcast: ManagedBroadcast,
    callbacks: ManageBroadcastCallbacks
): void {
    LemonDialog.open({
        width: 500,
        title: 'Archive broadcast?',
        description: `"${label(broadcast)}" moves to the archived list and any schedule stops sending. You can restore it later as a draft.`,
        shouldAwaitSubmit: true,
        primaryButton: {
            children: 'Archive',
            type: 'primary',
            status: 'danger',
            'data-attr': 'broadcast-archive-confirm',
            onClick: confirmHandler(callbacks, async () => {
                try {
                    // A send can start between opening the menu and confirming, so the runs are checked again here.
                    const jobs = await hogFlowsBatchJobsList(projectId, broadcast.id)
                    const runningReason = archiveDisabledReason(jobs.map((job) => job.status))
                    if (runningReason) {
                        lemonToast.error(runningReason)
                        return false
                    }
                    await hogFlowsPartialUpdate(projectId, broadcast.id, { status: 'archived' })
                    lemonToast.success(`Archived "${label(broadcast)}"`)
                    return true
                } catch (error: any) {
                    lemonToast.error(`Couldn't archive the broadcast: ${errorDetail(error)}`)
                    return false
                }
            }),
        },
        secondaryButton: { children: 'Cancel' },
    })
}

export async function restoreBroadcast(
    projectId: string,
    broadcast: ManagedBroadcast,
    callbacks: ManageBroadcastCallbacks
): Promise<void> {
    await runPending(callbacks, async () => {
        try {
            await hogFlowsPartialUpdate(projectId, broadcast.id, { status: 'draft' })
            lemonToast.success(`Restored "${label(broadcast)}" as a draft`)
            return true
        } catch (error: any) {
            lemonToast.error(`Couldn't restore the broadcast: ${errorDetail(error)}`)
            return false
        }
    })
}

export function confirmDeleteBroadcast(
    projectId: string,
    broadcast: ManagedBroadcast,
    callbacks: ManageBroadcastCallbacks
): void {
    LemonDialog.open({
        width: 500,
        title: 'Delete broadcast?',
        description: `"${label(broadcast)}" and its settings are deleted for good. This can't be undone.`,
        shouldAwaitSubmit: true,
        primaryButton: {
            children: 'Delete',
            type: 'primary',
            status: 'danger',
            'data-attr': 'broadcast-delete-confirm',
            onClick: confirmHandler(callbacks, async () => {
                try {
                    await hogFlowsDestroy(projectId, broadcast.id)
                    lemonToast.success(`Deleted "${label(broadcast)}"`)
                    return true
                } catch (error: any) {
                    lemonToast.error(`Couldn't delete the broadcast: ${errorDetail(error)}`)
                    return false
                }
            }),
        },
        secondaryButton: { children: 'Cancel' },
    })
}
