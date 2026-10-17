import { GitMetadataParser } from 'lib/components/Git/gitMetadataParser'

import { MessageTemplate } from './types'

export interface TemplateSource {
    path: string | null
    fileUrl: string | undefined
    repository: string | null
    repositoryUrl: string | undefined
    ref: string | null
    refUrl: string | undefined
}

export function isCodeManagedTemplate(template: Pick<MessageTemplate, 'managed_by'> | null | undefined): boolean {
    return template?.managed_by === 'code'
}

export function templateSource(template: MessageTemplate | null | undefined): TemplateSource | null {
    if (!isCodeManagedTemplate(template)) {
        return null
    }
    const repository = template?.source_repository || undefined
    const path = template?.source_path || undefined
    const ref = template?.source_ref || undefined
    if (!repository && !path && !ref) {
        return null
    }
    return {
        path: path ?? null,
        fileUrl: GitMetadataParser.getFileLink(repository, ref, path),
        repository: repository ?? null,
        repositoryUrl: GitMetadataParser.getRepoLink(repository),
        ref: ref ? shortRef(ref) : null,
        refUrl: GitMetadataParser.getRefLink(repository, ref),
    }
}

function shortRef(ref: string): string {
    return GitMetadataParser.isCommitSha(ref) ? ref.slice(0, 7) : ref
}
