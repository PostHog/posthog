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
    ColumnConfigurationApi,
    ElementApi,
    ElementsListParams,
    EnvironmentsColumnConfigurationsListParams,
    EnvironmentsElementsListParams,
    PaginatedColumnConfigurationListApi,
    PaginatedElementListApi,
    PatchedColumnConfigurationApi,
    PatchedElementApi,
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

export type environmentsColumnConfigurationsListResponse200 = {
    data: PaginatedColumnConfigurationListApi
    status: 200
}

export type environmentsColumnConfigurationsListResponseSuccess = environmentsColumnConfigurationsListResponse200 & {
    headers: Headers
}
export type environmentsColumnConfigurationsListResponse = environmentsColumnConfigurationsListResponseSuccess

export const getEnvironmentsColumnConfigurationsListUrl = (
    projectId: string,
    params?: EnvironmentsColumnConfigurationsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/column_configurations/?${stringifiedParams}`
        : `/api/environments/${projectId}/column_configurations/`
}

export const environmentsColumnConfigurationsList = async (
    projectId: string,
    params?: EnvironmentsColumnConfigurationsListParams,
    options?: RequestInit
): Promise<environmentsColumnConfigurationsListResponse> => {
    return apiMutator<environmentsColumnConfigurationsListResponse>(
        getEnvironmentsColumnConfigurationsListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsColumnConfigurationsCreateResponse201 = {
    data: ColumnConfigurationApi
    status: 201
}

export type environmentsColumnConfigurationsCreateResponseSuccess =
    environmentsColumnConfigurationsCreateResponse201 & {
        headers: Headers
    }
export type environmentsColumnConfigurationsCreateResponse = environmentsColumnConfigurationsCreateResponseSuccess

export const getEnvironmentsColumnConfigurationsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/column_configurations/`
}

export const environmentsColumnConfigurationsCreate = async (
    projectId: string,
    columnConfigurationApi: NonReadonly<ColumnConfigurationApi>,
    options?: RequestInit
): Promise<environmentsColumnConfigurationsCreateResponse> => {
    return apiMutator<environmentsColumnConfigurationsCreateResponse>(
        getEnvironmentsColumnConfigurationsCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(columnConfigurationApi),
        }
    )
}

export type environmentsColumnConfigurationsRetrieveResponse200 = {
    data: ColumnConfigurationApi
    status: 200
}

export type environmentsColumnConfigurationsRetrieveResponseSuccess =
    environmentsColumnConfigurationsRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsColumnConfigurationsRetrieveResponse = environmentsColumnConfigurationsRetrieveResponseSuccess

export const getEnvironmentsColumnConfigurationsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/column_configurations/${id}/`
}

export const environmentsColumnConfigurationsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsColumnConfigurationsRetrieveResponse> => {
    return apiMutator<environmentsColumnConfigurationsRetrieveResponse>(
        getEnvironmentsColumnConfigurationsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsColumnConfigurationsUpdateResponse200 = {
    data: ColumnConfigurationApi
    status: 200
}

export type environmentsColumnConfigurationsUpdateResponseSuccess =
    environmentsColumnConfigurationsUpdateResponse200 & {
        headers: Headers
    }
export type environmentsColumnConfigurationsUpdateResponse = environmentsColumnConfigurationsUpdateResponseSuccess

export const getEnvironmentsColumnConfigurationsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/column_configurations/${id}/`
}

export const environmentsColumnConfigurationsUpdate = async (
    projectId: string,
    id: string,
    columnConfigurationApi: NonReadonly<ColumnConfigurationApi>,
    options?: RequestInit
): Promise<environmentsColumnConfigurationsUpdateResponse> => {
    return apiMutator<environmentsColumnConfigurationsUpdateResponse>(
        getEnvironmentsColumnConfigurationsUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(columnConfigurationApi),
        }
    )
}

export type environmentsColumnConfigurationsPartialUpdateResponse200 = {
    data: ColumnConfigurationApi
    status: 200
}

export type environmentsColumnConfigurationsPartialUpdateResponseSuccess =
    environmentsColumnConfigurationsPartialUpdateResponse200 & {
        headers: Headers
    }
export type environmentsColumnConfigurationsPartialUpdateResponse =
    environmentsColumnConfigurationsPartialUpdateResponseSuccess

export const getEnvironmentsColumnConfigurationsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/column_configurations/${id}/`
}

export const environmentsColumnConfigurationsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedColumnConfigurationApi: NonReadonly<PatchedColumnConfigurationApi>,
    options?: RequestInit
): Promise<environmentsColumnConfigurationsPartialUpdateResponse> => {
    return apiMutator<environmentsColumnConfigurationsPartialUpdateResponse>(
        getEnvironmentsColumnConfigurationsPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedColumnConfigurationApi),
        }
    )
}

export type environmentsColumnConfigurationsDestroyResponse204 = {
    data: void
    status: 204
}

export type environmentsColumnConfigurationsDestroyResponseSuccess =
    environmentsColumnConfigurationsDestroyResponse204 & {
        headers: Headers
    }
export type environmentsColumnConfigurationsDestroyResponse = environmentsColumnConfigurationsDestroyResponseSuccess

export const getEnvironmentsColumnConfigurationsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/column_configurations/${id}/`
}

export const environmentsColumnConfigurationsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsColumnConfigurationsDestroyResponse> => {
    return apiMutator<environmentsColumnConfigurationsDestroyResponse>(
        getEnvironmentsColumnConfigurationsDestroyUrl(projectId, id),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type environmentsElementsListResponse200 = {
    data: PaginatedElementListApi
    status: 200
}

export type environmentsElementsListResponseSuccess = environmentsElementsListResponse200 & {
    headers: Headers
}
export type environmentsElementsListResponse = environmentsElementsListResponseSuccess

export const getEnvironmentsElementsListUrl = (projectId: string, params?: EnvironmentsElementsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/elements/?${stringifiedParams}`
        : `/api/environments/${projectId}/elements/`
}

export const environmentsElementsList = async (
    projectId: string,
    params?: EnvironmentsElementsListParams,
    options?: RequestInit
): Promise<environmentsElementsListResponse> => {
    return apiMutator<environmentsElementsListResponse>(getEnvironmentsElementsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type environmentsElementsCreateResponse201 = {
    data: ElementApi
    status: 201
}

export type environmentsElementsCreateResponseSuccess = environmentsElementsCreateResponse201 & {
    headers: Headers
}
export type environmentsElementsCreateResponse = environmentsElementsCreateResponseSuccess

export const getEnvironmentsElementsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/elements/`
}

export const environmentsElementsCreate = async (
    projectId: string,
    elementApi: ElementApi,
    options?: RequestInit
): Promise<environmentsElementsCreateResponse> => {
    return apiMutator<environmentsElementsCreateResponse>(getEnvironmentsElementsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(elementApi),
    })
}

export type environmentsElementsRetrieveResponse200 = {
    data: ElementApi
    status: 200
}

export type environmentsElementsRetrieveResponseSuccess = environmentsElementsRetrieveResponse200 & {
    headers: Headers
}
export type environmentsElementsRetrieveResponse = environmentsElementsRetrieveResponseSuccess

export const getEnvironmentsElementsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/elements/${id}/`
}

export const environmentsElementsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<environmentsElementsRetrieveResponse> => {
    return apiMutator<environmentsElementsRetrieveResponse>(getEnvironmentsElementsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type environmentsElementsUpdateResponse200 = {
    data: ElementApi
    status: 200
}

export type environmentsElementsUpdateResponseSuccess = environmentsElementsUpdateResponse200 & {
    headers: Headers
}
export type environmentsElementsUpdateResponse = environmentsElementsUpdateResponseSuccess

export const getEnvironmentsElementsUpdateUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/elements/${id}/`
}

export const environmentsElementsUpdate = async (
    projectId: string,
    id: number,
    elementApi: ElementApi,
    options?: RequestInit
): Promise<environmentsElementsUpdateResponse> => {
    return apiMutator<environmentsElementsUpdateResponse>(getEnvironmentsElementsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(elementApi),
    })
}

export type environmentsElementsPartialUpdateResponse200 = {
    data: ElementApi
    status: 200
}

export type environmentsElementsPartialUpdateResponseSuccess = environmentsElementsPartialUpdateResponse200 & {
    headers: Headers
}
export type environmentsElementsPartialUpdateResponse = environmentsElementsPartialUpdateResponseSuccess

export const getEnvironmentsElementsPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/elements/${id}/`
}

export const environmentsElementsPartialUpdate = async (
    projectId: string,
    id: number,
    patchedElementApi: PatchedElementApi,
    options?: RequestInit
): Promise<environmentsElementsPartialUpdateResponse> => {
    return apiMutator<environmentsElementsPartialUpdateResponse>(
        getEnvironmentsElementsPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedElementApi),
        }
    )
}

export type environmentsElementsDestroyResponse204 = {
    data: void
    status: 204
}

export type environmentsElementsDestroyResponseSuccess = environmentsElementsDestroyResponse204 & {
    headers: Headers
}
export type environmentsElementsDestroyResponse = environmentsElementsDestroyResponseSuccess

export const getEnvironmentsElementsDestroyUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/elements/${id}/`
}

export const environmentsElementsDestroy = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<environmentsElementsDestroyResponse> => {
    return apiMutator<environmentsElementsDestroyResponse>(getEnvironmentsElementsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * The original version of this API always and only returned $autocapture elements
If no include query parameter is sent this remains true.
Now, you can pass a combination of include query parameters to get different types of elements
Currently only $autocapture and $rageclick and $dead_click are supported
 */
export type environmentsElementsStatsRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsElementsStatsRetrieveResponseSuccess = environmentsElementsStatsRetrieveResponse200 & {
    headers: Headers
}
export type environmentsElementsStatsRetrieveResponse = environmentsElementsStatsRetrieveResponseSuccess

export const getEnvironmentsElementsStatsRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/elements/stats/`
}

export const environmentsElementsStatsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsElementsStatsRetrieveResponse> => {
    return apiMutator<environmentsElementsStatsRetrieveResponse>(getEnvironmentsElementsStatsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export type environmentsElementsValuesRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsElementsValuesRetrieveResponseSuccess = environmentsElementsValuesRetrieveResponse200 & {
    headers: Headers
}
export type environmentsElementsValuesRetrieveResponse = environmentsElementsValuesRetrieveResponseSuccess

export const getEnvironmentsElementsValuesRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/elements/values/`
}

export const environmentsElementsValuesRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsElementsValuesRetrieveResponse> => {
    return apiMutator<environmentsElementsValuesRetrieveResponse>(getEnvironmentsElementsValuesRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export type elementsListResponse200 = {
    data: PaginatedElementListApi
    status: 200
}

export type elementsListResponseSuccess = elementsListResponse200 & {
    headers: Headers
}
export type elementsListResponse = elementsListResponseSuccess

export const getElementsListUrl = (projectId: string, params?: ElementsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/elements/?${stringifiedParams}`
        : `/api/projects/${projectId}/elements/`
}

export const elementsList = async (
    projectId: string,
    params?: ElementsListParams,
    options?: RequestInit
): Promise<elementsListResponse> => {
    return apiMutator<elementsListResponse>(getElementsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type elementsCreateResponse201 = {
    data: ElementApi
    status: 201
}

export type elementsCreateResponseSuccess = elementsCreateResponse201 & {
    headers: Headers
}
export type elementsCreateResponse = elementsCreateResponseSuccess

export const getElementsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/elements/`
}

export const elementsCreate = async (
    projectId: string,
    elementApi: ElementApi,
    options?: RequestInit
): Promise<elementsCreateResponse> => {
    return apiMutator<elementsCreateResponse>(getElementsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(elementApi),
    })
}

export type elementsRetrieveResponse200 = {
    data: ElementApi
    status: 200
}

export type elementsRetrieveResponseSuccess = elementsRetrieveResponse200 & {
    headers: Headers
}
export type elementsRetrieveResponse = elementsRetrieveResponseSuccess

export const getElementsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/elements/${id}/`
}

export const elementsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<elementsRetrieveResponse> => {
    return apiMutator<elementsRetrieveResponse>(getElementsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type elementsUpdateResponse200 = {
    data: ElementApi
    status: 200
}

export type elementsUpdateResponseSuccess = elementsUpdateResponse200 & {
    headers: Headers
}
export type elementsUpdateResponse = elementsUpdateResponseSuccess

export const getElementsUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/elements/${id}/`
}

export const elementsUpdate = async (
    projectId: string,
    id: number,
    elementApi: ElementApi,
    options?: RequestInit
): Promise<elementsUpdateResponse> => {
    return apiMutator<elementsUpdateResponse>(getElementsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(elementApi),
    })
}

export type elementsPartialUpdateResponse200 = {
    data: ElementApi
    status: 200
}

export type elementsPartialUpdateResponseSuccess = elementsPartialUpdateResponse200 & {
    headers: Headers
}
export type elementsPartialUpdateResponse = elementsPartialUpdateResponseSuccess

export const getElementsPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/elements/${id}/`
}

export const elementsPartialUpdate = async (
    projectId: string,
    id: number,
    patchedElementApi: PatchedElementApi,
    options?: RequestInit
): Promise<elementsPartialUpdateResponse> => {
    return apiMutator<elementsPartialUpdateResponse>(getElementsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedElementApi),
    })
}

export type elementsDestroyResponse204 = {
    data: void
    status: 204
}

export type elementsDestroyResponseSuccess = elementsDestroyResponse204 & {
    headers: Headers
}
export type elementsDestroyResponse = elementsDestroyResponseSuccess

export const getElementsDestroyUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/elements/${id}/`
}

export const elementsDestroy = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<elementsDestroyResponse> => {
    return apiMutator<elementsDestroyResponse>(getElementsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * The original version of this API always and only returned $autocapture elements
If no include query parameter is sent this remains true.
Now, you can pass a combination of include query parameters to get different types of elements
Currently only $autocapture and $rageclick and $dead_click are supported
 */
export type elementsStatsRetrieveResponse200 = {
    data: void
    status: 200
}

export type elementsStatsRetrieveResponseSuccess = elementsStatsRetrieveResponse200 & {
    headers: Headers
}
export type elementsStatsRetrieveResponse = elementsStatsRetrieveResponseSuccess

export const getElementsStatsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/elements/stats/`
}

export const elementsStatsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<elementsStatsRetrieveResponse> => {
    return apiMutator<elementsStatsRetrieveResponse>(getElementsStatsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export type elementsValuesRetrieveResponse200 = {
    data: void
    status: 200
}

export type elementsValuesRetrieveResponseSuccess = elementsValuesRetrieveResponse200 & {
    headers: Headers
}
export type elementsValuesRetrieveResponse = elementsValuesRetrieveResponseSuccess

export const getElementsValuesRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/elements/values/`
}

export const elementsValuesRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<elementsValuesRetrieveResponse> => {
    return apiMutator<elementsValuesRetrieveResponse>(getElementsValuesRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}
