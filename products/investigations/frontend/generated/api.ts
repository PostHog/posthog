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
    InvestigationCreateApi,
    InvestigationListApi,
    InvestigationsListParams,
    PatchedInvestigationUpdateApi,
    SavedInvestigationApi,
} from './api.schemas'

export const getInvestigationsListUrl = (projectId: string, params?: InvestigationsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/investigations/?${stringifiedParams}`
        : `/api/projects/${projectId}/investigations/`
}

export const investigationsList = async (
    projectId: string,
    params?: InvestigationsListParams,
    options?: RequestInit
): Promise<InvestigationListApi> => {
    return apiMutator<InvestigationListApi>(getInvestigationsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getInvestigationsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/investigations/`
}

export const investigationsCreate = async (
    projectId: string,
    investigationCreateApi: InvestigationCreateApi,
    options?: RequestInit
): Promise<SavedInvestigationApi> => {
    return apiMutator<SavedInvestigationApi>(getInvestigationsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(investigationCreateApi),
    })
}

export const getInvestigationsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/investigations/${id}/`
}

export const investigationsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<SavedInvestigationApi> => {
    return apiMutator<SavedInvestigationApi>(getInvestigationsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getInvestigationsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/investigations/${id}/`
}

export const investigationsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedInvestigationUpdateApi?: PatchedInvestigationUpdateApi,
    options?: RequestInit
): Promise<SavedInvestigationApi> => {
    return apiMutator<SavedInvestigationApi>(getInvestigationsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedInvestigationUpdateApi),
    })
}
