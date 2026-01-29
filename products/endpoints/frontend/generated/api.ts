/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
import type {
    EndpointLastExecutionTimesRequestApi,
    EndpointRequestApi,
    EndpointRunRequestApi,
    QueryStatusResponseApi,
} from './api.schemas'

/**
 * List all endpoints for the team.
 */
export const getEndpointsRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/endpoints/`
}

export const endpointsRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getEndpointsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create a new endpoint
 */
export const getEndpointsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/endpoints/`
}

export const endpointsCreate = async (
    projectId: string,
    endpointRequestApi: EndpointRequestApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEndpointsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(endpointRequestApi),
    })
}

/**
 * Retrieve an endpoint.
 */
export const getEndpointsRetrieve2Url = (projectId: string, name: string) => {
    return `/api/environments/${projectId}/endpoints/${name}/`
}

export const endpointsRetrieve2 = async (projectId: string, name: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getEndpointsRetrieve2Url(projectId, name), {
        ...options,
        method: 'GET',
    })
}

/**
 * Update an existing endpoint. Parameters are optional. Use ?version=N to update a specific version's is_active status.
 */
export const getEndpointsUpdateUrl = (projectId: string, name: string) => {
    return `/api/environments/${projectId}/endpoints/${name}/`
}

export const endpointsUpdate = async (
    projectId: string,
    name: string,
    endpointRequestApi: EndpointRequestApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEndpointsUpdateUrl(projectId, name), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(endpointRequestApi),
    })
}

export const getEndpointsPartialUpdateUrl = (projectId: string, name: string) => {
    return `/api/environments/${projectId}/endpoints/${name}/`
}

export const endpointsPartialUpdate = async (projectId: string, name: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getEndpointsPartialUpdateUrl(projectId, name), {
        ...options,
        method: 'PATCH',
    })
}

/**
 * Delete an endpoint and clean up materialized query.
 */
export const getEndpointsDestroyUrl = (projectId: string, name: string) => {
    return `/api/environments/${projectId}/endpoints/${name}/`
}

export const endpointsDestroy = async (projectId: string, name: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getEndpointsDestroyUrl(projectId, name), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Get materialization status for an endpoint.
 */
export const getEndpointsMaterializationStatusRetrieveUrl = (projectId: string, name: string) => {
    return `/api/environments/${projectId}/endpoints/${name}/materialization_status/`
}

export const endpointsMaterializationStatusRetrieve = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEndpointsMaterializationStatusRetrieveUrl(projectId, name), {
        ...options,
        method: 'GET',
    })
}

/**
 * Get OpenAPI 3.0 specification for this endpoint. Use this to generate typed SDK clients.
 */
export const getEndpointsOpenapiJsonRetrieveUrl = (projectId: string, name: string) => {
    return `/api/environments/${projectId}/endpoints/${name}/openapi.json/`
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
    return `/api/environments/${projectId}/endpoints/${name}/run/`
}

export const endpointsRunRetrieve = async (projectId: string, name: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getEndpointsRunRetrieveUrl(projectId, name), {
        ...options,
        method: 'GET',
    })
}

/**
 * Execute endpoint with optional materialization. Supports version parameter, runs latest version if not set.
 */
export const getEndpointsRunCreateUrl = (projectId: string, name: string) => {
    return `/api/environments/${projectId}/endpoints/${name}/run/`
}

export const endpointsRunCreate = async (
    projectId: string,
    name: string,
    endpointRunRequestApi: EndpointRunRequestApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEndpointsRunCreateUrl(projectId, name), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(endpointRunRequestApi),
    })
}

/**
 * List all versions for an endpoint.
 */
export const getEndpointsVersionsRetrieveUrl = (projectId: string, name: string) => {
    return `/api/environments/${projectId}/endpoints/${name}/versions/`
}

export const endpointsVersionsRetrieve = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEndpointsVersionsRetrieveUrl(projectId, name), {
        ...options,
        method: 'GET',
    })
}

/**
 * Get details of a specific endpoint version.
 */
export const getEndpointsVersionsRetrieve2Url = (projectId: string, name: string, versionNumber: string) => {
    return `/api/environments/${projectId}/endpoints/${name}/versions/${versionNumber}/`
}

export const endpointsVersionsRetrieve2 = async (
    projectId: string,
    name: string,
    versionNumber: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEndpointsVersionsRetrieve2Url(projectId, name, versionNumber), {
        ...options,
        method: 'GET',
    })
}

/**
 * Get the last execution times in the past 6 months for multiple endpoints.
 */
export const getEndpointsLastExecutionTimesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/endpoints/last_execution_times/`
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

/**
 * List all endpoints for the team.
 */
export const getEndpointsRetrieve3Url = (projectId: string) => {
    return `/api/projects/${projectId}/endpoints/`
}

export const endpointsRetrieve3 = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getEndpointsRetrieve3Url(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create a new endpoint
 */
export const getEndpointsCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/endpoints/`
}

export const endpointsCreate2 = async (
    projectId: string,
    endpointRequestApi: EndpointRequestApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEndpointsCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(endpointRequestApi),
    })
}

/**
 * Retrieve an endpoint.
 */
export const getEndpointsRetrieve4Url = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/`
}

export const endpointsRetrieve4 = async (projectId: string, name: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getEndpointsRetrieve4Url(projectId, name), {
        ...options,
        method: 'GET',
    })
}

/**
 * Update an existing endpoint. Parameters are optional. Use ?version=N to update a specific version's is_active status.
 */
export const getEndpointsUpdate2Url = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/`
}

export const endpointsUpdate2 = async (
    projectId: string,
    name: string,
    endpointRequestApi: EndpointRequestApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEndpointsUpdate2Url(projectId, name), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(endpointRequestApi),
    })
}

export const getEndpointsPartialUpdate2Url = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/`
}

export const endpointsPartialUpdate2 = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEndpointsPartialUpdate2Url(projectId, name), {
        ...options,
        method: 'PATCH',
    })
}

/**
 * Delete an endpoint and clean up materialized query.
 */
export const getEndpointsDestroy2Url = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/`
}

export const endpointsDestroy2 = async (projectId: string, name: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getEndpointsDestroy2Url(projectId, name), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Get materialization status for an endpoint.
 */
export const getEndpointsMaterializationStatusRetrieve2Url = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/materialization_status/`
}

export const endpointsMaterializationStatusRetrieve2 = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEndpointsMaterializationStatusRetrieve2Url(projectId, name), {
        ...options,
        method: 'GET',
    })
}

/**
 * Get OpenAPI 3.0 specification for this endpoint. Use this to generate typed SDK clients.
 */
export const getEndpointsOpenapiJsonRetrieve2Url = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/openapi.json/`
}

export const endpointsOpenapiJsonRetrieve2 = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEndpointsOpenapiJsonRetrieve2Url(projectId, name), {
        ...options,
        method: 'GET',
    })
}

/**
 * Execute endpoint with optional materialization. Supports version parameter, runs latest version if not set.
 */
export const getEndpointsRunRetrieve2Url = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/run/`
}

export const endpointsRunRetrieve2 = async (projectId: string, name: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getEndpointsRunRetrieve2Url(projectId, name), {
        ...options,
        method: 'GET',
    })
}

/**
 * Execute endpoint with optional materialization. Supports version parameter, runs latest version if not set.
 */
export const getEndpointsRunCreate2Url = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/run/`
}

export const endpointsRunCreate2 = async (
    projectId: string,
    name: string,
    endpointRunRequestApi: EndpointRunRequestApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEndpointsRunCreate2Url(projectId, name), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(endpointRunRequestApi),
    })
}

/**
 * List all versions for an endpoint.
 */
export const getEndpointsVersionsRetrieve3Url = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/versions/`
}

export const endpointsVersionsRetrieve3 = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEndpointsVersionsRetrieve3Url(projectId, name), {
        ...options,
        method: 'GET',
    })
}

/**
 * Get details of a specific endpoint version.
 */
export const getEndpointsVersionsRetrieve4Url = (projectId: string, name: string, versionNumber: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/versions/${versionNumber}/`
}

export const endpointsVersionsRetrieve4 = async (
    projectId: string,
    name: string,
    versionNumber: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEndpointsVersionsRetrieve4Url(projectId, name, versionNumber), {
        ...options,
        method: 'GET',
    })
}

/**
 * Get the last execution times in the past 6 months for multiple endpoints.
 */
export const getEndpointsLastExecutionTimesCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/endpoints/last_execution_times/`
}

export const endpointsLastExecutionTimesCreate2 = async (
    projectId: string,
    endpointLastExecutionTimesRequestApi: EndpointLastExecutionTimesRequestApi,
    options?: RequestInit
): Promise<QueryStatusResponseApi> => {
    return apiMutator<QueryStatusResponseApi>(getEndpointsLastExecutionTimesCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(endpointLastExecutionTimesRequestApi),
    })
}
