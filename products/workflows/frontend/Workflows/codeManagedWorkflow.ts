import { GitMetadataParser } from 'lib/components/Git/gitMetadataParser'

import { HogFlow } from './hogflows/types'

export function isCodeManagedWorkflow(workflow: HogFlow | null | undefined): boolean {
    return workflow?.managed_by === 'code'
}

export function workflowSourceLabel(workflow: HogFlow | null | undefined): string {
    if (workflow?.source_repository && workflow.source_path) {
        return `${workflow.source_path} in ${workflow.source_repository}`
    }
    return workflow?.source_repository || workflow?.source_path || 'its repository'
}

export function codeManagedReason(workflow: HogFlow | null | undefined): string {
    return `This workflow is managed by code in ${workflowSourceLabel(workflow)}. Changes made here are not saved. To keep them, copy the code, commit it to the workflow's file, and push.`
}

export function codeManagedDeleteReason(workflow: HogFlow | null | undefined): string {
    return `This workflow is managed by code, in ${workflowSourceLabel(workflow)}. It cannot be deleted here.`
}

export interface WorkflowSource {
    path: string | null
    fileUrl: string | undefined
    repository: string | null
    repositoryUrl: string | undefined
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
