import { LemonDialog, lemonToast } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { pluralize } from 'lib/utils/strings'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import {
    hogFlowsBatchJobsList,
    hogFlowsBroadcastConversionCandidatesRetrieve,
    hogFlowsConvertToBroadcast,
    hogFlowsDestroy,
    hogFlowsPartialUpdate,
} from 'products/workflows/frontend/generated/api'
import type { BroadcastConversionCandidateApi } from 'products/workflows/frontend/generated/api.schemas'

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
                    // A send can start between opening the menu and confirming, so the runs are checked again here.
                    const jobs = await hogFlowsBatchJobsList(projectId, broadcast.id)
                    const runningReason = archiveDisabledReason(jobs.map((job) => job.status))
                    if (runningReason) {
                        lemonToast.error(runningReason)
                        return
                    }
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

export function confirmOpenInWorkflowEditor(onConfirm: () => void): void {
    LemonDialog.open({
        width: 500,
        title: 'Open in the workflow editor?',
        description:
            'Add delays, follow-up emails, branches or other steps there. After you add steps, the broadcast shows here read-only and you keep editing it in the workflow editor.',
        primaryButton: {
            children: 'Open workflow editor',
            type: 'primary',
            'data-attr': 'broadcast-open-in-workflow-editor-confirm',
            onClick: onConfirm,
        },
        secondaryButton: { children: 'Cancel' },
    })
}

export type CreateAsBroadcastChoice = 'broadcast' | 'broadcast_and_move' | 'workflow'

/**
 * Resolves to null when the user closes the dialog without a choice. `others` are the existing
 * workflows that could move to broadcasts too; the dialog names them and offers to move them.
 */
export function confirmCreateAsBroadcast(
    others: readonly BroadcastConversionCandidateApi[] = []
): Promise<CreateAsBroadcastChoice | null> {
    const overview =
        'Broadcasts come with an overview built for sends to an audience. Watch deliveries, opens, clicks and conversions come in, and compare them across sends.'
    const keepAsWorkflow = {
        children: 'Keep as workflow',
        'data-attr': 'workflow-create-as-broadcast-decline',
    }
    const hasOthers = others.length > 0
    return new Promise((resolve) => {
        LemonDialog.open({
            // Three buttons do not fit on one row at the default width.
            width: hasOthers ? 600 : 500,
            title: 'Track this send as a broadcast?',
            description: hasOthers ? (
                <>
                    <p className="mb-2">{overview}</p>
                    <p className="mb-1">
                        Also move {others.length === 1 ? 'this workflow' : `these ${others.length} workflows`} to
                        broadcasts?
                    </p>
                    <ul className="list-disc pl-5 mb-0 max-h-40 overflow-y-auto">
                        {others.map((other) => (
                            <li key={other.id}>{other.name || 'Untitled workflow'}</li>
                        ))}
                    </ul>
                </>
            ) : (
                overview
            ),
            primaryButton: hasOthers
                ? {
                      children: `Create and move ${others.length} more`,
                      type: 'primary',
                      'data-attr': 'workflow-create-as-broadcast-and-move',
                      onClick: () => resolve('broadcast_and_move'),
                  }
                : {
                      children: 'Create broadcast',
                      type: 'primary',
                      'data-attr': 'workflow-create-as-broadcast-confirm',
                      onClick: () => resolve('broadcast'),
                  },
            secondaryButton: hasOthers
                ? {
                      children: 'Create broadcast',
                      'data-attr': 'workflow-create-as-broadcast-confirm',
                      onClick: () => resolve('broadcast'),
                  }
                : { ...keepAsWorkflow, onClick: () => resolve('workflow') },
            tertiaryButton: hasOthers ? { ...keepAsWorkflow, onClick: () => resolve('workflow') } : undefined,
            // A button click resolves first, so this only takes effect when the dialog is dismissed.
            onAfterClose: () => resolve(null),
        })
    })
}

/** The existing workflows that could move to broadcasts. Empty when the list cannot load. */
export async function loadBroadcastConversionCandidates(
    projectId: string
): Promise<readonly BroadcastConversionCandidateApi[]> {
    try {
        return (await hogFlowsBroadcastConversionCandidatesRetrieve(projectId)).results
    } catch {
        // The offer to move other workflows is optional, so a failed lookup must not block the save.
        return []
    }
}

/** Moves each workflow to broadcasts and returns how many moved. */
export async function moveWorkflowsToBroadcasts(projectId: string, workflowIds: string[]): Promise<number> {
    const results = await Promise.allSettled(workflowIds.map((id) => hogFlowsConvertToBroadcast(projectId, id)))
    return results.filter((result) => result.status === 'fulfilled').length
}

export function movedToBroadcastsMessage(requested: number, moved: number): string {
    return moved === requested
        ? `Broadcast saved. ${pluralize(moved, 'other workflow')} moved to broadcasts.`
        : `Broadcast saved. ${requested - moved} of ${requested} other workflows did not move. They stay in the Workflows list.`
}
