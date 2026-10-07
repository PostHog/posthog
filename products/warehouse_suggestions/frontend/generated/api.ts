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
    DismissWarehouseSuggestionApi,
    PaginatedWarehouseSuggestionListApi,
    WarehouseSuggestionApi,
    WarehouseSuggestionStatusApi,
    WarehouseSuggestionsListParams,
} from './api.schemas'

export const getWarehouseSuggestionsListUrl = (projectId: string, params?: WarehouseSuggestionsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/warehouse_suggestions/?${stringifiedParams}`
        : `/api/projects/${projectId}/warehouse_suggestions/`
}

export const warehouseSuggestionsList = async (
    projectId: string,
    params?: WarehouseSuggestionsListParams,
    options?: RequestInit
): Promise<PaginatedWarehouseSuggestionListApi> => {
    return apiMutator<PaginatedWarehouseSuggestionListApi>(getWarehouseSuggestionsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getWarehouseSuggestionsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_suggestions/${id}/`
}

export const warehouseSuggestionsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<WarehouseSuggestionApi> => {
    return apiMutator<WarehouseSuggestionApi>(getWarehouseSuggestionsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getWarehouseSuggestionsDismissCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_suggestions/${id}/dismiss/`
}

export const warehouseSuggestionsDismissCreate = async (
    projectId: string,
    id: string,
    dismissWarehouseSuggestionApi: DismissWarehouseSuggestionApi,
    options?: RequestInit
): Promise<WarehouseSuggestionApi> => {
    return apiMutator<WarehouseSuggestionApi>(getWarehouseSuggestionsDismissCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(dismissWarehouseSuggestionApi),
    })
}

export const getWarehouseSuggestionsResumeCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/warehouse_suggestions/${id}/resume/`
}

export const warehouseSuggestionsResumeCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<WarehouseSuggestionApi> => {
    return apiMutator<WarehouseSuggestionApi>(getWarehouseSuggestionsResumeCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getWarehouseSuggestionsStatusRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/warehouse_suggestions/status/`
}

export const warehouseSuggestionsStatusRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<WarehouseSuggestionStatusApi> => {
    return apiMutator<WarehouseSuggestionStatusApi>(getWarehouseSuggestionsStatusRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}
