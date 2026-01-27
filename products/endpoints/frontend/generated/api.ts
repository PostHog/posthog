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
export type endpointsRetrieveResponse200 = {
    data: void
    status: 200
}

export type endpointsRetrieveResponseSuccess = endpointsRetrieveResponse200 & {
    headers: Headers
}
export type endpointsRetrieveResponse = endpointsRetrieveResponseSuccess

export const getEndpointsRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/endpoints/`
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
    return `/api/environments/${projectId}/endpoints/`
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
    return `/api/environments/${projectId}/endpoints/${name}/`
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
 * Update an existing endpoint. Parameters are optional. Use ?version=N to update a specific version's is_active status.
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
    return `/api/environments/${projectId}/endpoints/${name}/`
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
    return `/api/environments/${projectId}/endpoints/${name}/`
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
    return `/api/environments/${projectId}/endpoints/${name}/`
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
    return `/api/environments/${projectId}/endpoints/${name}/materialization_status/`
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
    return `/api/environments/${projectId}/endpoints/${name}/openapi.json/`
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
    return `/api/environments/${projectId}/endpoints/${name}/run/`
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
    return `/api/environments/${projectId}/endpoints/${name}/run/`
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
    return `/api/environments/${projectId}/endpoints/${name}/versions/`
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
    return `/api/environments/${projectId}/endpoints/${name}/versions/${versionNumber}/`
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
    return `/api/environments/${projectId}/endpoints/last_execution_times/`
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

/**
 * List all endpoints for the team.
 */
export type endpointsRetrieve3Response200 = {
    data: void
    status: 200
}

export type endpointsRetrieve3ResponseSuccess = endpointsRetrieve3Response200 & {
    headers: Headers
}
export type endpointsRetrieve3Response = endpointsRetrieve3ResponseSuccess

export const getEndpointsRetrieve3Url = (projectId: string) => {
    return `/api/projects/${projectId}/endpoints/`
}

export const endpointsRetrieve3 = async (
    projectId: string,
    options?: RequestInit
): Promise<endpointsRetrieve3Response> => {
    return apiMutator<endpointsRetrieve3Response>(getEndpointsRetrieve3Url(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create a new endpoint
 */
export type endpointsCreate2Response201 = {
    data: void
    status: 201
}

export type endpointsCreate2ResponseSuccess = endpointsCreate2Response201 & {
    headers: Headers
}
export type endpointsCreate2Response = endpointsCreate2ResponseSuccess

export const getEndpointsCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/endpoints/`
}

export const endpointsCreate2 = async (
    projectId: string,
    endpointRequestApi: EndpointRequestApi,
    options?: RequestInit
): Promise<endpointsCreate2Response> => {
    return apiMutator<endpointsCreate2Response>(getEndpointsCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(endpointRequestApi),
    })
}

/**
 * Retrieve an endpoint.
 */
export type endpointsRetrieve4Response200 = {
    data: void
    status: 200
}

export type endpointsRetrieve4ResponseSuccess = endpointsRetrieve4Response200 & {
    headers: Headers
}
export type endpointsRetrieve4Response = endpointsRetrieve4ResponseSuccess

export const getEndpointsRetrieve4Url = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/`
}

export const endpointsRetrieve4 = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<endpointsRetrieve4Response> => {
    return apiMutator<endpointsRetrieve4Response>(getEndpointsRetrieve4Url(projectId, name), {
        ...options,
        method: 'GET',
    })
}

/**
 * Update an existing endpoint. Parameters are optional. Use ?version=N to update a specific version's is_active status.
 */
export type endpointsUpdate2Response200 = {
    data: void
    status: 200
}

export type endpointsUpdate2ResponseSuccess = endpointsUpdate2Response200 & {
    headers: Headers
}
export type endpointsUpdate2Response = endpointsUpdate2ResponseSuccess

export const getEndpointsUpdate2Url = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/`
}

export const endpointsUpdate2 = async (
    projectId: string,
    name: string,
    endpointRequestApi: EndpointRequestApi,
    options?: RequestInit
): Promise<endpointsUpdate2Response> => {
    return apiMutator<endpointsUpdate2Response>(getEndpointsUpdate2Url(projectId, name), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(endpointRequestApi),
    })
}

export type endpointsPartialUpdate2Response200 = {
    data: void
    status: 200
}

export type endpointsPartialUpdate2ResponseSuccess = endpointsPartialUpdate2Response200 & {
    headers: Headers
}
export type endpointsPartialUpdate2Response = endpointsPartialUpdate2ResponseSuccess

export const getEndpointsPartialUpdate2Url = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/`
}

export const endpointsPartialUpdate2 = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<endpointsPartialUpdate2Response> => {
    return apiMutator<endpointsPartialUpdate2Response>(getEndpointsPartialUpdate2Url(projectId, name), {
        ...options,
        method: 'PATCH',
    })
}

/**
 * Delete an endpoint and clean up materialized query.
 */
export type endpointsDestroy2Response204 = {
    data: void
    status: 204
}

export type endpointsDestroy2ResponseSuccess = endpointsDestroy2Response204 & {
    headers: Headers
}
export type endpointsDestroy2Response = endpointsDestroy2ResponseSuccess

export const getEndpointsDestroy2Url = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/`
}

export const endpointsDestroy2 = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<endpointsDestroy2Response> => {
    return apiMutator<endpointsDestroy2Response>(getEndpointsDestroy2Url(projectId, name), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Get materialization status for an endpoint.
 */
export type endpointsMaterializationStatusRetrieve2Response200 = {
    data: void
    status: 200
}

export type endpointsMaterializationStatusRetrieve2ResponseSuccess =
    endpointsMaterializationStatusRetrieve2Response200 & {
        headers: Headers
    }
export type endpointsMaterializationStatusRetrieve2Response = endpointsMaterializationStatusRetrieve2ResponseSuccess

export const getEndpointsMaterializationStatusRetrieve2Url = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/materialization_status/`
}

export const endpointsMaterializationStatusRetrieve2 = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<endpointsMaterializationStatusRetrieve2Response> => {
    return apiMutator<endpointsMaterializationStatusRetrieve2Response>(
        getEndpointsMaterializationStatusRetrieve2Url(projectId, name),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Get OpenAPI 3.0 specification for this endpoint. Use this to generate typed SDK clients.
 */
export type endpointsOpenapiJsonRetrieve2Response200 = {
    data: void
    status: 200
}

export type endpointsOpenapiJsonRetrieve2ResponseSuccess = endpointsOpenapiJsonRetrieve2Response200 & {
    headers: Headers
}
export type endpointsOpenapiJsonRetrieve2Response = endpointsOpenapiJsonRetrieve2ResponseSuccess

export const getEndpointsOpenapiJsonRetrieve2Url = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/openapi.json/`
}

export const endpointsOpenapiJsonRetrieve2 = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<endpointsOpenapiJsonRetrieve2Response> => {
    return apiMutator<endpointsOpenapiJsonRetrieve2Response>(getEndpointsOpenapiJsonRetrieve2Url(projectId, name), {
        ...options,
        method: 'GET',
    })
}

/**
 * Execute endpoint with optional materialization. Supports version parameter, runs latest version if not set.
 */
export type endpointsRunRetrieve2Response200 = {
    data: void
    status: 200
}

export type endpointsRunRetrieve2ResponseSuccess = endpointsRunRetrieve2Response200 & {
    headers: Headers
}
export type endpointsRunRetrieve2Response = endpointsRunRetrieve2ResponseSuccess

export const getEndpointsRunRetrieve2Url = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/run/`
}

export const endpointsRunRetrieve2 = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<endpointsRunRetrieve2Response> => {
    return apiMutator<endpointsRunRetrieve2Response>(getEndpointsRunRetrieve2Url(projectId, name), {
        ...options,
        method: 'GET',
    })
}

/**
 * Execute endpoint with optional materialization. Supports version parameter, runs latest version if not set.
 */
export type endpointsRunCreate2Response200 = {
    data: void
    status: 200
}

export type endpointsRunCreate2ResponseSuccess = endpointsRunCreate2Response200 & {
    headers: Headers
}
export type endpointsRunCreate2Response = endpointsRunCreate2ResponseSuccess

export const getEndpointsRunCreate2Url = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/run/`
}

export const endpointsRunCreate2 = async (
    projectId: string,
    name: string,
    endpointRunRequestApi: EndpointRunRequestApi,
    options?: RequestInit
): Promise<endpointsRunCreate2Response> => {
    return apiMutator<endpointsRunCreate2Response>(getEndpointsRunCreate2Url(projectId, name), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(endpointRunRequestApi),
    })
}

/**
 * List all versions for an endpoint.
 */
export type endpointsVersionsRetrieve3Response200 = {
    data: void
    status: 200
}

export type endpointsVersionsRetrieve3ResponseSuccess = endpointsVersionsRetrieve3Response200 & {
    headers: Headers
}
export type endpointsVersionsRetrieve3Response = endpointsVersionsRetrieve3ResponseSuccess

export const getEndpointsVersionsRetrieve3Url = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/versions/`
}

export const endpointsVersionsRetrieve3 = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<endpointsVersionsRetrieve3Response> => {
    return apiMutator<endpointsVersionsRetrieve3Response>(getEndpointsVersionsRetrieve3Url(projectId, name), {
        ...options,
        method: 'GET',
    })
}

/**
 * Get details of a specific endpoint version.
 */
export type endpointsVersionsRetrieve4Response200 = {
    data: void
    status: 200
}

export type endpointsVersionsRetrieve4ResponseSuccess = endpointsVersionsRetrieve4Response200 & {
    headers: Headers
}
export type endpointsVersionsRetrieve4Response = endpointsVersionsRetrieve4ResponseSuccess

export const getEndpointsVersionsRetrieve4Url = (projectId: string, name: string, versionNumber: string) => {
    return `/api/projects/${projectId}/endpoints/${name}/versions/${versionNumber}/`
}

export const endpointsVersionsRetrieve4 = async (
    projectId: string,
    name: string,
    versionNumber: string,
    options?: RequestInit
): Promise<endpointsVersionsRetrieve4Response> => {
    return apiMutator<endpointsVersionsRetrieve4Response>(
        getEndpointsVersionsRetrieve4Url(projectId, name, versionNumber),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Get the last execution times in the past 6 months for multiple endpoints.
 */
export type endpointsLastExecutionTimesCreate2Response200 = {
    data: QueryStatusResponseApi
    status: 200
}

export type endpointsLastExecutionTimesCreate2ResponseSuccess = endpointsLastExecutionTimesCreate2Response200 & {
    headers: Headers
}
export type endpointsLastExecutionTimesCreate2Response = endpointsLastExecutionTimesCreate2ResponseSuccess

export const getEndpointsLastExecutionTimesCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/endpoints/last_execution_times/`
}

export const endpointsLastExecutionTimesCreate2 = async (
    projectId: string,
    endpointLastExecutionTimesRequestApi: EndpointLastExecutionTimesRequestApi,
    options?: RequestInit
): Promise<endpointsLastExecutionTimesCreate2Response> => {
    return apiMutator<endpointsLastExecutionTimesCreate2Response>(getEndpointsLastExecutionTimesCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(endpointLastExecutionTimesRequestApi),
    })
}
