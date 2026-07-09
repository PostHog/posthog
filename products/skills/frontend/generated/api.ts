import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import type {
    LLMSkillApi,
    LLMSkillCreateApi,
    LLMSkillDuplicateApi,
    LLMSkillFileApi,
    LLMSkillFileCreateApi,
    LLMSkillFileRenameApi,
    LLMSkillImportApi,
    LLMSkillMarketplaceCommandApi,
    LLMSkillMarketplaceIssueApi,
    LLMSkillResolveResponseApi,
    LlmSkillsListParams,
    LlmSkillsNameExportRetrieveParams,
    LlmSkillsNameFilesDestroyParams,
    LlmSkillsNameFilesRetrieveParams,
    LlmSkillsNameRetrieveParams,
    LlmSkillsResolveNameRetrieveParams,
    PaginatedLLMSkillListListApi,
    PatchedLLMSkillPublishApi,
} from './api.schemas'

// https://stackoverflow.com/questions/49579094/typescript-conditional-types-filter-out-readonly-properties-pick-only-requir/49579497#49579497
type IfEquals<X, Y, A = X, B = never> = (<T>() => T extends X ? 1 : 2) extends <T>() => T extends Y ? 1 : 2 ? A : B

type WritableKeys<T> = {
    [P in keyof T]-?: IfEquals<{ [Q in P]: T[P] }, { -readonly [Q in P]: T[P] }, P>
}[keyof T]

type UnionToIntersection<U> = (U extends any ? (k: U) => void : never) extends (k: infer I) => void ? I : never
type DistributeReadOnlyOverUnions<T> = T extends any ? NonReadonly<T> : never

type Writable<T> = Pick<T, WritableKeys<T>>
type NonReadonly<T> = [T] extends [UnionToIntersection<T>]
    ? {
          [P in keyof Writable<T>]: T[P] extends object ? NonReadonly<NonNullable<T[P]>> : T[P]
      }
    : DistributeReadOnlyOverUnions<T>

export const getLlmSkillsListUrl = (projectId: string, params?: LlmSkillsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/llm_skills/?${stringifiedParams}`
        : `/api/projects/${projectId}/llm_skills/`
}

export const llmSkillsList = async (
    projectId: string,
    params?: LlmSkillsListParams,
    options?: RequestInit
): Promise<PaginatedLLMSkillListListApi> => {
    return apiMutator<PaginatedLLMSkillListListApi>(getLlmSkillsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getLlmSkillsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/llm_skills/`
}

export const llmSkillsCreate = async (
    projectId: string,
    lLMSkillCreateApi: NonReadonly<LLMSkillCreateApi>,
    options?: RequestInit
): Promise<LLMSkillCreateApi> => {
    return apiMutator<LLMSkillCreateApi>(getLlmSkillsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(lLMSkillCreateApi),
    })
}

export const getLlmSkillsImportCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/llm_skills/import/`
}

export const llmSkillsImportCreate = async (
    projectId: string,
    lLMSkillImportApi: LLMSkillImportApi,
    options?: RequestInit
): Promise<LLMSkillApi> => {
    const formData = new FormData()
    formData.append(`file`, lLMSkillImportApi.file)

    return apiMutator<LLMSkillApi>(getLlmSkillsImportCreateUrl(projectId), {
        ...options,
        method: 'POST',
        body: formData,
    })
}

export const getLlmSkillsMarketplaceInstallCommandRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/llm_skills/marketplace/install-command/`
}

/**
 * Report whether the user already has a marketplace credential, without minting one.
 *
 * The token is unrecoverable, so an existing credential returns its mask only — the UI shows
 * "already connected, existing setups keep working" and offers an explicit rotate.
 */
export const llmSkillsMarketplaceInstallCommandRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<LLMSkillMarketplaceCommandApi> => {
    return apiMutator<LLMSkillMarketplaceCommandApi>(getLlmSkillsMarketplaceInstallCommandRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getLlmSkillsMarketplaceInstallCommandCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/llm_skills/marketplace/install-command/`
}

/**
 * Mint the user's read-only marketplace credential (or rotate it) and return the install command.
 *
 * Per-user: rotating only ever invalidates this user's own credential, never a teammate's.
 */
export const llmSkillsMarketplaceInstallCommandCreate = async (
    projectId: string,
    lLMSkillMarketplaceIssueApi?: LLMSkillMarketplaceIssueApi,
    options?: RequestInit
): Promise<LLMSkillMarketplaceCommandApi> => {
    return apiMutator<LLMSkillMarketplaceCommandApi>(getLlmSkillsMarketplaceInstallCommandCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(lLMSkillMarketplaceIssueApi),
    })
}

export const getLlmSkillsNameRetrieveUrl = (
    projectId: string,
    skillName: string,
    params?: LlmSkillsNameRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/llm_skills/name/${skillName}/?${stringifiedParams}`
        : `/api/projects/${projectId}/llm_skills/name/${skillName}/`
}

export const llmSkillsNameRetrieve = async (
    projectId: string,
    skillName: string,
    params?: LlmSkillsNameRetrieveParams,
    options?: RequestInit
): Promise<LLMSkillApi> => {
    return apiMutator<LLMSkillApi>(getLlmSkillsNameRetrieveUrl(projectId, skillName, params), {
        ...options,
        method: 'GET',
    })
}

export const getLlmSkillsNamePartialUpdateUrl = (projectId: string, skillName: string) => {
    return `/api/projects/${projectId}/llm_skills/name/${skillName}/`
}

export const llmSkillsNamePartialUpdate = async (
    projectId: string,
    skillName: string,
    patchedLLMSkillPublishApi?: PatchedLLMSkillPublishApi,
    options?: RequestInit
): Promise<LLMSkillApi> => {
    return apiMutator<LLMSkillApi>(getLlmSkillsNamePartialUpdateUrl(projectId, skillName), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedLLMSkillPublishApi),
    })
}

export const getLlmSkillsNameArchiveCreateUrl = (projectId: string, skillName: string) => {
    return `/api/projects/${projectId}/llm_skills/name/${skillName}/archive/`
}

export const llmSkillsNameArchiveCreate = async (
    projectId: string,
    skillName: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getLlmSkillsNameArchiveCreateUrl(projectId, skillName), {
        ...options,
        method: 'POST',
    })
}

export const getLlmSkillsNameDuplicateCreateUrl = (projectId: string, skillName: string) => {
    return `/api/projects/${projectId}/llm_skills/name/${skillName}/duplicate/`
}

export const llmSkillsNameDuplicateCreate = async (
    projectId: string,
    skillName: string,
    lLMSkillDuplicateApi: LLMSkillDuplicateApi,
    options?: RequestInit
): Promise<LLMSkillApi> => {
    return apiMutator<LLMSkillApi>(getLlmSkillsNameDuplicateCreateUrl(projectId, skillName), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(lLMSkillDuplicateApi),
    })
}

export const getLlmSkillsNameExportRetrieveUrl = (
    projectId: string,
    skillName: string,
    params?: LlmSkillsNameExportRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/llm_skills/name/${skillName}/export/?${stringifiedParams}`
        : `/api/projects/${projectId}/llm_skills/name/${skillName}/export/`
}

export const llmSkillsNameExportRetrieve = async (
    projectId: string,
    skillName: string,
    params?: LlmSkillsNameExportRetrieveParams,
    options?: RequestInit
): Promise<Blob> => {
    return apiMutator<Blob>(getLlmSkillsNameExportRetrieveUrl(projectId, skillName, params), {
        ...options,
        method: 'GET',
    })
}

export const getLlmSkillsNameFilesCreateUrl = (projectId: string, skillName: string) => {
    return `/api/projects/${projectId}/llm_skills/name/${skillName}/files/`
}

export const llmSkillsNameFilesCreate = async (
    projectId: string,
    skillName: string,
    lLMSkillFileCreateApi: LLMSkillFileCreateApi,
    options?: RequestInit
): Promise<LLMSkillApi> => {
    return apiMutator<LLMSkillApi>(getLlmSkillsNameFilesCreateUrl(projectId, skillName), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(lLMSkillFileCreateApi),
    })
}

export const getLlmSkillsNameFilesRenameCreateUrl = (projectId: string, skillName: string) => {
    return `/api/projects/${projectId}/llm_skills/name/${skillName}/files-rename/`
}

export const llmSkillsNameFilesRenameCreate = async (
    projectId: string,
    skillName: string,
    lLMSkillFileRenameApi: LLMSkillFileRenameApi,
    options?: RequestInit
): Promise<LLMSkillApi> => {
    return apiMutator<LLMSkillApi>(getLlmSkillsNameFilesRenameCreateUrl(projectId, skillName), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(lLMSkillFileRenameApi),
    })
}

export const getLlmSkillsNameFilesRetrieveUrl = (
    projectId: string,
    skillName: string,
    filePath: string,
    params?: LlmSkillsNameFilesRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/llm_skills/name/${skillName}/files/${filePath}/?${stringifiedParams}`
        : `/api/projects/${projectId}/llm_skills/name/${skillName}/files/${filePath}/`
}

export const llmSkillsNameFilesRetrieve = async (
    projectId: string,
    skillName: string,
    filePath: string,
    params?: LlmSkillsNameFilesRetrieveParams,
    options?: RequestInit
): Promise<LLMSkillFileApi> => {
    return apiMutator<LLMSkillFileApi>(getLlmSkillsNameFilesRetrieveUrl(projectId, skillName, filePath, params), {
        ...options,
        method: 'GET',
    })
}

export const getLlmSkillsNameFilesDestroyUrl = (
    projectId: string,
    skillName: string,
    filePath: string,
    params?: LlmSkillsNameFilesDestroyParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/llm_skills/name/${skillName}/files/${filePath}/?${stringifiedParams}`
        : `/api/projects/${projectId}/llm_skills/name/${skillName}/files/${filePath}/`
}

export const llmSkillsNameFilesDestroy = async (
    projectId: string,
    skillName: string,
    filePath: string,
    params?: LlmSkillsNameFilesDestroyParams,
    options?: RequestInit
): Promise<LLMSkillApi> => {
    return apiMutator<LLMSkillApi>(getLlmSkillsNameFilesDestroyUrl(projectId, skillName, filePath, params), {
        ...options,
        method: 'DELETE',
    })
}

export const getLlmSkillsResolveNameRetrieveUrl = (
    projectId: string,
    skillName: string,
    params?: LlmSkillsResolveNameRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/llm_skills/resolve/name/${skillName}/?${stringifiedParams}`
        : `/api/projects/${projectId}/llm_skills/resolve/name/${skillName}/`
}

export const llmSkillsResolveNameRetrieve = async (
    projectId: string,
    skillName: string,
    params?: LlmSkillsResolveNameRetrieveParams,
    options?: RequestInit
): Promise<LLMSkillResolveResponseApi> => {
    return apiMutator<LLMSkillResolveResponseApi>(getLlmSkillsResolveNameRetrieveUrl(projectId, skillName, params), {
        ...options,
        method: 'GET',
    })
}
