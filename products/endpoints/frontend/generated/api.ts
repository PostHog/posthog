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
    EndpointMaterializationConditionsApi,
    EndpointMaterializationSuggestionApi,
    EndpointMaterializationSuggestionRequestApi,
    EndpointRequestApi,
    EndpointResponseApi,
    EndpointRunRequestApi,
    EndpointRunResponseApi,
    EndpointVersionResponseApi,
    EndpointsListParams,
    EndpointsLogsRetrieveParams,
    EndpointsOpenapiSpecRetrieveParams,
    EndpointsVersionsListParams,
    MaterializationPreviewRequestApi,
    PaginatedEndpointResponseListApi,
    PaginatedEndpointVersionResponseListApi,
    PatchedEndpointRequestApi,
    QueryStatusResponseApi,
} from './api.schemas'

export const getEndpointsListUrl = (projectId: string, params?: EndpointsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/endpoints/?${stringifiedParams}`
        : `/api/projects/${projectId}/endpoints/`
}

/**
 * List all endpoints for the team.
 */
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

export const getEndpointsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/endpoints/`
}

/**
 * Create a new endpoint.
 */
export const endpointsCreate = async (
    projectId: string,
    endpointRequestApi?: EndpointRequestApi,
    options?: RequestInit
): Promise<EndpointResponseApi> => {
    return apiMutator<EndpointResponseApi>(getEndpointsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(endpointRequestApi),
    })
}

export const getEndpointsRetrieveUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/`
}

/**
 * Retrieve an endpoint, or a specific version via ?version=N.
 */
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

export const getEndpointsUpdateUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/`
}

/**
 * Update an existing endpoint. Parameters are optional. Pass version in body or ?version=N query param to target a specific version.
 */
export const endpointsUpdate = async (
    projectId: string,
    name: string,
    endpointRequestApi?: EndpointRequestApi,
    options?: RequestInit
): Promise<EndpointResponseApi> => {
    return apiMutator<EndpointResponseApi>(getEndpointsUpdateUrl(projectId, name), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(endpointRequestApi),
    })
}

export const getEndpointsPartialUpdateUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/`
}

/**
 * Update an existing endpoint.
 */
export const endpointsPartialUpdate = async (
    projectId: string,
    name: string,
    patchedEndpointRequestApi?: PatchedEndpointRequestApi,
    options?: RequestInit
): Promise<EndpointResponseApi> => {
    return apiMutator<EndpointResponseApi>(getEndpointsPartialUpdateUrl(projectId, name), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedEndpointRequestApi),
    })
}

export const getEndpointsDestroyUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/`
}

/**
 * Delete an endpoint and clean up materialized query.
 */
export const endpointsDestroy = async (projectId: string, name: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getEndpointsDestroyUrl(projectId, name), {
        ...options,
        method: 'DELETE',
    })
}

export const getEndpointsLogsRetrieveUrl = (projectId: string, name: string, params?: EndpointsLogsRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/endpoints/${name}/logs/?${stringifiedParams}`
        : `/api/projects/${projectId}/endpoints/${name}/logs/`
}

export const endpointsLogsRetrieve = async (
    projectId: string,
    name: string,
    params?: EndpointsLogsRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEndpointsLogsRetrieveUrl(projectId, name, params), {
        ...options,
        method: 'GET',
    })
}

export const getEndpointsMaterializationPreviewCreateUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/materialization_preview/`
}

/**
 * Preview the materialization transform for an endpoint. Shows what the query will look like after materialization, including range pair detection and bucket functions.
 */
export const endpointsMaterializationPreviewCreate = async (
    projectId: string,
    name: string,
    materializationPreviewRequestApi?: MaterializationPreviewRequestApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEndpointsMaterializationPreviewCreateUrl(projectId, name), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(materializationPreviewRequestApi),
    })
}

export const getEndpointsMaterializationStatusRetrieveUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/materialization_status/`
}

/**
 * Get materialization status for an endpoint. Supports ?version=N query param.
 */
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

export const getEndpointsMaterializationSuggestionCreateUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/materialization_suggestion/`
}

/**
 * Ask AI to rewrite the endpoint's query into a semantically equivalent form that can be materialized. Only applicable to SQL (HogQL) endpoints that currently fail the materialization checks. The suggestion is validated against the live checks before being returned; nothing is saved. Requires the organization's AI data processing approval.
 */
export const endpointsMaterializationSuggestionCreate = async (
    projectId: string,
    name: string,
    endpointMaterializationSuggestionRequestApi?: EndpointMaterializationSuggestionRequestApi,
    options?: RequestInit
): Promise<EndpointMaterializationSuggestionApi> => {
    return apiMutator<EndpointMaterializationSuggestionApi>(
        getEndpointsMaterializationSuggestionCreateUrl(projectId, name),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(endpointMaterializationSuggestionRequestApi),
        }
    )
}

export const getEndpointsOpenapiSpecRetrieveUrl = (
    projectId: string,
    name: string,
    params?: EndpointsOpenapiSpecRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/endpoints/${name}/openapi.json/?${stringifiedParams}`
        : `/api/projects/${projectId}/endpoints/${name}/openapi.json/`
}

/**
 * Get OpenAPI 3.0 specification for this endpoint. Use this to generate typed SDK clients.
 */
export const endpointsOpenapiSpecRetrieve = async (
    projectId: string,
    name: string,
    params?: EndpointsOpenapiSpecRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEndpointsOpenapiSpecRetrieveUrl(projectId, name, params), {
        ...options,
        method: 'GET',
    })
}

export const getEndpointsRunRetrieveUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/run/`
}

/**
 * Execute endpoint with optional materialization. Supports version parameter, runs latest version if not set.
 */
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

export const getEndpointsRunCreateUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/run/`
}

/**
 * Execute endpoint with optional materialization. Supports version parameter, runs latest version if not set.
 */
export const endpointsRunCreate = async (
    projectId: string,
    name: string,
    endpointRunRequestApi?: EndpointRunRequestApi,
    options?: RequestInit
): Promise<EndpointRunResponseApi> => {
    return apiMutator<EndpointRunResponseApi>(getEndpointsRunCreateUrl(projectId, name), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(endpointRunRequestApi),
    })
}

export const getEndpointsVersionsListUrl = (projectId: string, name: string, params?: EndpointsVersionsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/endpoints/${name}/versions/?${stringifiedParams}`
        : `/api/projects/${projectId}/endpoints/${name}/versions/`
}

/**
 * List all versions for an endpoint.
 */
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

export const getEndpointsLastExecutionTimesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/endpoints/last_execution_times/`
}

/**
 * Get the most recent execution time per endpoint (endpoint-level). Timestamps are recorded by the run path for personal-API-key calls. For per-version usage, query the query_log table directly.
 */
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

export const getEndpointsMaterializationConditionsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/endpoints/materialization_conditions/`
}

/**
 * Get the source code of the live materialization checks, plus the rewrite contract. Lets an agent rewrite a rejected endpoint query itself: fetch these conditions, produce a semantically equivalent query that passes every check, update the endpoint with it, then confirm via materialization_status. The source is read from the running system, so it always matches the checks this instance enforces.
 */
export const endpointsMaterializationConditionsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<EndpointMaterializationConditionsApi> => {
    return apiMutator<EndpointMaterializationConditionsApi>(
        getEndpointsMaterializationConditionsRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}
