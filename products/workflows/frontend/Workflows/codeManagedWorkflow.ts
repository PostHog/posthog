import { HogFlow } from './hogflows/types'

/** Whether a repository owns this workflow's content, which makes it read-only here. */
export function isCodeManagedWorkflow(workflow: HogFlow | null | undefined): boolean {
    return workflow?.managed_by === 'code'
}

/**
 * The file that owns a workflow, as far as the row records it. The parts are nullable until a push
 * writes them, so every caller needs the fallback.
 */
export function workflowSourceLabel(workflow: HogFlow | null | undefined): string {
    if (workflow?.source_repository && workflow.source_path) {
        return `${workflow.source_path} in ${workflow.source_repository}`
    }
    return workflow?.source_repository || workflow?.source_path || 'its repository'
}

/** Why the editor is read-only, in the shape a `disabledReason` and a tooltip both want. */
export function codeManagedReason(workflow: HogFlow | null | undefined): string {
    return `This workflow is managed by code. Edit ${workflowSourceLabel(workflow)} and push.`
}

/** Why a code-managed workflow cannot be deleted, and the three steps that let it be. */
export function codeManagedDeleteReason(workflow: HogFlow | null | undefined): string {
    return `This workflow is managed by code, in ${workflowSourceLabel(
        workflow
    )}. Hand it back to the UI first, then archive it, then delete it.`
}
