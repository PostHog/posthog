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
export type environmentsEndpointsRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsEndpointsRetrieveResponseSuccess = environmentsEndpointsRetrieveResponse200 & {
    headers: Headers
}
export type environmentsEndpointsRetrieveResponse = environmentsEndpointsRetrieveResponseSuccess

export const getEnvironmentsEndpointsRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/endpoints/`
}

export const environmentsEndpointsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsEndpointsRetrieveResponse> => {
    return apiMutator<environmentsEndpointsRetrieveResponse>(getEnvironmentsEndpointsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create a new endpoint
 */
export type environmentsEndpointsCreateResponse201 = {
    data: void
    status: 201
}

export type environmentsEndpointsCreateResponseSuccess = environmentsEndpointsCreateResponse201 & {
    headers: Headers
}
export type environmentsEndpointsCreateResponse = environmentsEndpointsCreateResponseSuccess

export const getEnvironmentsEndpointsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/endpoints/`
}

export const environmentsEndpointsCreate = async (
    projectId: string,
    endpointRequestApi: EndpointRequestApi,
    options?: RequestInit
): Promise<environmentsEndpointsCreateResponse> => {
    return apiMutator<environmentsEndpointsCreateResponse>(getEnvironmentsEndpointsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(endpointRequestApi),
    })
}

/**
 * Retrieve an endpoint.
 */
export type environmentsEndpointsRetrieve2Response200 = {
    data: void
    status: 200
}

export type environmentsEndpointsRetrieve2ResponseSuccess = environmentsEndpointsRetrieve2Response200 & {
    headers: Headers
}
export type environmentsEndpointsRetrieve2Response = environmentsEndpointsRetrieve2ResponseSuccess

export const getEnvironmentsEndpointsRetrieve2Url = (projectId: string, name: string) => {
    return `/api/environments/${projectId}/endpoints/${name}/`
}

export const environmentsEndpointsRetrieve2 = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<environmentsEndpointsRetrieve2Response> => {
    return apiMutator<environmentsEndpointsRetrieve2Response>(getEnvironmentsEndpointsRetrieve2Url(projectId, name), {
        ...options,
        method: 'GET',
    })
}

/**
 * Update an existing endpoint. Parameters are optional.
 */
export type environmentsEndpointsUpdateResponse200 = {
    data: void
    status: 200
}

export type environmentsEndpointsUpdateResponseSuccess = environmentsEndpointsUpdateResponse200 & {
    headers: Headers
}
export type environmentsEndpointsUpdateResponse = environmentsEndpointsUpdateResponseSuccess

export const getEnvironmentsEndpointsUpdateUrl = (projectId: string, name: string) => {
    return `/api/environments/${projectId}/endpoints/${name}/`
}

export const environmentsEndpointsUpdate = async (
    projectId: string,
    name: string,
    endpointRequestApi: EndpointRequestApi,
    options?: RequestInit
): Promise<environmentsEndpointsUpdateResponse> => {
    return apiMutator<environmentsEndpointsUpdateResponse>(getEnvironmentsEndpointsUpdateUrl(projectId, name), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(endpointRequestApi),
    })
}

export type environmentsEndpointsPartialUpdateResponse200 = {
    data: void
    status: 200
}

export type environmentsEndpointsPartialUpdateResponseSuccess = environmentsEndpointsPartialUpdateResponse200 & {
    headers: Headers
}
export type environmentsEndpointsPartialUpdateResponse = environmentsEndpointsPartialUpdateResponseSuccess

export const getEnvironmentsEndpointsPartialUpdateUrl = (projectId: string, name: string) => {
    return `/api/environments/${projectId}/endpoints/${name}/`
}

export const environmentsEndpointsPartialUpdate = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<environmentsEndpointsPartialUpdateResponse> => {
    return apiMutator<environmentsEndpointsPartialUpdateResponse>(
        getEnvironmentsEndpointsPartialUpdateUrl(projectId, name),
        {
            ...options,
            method: 'PATCH',
        }
    )
}

/**
 * Delete an endpoint and clean up materialized query.
 */
export type environmentsEndpointsDestroyResponse204 = {
    data: void
    status: 204
}

export type environmentsEndpointsDestroyResponseSuccess = environmentsEndpointsDestroyResponse204 & {
    headers: Headers
}
export type environmentsEndpointsDestroyResponse = environmentsEndpointsDestroyResponseSuccess

export const getEnvironmentsEndpointsDestroyUrl = (projectId: string, name: string) => {
    return `/api/environments/${projectId}/endpoints/${name}/`
}

export const environmentsEndpointsDestroy = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<environmentsEndpointsDestroyResponse> => {
    return apiMutator<environmentsEndpointsDestroyResponse>(getEnvironmentsEndpointsDestroyUrl(projectId, name), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Get materialization status for an endpoint.
 */
export type environmentsEndpointsMaterializationStatusRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsEndpointsMaterializationStatusRetrieveResponseSuccess =
    environmentsEndpointsMaterializationStatusRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsEndpointsMaterializationStatusRetrieveResponse =
    environmentsEndpointsMaterializationStatusRetrieveResponseSuccess

export const getEnvironmentsEndpointsMaterializationStatusRetrieveUrl = (projectId: string, name: string) => {
    return `/api/environments/${projectId}/endpoints/${name}/materialization_status/`
}

export const environmentsEndpointsMaterializationStatusRetrieve = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<environmentsEndpointsMaterializationStatusRetrieveResponse> => {
    return apiMutator<environmentsEndpointsMaterializationStatusRetrieveResponse>(
        getEnvironmentsEndpointsMaterializationStatusRetrieveUrl(projectId, name),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Get OpenAPI 3.0 specification for this endpoint. Use this to generate typed SDK clients.
 */
export type environmentsEndpointsOpenapiJsonRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsEndpointsOpenapiJsonRetrieveResponseSuccess =
    environmentsEndpointsOpenapiJsonRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsEndpointsOpenapiJsonRetrieveResponse = environmentsEndpointsOpenapiJsonRetrieveResponseSuccess

export const getEnvironmentsEndpointsOpenapiJsonRetrieveUrl = (projectId: string, name: string) => {
    return `/api/environments/${projectId}/endpoints/${name}/openapi.json/`
}

export const environmentsEndpointsOpenapiJsonRetrieve = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<environmentsEndpointsOpenapiJsonRetrieveResponse> => {
    return apiMutator<environmentsEndpointsOpenapiJsonRetrieveResponse>(
        getEnvironmentsEndpointsOpenapiJsonRetrieveUrl(projectId, name),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Execute endpoint with optional materialization. Supports version parameter, runs latest version if not set.
 */
export type environmentsEndpointsRunRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsEndpointsRunRetrieveResponseSuccess = environmentsEndpointsRunRetrieveResponse200 & {
    headers: Headers
}
export type environmentsEndpointsRunRetrieveResponse = environmentsEndpointsRunRetrieveResponseSuccess

export const getEnvironmentsEndpointsRunRetrieveUrl = (projectId: string, name: string) => {
    return `/api/environments/${projectId}/endpoints/${name}/run/`
}

export const environmentsEndpointsRunRetrieve = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<environmentsEndpointsRunRetrieveResponse> => {
    return apiMutator<environmentsEndpointsRunRetrieveResponse>(
        getEnvironmentsEndpointsRunRetrieveUrl(projectId, name),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Execute endpoint with optional materialization. Supports version parameter, runs latest version if not set.
 */
export type environmentsEndpointsRunCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsEndpointsRunCreateResponseSuccess = environmentsEndpointsRunCreateResponse200 & {
    headers: Headers
}
export type environmentsEndpointsRunCreateResponse = environmentsEndpointsRunCreateResponseSuccess

export const getEnvironmentsEndpointsRunCreateUrl = (projectId: string, name: string) => {
    return `/api/environments/${projectId}/endpoints/${name}/run/`
}

export const environmentsEndpointsRunCreate = async (
    projectId: string,
    name: string,
    endpointRunRequestApi: EndpointRunRequestApi,
    options?: RequestInit
): Promise<environmentsEndpointsRunCreateResponse> => {
    return apiMutator<environmentsEndpointsRunCreateResponse>(getEnvironmentsEndpointsRunCreateUrl(projectId, name), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(endpointRunRequestApi),
    })
}

/**
 * List all versions for an endpoint.
 */
export type environmentsEndpointsVersionsRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsEndpointsVersionsRetrieveResponseSuccess = environmentsEndpointsVersionsRetrieveResponse200 & {
    headers: Headers
}
export type environmentsEndpointsVersionsRetrieveResponse = environmentsEndpointsVersionsRetrieveResponseSuccess

export const getEnvironmentsEndpointsVersionsRetrieveUrl = (projectId: string, name: string) => {
    return `/api/environments/${projectId}/endpoints/${name}/versions/`
}

export const environmentsEndpointsVersionsRetrieve = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<environmentsEndpointsVersionsRetrieveResponse> => {
    return apiMutator<environmentsEndpointsVersionsRetrieveResponse>(
        getEnvironmentsEndpointsVersionsRetrieveUrl(projectId, name),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Get details of a specific endpoint version.
 */
export type environmentsEndpointsVersionsRetrieve2Response200 = {
    data: void
    status: 200
}

export type environmentsEndpointsVersionsRetrieve2ResponseSuccess =
    environmentsEndpointsVersionsRetrieve2Response200 & {
        headers: Headers
    }
export type environmentsEndpointsVersionsRetrieve2Response = environmentsEndpointsVersionsRetrieve2ResponseSuccess

export const getEnvironmentsEndpointsVersionsRetrieve2Url = (
    projectId: string,
    name: string,
    versionNumber: string
) => {
    return `/api/environments/${projectId}/endpoints/${name}/versions/${versionNumber}/`
}

export const environmentsEndpointsVersionsRetrieve2 = async (
    projectId: string,
    name: string,
    versionNumber: string,
    options?: RequestInit
): Promise<environmentsEndpointsVersionsRetrieve2Response> => {
    return apiMutator<environmentsEndpointsVersionsRetrieve2Response>(
        getEnvironmentsEndpointsVersionsRetrieve2Url(projectId, name, versionNumber),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Get the last execution times in the past 6 months for multiple endpoints.
 */
export type environmentsEndpointsLastExecutionTimesCreateResponse200 = {
    data: QueryStatusResponseApi
    status: 200
}

export type environmentsEndpointsLastExecutionTimesCreateResponseSuccess =
    environmentsEndpointsLastExecutionTimesCreateResponse200 & {
        headers: Headers
    }
export type environmentsEndpointsLastExecutionTimesCreateResponse =
    environmentsEndpointsLastExecutionTimesCreateResponseSuccess

export const getEnvironmentsEndpointsLastExecutionTimesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/endpoints/last_execution_times/`
}

export const environmentsEndpointsLastExecutionTimesCreate = async (
    projectId: string,
    endpointLastExecutionTimesRequestApi: EndpointLastExecutionTimesRequestApi,
    options?: RequestInit
): Promise<environmentsEndpointsLastExecutionTimesCreateResponse> => {
    return apiMutator<environmentsEndpointsLastExecutionTimesCreateResponse>(
        getEnvironmentsEndpointsLastExecutionTimesCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(endpointLastExecutionTimesRequestApi),
        }
    )
}

/**
 * List all endpoints for the team.
 */
export type endpointsRetrieveResponse200 = {
    data: void
    status: 200
}

export type endpointsRetrieveResponseSuccess = endpointsRetrieveResponse200 & {
    headers: Headers
}
export type endpointsRetrieveResponse = endpointsRetrieveResponseSuccess

export const getEndpointsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/endpoints/`
}

export const endpointsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<endpointsRetrieveResponse> => {
    return apiMutator<endpointsRetrieveResponse>(getEndpointsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create a new endpoint
 */
export type endpointsCreateResponse201 = {
    data: void
    status: 201
}

export type endpointsCreateResponseSuccess = endpointsCreateResponse201 & {
    headers: Headers
}
export type endpointsCreateResponse = endpointsCreateResponseSuccess

export const getEndpointsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/endpoints/`
}

export const endpointsCreate = async (
    projectId: string,
    endpointRequestApi: EndpointRequestApi,
    options?: RequestInit
): Promise<endpointsCreateResponse> => {
    return apiMutator<endpointsCreateResponse>(getEndpointsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(endpointRequestApi),
    })
}

/**
 * Retrieve an endpoint.
 */
export type endpointsRetrieve2Response200 = {
    data: void
    status: 200
}

export type endpointsRetrieve2ResponseSuccess = endpointsRetrieve2Response200 & {
    headers: Headers
}
export type endpointsRetrieve2Response = endpointsRetrieve2ResponseSuccess

export const getEndpointsRetrieve2Url = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/`
}

export const endpointsRetrieve2 = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<endpointsRetrieve2Response> => {
    return apiMutator<endpointsRetrieve2Response>(getEndpointsRetrieve2Url(projectId, name), {
        ...options,
        method: 'GET',
    })
}

/**
 * Update an existing endpoint. Parameters are optional.
 */
export type endpointsUpdateResponse200 = {
    data: void
    status: 200
}

export type endpointsUpdateResponseSuccess = endpointsUpdateResponse200 & {
    headers: Headers
}
export type endpointsUpdateResponse = endpointsUpdateResponseSuccess

export const getEndpointsUpdateUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/`
}

export const endpointsUpdate = async (
    projectId: string,
    name: string,
    endpointRequestApi: EndpointRequestApi,
    options?: RequestInit
): Promise<endpointsUpdateResponse> => {
    return apiMutator<endpointsUpdateResponse>(getEndpointsUpdateUrl(projectId, name), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(endpointRequestApi),
    })
}

export type endpointsPartialUpdateResponse200 = {
    data: void
    status: 200
}

export type endpointsPartialUpdateResponseSuccess = endpointsPartialUpdateResponse200 & {
    headers: Headers
}
export type endpointsPartialUpdateResponse = endpointsPartialUpdateResponseSuccess

export const getEndpointsPartialUpdateUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/`
}

export const endpointsPartialUpdate = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<endpointsPartialUpdateResponse> => {
    return apiMutator<endpointsPartialUpdateResponse>(getEndpointsPartialUpdateUrl(projectId, name), {
        ...options,
        method: 'PATCH',
    })
}

/**
 * Delete an endpoint and clean up materialized query.
 */
export type endpointsDestroyResponse204 = {
    data: void
    status: 204
}

export type endpointsDestroyResponseSuccess = endpointsDestroyResponse204 & {
    headers: Headers
}
export type endpointsDestroyResponse = endpointsDestroyResponseSuccess

export const getEndpointsDestroyUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/`
}

export const endpointsDestroy = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<endpointsDestroyResponse> => {
    return apiMutator<endpointsDestroyResponse>(getEndpointsDestroyUrl(projectId, name), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Get materialization status for an endpoint.
 */
export type endpointsMaterializationStatusRetrieveResponse200 = {
    data: void
    status: 200
}

export type endpointsMaterializationStatusRetrieveResponseSuccess =
    endpointsMaterializationStatusRetrieveResponse200 & {
        headers: Headers
    }
export type endpointsMaterializationStatusRetrieveResponse = endpointsMaterializationStatusRetrieveResponseSuccess

export const getEndpointsMaterializationStatusRetrieveUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/materialization_status/`
}

export const endpointsMaterializationStatusRetrieve = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<endpointsMaterializationStatusRetrieveResponse> => {
    return apiMutator<endpointsMaterializationStatusRetrieveResponse>(
        getEndpointsMaterializationStatusRetrieveUrl(projectId, name),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Get OpenAPI 3.0 specification for this endpoint. Use this to generate typed SDK clients.
 */
export type endpointsOpenapiJsonRetrieveResponse200 = {
    data: void
    status: 200
}

export type endpointsOpenapiJsonRetrieveResponseSuccess = endpointsOpenapiJsonRetrieveResponse200 & {
    headers: Headers
}
export type endpointsOpenapiJsonRetrieveResponse = endpointsOpenapiJsonRetrieveResponseSuccess

export const getEndpointsOpenapiJsonRetrieveUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/openapi.json/`
}

export const endpointsOpenapiJsonRetrieve = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<endpointsOpenapiJsonRetrieveResponse> => {
    return apiMutator<endpointsOpenapiJsonRetrieveResponse>(getEndpointsOpenapiJsonRetrieveUrl(projectId, name), {
        ...options,
        method: 'GET',
    })
}

/**
 * Execute endpoint with optional materialization. Supports version parameter, runs latest version if not set.
 */
export type endpointsRunRetrieveResponse200 = {
    data: void
    status: 200
}

export type endpointsRunRetrieveResponseSuccess = endpointsRunRetrieveResponse200 & {
    headers: Headers
}
export type endpointsRunRetrieveResponse = endpointsRunRetrieveResponseSuccess

export const getEndpointsRunRetrieveUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/run/`
}

export const endpointsRunRetrieve = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<endpointsRunRetrieveResponse> => {
    return apiMutator<endpointsRunRetrieveResponse>(getEndpointsRunRetrieveUrl(projectId, name), {
        ...options,
        method: 'GET',
    })
}

/**
 * Execute endpoint with optional materialization. Supports version parameter, runs latest version if not set.
 */
export type endpointsRunCreateResponse200 = {
    data: void
    status: 200
}

export type endpointsRunCreateResponseSuccess = endpointsRunCreateResponse200 & {
    headers: Headers
}
export type endpointsRunCreateResponse = endpointsRunCreateResponseSuccess

export const getEndpointsRunCreateUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/run/`
}

export const endpointsRunCreate = async (
    projectId: string,
    name: string,
    endpointRunRequestApi: EndpointRunRequestApi,
    options?: RequestInit
): Promise<endpointsRunCreateResponse> => {
    return apiMutator<endpointsRunCreateResponse>(getEndpointsRunCreateUrl(projectId, name), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(endpointRunRequestApi),
    })
}

/**
 * List all versions for an endpoint.
 */
export type endpointsVersionsRetrieveResponse200 = {
    data: void
    status: 200
}

export type endpointsVersionsRetrieveResponseSuccess = endpointsVersionsRetrieveResponse200 & {
    headers: Headers
}
export type endpointsVersionsRetrieveResponse = endpointsVersionsRetrieveResponseSuccess

export const getEndpointsVersionsRetrieveUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/versions/`
}

export const endpointsVersionsRetrieve = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<endpointsVersionsRetrieveResponse> => {
    return apiMutator<endpointsVersionsRetrieveResponse>(getEndpointsVersionsRetrieveUrl(projectId, name), {
        ...options,
        method: 'GET',
    })
}

/**
 * Get details of a specific endpoint version.
 */
export type endpointsVersionsRetrieve2Response200 = {
    data: void
    status: 200
}

export type endpointsVersionsRetrieve2ResponseSuccess = endpointsVersionsRetrieve2Response200 & {
    headers: Headers
}
export type endpointsVersionsRetrieve2Response = endpointsVersionsRetrieve2ResponseSuccess

export const getEndpointsVersionsRetrieve2Url = (projectId: string, name: string, versionNumber: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/versions/${versionNumber}/`
}

export const endpointsVersionsRetrieve2 = async (
    projectId: string,
    name: string,
    versionNumber: string,
    options?: RequestInit
): Promise<endpointsVersionsRetrieve2Response> => {
    return apiMutator<endpointsVersionsRetrieve2Response>(
        getEndpointsVersionsRetrieve2Url(projectId, name, versionNumber),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Get the last execution times in the past 6 months for multiple endpoints.
 */
export type endpointsLastExecutionTimesCreateResponse200 = {
    data: QueryStatusResponseApi
    status: 200
}

export type endpointsLastExecutionTimesCreateResponseSuccess = endpointsLastExecutionTimesCreateResponse200 & {
    headers: Headers
}
export type endpointsLastExecutionTimesCreateResponse = endpointsLastExecutionTimesCreateResponseSuccess

export const getEndpointsLastExecutionTimesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/endpoints/last_execution_times/`
}

export const endpointsLastExecutionTimesCreate = async (
    projectId: string,
    endpointLastExecutionTimesRequestApi: EndpointLastExecutionTimesRequestApi,
    options?: RequestInit
): Promise<endpointsLastExecutionTimesCreateResponse> => {
    return apiMutator<endpointsLastExecutionTimesCreateResponse>(getEndpointsLastExecutionTimesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(endpointLastExecutionTimesRequestApi),
    })
}
