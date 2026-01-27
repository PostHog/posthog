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
    ColumnConfigurationsListParams,
    ElementApi,
    ElementsList2Params,
    ElementsListParams,
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

export type columnConfigurationsListResponse200 = {
    data: PaginatedColumnConfigurationListApi
    status: 200
}

export type columnConfigurationsListResponseSuccess = columnConfigurationsListResponse200 & {
    headers: Headers
}
export type columnConfigurationsListResponse = columnConfigurationsListResponseSuccess

export const getColumnConfigurationsListUrl = (projectId: string, params?: ColumnConfigurationsListParams) => {
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

export const columnConfigurationsList = async (
    projectId: string,
    params?: ColumnConfigurationsListParams,
    options?: RequestInit
): Promise<columnConfigurationsListResponse> => {
    return apiMutator<columnConfigurationsListResponse>(getColumnConfigurationsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}


export type columnConfigurationsCreateResponse201 = {
    data: ColumnConfigurationApi
    status: 201
}

export type columnConfigurationsCreateResponseSuccess = columnConfigurationsCreateResponse201 & {
    headers: Headers
}
export type columnConfigurationsCreateResponse = columnConfigurationsCreateResponseSuccess

export const getColumnConfigurationsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/column_configurations/`
}

export const columnConfigurationsCreate = async (
    projectId: string,
    columnConfigurationApi: NonReadonly<ColumnConfigurationApi>,
    options?: RequestInit
): Promise<columnConfigurationsCreateResponse> => {
    return apiMutator<columnConfigurationsCreateResponse>(getColumnConfigurationsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(columnConfigurationApi),
    })
}

export type columnConfigurationsRetrieveResponse200 = {
    data: ColumnConfigurationApi
    status: 200
}

export type columnConfigurationsRetrieveResponseSuccess = columnConfigurationsRetrieveResponse200 & {
    headers: Headers
}
export type columnConfigurationsRetrieveResponse = columnConfigurationsRetrieveResponseSuccess

export const getColumnConfigurationsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/column_configurations/${id}/`
}

export const columnConfigurationsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<columnConfigurationsRetrieveResponse> => {
    return apiMutator<columnConfigurationsRetrieveResponse>(getColumnConfigurationsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type columnConfigurationsUpdateResponse200 = {
    data: ColumnConfigurationApi
    status: 200
}

export type columnConfigurationsUpdateResponseSuccess = columnConfigurationsUpdateResponse200 & {
    headers: Headers
}
export type columnConfigurationsUpdateResponse = columnConfigurationsUpdateResponseSuccess

export const getColumnConfigurationsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/column_configurations/${id}/`
}

export const columnConfigurationsUpdate = async (
    projectId: string,
    id: string,
    columnConfigurationApi: NonReadonly<ColumnConfigurationApi>,
    options?: RequestInit
): Promise<columnConfigurationsUpdateResponse> => {
    return apiMutator<columnConfigurationsUpdateResponse>(getColumnConfigurationsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(columnConfigurationApi),
    })
}

export type columnConfigurationsPartialUpdateResponse200 = {
    data: ColumnConfigurationApi
    status: 200
}

export type columnConfigurationsPartialUpdateResponseSuccess = columnConfigurationsPartialUpdateResponse200 & {
    headers: Headers
}
export type columnConfigurationsPartialUpdateResponse = columnConfigurationsPartialUpdateResponseSuccess

export const getColumnConfigurationsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/column_configurations/${id}/`
}

export const columnConfigurationsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedColumnConfigurationApi: NonReadonly<PatchedColumnConfigurationApi>,
    options?: RequestInit
): Promise<columnConfigurationsPartialUpdateResponse> => {
    return apiMutator<columnConfigurationsPartialUpdateResponse>(
        getColumnConfigurationsPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedColumnConfigurationApi),
        }
    )
}

export type columnConfigurationsDestroyResponse204 = {
    data: void
    status: 204
}

export type columnConfigurationsDestroyResponseSuccess = columnConfigurationsDestroyResponse204 & {
    headers: Headers
}
export type columnConfigurationsDestroyResponse = columnConfigurationsDestroyResponseSuccess

export const getColumnConfigurationsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/column_configurations/${id}/`
}

export const columnConfigurationsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<columnConfigurationsDestroyResponse> => {
    return apiMutator<columnConfigurationsDestroyResponse>(getColumnConfigurationsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
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
        ? `/api/environments/${projectId}/elements/?${stringifiedParams}`
        : `/api/environments/${projectId}/elements/`
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
    return `/api/environments/${projectId}/elements/`
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
    return `/api/environments/${projectId}/elements/${id}/`
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
    return `/api/environments/${projectId}/elements/${id}/`
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
    return `/api/environments/${projectId}/elements/${id}/`
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
    return `/api/environments/${projectId}/elements/${id}/`
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
    return `/api/environments/${projectId}/elements/stats/`
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
    return `/api/environments/${projectId}/elements/values/`
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

export type elementsList2Response200 = {
    data: PaginatedElementListApi
    status: 200
}

export type elementsList2ResponseSuccess = elementsList2Response200 & {
    headers: Headers
}
export type elementsList2Response = elementsList2ResponseSuccess

export const getElementsList2Url = (projectId: string, params?: ElementsList2Params) => {
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

export const elementsList2 = async (
    projectId: string,
    params?: ElementsList2Params,
    options?: RequestInit
): Promise<elementsList2Response> => {
    return apiMutator<elementsList2Response>(getElementsList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type elementsCreate2Response201 = {
    data: ElementApi
    status: 201
}

export type elementsCreate2ResponseSuccess = elementsCreate2Response201 & {
    headers: Headers
}
export type elementsCreate2Response = elementsCreate2ResponseSuccess

export const getElementsCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/elements/`
}

export const elementsCreate2 = async (
    projectId: string,
    elementApi: ElementApi,
    options?: RequestInit
): Promise<elementsCreate2Response> => {
    return apiMutator<elementsCreate2Response>(getElementsCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(elementApi),
    })
}

export type elementsRetrieve2Response200 = {
    data: ElementApi
    status: 200
}

export type elementsRetrieve2ResponseSuccess = elementsRetrieve2Response200 & {
    headers: Headers
}
export type elementsRetrieve2Response = elementsRetrieve2ResponseSuccess

export const getElementsRetrieve2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/elements/${id}/`
}

export const elementsRetrieve2 = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<elementsRetrieve2Response> => {
    return apiMutator<elementsRetrieve2Response>(getElementsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type elementsUpdate2Response200 = {
    data: ElementApi
    status: 200
}

export type elementsUpdate2ResponseSuccess = elementsUpdate2Response200 & {
    headers: Headers
}
export type elementsUpdate2Response = elementsUpdate2ResponseSuccess

export const getElementsUpdate2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/elements/${id}/`
}

export const elementsUpdate2 = async (
    projectId: string,
    id: number,
    elementApi: ElementApi,
    options?: RequestInit
): Promise<elementsUpdate2Response> => {
    return apiMutator<elementsUpdate2Response>(getElementsUpdate2Url(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(elementApi),
    })
}

export type elementsPartialUpdate2Response200 = {
    data: ElementApi
    status: 200
}

export type elementsPartialUpdate2ResponseSuccess = elementsPartialUpdate2Response200 & {
    headers: Headers
}
export type elementsPartialUpdate2Response = elementsPartialUpdate2ResponseSuccess

export const getElementsPartialUpdate2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/elements/${id}/`
}

export const elementsPartialUpdate2 = async (
    projectId: string,
    id: number,
    patchedElementApi: PatchedElementApi,
    options?: RequestInit
): Promise<elementsPartialUpdate2Response> => {
    return apiMutator<elementsPartialUpdate2Response>(getElementsPartialUpdate2Url(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedElementApi),
    })
}

export type elementsDestroy2Response204 = {
    data: void
    status: 204
}

export type elementsDestroy2ResponseSuccess = elementsDestroy2Response204 & {
    headers: Headers
}
export type elementsDestroy2Response = elementsDestroy2ResponseSuccess

export const getElementsDestroy2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/elements/${id}/`
}

export const elementsDestroy2 = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<elementsDestroy2Response> => {
    return apiMutator<elementsDestroy2Response>(getElementsDestroy2Url(projectId, id), {
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
export type elementsStatsRetrieve2Response200 = {
    data: void
    status: 200
}

export type elementsStatsRetrieve2ResponseSuccess = elementsStatsRetrieve2Response200 & {
    headers: Headers
}
export type elementsStatsRetrieve2Response = elementsStatsRetrieve2ResponseSuccess

export const getElementsStatsRetrieve2Url = (projectId: string) => {
    return `/api/projects/${projectId}/elements/stats/`
}

export const elementsStatsRetrieve2 = async (
    projectId: string,
    options?: RequestInit
): Promise<elementsStatsRetrieve2Response> => {
    return apiMutator<elementsStatsRetrieve2Response>(getElementsStatsRetrieve2Url(projectId), {
        ...options,
        method: 'GET',
    })
}

export type elementsValuesRetrieve2Response200 = {
    data: void
    status: 200
}

export type elementsValuesRetrieve2ResponseSuccess = elementsValuesRetrieve2Response200 & {
    headers: Headers
}
export type elementsValuesRetrieve2Response = elementsValuesRetrieve2ResponseSuccess

export const getElementsValuesRetrieve2Url = (projectId: string) => {
    return `/api/projects/${projectId}/elements/values/`
}

export const elementsValuesRetrieve2 = async (
    projectId: string,
    options?: RequestInit
): Promise<elementsValuesRetrieve2Response> => {
    return apiMutator<elementsValuesRetrieve2Response>(getElementsValuesRetrieve2Url(projectId), {
        ...options,
        method: 'GET',
    })
}
