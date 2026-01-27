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
    BatchCheckRequestApi,
    BatchCheckResponseApi,
    ClusteringRunRequestApi,
    DatasetApi,
    DatasetItemApi,
    DatasetItemsList2Params,
    DatasetItemsListParams,
    DatasetsList2Params,
    DatasetsListParams,
    EvaluationApi,
    EvaluationsListParams,
    LLMProviderKeyApi,
    LlmAnalyticsProviderKeysListParams,
    LlmAnalyticsSummarizationBatchCheckCreate400,
    LlmAnalyticsSummarizationBatchCheckCreate403,
    LlmAnalyticsSummarizationCreate400,
    LlmAnalyticsSummarizationCreate403,
    LlmAnalyticsSummarizationCreate500,
    LlmAnalyticsTextReprCreate400,
    LlmAnalyticsTextReprCreate500,
    LlmAnalyticsTextReprCreate503,
    PaginatedDatasetItemListApi,
    PaginatedDatasetListApi,
    PaginatedEvaluationListApi,
    PaginatedLLMProviderKeyListApi,
    PatchedDatasetApi,
    PatchedDatasetItemApi,
    PatchedLLMProviderKeyApi,
    SummarizeRequestApi,
    SummarizeResponseApi,
    TextReprRequestApi,
    TextReprResponseApi,
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
        ? `/api/environments/${projectId}/dataset_items/?${stringifiedParams}`
        : `/api/environments/${projectId}/dataset_items/`
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
    return `/api/environments/${projectId}/dataset_items/`
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
    return `/api/environments/${projectId}/dataset_items/${id}/`
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
    return `/api/environments/${projectId}/dataset_items/${id}/`
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
    return `/api/environments/${projectId}/dataset_items/${id}/`
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
    return `/api/environments/${projectId}/dataset_items/${id}/`
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
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/datasets/?${stringifiedParams}`
        : `/api/environments/${projectId}/datasets/`
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
    return `/api/environments/${projectId}/datasets/`
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
    return `/api/environments/${projectId}/datasets/${id}/`
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
    return `/api/environments/${projectId}/datasets/${id}/`
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
    return `/api/environments/${projectId}/datasets/${id}/`
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
    return `/api/environments/${projectId}/datasets/${id}/`
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

/**
 * Create a new evaluation run.

This endpoint validates the request and enqueues a Temporal workflow
to asynchronously execute the evaluation.
 */
export type evaluationRunsCreateResponse201 = {
    data: void
    status: 201
}

export type evaluationRunsCreateResponseSuccess = evaluationRunsCreateResponse201 & {
    headers: Headers
}
export type evaluationRunsCreateResponse = evaluationRunsCreateResponseSuccess

export const getEvaluationRunsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/evaluation_runs/`
}

export const evaluationRunsCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<evaluationRunsCreateResponse> => {
    return apiMutator<evaluationRunsCreateResponse>(getEvaluationRunsCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export type evaluationsListResponse200 = {
    data: PaginatedEvaluationListApi
    status: 200
}

export type evaluationsListResponseSuccess = evaluationsListResponse200 & {
    headers: Headers
}
export type evaluationsListResponse = evaluationsListResponseSuccess

export const getEvaluationsListUrl = (projectId: string, params?: EvaluationsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/evaluations/?${stringifiedParams}`
        : `/api/environments/${projectId}/evaluations/`
}

export const evaluationsList = async (
    projectId: string,
    params?: EvaluationsListParams,
    options?: RequestInit
): Promise<evaluationsListResponse> => {
    return apiMutator<evaluationsListResponse>(getEvaluationsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type evaluationsCreateResponse201 = {
    data: EvaluationApi
    status: 201
}

export type evaluationsCreateResponseSuccess = evaluationsCreateResponse201 & {
    headers: Headers
}
export type evaluationsCreateResponse = evaluationsCreateResponseSuccess

export const getEvaluationsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/evaluations/`
}

export const evaluationsCreate = async (
    projectId: string,
    evaluationApi: NonReadonly<EvaluationApi>,
    options?: RequestInit
): Promise<evaluationsCreateResponse> => {
    return apiMutator<evaluationsCreateResponse>(getEvaluationsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(evaluationApi),
    })
}

/**
 * Trigger a new clustering workflow run.

This endpoint validates the request parameters and starts a Temporal workflow
to perform trace clustering with the specified configuration.
 */
export type llmAnalyticsClusteringRunsCreateResponse201 = {
    data: ClusteringRunRequestApi
    status: 201
}

export type llmAnalyticsClusteringRunsCreateResponseSuccess = llmAnalyticsClusteringRunsCreateResponse201 & {
    headers: Headers
}
export type llmAnalyticsClusteringRunsCreateResponse = llmAnalyticsClusteringRunsCreateResponseSuccess

export const getLlmAnalyticsClusteringRunsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/clustering_runs/`
}

export const llmAnalyticsClusteringRunsCreate = async (
    projectId: string,
    clusteringRunRequestApi: ClusteringRunRequestApi,
    options?: RequestInit
): Promise<llmAnalyticsClusteringRunsCreateResponse> => {
    return apiMutator<llmAnalyticsClusteringRunsCreateResponse>(getLlmAnalyticsClusteringRunsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(clusteringRunRequestApi),
    })
}

/**
 * Get the evaluation config for this team
 */
export type llmAnalyticsEvaluationConfigRetrieveResponse200 = {
    data: void
    status: 200
}

export type llmAnalyticsEvaluationConfigRetrieveResponseSuccess = llmAnalyticsEvaluationConfigRetrieveResponse200 & {
    headers: Headers
}
export type llmAnalyticsEvaluationConfigRetrieveResponse = llmAnalyticsEvaluationConfigRetrieveResponseSuccess

export const getLlmAnalyticsEvaluationConfigRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/evaluation_config/`
}

export const llmAnalyticsEvaluationConfigRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<llmAnalyticsEvaluationConfigRetrieveResponse> => {
    return apiMutator<llmAnalyticsEvaluationConfigRetrieveResponse>(
        getLlmAnalyticsEvaluationConfigRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Set the active provider key for evaluations
 */
export type llmAnalyticsEvaluationConfigSetActiveKeyCreateResponse200 = {
    data: void
    status: 200
}

export type llmAnalyticsEvaluationConfigSetActiveKeyCreateResponseSuccess =
    llmAnalyticsEvaluationConfigSetActiveKeyCreateResponse200 & {
        headers: Headers
    }
export type llmAnalyticsEvaluationConfigSetActiveKeyCreateResponse =
    llmAnalyticsEvaluationConfigSetActiveKeyCreateResponseSuccess

export const getLlmAnalyticsEvaluationConfigSetActiveKeyCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/evaluation_config/set_active_key/`
}

export const llmAnalyticsEvaluationConfigSetActiveKeyCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<llmAnalyticsEvaluationConfigSetActiveKeyCreateResponse> => {
    return apiMutator<llmAnalyticsEvaluationConfigSetActiveKeyCreateResponse>(
        getLlmAnalyticsEvaluationConfigSetActiveKeyCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
        }
    )
}

/**
 * Validate LLM provider API keys without persisting them
 */
export type llmAnalyticsProviderKeyValidationsCreateResponse201 = {
    data: void
    status: 201
}

export type llmAnalyticsProviderKeyValidationsCreateResponseSuccess =
    llmAnalyticsProviderKeyValidationsCreateResponse201 & {
        headers: Headers
    }
export type llmAnalyticsProviderKeyValidationsCreateResponse = llmAnalyticsProviderKeyValidationsCreateResponseSuccess

export const getLlmAnalyticsProviderKeyValidationsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/provider_key_validations/`
}

export const llmAnalyticsProviderKeyValidationsCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<llmAnalyticsProviderKeyValidationsCreateResponse> => {
    return apiMutator<llmAnalyticsProviderKeyValidationsCreateResponse>(
        getLlmAnalyticsProviderKeyValidationsCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
        }
    )
}

export type llmAnalyticsProviderKeysListResponse200 = {
    data: PaginatedLLMProviderKeyListApi
    status: 200
}

export type llmAnalyticsProviderKeysListResponseSuccess = llmAnalyticsProviderKeysListResponse200 & {
    headers: Headers
}
export type llmAnalyticsProviderKeysListResponse = llmAnalyticsProviderKeysListResponseSuccess

export const getLlmAnalyticsProviderKeysListUrl = (projectId: string, params?: LlmAnalyticsProviderKeysListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/llm_analytics/provider_keys/?${stringifiedParams}`
        : `/api/environments/${projectId}/llm_analytics/provider_keys/`
}

export const llmAnalyticsProviderKeysList = async (
    projectId: string,
    params?: LlmAnalyticsProviderKeysListParams,
    options?: RequestInit
): Promise<llmAnalyticsProviderKeysListResponse> => {
    return apiMutator<llmAnalyticsProviderKeysListResponse>(getLlmAnalyticsProviderKeysListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type llmAnalyticsProviderKeysCreateResponse201 = {
    data: LLMProviderKeyApi
    status: 201
}

export type llmAnalyticsProviderKeysCreateResponseSuccess = llmAnalyticsProviderKeysCreateResponse201 & {
    headers: Headers
}
export type llmAnalyticsProviderKeysCreateResponse = llmAnalyticsProviderKeysCreateResponseSuccess

export const getLlmAnalyticsProviderKeysCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/provider_keys/`
}

export const llmAnalyticsProviderKeysCreate = async (
    projectId: string,
    lLMProviderKeyApi: NonReadonly<LLMProviderKeyApi>,
    options?: RequestInit
): Promise<llmAnalyticsProviderKeysCreateResponse> => {
    return apiMutator<llmAnalyticsProviderKeysCreateResponse>(getLlmAnalyticsProviderKeysCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(lLMProviderKeyApi),
    })
}

export type llmAnalyticsProviderKeysRetrieveResponse200 = {
    data: LLMProviderKeyApi
    status: 200
}

export type llmAnalyticsProviderKeysRetrieveResponseSuccess = llmAnalyticsProviderKeysRetrieveResponse200 & {
    headers: Headers
}
export type llmAnalyticsProviderKeysRetrieveResponse = llmAnalyticsProviderKeysRetrieveResponseSuccess

export const getLlmAnalyticsProviderKeysRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/provider_keys/${id}/`
}

export const llmAnalyticsProviderKeysRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<llmAnalyticsProviderKeysRetrieveResponse> => {
    return apiMutator<llmAnalyticsProviderKeysRetrieveResponse>(getLlmAnalyticsProviderKeysRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type llmAnalyticsProviderKeysUpdateResponse200 = {
    data: LLMProviderKeyApi
    status: 200
}

export type llmAnalyticsProviderKeysUpdateResponseSuccess = llmAnalyticsProviderKeysUpdateResponse200 & {
    headers: Headers
}
export type llmAnalyticsProviderKeysUpdateResponse = llmAnalyticsProviderKeysUpdateResponseSuccess

export const getLlmAnalyticsProviderKeysUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/provider_keys/${id}/`
}

export const llmAnalyticsProviderKeysUpdate = async (
    projectId: string,
    id: string,
    lLMProviderKeyApi: NonReadonly<LLMProviderKeyApi>,
    options?: RequestInit
): Promise<llmAnalyticsProviderKeysUpdateResponse> => {
    return apiMutator<llmAnalyticsProviderKeysUpdateResponse>(getLlmAnalyticsProviderKeysUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(lLMProviderKeyApi),
    })
}

export type llmAnalyticsProviderKeysPartialUpdateResponse200 = {
    data: LLMProviderKeyApi
    status: 200
}

export type llmAnalyticsProviderKeysPartialUpdateResponseSuccess = llmAnalyticsProviderKeysPartialUpdateResponse200 & {
    headers: Headers
}
export type llmAnalyticsProviderKeysPartialUpdateResponse = llmAnalyticsProviderKeysPartialUpdateResponseSuccess

export const getLlmAnalyticsProviderKeysPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/provider_keys/${id}/`
}

export const llmAnalyticsProviderKeysPartialUpdate = async (
    projectId: string,
    id: string,
    patchedLLMProviderKeyApi: NonReadonly<PatchedLLMProviderKeyApi>,
    options?: RequestInit
): Promise<llmAnalyticsProviderKeysPartialUpdateResponse> => {
    return apiMutator<llmAnalyticsProviderKeysPartialUpdateResponse>(
        getLlmAnalyticsProviderKeysPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedLLMProviderKeyApi),
        }
    )
}

export type llmAnalyticsProviderKeysDestroyResponse204 = {
    data: void
    status: 204
}

export type llmAnalyticsProviderKeysDestroyResponseSuccess = llmAnalyticsProviderKeysDestroyResponse204 & {
    headers: Headers
}
export type llmAnalyticsProviderKeysDestroyResponse = llmAnalyticsProviderKeysDestroyResponseSuccess

export const getLlmAnalyticsProviderKeysDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/provider_keys/${id}/`
}

export const llmAnalyticsProviderKeysDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<llmAnalyticsProviderKeysDestroyResponse> => {
    return apiMutator<llmAnalyticsProviderKeysDestroyResponse>(getLlmAnalyticsProviderKeysDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export type llmAnalyticsProviderKeysValidateCreateResponse200 = {
    data: LLMProviderKeyApi
    status: 200
}

export type llmAnalyticsProviderKeysValidateCreateResponseSuccess =
    llmAnalyticsProviderKeysValidateCreateResponse200 & {
        headers: Headers
    }
export type llmAnalyticsProviderKeysValidateCreateResponse = llmAnalyticsProviderKeysValidateCreateResponseSuccess

export const getLlmAnalyticsProviderKeysValidateCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/provider_keys/${id}/validate/`
}

export const llmAnalyticsProviderKeysValidateCreate = async (
    projectId: string,
    id: string,
    lLMProviderKeyApi: NonReadonly<LLMProviderKeyApi>,
    options?: RequestInit
): Promise<llmAnalyticsProviderKeysValidateCreateResponse> => {
    return apiMutator<llmAnalyticsProviderKeysValidateCreateResponse>(
        getLlmAnalyticsProviderKeysValidateCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(lLMProviderKeyApi),
        }
    )
}

/**
 * 
Generate an AI-powered summary of an LLM trace or event.

This endpoint analyzes the provided trace/event, generates a line-numbered text
representation, and uses an LLM to create a concise summary with line references.

**Summary Format:**
- 5-10 bullet points covering main flow and key decisions
- "Interesting Notes" section for failures, successes, or unusual patterns
- Line references in [L45] or [L45-52] format pointing to relevant sections

**Use Cases:**
- Quick understanding of complex traces
- Identifying key events and patterns
- Debugging with AI-assisted analysis
- Documentation and reporting

The response includes the summary text and optional metadata.
        
 */
export type llmAnalyticsSummarizationCreateResponse200 = {
    data: SummarizeResponseApi
    status: 200
}

export type llmAnalyticsSummarizationCreateResponse400 = {
    data: LlmAnalyticsSummarizationCreate400
    status: 400
}

export type llmAnalyticsSummarizationCreateResponse403 = {
    data: LlmAnalyticsSummarizationCreate403
    status: 403
}

export type llmAnalyticsSummarizationCreateResponse500 = {
    data: LlmAnalyticsSummarizationCreate500
    status: 500
}

export type llmAnalyticsSummarizationCreateResponseSuccess = llmAnalyticsSummarizationCreateResponse200 & {
    headers: Headers
}
export type llmAnalyticsSummarizationCreateResponseError = (
    | llmAnalyticsSummarizationCreateResponse400
    | llmAnalyticsSummarizationCreateResponse403
    | llmAnalyticsSummarizationCreateResponse500
) & {
    headers: Headers
}

export type llmAnalyticsSummarizationCreateResponse =
    | llmAnalyticsSummarizationCreateResponseSuccess
    | llmAnalyticsSummarizationCreateResponseError

export const getLlmAnalyticsSummarizationCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/summarization/`
}

export const llmAnalyticsSummarizationCreate = async (
    projectId: string,
    summarizeRequestApi: SummarizeRequestApi,
    options?: RequestInit
): Promise<llmAnalyticsSummarizationCreateResponse> => {
    return apiMutator<llmAnalyticsSummarizationCreateResponse>(getLlmAnalyticsSummarizationCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(summarizeRequestApi),
    })
}

/**
 * 
Check which traces have cached summaries available.

This endpoint allows batch checking of multiple trace IDs to see which ones
have cached summaries. Returns only the traces that have cached summaries
with their titles.

**Use Cases:**
- Load cached summaries on session view load
- Avoid unnecessary LLM calls for already-summarized traces
- Display summary previews without generating new summaries
        
 */
export type llmAnalyticsSummarizationBatchCheckCreateResponse200 = {
    data: BatchCheckResponseApi
    status: 200
}

export type llmAnalyticsSummarizationBatchCheckCreateResponse400 = {
    data: LlmAnalyticsSummarizationBatchCheckCreate400
    status: 400
}

export type llmAnalyticsSummarizationBatchCheckCreateResponse403 = {
    data: LlmAnalyticsSummarizationBatchCheckCreate403
    status: 403
}

export type llmAnalyticsSummarizationBatchCheckCreateResponseSuccess =
    llmAnalyticsSummarizationBatchCheckCreateResponse200 & {
        headers: Headers
    }
export type llmAnalyticsSummarizationBatchCheckCreateResponseError = (
    | llmAnalyticsSummarizationBatchCheckCreateResponse400
    | llmAnalyticsSummarizationBatchCheckCreateResponse403
) & {
    headers: Headers
}

export type llmAnalyticsSummarizationBatchCheckCreateResponse =
    | llmAnalyticsSummarizationBatchCheckCreateResponseSuccess
    | llmAnalyticsSummarizationBatchCheckCreateResponseError

export const getLlmAnalyticsSummarizationBatchCheckCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/summarization/batch_check/`
}

export const llmAnalyticsSummarizationBatchCheckCreate = async (
    projectId: string,
    batchCheckRequestApi: BatchCheckRequestApi,
    options?: RequestInit
): Promise<llmAnalyticsSummarizationBatchCheckCreateResponse> => {
    return apiMutator<llmAnalyticsSummarizationBatchCheckCreateResponse>(
        getLlmAnalyticsSummarizationBatchCheckCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(batchCheckRequestApi),
        }
    )
}

/**
 * 
Generate a human-readable text representation of an LLM trace event.

This endpoint converts LLM analytics events ($ai_generation, $ai_span, $ai_embedding, or $ai_trace)
into formatted text representations suitable for display, logging, or analysis.

**Supported Event Types:**
- `$ai_generation`: Individual LLM API calls with input/output messages
- `$ai_span`: Logical spans with state transitions
- `$ai_embedding`: Embedding generation events (text input → vector)
- `$ai_trace`: Full traces with hierarchical structure

**Options:**
- `max_length`: Maximum character count (default: 2000000)
- `truncated`: Enable middle-content truncation within events (default: true)
- `truncate_buffer`: Characters at start/end when truncating (default: 1000)
- `include_markers`: Use interactive markers vs plain text indicators (default: true)
  - Frontend: set true for `<<<TRUNCATED|base64|...>>>` markers
  - Backend/LLM: set false for `... (X chars truncated) ...` text
- `collapsed`: Show summary vs full trace tree (default: false)
- `include_hierarchy`: Include tree structure for traces (default: true)
- `max_depth`: Maximum depth for hierarchical rendering (default: unlimited)
- `tools_collapse_threshold`: Number of tools before auto-collapsing list (default: 5)
  - Tool lists >5 items show `<<<TOOLS_EXPANDABLE|...>>>` marker for frontend
  - Or `[+] AVAILABLE TOOLS: N` for backend when `include_markers: false`
- `include_line_numbers`: Prefix each line with line number like L001:, L010: (default: false)

**Use Cases:**
- Frontend display: `truncated: true, include_markers: true, include_line_numbers: true`
- Backend LLM context (summary): `truncated: true, include_markers: false, collapsed: true`
- Backend LLM context (full): `truncated: false`

The response includes the formatted text and metadata about the rendering.
        
 */
export type llmAnalyticsTextReprCreateResponse200 = {
    data: TextReprResponseApi
    status: 200
}

export type llmAnalyticsTextReprCreateResponse400 = {
    data: LlmAnalyticsTextReprCreate400
    status: 400
}

export type llmAnalyticsTextReprCreateResponse500 = {
    data: LlmAnalyticsTextReprCreate500
    status: 500
}

export type llmAnalyticsTextReprCreateResponse503 = {
    data: LlmAnalyticsTextReprCreate503
    status: 503
}

export type llmAnalyticsTextReprCreateResponseSuccess = llmAnalyticsTextReprCreateResponse200 & {
    headers: Headers
}
export type llmAnalyticsTextReprCreateResponseError = (
    | llmAnalyticsTextReprCreateResponse400
    | llmAnalyticsTextReprCreateResponse500
    | llmAnalyticsTextReprCreateResponse503
) & {
    headers: Headers
}

export type llmAnalyticsTextReprCreateResponse =
    | llmAnalyticsTextReprCreateResponseSuccess
    | llmAnalyticsTextReprCreateResponseError

export const getLlmAnalyticsTextReprCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/text_repr/`
}

export const llmAnalyticsTextReprCreate = async (
    projectId: string,
    textReprRequestApi: TextReprRequestApi,
    options?: RequestInit
): Promise<llmAnalyticsTextReprCreateResponse> => {
    return apiMutator<llmAnalyticsTextReprCreateResponse>(getLlmAnalyticsTextReprCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(textReprRequestApi),
    })
}

/**
 * Translate text to target language.
 */
export type llmAnalyticsTranslateCreateResponse201 = {
    data: void
    status: 201
}

export type llmAnalyticsTranslateCreateResponseSuccess = llmAnalyticsTranslateCreateResponse201 & {
    headers: Headers
}
export type llmAnalyticsTranslateCreateResponse = llmAnalyticsTranslateCreateResponseSuccess

export const getLlmAnalyticsTranslateCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/translate/`
}

export const llmAnalyticsTranslateCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<llmAnalyticsTranslateCreateResponse> => {
    return apiMutator<llmAnalyticsTranslateCreateResponse>(getLlmAnalyticsTranslateCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export type datasetItemsList2Response200 = {
    data: PaginatedDatasetItemListApi
    status: 200
}

export type datasetItemsList2ResponseSuccess = datasetItemsList2Response200 & {
    headers: Headers
}
export type datasetItemsList2Response = datasetItemsList2ResponseSuccess

export const getDatasetItemsList2Url = (projectId: string, params?: DatasetItemsList2Params) => {
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

export const datasetItemsList2 = async (
    projectId: string,
    params?: DatasetItemsList2Params,
    options?: RequestInit
): Promise<datasetItemsList2Response> => {
    return apiMutator<datasetItemsList2Response>(getDatasetItemsList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type datasetItemsCreate2Response201 = {
    data: DatasetItemApi
    status: 201
}

export type datasetItemsCreate2ResponseSuccess = datasetItemsCreate2Response201 & {
    headers: Headers
}
export type datasetItemsCreate2Response = datasetItemsCreate2ResponseSuccess

export const getDatasetItemsCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/dataset_items/`
}

export const datasetItemsCreate2 = async (
    projectId: string,
    datasetItemApi: NonReadonly<DatasetItemApi>,
    options?: RequestInit
): Promise<datasetItemsCreate2Response> => {
    return apiMutator<datasetItemsCreate2Response>(getDatasetItemsCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(datasetItemApi),
    })
}

export type datasetItemsRetrieve2Response200 = {
    data: DatasetItemApi
    status: 200
}

export type datasetItemsRetrieve2ResponseSuccess = datasetItemsRetrieve2Response200 & {
    headers: Headers
}
export type datasetItemsRetrieve2Response = datasetItemsRetrieve2ResponseSuccess

export const getDatasetItemsRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/dataset_items/${id}/`
}

export const datasetItemsRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<datasetItemsRetrieve2Response> => {
    return apiMutator<datasetItemsRetrieve2Response>(getDatasetItemsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type datasetItemsUpdate2Response200 = {
    data: DatasetItemApi
    status: 200
}

export type datasetItemsUpdate2ResponseSuccess = datasetItemsUpdate2Response200 & {
    headers: Headers
}
export type datasetItemsUpdate2Response = datasetItemsUpdate2ResponseSuccess

export const getDatasetItemsUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/dataset_items/${id}/`
}

export const datasetItemsUpdate2 = async (
    projectId: string,
    id: string,
    datasetItemApi: NonReadonly<DatasetItemApi>,
    options?: RequestInit
): Promise<datasetItemsUpdate2Response> => {
    return apiMutator<datasetItemsUpdate2Response>(getDatasetItemsUpdate2Url(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(datasetItemApi),
    })
}

export type datasetItemsPartialUpdate2Response200 = {
    data: DatasetItemApi
    status: 200
}

export type datasetItemsPartialUpdate2ResponseSuccess = datasetItemsPartialUpdate2Response200 & {
    headers: Headers
}
export type datasetItemsPartialUpdate2Response = datasetItemsPartialUpdate2ResponseSuccess

export const getDatasetItemsPartialUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/dataset_items/${id}/`
}

export const datasetItemsPartialUpdate2 = async (
    projectId: string,
    id: string,
    patchedDatasetItemApi: NonReadonly<PatchedDatasetItemApi>,
    options?: RequestInit
): Promise<datasetItemsPartialUpdate2Response> => {
    return apiMutator<datasetItemsPartialUpdate2Response>(getDatasetItemsPartialUpdate2Url(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDatasetItemApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export type datasetItemsDestroy2Response405 = {
    data: void
    status: 405
}
export type datasetItemsDestroy2ResponseError = datasetItemsDestroy2Response405 & {
    headers: Headers
}

export type datasetItemsDestroy2Response = datasetItemsDestroy2ResponseError

export const getDatasetItemsDestroy2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/dataset_items/${id}/`
}

export const datasetItemsDestroy2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<datasetItemsDestroy2Response> => {
    return apiMutator<datasetItemsDestroy2Response>(getDatasetItemsDestroy2Url(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export type datasetsList2Response200 = {
    data: PaginatedDatasetListApi
    status: 200
}

export type datasetsList2ResponseSuccess = datasetsList2Response200 & {
    headers: Headers
}
export type datasetsList2Response = datasetsList2ResponseSuccess

export const getDatasetsList2Url = (projectId: string, params?: DatasetsList2Params) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/datasets/?${stringifiedParams}`
        : `/api/projects/${projectId}/datasets/`
}

export const datasetsList2 = async (
    projectId: string,
    params?: DatasetsList2Params,
    options?: RequestInit
): Promise<datasetsList2Response> => {
    return apiMutator<datasetsList2Response>(getDatasetsList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type datasetsCreate2Response201 = {
    data: DatasetApi
    status: 201
}

export type datasetsCreate2ResponseSuccess = datasetsCreate2Response201 & {
    headers: Headers
}
export type datasetsCreate2Response = datasetsCreate2ResponseSuccess

export const getDatasetsCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/datasets/`
}

export const datasetsCreate2 = async (
    projectId: string,
    datasetApi: NonReadonly<DatasetApi>,
    options?: RequestInit
): Promise<datasetsCreate2Response> => {
    return apiMutator<datasetsCreate2Response>(getDatasetsCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(datasetApi),
    })
}

export type datasetsRetrieve2Response200 = {
    data: DatasetApi
    status: 200
}

export type datasetsRetrieve2ResponseSuccess = datasetsRetrieve2Response200 & {
    headers: Headers
}
export type datasetsRetrieve2Response = datasetsRetrieve2ResponseSuccess

export const getDatasetsRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/datasets/${id}/`
}

export const datasetsRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<datasetsRetrieve2Response> => {
    return apiMutator<datasetsRetrieve2Response>(getDatasetsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type datasetsUpdate2Response200 = {
    data: DatasetApi
    status: 200
}

export type datasetsUpdate2ResponseSuccess = datasetsUpdate2Response200 & {
    headers: Headers
}
export type datasetsUpdate2Response = datasetsUpdate2ResponseSuccess

export const getDatasetsUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/datasets/${id}/`
}

export const datasetsUpdate2 = async (
    projectId: string,
    id: string,
    datasetApi: NonReadonly<DatasetApi>,
    options?: RequestInit
): Promise<datasetsUpdate2Response> => {
    return apiMutator<datasetsUpdate2Response>(getDatasetsUpdate2Url(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(datasetApi),
    })
}

export type datasetsPartialUpdate2Response200 = {
    data: DatasetApi
    status: 200
}

export type datasetsPartialUpdate2ResponseSuccess = datasetsPartialUpdate2Response200 & {
    headers: Headers
}
export type datasetsPartialUpdate2Response = datasetsPartialUpdate2ResponseSuccess

export const getDatasetsPartialUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/datasets/${id}/`
}

export const datasetsPartialUpdate2 = async (
    projectId: string,
    id: string,
    patchedDatasetApi: NonReadonly<PatchedDatasetApi>,
    options?: RequestInit
): Promise<datasetsPartialUpdate2Response> => {
    return apiMutator<datasetsPartialUpdate2Response>(getDatasetsPartialUpdate2Url(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDatasetApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export type datasetsDestroy2Response405 = {
    data: void
    status: 405
}
export type datasetsDestroy2ResponseError = datasetsDestroy2Response405 & {
    headers: Headers
}

export type datasetsDestroy2Response = datasetsDestroy2ResponseError

export const getDatasetsDestroy2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/datasets/${id}/`
}

export const datasetsDestroy2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<datasetsDestroy2Response> => {
    return apiMutator<datasetsDestroy2Response>(getDatasetsDestroy2Url(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}
