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

export function isChangeDescribed(sentence: string, starter: string): boolean {
    const described = sentence.trim()
    return described !== '' && described !== starter.trim()
}

const GITHUB_REPOSITORY = /^github\.com\/[A-Za-z0-9-]+\/[A-Za-z0-9._-]+?(\.git)?$/i

export function isGitHubRepository(repository: string | null | undefined): boolean {
    return GITHUB_REPOSITORY.test(repository ?? '')
}

function shortRef(ref: string): string {
    return GitMetadataParser.isCommitSha(ref) ? ref.slice(0, 7) : ref
}

const SERVER_OWNED_FIELDS = [
    'key',
    'managed_by',
    'source_repository',
    'source_path',
    'source_ref',
    'change_prompt_starter',
    'change_prompt_context',
    'change_prompt_variables',
] as const

/** The editor sends the whole form, but the server alone sets these, so a key set elsewhere never blocks a save. */
export function withoutServerOwnedFields(template: MessageTemplate): Partial<MessageTemplate> {
    const editable: Partial<MessageTemplate> = { ...template }
    for (const field of SERVER_OWNED_FIELDS) {
        delete editable[field]
    }
    return editable
}
