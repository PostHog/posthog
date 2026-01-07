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
    DatasetApi,
    DatasetItemApi,
    DatasetItemsListParams,
    DatasetsListParams,
    EnvironmentsDatasetItemsListParams,
    EnvironmentsDatasetsListParams,
    PaginatedDatasetItemListApi,
    PaginatedDatasetListApi,
    PatchedDatasetApi,
    PatchedDatasetItemApi,
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

export type environmentsDatasetItemsListResponse200 = {
    data: PaginatedDatasetItemListApi
    status: 200
}

export type environmentsDatasetItemsListResponseSuccess = environmentsDatasetItemsListResponse200 & {
    headers: Headers
}
export type environmentsDatasetItemsListResponse = environmentsDatasetItemsListResponseSuccess

export const getEnvironmentsDatasetItemsListUrl = (projectId: string, params?: EnvironmentsDatasetItemsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/dataset_items/?${stringifiedParams}`
        : `/api/environments/${projectId}/dataset_items/`
}

export const environmentsDatasetItemsList = async (
    projectId: string,
    params?: EnvironmentsDatasetItemsListParams,
    options?: RequestInit
): Promise<environmentsDatasetItemsListResponse> => {
    return apiMutator<environmentsDatasetItemsListResponse>(getEnvironmentsDatasetItemsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type environmentsDatasetItemsCreateResponse201 = {
    data: DatasetItemApi
    status: 201
}

export type environmentsDatasetItemsCreateResponseSuccess = environmentsDatasetItemsCreateResponse201 & {
    headers: Headers
}
export type environmentsDatasetItemsCreateResponse = environmentsDatasetItemsCreateResponseSuccess

export const getEnvironmentsDatasetItemsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/dataset_items/`
}

export const environmentsDatasetItemsCreate = async (
    projectId: string,
    datasetItemApi: NonReadonly<DatasetItemApi>,
    options?: RequestInit
): Promise<environmentsDatasetItemsCreateResponse> => {
    return apiMutator<environmentsDatasetItemsCreateResponse>(getEnvironmentsDatasetItemsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(datasetItemApi),
    })
}

export type environmentsDatasetItemsRetrieveResponse200 = {
    data: DatasetItemApi
    status: 200
}

export type environmentsDatasetItemsRetrieveResponseSuccess = environmentsDatasetItemsRetrieveResponse200 & {
    headers: Headers
}
export type environmentsDatasetItemsRetrieveResponse = environmentsDatasetItemsRetrieveResponseSuccess

export const getEnvironmentsDatasetItemsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/dataset_items/${id}/`
}

export const environmentsDatasetItemsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsDatasetItemsRetrieveResponse> => {
    return apiMutator<environmentsDatasetItemsRetrieveResponse>(getEnvironmentsDatasetItemsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type environmentsDatasetItemsUpdateResponse200 = {
    data: DatasetItemApi
    status: 200
}

export type environmentsDatasetItemsUpdateResponseSuccess = environmentsDatasetItemsUpdateResponse200 & {
    headers: Headers
}
export type environmentsDatasetItemsUpdateResponse = environmentsDatasetItemsUpdateResponseSuccess

export const getEnvironmentsDatasetItemsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/dataset_items/${id}/`
}

export const environmentsDatasetItemsUpdate = async (
    projectId: string,
    id: string,
    datasetItemApi: NonReadonly<DatasetItemApi>,
    options?: RequestInit
): Promise<environmentsDatasetItemsUpdateResponse> => {
    return apiMutator<environmentsDatasetItemsUpdateResponse>(getEnvironmentsDatasetItemsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(datasetItemApi),
    })
}

export type environmentsDatasetItemsPartialUpdateResponse200 = {
    data: DatasetItemApi
    status: 200
}

export type environmentsDatasetItemsPartialUpdateResponseSuccess = environmentsDatasetItemsPartialUpdateResponse200 & {
    headers: Headers
}
export type environmentsDatasetItemsPartialUpdateResponse = environmentsDatasetItemsPartialUpdateResponseSuccess

export const getEnvironmentsDatasetItemsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/dataset_items/${id}/`
}

export const environmentsDatasetItemsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedDatasetItemApi: NonReadonly<PatchedDatasetItemApi>,
    options?: RequestInit
): Promise<environmentsDatasetItemsPartialUpdateResponse> => {
    return apiMutator<environmentsDatasetItemsPartialUpdateResponse>(
        getEnvironmentsDatasetItemsPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedDatasetItemApi),
        }
    )
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export type environmentsDatasetItemsDestroyResponse405 = {
    data: void
    status: 405
}
export type environmentsDatasetItemsDestroyResponseError = environmentsDatasetItemsDestroyResponse405 & {
    headers: Headers
}

export type environmentsDatasetItemsDestroyResponse = environmentsDatasetItemsDestroyResponseError

export const getEnvironmentsDatasetItemsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/dataset_items/${id}/`
}

export const environmentsDatasetItemsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsDatasetItemsDestroyResponse> => {
    return apiMutator<environmentsDatasetItemsDestroyResponse>(getEnvironmentsDatasetItemsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export type environmentsDatasetsListResponse200 = {
    data: PaginatedDatasetListApi
    status: 200
}

export type environmentsDatasetsListResponseSuccess = environmentsDatasetsListResponse200 & {
    headers: Headers
}
export type environmentsDatasetsListResponse = environmentsDatasetsListResponseSuccess

export const getEnvironmentsDatasetsListUrl = (projectId: string, params?: EnvironmentsDatasetsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        const explodeParameters = ['id__in', 'order_by']

        if (Array.isArray(value) && explodeParameters.includes(key)) {
            value.forEach((v) => {
                normalizedParams.append(key, v === null ? 'null' : v.toString())
            })
            return
        }

        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/datasets/?${stringifiedParams}`
        : `/api/environments/${projectId}/datasets/`
}

export const environmentsDatasetsList = async (
    projectId: string,
    params?: EnvironmentsDatasetsListParams,
    options?: RequestInit
): Promise<environmentsDatasetsListResponse> => {
    return apiMutator<environmentsDatasetsListResponse>(getEnvironmentsDatasetsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type environmentsDatasetsCreateResponse201 = {
    data: DatasetApi
    status: 201
}

export type environmentsDatasetsCreateResponseSuccess = environmentsDatasetsCreateResponse201 & {
    headers: Headers
}
export type environmentsDatasetsCreateResponse = environmentsDatasetsCreateResponseSuccess

export const getEnvironmentsDatasetsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/datasets/`
}

export const environmentsDatasetsCreate = async (
    projectId: string,
    datasetApi: NonReadonly<DatasetApi>,
    options?: RequestInit
): Promise<environmentsDatasetsCreateResponse> => {
    return apiMutator<environmentsDatasetsCreateResponse>(getEnvironmentsDatasetsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(datasetApi),
    })
}

export type environmentsDatasetsRetrieveResponse200 = {
    data: DatasetApi
    status: 200
}

export type environmentsDatasetsRetrieveResponseSuccess = environmentsDatasetsRetrieveResponse200 & {
    headers: Headers
}
export type environmentsDatasetsRetrieveResponse = environmentsDatasetsRetrieveResponseSuccess

export const getEnvironmentsDatasetsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/datasets/${id}/`
}

export const environmentsDatasetsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsDatasetsRetrieveResponse> => {
    return apiMutator<environmentsDatasetsRetrieveResponse>(getEnvironmentsDatasetsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type environmentsDatasetsUpdateResponse200 = {
    data: DatasetApi
    status: 200
}

export type environmentsDatasetsUpdateResponseSuccess = environmentsDatasetsUpdateResponse200 & {
    headers: Headers
}
export type environmentsDatasetsUpdateResponse = environmentsDatasetsUpdateResponseSuccess

export const getEnvironmentsDatasetsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/datasets/${id}/`
}

export const environmentsDatasetsUpdate = async (
    projectId: string,
    id: string,
    datasetApi: NonReadonly<DatasetApi>,
    options?: RequestInit
): Promise<environmentsDatasetsUpdateResponse> => {
    return apiMutator<environmentsDatasetsUpdateResponse>(getEnvironmentsDatasetsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(datasetApi),
    })
}

export type environmentsDatasetsPartialUpdateResponse200 = {
    data: DatasetApi
    status: 200
}

export type environmentsDatasetsPartialUpdateResponseSuccess = environmentsDatasetsPartialUpdateResponse200 & {
    headers: Headers
}
export type environmentsDatasetsPartialUpdateResponse = environmentsDatasetsPartialUpdateResponseSuccess

export const getEnvironmentsDatasetsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/datasets/${id}/`
}

export const environmentsDatasetsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedDatasetApi: NonReadonly<PatchedDatasetApi>,
    options?: RequestInit
): Promise<environmentsDatasetsPartialUpdateResponse> => {
    return apiMutator<environmentsDatasetsPartialUpdateResponse>(
        getEnvironmentsDatasetsPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedDatasetApi),
        }
    )
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export type environmentsDatasetsDestroyResponse405 = {
    data: void
    status: 405
}
export type environmentsDatasetsDestroyResponseError = environmentsDatasetsDestroyResponse405 & {
    headers: Headers
}

export type environmentsDatasetsDestroyResponse = environmentsDatasetsDestroyResponseError

export const getEnvironmentsDatasetsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/datasets/${id}/`
}

export const environmentsDatasetsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsDatasetsDestroyResponse> => {
    return apiMutator<environmentsDatasetsDestroyResponse>(getEnvironmentsDatasetsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export type datasetItemsListResponse200 = {
    data: PaginatedDatasetItemListApi
    status: 200
}

export type datasetItemsListResponseSuccess = datasetItemsListResponse200 & {
    headers: Headers
}
export type datasetItemsListResponse = datasetItemsListResponseSuccess

export const getDatasetItemsListUrl = (projectId: string, params?: DatasetItemsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/dataset_items/?${stringifiedParams}`
        : `/api/projects/${projectId}/dataset_items/`
}

export const datasetItemsList = async (
    projectId: string,
    params?: DatasetItemsListParams,
    options?: RequestInit
): Promise<datasetItemsListResponse> => {
    return apiMutator<datasetItemsListResponse>(getDatasetItemsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type datasetItemsCreateResponse201 = {
    data: DatasetItemApi
    status: 201
}

export type datasetItemsCreateResponseSuccess = datasetItemsCreateResponse201 & {
    headers: Headers
}
export type datasetItemsCreateResponse = datasetItemsCreateResponseSuccess

export const getDatasetItemsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/dataset_items/`
}

export const datasetItemsCreate = async (
    projectId: string,
    datasetItemApi: NonReadonly<DatasetItemApi>,
    options?: RequestInit
): Promise<datasetItemsCreateResponse> => {
    return apiMutator<datasetItemsCreateResponse>(getDatasetItemsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(datasetItemApi),
    })
}

export type datasetItemsRetrieveResponse200 = {
    data: DatasetItemApi
    status: 200
}

export type datasetItemsRetrieveResponseSuccess = datasetItemsRetrieveResponse200 & {
    headers: Headers
}
export type datasetItemsRetrieveResponse = datasetItemsRetrieveResponseSuccess

export const getDatasetItemsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/dataset_items/${id}/`
}

export const datasetItemsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<datasetItemsRetrieveResponse> => {
    return apiMutator<datasetItemsRetrieveResponse>(getDatasetItemsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type datasetItemsUpdateResponse200 = {
    data: DatasetItemApi
    status: 200
}

export type datasetItemsUpdateResponseSuccess = datasetItemsUpdateResponse200 & {
    headers: Headers
}
export type datasetItemsUpdateResponse = datasetItemsUpdateResponseSuccess

export const getDatasetItemsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/dataset_items/${id}/`
}

export const datasetItemsUpdate = async (
    projectId: string,
    id: string,
    datasetItemApi: NonReadonly<DatasetItemApi>,
    options?: RequestInit
): Promise<datasetItemsUpdateResponse> => {
    return apiMutator<datasetItemsUpdateResponse>(getDatasetItemsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(datasetItemApi),
    })
}

export type datasetItemsPartialUpdateResponse200 = {
    data: DatasetItemApi
    status: 200
}

export type datasetItemsPartialUpdateResponseSuccess = datasetItemsPartialUpdateResponse200 & {
    headers: Headers
}
export type datasetItemsPartialUpdateResponse = datasetItemsPartialUpdateResponseSuccess

export const getDatasetItemsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/dataset_items/${id}/`
}

export const datasetItemsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedDatasetItemApi: NonReadonly<PatchedDatasetItemApi>,
    options?: RequestInit
): Promise<datasetItemsPartialUpdateResponse> => {
    return apiMutator<datasetItemsPartialUpdateResponse>(getDatasetItemsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDatasetItemApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export type datasetItemsDestroyResponse405 = {
    data: void
    status: 405
}
export type datasetItemsDestroyResponseError = datasetItemsDestroyResponse405 & {
    headers: Headers
}

export type datasetItemsDestroyResponse = datasetItemsDestroyResponseError

export const getDatasetItemsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/dataset_items/${id}/`
}

export const datasetItemsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<datasetItemsDestroyResponse> => {
    return apiMutator<datasetItemsDestroyResponse>(getDatasetItemsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export type datasetsListResponse200 = {
    data: PaginatedDatasetListApi
    status: 200
}

export type datasetsListResponseSuccess = datasetsListResponse200 & {
    headers: Headers
}
export type datasetsListResponse = datasetsListResponseSuccess

export const getDatasetsListUrl = (projectId: string, params?: DatasetsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        const explodeParameters = ['id__in', 'order_by']

        if (Array.isArray(value) && explodeParameters.includes(key)) {
            value.forEach((v) => {
                normalizedParams.append(key, v === null ? 'null' : v.toString())
            })
            return
        }

        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/datasets/?${stringifiedParams}`
        : `/api/projects/${projectId}/datasets/`
}

export const datasetsList = async (
    projectId: string,
    params?: DatasetsListParams,
    options?: RequestInit
): Promise<datasetsListResponse> => {
    return apiMutator<datasetsListResponse>(getDatasetsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type datasetsCreateResponse201 = {
    data: DatasetApi
    status: 201
}

export type datasetsCreateResponseSuccess = datasetsCreateResponse201 & {
    headers: Headers
}
export type datasetsCreateResponse = datasetsCreateResponseSuccess

export const getDatasetsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/datasets/`
}

export const datasetsCreate = async (
    projectId: string,
    datasetApi: NonReadonly<DatasetApi>,
    options?: RequestInit
): Promise<datasetsCreateResponse> => {
    return apiMutator<datasetsCreateResponse>(getDatasetsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(datasetApi),
    })
}

export type datasetsRetrieveResponse200 = {
    data: DatasetApi
    status: 200
}

export type datasetsRetrieveResponseSuccess = datasetsRetrieveResponse200 & {
    headers: Headers
}
export type datasetsRetrieveResponse = datasetsRetrieveResponseSuccess

export const getDatasetsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/datasets/${id}/`
}

export const datasetsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<datasetsRetrieveResponse> => {
    return apiMutator<datasetsRetrieveResponse>(getDatasetsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type datasetsUpdateResponse200 = {
    data: DatasetApi
    status: 200
}

export type datasetsUpdateResponseSuccess = datasetsUpdateResponse200 & {
    headers: Headers
}
export type datasetsUpdateResponse = datasetsUpdateResponseSuccess

export const getDatasetsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/datasets/${id}/`
}

export const datasetsUpdate = async (
    projectId: string,
    id: string,
    datasetApi: NonReadonly<DatasetApi>,
    options?: RequestInit
): Promise<datasetsUpdateResponse> => {
    return apiMutator<datasetsUpdateResponse>(getDatasetsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(datasetApi),
    })
}

export type datasetsPartialUpdateResponse200 = {
    data: DatasetApi
    status: 200
}

export type datasetsPartialUpdateResponseSuccess = datasetsPartialUpdateResponse200 & {
    headers: Headers
}
export type datasetsPartialUpdateResponse = datasetsPartialUpdateResponseSuccess

export const getDatasetsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/datasets/${id}/`
}

export const datasetsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedDatasetApi: NonReadonly<PatchedDatasetApi>,
    options?: RequestInit
): Promise<datasetsPartialUpdateResponse> => {
    return apiMutator<datasetsPartialUpdateResponse>(getDatasetsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDatasetApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export type datasetsDestroyResponse405 = {
    data: void
    status: 405
}
export type datasetsDestroyResponseError = datasetsDestroyResponse405 & {
    headers: Headers
}

export type datasetsDestroyResponse = datasetsDestroyResponseError

export const getDatasetsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/datasets/${id}/`
}

export const datasetsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<datasetsDestroyResponse> => {
    return apiMutator<datasetsDestroyResponse>(getDatasetsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}
