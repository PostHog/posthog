import { LemonDialog, lemonToast } from '@posthog/lemon-ui'

import { deleteFromTree } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'

import { hogFlowsDestroy, hogFlowsPartialUpdate } from 'products/workflows/frontend/generated/api'
import type { HogFlowUpdateApi } from 'products/workflows/frontend/generated/api.schemas'

/** What the row actions need to know about a workflow, in either list. */
export interface WorkflowRowTarget {
    id: string
    name: string | null
    status?: string
}

type WorkflowStatus = 'draft' | 'active' | 'archived'

export type WorkflowRowAction = 'toggle' | 'duplicate' | 'archive' | 'restore' | 'delete'

export function workflowActionErrorDetail(error: unknown): string {
    const e = error as { detail?: string; message?: string } | undefined
    return e?.detail || e?.message || 'Unknown error'
}

/** Resolves to the updated workflow, or null after it showed an error. */
export async function setWorkflowStatus(
    teamId: string,
    workflow: WorkflowRowTarget,
    status: WorkflowStatus
): Promise<HogFlowUpdateApi | null> {
    try {
        return await hogFlowsPartialUpdate(teamId, workflow.id, { status })
    } catch (error) {
        lemonToast.error(`Failed to update workflow: ${workflowActionErrorDetail(error)}`)
        return null
    }
}

export async function restoreWorkflowToDraft(
    teamId: string,
    workflow: WorkflowRowTarget
): Promise<HogFlowUpdateApi | null> {
    try {
        const updated = await hogFlowsPartialUpdate(teamId, workflow.id, { status: 'draft' })
        lemonToast.success(`Workflow "${workflow.name}" restored to draft status`)
        return updated
    } catch (error) {
        lemonToast.error(`Failed to restore workflow: ${workflowActionErrorDetail(error)}`)
        return null
    }
}

/**
 * Asks first, then archives. `onArchived` runs only after the server accepted the change.
 * `onPendingChange` brackets the request, from the confirm press to the answer.
 */
export function confirmArchiveWorkflow(
    teamId: string,
    workflow: WorkflowRowTarget,
    onArchived: (updated: HogFlowUpdateApi) => void,
    onPendingChange?: (pending: boolean) => void
): void {
    LemonDialog.open({
        width: 500,
        title: 'Archive workflow?',
        description: `Are you sure you want to archive "${workflow.name}"?${
            workflow.status === 'active' ? ' In-progress workflow invocations will end without completing.' : ''
        }`,
        primaryButton: {
            children: 'Archive',
            type: 'primary',
            status: 'danger',
            onClick: async () => {
                onPendingChange?.(true)
                try {
                    const updated = await hogFlowsPartialUpdate(teamId, workflow.id, { status: 'archived' })
                    lemonToast.success(`Workflow "${workflow.name}" archived`)
                    onArchived(updated)
                } catch (error) {
                    lemonToast.error(`Failed to archive workflow: ${workflowActionErrorDetail(error)}`)
                } finally {
                    onPendingChange?.(false)
                }
            },
        },
        secondaryButton: {
            children: 'Cancel',
        },
    })
}

/** Asks first, then deletes. `onDeleted` runs only after the server deleted the workflow. */
export function confirmDeleteWorkflow(
    teamId: string,
    workflow: WorkflowRowTarget,
    onDeleted: () => void,
    onPendingChange?: (pending: boolean) => void
): void {
    LemonDialog.open({
        width: 500,
        title: 'Delete workflow?',
        description: `Are you sure you want to permanently delete "${workflow.name}"? This action cannot be undone.`,
        primaryButton: {
            children: 'Delete',
            type: 'primary',
            status: 'danger',
            onClick: async () => {
                onPendingChange?.(true)
                try {
                    await hogFlowsDestroy(teamId, workflow.id)
                    lemonToast.success(`Workflow "${workflow.name}" deleted`)
                    deleteFromTree('hog_flow/', workflow.id)
                    onDeleted()
                } catch (error) {
                    lemonToast.error(`Failed to delete workflow: ${workflowActionErrorDetail(error)}`)
                } finally {
                    onPendingChange?.(false)
                }
            },
        },
        secondaryButton: {
            children: 'Cancel',
        },
    })
}
