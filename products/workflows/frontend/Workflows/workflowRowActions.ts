import { LemonDialog, lemonToast } from '@posthog/lemon-ui'

import { deleteFromTree } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'

import { hogFlowsDestroy, hogFlowsPartialUpdate } from 'products/workflows/frontend/generated/api'

/** What the row actions need to know about a workflow, in either list. */
export interface WorkflowRowTarget {
    id: string
    name: string | null
    status?: string
}

type WorkflowStatus = 'draft' | 'active' | 'archived'

export function workflowActionErrorDetail(error: unknown): string {
    const e = error as { detail?: string; message?: string } | undefined
    return e?.detail || e?.message || 'Unknown error'
}

/** Resolves true when the status changed, false after it showed an error. */
export async function setWorkflowStatus(
    projectId: string,
    workflow: WorkflowRowTarget,
    status: WorkflowStatus
): Promise<boolean> {
    try {
        await hogFlowsPartialUpdate(projectId, workflow.id, { status })
        return true
    } catch (error) {
        lemonToast.error(`Failed to update workflow: ${workflowActionErrorDetail(error)}`)
        return false
    }
}

export async function restoreWorkflowToDraft(projectId: string, workflow: WorkflowRowTarget): Promise<boolean> {
    try {
        await hogFlowsPartialUpdate(projectId, workflow.id, { status: 'draft' })
        lemonToast.success(`Workflow "${workflow.name}" restored to draft status`)
        return true
    } catch (error) {
        lemonToast.error(`Failed to restore workflow: ${workflowActionErrorDetail(error)}`)
        return false
    }
}

/** Asks first, then archives. `onArchived` runs only after the server accepted the change. */
export function confirmArchiveWorkflow(projectId: string, workflow: WorkflowRowTarget, onArchived: () => void): void {
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
                try {
                    await hogFlowsPartialUpdate(projectId, workflow.id, { status: 'archived' })
                    lemonToast.success(`Workflow "${workflow.name}" archived`)
                    onArchived()
                } catch (error) {
                    lemonToast.error(`Failed to archive workflow: ${workflowActionErrorDetail(error)}`)
                }
            },
        },
        secondaryButton: {
            children: 'Cancel',
        },
    })
}

/** Asks first, then deletes. `onDeleted` runs only after the server deleted the workflow. */
export function confirmDeleteWorkflow(projectId: string, workflow: WorkflowRowTarget, onDeleted: () => void): void {
    LemonDialog.open({
        width: 500,
        title: 'Delete workflow?',
        description: `Are you sure you want to permanently delete "${workflow.name}"? This action cannot be undone.`,
        primaryButton: {
            children: 'Delete',
            type: 'primary',
            status: 'danger',
            onClick: async () => {
                try {
                    await hogFlowsDestroy(projectId, workflow.id)
                    lemonToast.success(`Workflow "${workflow.name}" deleted`)
                    deleteFromTree('hog_flow/', workflow.id)
                    onDeleted()
                } catch (error) {
                    lemonToast.error(`Failed to delete workflow: ${workflowActionErrorDetail(error)}`)
                }
            },
        },
        secondaryButton: {
            children: 'Cancel',
        },
    })
}
