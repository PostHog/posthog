import { GitMetadataParser } from 'lib/components/Git/gitMetadataParser'

import { HogFlow } from './hogflows/types'

/**
 * Whether a repository owns this workflow's content. The editor still accepts edits to it, but only
 * a push saves content, so the form never reaches the API.
 */
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

/** Why edits made in the editor are not saved, in the shape a `disabledReason` and a tooltip both want. */
export function codeManagedReason(workflow: HogFlow | null | undefined): string {
    return `This workflow is managed by code, so changes made here are not saved. Edit ${workflowSourceLabel(workflow)} and push.`
}

/** Why a code-managed workflow cannot be deleted here. */
export function codeManagedDeleteReason(workflow: HogFlow | null | undefined): string {
    return `This workflow is managed by code, in ${workflowSourceLabel(workflow)}. It cannot be deleted here.`
}

/**
 * The recorded source of a workflow, with a link for each part that the host lets us build one for.
 * A part the row does not record is null, and a part on a host we cannot link has no URL.
 */
export interface WorkflowSource {
    path: string | null
    fileUrl: string | undefined
    repository: string | null
    repositoryUrl: string | undefined
    /** A sha shortened to 7 characters, or a branch as it is. */
    ref: string | null
    refUrl: string | undefined
}

export function workflowSource(workflow: HogFlow | null | undefined): WorkflowSource {
    const repository = workflow?.source_repository || undefined
    const path = workflow?.source_path || undefined
    const ref = workflow?.source_ref || undefined
    return {
        path: path ?? null,
        fileUrl: GitMetadataParser.getFileLink(repository, ref, path),
        repository: repository ?? null,
        repositoryUrl: GitMetadataParser.getRepoLink(repository),
        ref: ref ? (GitMetadataParser.isCommitSha(ref) ? ref.slice(0, 7) : ref) : null,
        refUrl: GitMetadataParser.getRefLink(repository, ref),
    }
}
