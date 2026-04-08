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
    EndpointLastExecutionTimesRequestApi,
    EndpointMaterializationApi,
    EndpointRequestApi,
    EndpointResponseApi,
    EndpointRunRequestApi,
    EndpointRunResponseApi,
    EndpointVersionResponseApi,
    EndpointsListParams,
    EndpointsVersionsListParams,
    MaterializationPreviewRequestApi,
    PaginatedEndpointResponseListApi,
    PaginatedEndpointVersionResponseListApi,
    PatchedEndpointRequestApi,
    QueryStatusResponseApi,
} from './api.schemas'

/**
 * List all endpoints for the team.
 */
export const getEndpointsListUrl = (projectId: string, params?: EndpointsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/endpoints/?${stringifiedParams}`
        : `/api/projects/${projectId}/endpoints/`
}

export const endpointsList = async (
    projectId: string,
    params?: EndpointsListParams,
    options?: RequestInit
): Promise<PaginatedEndpointResponseListApi> => {
    return apiMutator<PaginatedEndpointResponseListApi>(getEndpointsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create a new endpoint.
 */
export const getEndpointsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/endpoints/`
}

export const endpointsCreate = async (
    projectId: string,
    endpointRequestApi: EndpointRequestApi,
    options?: RequestInit
): Promise<EndpointResponseApi> => {
    return apiMutator<EndpointResponseApi>(getEndpointsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(endpointRequestApi),
    })
}

/**
 * Retrieve an endpoint, or a specific version via ?version=N.
 */
export const getEndpointsRetrieveUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/`
}

export const endpointsRetrieve = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<EndpointVersionResponseApi> => {
    return apiMutator<EndpointVersionResponseApi>(getEndpointsRetrieveUrl(projectId, name), {
        ...options,
        method: 'GET',
    })
}

/**
 * Update an existing endpoint. Parameters are optional. Pass version in body or ?version=N query param to target a specific version.
 */
export const getEndpointsUpdateUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/`
}

export const endpointsUpdate = async (
    projectId: string,
    name: string,
    endpointRequestApi: EndpointRequestApi,
    options?: RequestInit
): Promise<EndpointResponseApi> => {
    return apiMutator<EndpointResponseApi>(getEndpointsUpdateUrl(projectId, name), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(endpointRequestApi),
    })
}

/**
 * Update an existing endpoint.
 */
export const getEndpointsPartialUpdateUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/`
}

export const endpointsPartialUpdate = async (
    projectId: string,
    name: string,
    patchedEndpointRequestApi: PatchedEndpointRequestApi,
    options?: RequestInit
): Promise<EndpointResponseApi> => {
    return apiMutator<EndpointResponseApi>(getEndpointsPartialUpdateUrl(projectId, name), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedEndpointRequestApi),
    })
}

/**
 * Delete an endpoint and clean up materialized query.
 */
export const getEndpointsDestroyUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/`
}

export const endpointsDestroy = async (projectId: string, name: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getEndpointsDestroyUrl(projectId, name), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Preview the materialization transform for an endpoint. Shows what the query will look like after materialization, including range pair detection and bucket functions.
 */
export const getEndpointsMaterializationPreviewCreateUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/materialization_preview/`
}

export const endpointsMaterializationPreviewCreate = async (
    projectId: string,
    name: string,
    materializationPreviewRequestApi: MaterializationPreviewRequestApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEndpointsMaterializationPreviewCreateUrl(projectId, name), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(materializationPreviewRequestApi),
    })
}

/**
 * Get materialization status for an endpoint. Supports ?version=N query param.
 */
export const getEndpointsMaterializationStatusRetrieveUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/materialization_status/`
}

export const endpointsMaterializationStatusRetrieve = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<EndpointMaterializationApi> => {
    return apiMutator<EndpointMaterializationApi>(getEndpointsMaterializationStatusRetrieveUrl(projectId, name), {
        ...options,
        method: 'GET',
    })
}

/**
 * Get OpenAPI 3.0 specification for this endpoint. Use this to generate typed SDK clients.
 */
export const getEndpointsOpenapiJsonRetrieveUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/openapi.json/`
}

export const endpointsOpenapiJsonRetrieve = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEndpointsOpenapiJsonRetrieveUrl(projectId, name), {
        ...options,
        method: 'GET',
    })
}

/**
 * Execute endpoint with optional materialization. Supports version parameter, runs latest version if not set.
 */
export const getEndpointsRunRetrieveUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/run/`
}

export const endpointsRunRetrieve = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<EndpointRunResponseApi> => {
    return apiMutator<EndpointRunResponseApi>(getEndpointsRunRetrieveUrl(projectId, name), {
        ...options,
        method: 'GET',
    })
}

/**
 * Execute endpoint with optional materialization. Supports version parameter, runs latest version if not set.
 */
export const getEndpointsRunCreateUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/run/`
}

export const endpointsRunCreate = async (
    projectId: string,
    name: string,
    endpointRunRequestApi: EndpointRunRequestApi,
    options?: RequestInit
): Promise<EndpointRunResponseApi> => {
    return apiMutator<EndpointRunResponseApi>(getEndpointsRunCreateUrl(projectId, name), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(endpointRunRequestApi),
    })
}

/**
 * List all versions for an endpoint.
 */
export const getEndpointsVersionsListUrl = (projectId: string, name: string, params?: EndpointsVersionsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/endpoints/${name}/versions/?${stringifiedParams}`
        : `/api/projects/${projectId}/endpoints/${name}/versions/`
}

export const endpointsVersionsList = async (
    projectId: string,
    name: string,
    params?: EndpointsVersionsListParams,
    options?: RequestInit
): Promise<PaginatedEndpointVersionResponseListApi> => {
    return apiMutator<PaginatedEndpointVersionResponseListApi>(getEndpointsVersionsListUrl(projectId, name, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Get the last execution times in the past 6 months for multiple endpoints.
 */
export const getEndpointsLastExecutionTimesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/endpoints/last_execution_times/`
}

export const endpointsLastExecutionTimesCreate = async (
    projectId: string,
    endpointLastExecutionTimesRequestApi: EndpointLastExecutionTimesRequestApi,
    options?: RequestInit
): Promise<QueryStatusResponseApi> => {
    return apiMutator<QueryStatusResponseApi>(getEndpointsLastExecutionTimesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(endpointLastExecutionTimesRequestApi),
    })
}
