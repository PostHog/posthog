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
    DatasetItemsListParams,
    DatasetsListParams,
    EnvironmentsDatasetItemsListParams,
    EnvironmentsDatasetsListParams,
    EnvironmentsEvaluationsListParams,
    EnvironmentsLlmAnalyticsProviderKeysListParams,
    EnvironmentsLlmAnalyticsSummarizationBatchCheckCreate400,
    EnvironmentsLlmAnalyticsSummarizationBatchCheckCreate403,
    EnvironmentsLlmAnalyticsSummarizationCreate400,
    EnvironmentsLlmAnalyticsSummarizationCreate403,
    EnvironmentsLlmAnalyticsSummarizationCreate500,
    EnvironmentsLlmAnalyticsTextReprCreate400,
    EnvironmentsLlmAnalyticsTextReprCreate500,
    EnvironmentsLlmAnalyticsTextReprCreate503,
    EvaluationApi,
    FeatureFlagsEvaluationReasonsRetrieveParams,
    FeatureFlagsLocalEvaluationRetrieve402,
    FeatureFlagsLocalEvaluationRetrieve500,
    FeatureFlagsLocalEvaluationRetrieveParams,
    LLMProviderKeyApi,
    LocalEvaluationResponseApi,
    PaginatedDatasetItemListApi,
    PaginatedDatasetListApi,
    PaginatedEvaluationListApi,
    PaginatedLLMProviderKeyListApi,
    PatchedDatasetApi,
    PatchedDatasetItemApi,
    PatchedEvaluationApi,
    PatchedLLMProviderKeyApi,
    SummarizeRequestApi,
    SummarizeResponseApi,
    TeamApi,
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

/**
 * Create a new evaluation run.

This endpoint validates the request and enqueues a Temporal workflow
to asynchronously execute the evaluation.
 */
export type environmentsEvaluationRunsCreateResponse201 = {
    data: void
    status: 201
}

export type environmentsEvaluationRunsCreateResponseSuccess = environmentsEvaluationRunsCreateResponse201 & {
    headers: Headers
}
export type environmentsEvaluationRunsCreateResponse = environmentsEvaluationRunsCreateResponseSuccess

export const getEnvironmentsEvaluationRunsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/evaluation_runs/`
}

export const environmentsEvaluationRunsCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsEvaluationRunsCreateResponse> => {
    return apiMutator<environmentsEvaluationRunsCreateResponse>(getEnvironmentsEvaluationRunsCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export type environmentsEvaluationsListResponse200 = {
    data: PaginatedEvaluationListApi
    status: 200
}

export type environmentsEvaluationsListResponseSuccess = environmentsEvaluationsListResponse200 & {
    headers: Headers
}
export type environmentsEvaluationsListResponse = environmentsEvaluationsListResponseSuccess

export const getEnvironmentsEvaluationsListUrl = (projectId: string, params?: EnvironmentsEvaluationsListParams) => {
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

export const environmentsEvaluationsList = async (
    projectId: string,
    params?: EnvironmentsEvaluationsListParams,
    options?: RequestInit
): Promise<environmentsEvaluationsListResponse> => {
    return apiMutator<environmentsEvaluationsListResponse>(getEnvironmentsEvaluationsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type environmentsEvaluationsCreateResponse201 = {
    data: EvaluationApi
    status: 201
}

export type environmentsEvaluationsCreateResponseSuccess = environmentsEvaluationsCreateResponse201 & {
    headers: Headers
}
export type environmentsEvaluationsCreateResponse = environmentsEvaluationsCreateResponseSuccess

export const getEnvironmentsEvaluationsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/evaluations/`
}

export const environmentsEvaluationsCreate = async (
    projectId: string,
    evaluationApi: NonReadonly<EvaluationApi>,
    options?: RequestInit
): Promise<environmentsEvaluationsCreateResponse> => {
    return apiMutator<environmentsEvaluationsCreateResponse>(getEnvironmentsEvaluationsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(evaluationApi),
    })
}

export type environmentsEvaluationsRetrieveResponse200 = {
    data: EvaluationApi
    status: 200
}

export type environmentsEvaluationsRetrieveResponseSuccess = environmentsEvaluationsRetrieveResponse200 & {
    headers: Headers
}
export type environmentsEvaluationsRetrieveResponse = environmentsEvaluationsRetrieveResponseSuccess

export const getEnvironmentsEvaluationsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/evaluations/${id}/`
}

export const environmentsEvaluationsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsEvaluationsRetrieveResponse> => {
    return apiMutator<environmentsEvaluationsRetrieveResponse>(getEnvironmentsEvaluationsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type environmentsEvaluationsUpdateResponse200 = {
    data: EvaluationApi
    status: 200
}

export type environmentsEvaluationsUpdateResponseSuccess = environmentsEvaluationsUpdateResponse200 & {
    headers: Headers
}
export type environmentsEvaluationsUpdateResponse = environmentsEvaluationsUpdateResponseSuccess

export const getEnvironmentsEvaluationsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/evaluations/${id}/`
}

export const environmentsEvaluationsUpdate = async (
    projectId: string,
    id: string,
    evaluationApi: NonReadonly<EvaluationApi>,
    options?: RequestInit
): Promise<environmentsEvaluationsUpdateResponse> => {
    return apiMutator<environmentsEvaluationsUpdateResponse>(getEnvironmentsEvaluationsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(evaluationApi),
    })
}

export type environmentsEvaluationsPartialUpdateResponse200 = {
    data: EvaluationApi
    status: 200
}

export type environmentsEvaluationsPartialUpdateResponseSuccess = environmentsEvaluationsPartialUpdateResponse200 & {
    headers: Headers
}
export type environmentsEvaluationsPartialUpdateResponse = environmentsEvaluationsPartialUpdateResponseSuccess

export const getEnvironmentsEvaluationsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/evaluations/${id}/`
}

export const environmentsEvaluationsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedEvaluationApi: NonReadonly<PatchedEvaluationApi>,
    options?: RequestInit
): Promise<environmentsEvaluationsPartialUpdateResponse> => {
    return apiMutator<environmentsEvaluationsPartialUpdateResponse>(
        getEnvironmentsEvaluationsPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedEvaluationApi),
        }
    )
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export type environmentsEvaluationsDestroyResponse405 = {
    data: void
    status: 405
}
export type environmentsEvaluationsDestroyResponseError = environmentsEvaluationsDestroyResponse405 & {
    headers: Headers
}

export type environmentsEvaluationsDestroyResponse = environmentsEvaluationsDestroyResponseError

export const getEnvironmentsEvaluationsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/evaluations/${id}/`
}

export const environmentsEvaluationsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsEvaluationsDestroyResponse> => {
    return apiMutator<environmentsEvaluationsDestroyResponse>(getEnvironmentsEvaluationsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Trigger a new clustering workflow run.

This endpoint validates the request parameters and starts a Temporal workflow
to perform trace clustering with the specified configuration.
 */
export type environmentsLlmAnalyticsClusteringRunsCreateResponse201 = {
    data: ClusteringRunRequestApi
    status: 201
}

export type environmentsLlmAnalyticsClusteringRunsCreateResponseSuccess =
    environmentsLlmAnalyticsClusteringRunsCreateResponse201 & {
        headers: Headers
    }
export type environmentsLlmAnalyticsClusteringRunsCreateResponse =
    environmentsLlmAnalyticsClusteringRunsCreateResponseSuccess

export const getEnvironmentsLlmAnalyticsClusteringRunsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/clustering_runs/`
}

export const environmentsLlmAnalyticsClusteringRunsCreate = async (
    projectId: string,
    clusteringRunRequestApi: ClusteringRunRequestApi,
    options?: RequestInit
): Promise<environmentsLlmAnalyticsClusteringRunsCreateResponse> => {
    return apiMutator<environmentsLlmAnalyticsClusteringRunsCreateResponse>(
        getEnvironmentsLlmAnalyticsClusteringRunsCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(clusteringRunRequestApi),
        }
    )
}

/**
 * Get the evaluation config for this team
 */
export type environmentsLlmAnalyticsEvaluationConfigRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsLlmAnalyticsEvaluationConfigRetrieveResponseSuccess =
    environmentsLlmAnalyticsEvaluationConfigRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsLlmAnalyticsEvaluationConfigRetrieveResponse =
    environmentsLlmAnalyticsEvaluationConfigRetrieveResponseSuccess

export const getEnvironmentsLlmAnalyticsEvaluationConfigRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/evaluation_config/`
}

export const environmentsLlmAnalyticsEvaluationConfigRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsLlmAnalyticsEvaluationConfigRetrieveResponse> => {
    return apiMutator<environmentsLlmAnalyticsEvaluationConfigRetrieveResponse>(
        getEnvironmentsLlmAnalyticsEvaluationConfigRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Set the active provider key for evaluations
 */
export type environmentsLlmAnalyticsEvaluationConfigSetActiveKeyCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsLlmAnalyticsEvaluationConfigSetActiveKeyCreateResponseSuccess =
    environmentsLlmAnalyticsEvaluationConfigSetActiveKeyCreateResponse200 & {
        headers: Headers
    }
export type environmentsLlmAnalyticsEvaluationConfigSetActiveKeyCreateResponse =
    environmentsLlmAnalyticsEvaluationConfigSetActiveKeyCreateResponseSuccess

export const getEnvironmentsLlmAnalyticsEvaluationConfigSetActiveKeyCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/evaluation_config/set_active_key/`
}

export const environmentsLlmAnalyticsEvaluationConfigSetActiveKeyCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsLlmAnalyticsEvaluationConfigSetActiveKeyCreateResponse> => {
    return apiMutator<environmentsLlmAnalyticsEvaluationConfigSetActiveKeyCreateResponse>(
        getEnvironmentsLlmAnalyticsEvaluationConfigSetActiveKeyCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
        }
    )
}

/**
 * Validate LLM provider API keys without persisting them
 */
export type environmentsLlmAnalyticsProviderKeyValidationsCreateResponse201 = {
    data: void
    status: 201
}

export type environmentsLlmAnalyticsProviderKeyValidationsCreateResponseSuccess =
    environmentsLlmAnalyticsProviderKeyValidationsCreateResponse201 & {
        headers: Headers
    }
export type environmentsLlmAnalyticsProviderKeyValidationsCreateResponse =
    environmentsLlmAnalyticsProviderKeyValidationsCreateResponseSuccess

export const getEnvironmentsLlmAnalyticsProviderKeyValidationsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/provider_key_validations/`
}

export const environmentsLlmAnalyticsProviderKeyValidationsCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsLlmAnalyticsProviderKeyValidationsCreateResponse> => {
    return apiMutator<environmentsLlmAnalyticsProviderKeyValidationsCreateResponse>(
        getEnvironmentsLlmAnalyticsProviderKeyValidationsCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
        }
    )
}

export type environmentsLlmAnalyticsProviderKeysListResponse200 = {
    data: PaginatedLLMProviderKeyListApi
    status: 200
}

export type environmentsLlmAnalyticsProviderKeysListResponseSuccess =
    environmentsLlmAnalyticsProviderKeysListResponse200 & {
        headers: Headers
    }
export type environmentsLlmAnalyticsProviderKeysListResponse = environmentsLlmAnalyticsProviderKeysListResponseSuccess

export const getEnvironmentsLlmAnalyticsProviderKeysListUrl = (
    projectId: string,
    params?: EnvironmentsLlmAnalyticsProviderKeysListParams
) => {
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

export const environmentsLlmAnalyticsProviderKeysList = async (
    projectId: string,
    params?: EnvironmentsLlmAnalyticsProviderKeysListParams,
    options?: RequestInit
): Promise<environmentsLlmAnalyticsProviderKeysListResponse> => {
    return apiMutator<environmentsLlmAnalyticsProviderKeysListResponse>(
        getEnvironmentsLlmAnalyticsProviderKeysListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsLlmAnalyticsProviderKeysCreateResponse201 = {
    data: LLMProviderKeyApi
    status: 201
}

export type environmentsLlmAnalyticsProviderKeysCreateResponseSuccess =
    environmentsLlmAnalyticsProviderKeysCreateResponse201 & {
        headers: Headers
    }
export type environmentsLlmAnalyticsProviderKeysCreateResponse =
    environmentsLlmAnalyticsProviderKeysCreateResponseSuccess

export const getEnvironmentsLlmAnalyticsProviderKeysCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/provider_keys/`
}

export const environmentsLlmAnalyticsProviderKeysCreate = async (
    projectId: string,
    lLMProviderKeyApi: NonReadonly<LLMProviderKeyApi>,
    options?: RequestInit
): Promise<environmentsLlmAnalyticsProviderKeysCreateResponse> => {
    return apiMutator<environmentsLlmAnalyticsProviderKeysCreateResponse>(
        getEnvironmentsLlmAnalyticsProviderKeysCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(lLMProviderKeyApi),
        }
    )
}

export type environmentsLlmAnalyticsProviderKeysRetrieveResponse200 = {
    data: LLMProviderKeyApi
    status: 200
}

export type environmentsLlmAnalyticsProviderKeysRetrieveResponseSuccess =
    environmentsLlmAnalyticsProviderKeysRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsLlmAnalyticsProviderKeysRetrieveResponse =
    environmentsLlmAnalyticsProviderKeysRetrieveResponseSuccess

export const getEnvironmentsLlmAnalyticsProviderKeysRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/provider_keys/${id}/`
}

export const environmentsLlmAnalyticsProviderKeysRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsLlmAnalyticsProviderKeysRetrieveResponse> => {
    return apiMutator<environmentsLlmAnalyticsProviderKeysRetrieveResponse>(
        getEnvironmentsLlmAnalyticsProviderKeysRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsLlmAnalyticsProviderKeysUpdateResponse200 = {
    data: LLMProviderKeyApi
    status: 200
}

export type environmentsLlmAnalyticsProviderKeysUpdateResponseSuccess =
    environmentsLlmAnalyticsProviderKeysUpdateResponse200 & {
        headers: Headers
    }
export type environmentsLlmAnalyticsProviderKeysUpdateResponse =
    environmentsLlmAnalyticsProviderKeysUpdateResponseSuccess

export const getEnvironmentsLlmAnalyticsProviderKeysUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/provider_keys/${id}/`
}

export const environmentsLlmAnalyticsProviderKeysUpdate = async (
    projectId: string,
    id: string,
    lLMProviderKeyApi: NonReadonly<LLMProviderKeyApi>,
    options?: RequestInit
): Promise<environmentsLlmAnalyticsProviderKeysUpdateResponse> => {
    return apiMutator<environmentsLlmAnalyticsProviderKeysUpdateResponse>(
        getEnvironmentsLlmAnalyticsProviderKeysUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(lLMProviderKeyApi),
        }
    )
}

export type environmentsLlmAnalyticsProviderKeysPartialUpdateResponse200 = {
    data: LLMProviderKeyApi
    status: 200
}

export type environmentsLlmAnalyticsProviderKeysPartialUpdateResponseSuccess =
    environmentsLlmAnalyticsProviderKeysPartialUpdateResponse200 & {
        headers: Headers
    }
export type environmentsLlmAnalyticsProviderKeysPartialUpdateResponse =
    environmentsLlmAnalyticsProviderKeysPartialUpdateResponseSuccess

export const getEnvironmentsLlmAnalyticsProviderKeysPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/provider_keys/${id}/`
}

export const environmentsLlmAnalyticsProviderKeysPartialUpdate = async (
    projectId: string,
    id: string,
    patchedLLMProviderKeyApi: NonReadonly<PatchedLLMProviderKeyApi>,
    options?: RequestInit
): Promise<environmentsLlmAnalyticsProviderKeysPartialUpdateResponse> => {
    return apiMutator<environmentsLlmAnalyticsProviderKeysPartialUpdateResponse>(
        getEnvironmentsLlmAnalyticsProviderKeysPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedLLMProviderKeyApi),
        }
    )
}

export type environmentsLlmAnalyticsProviderKeysDestroyResponse204 = {
    data: void
    status: 204
}

export type environmentsLlmAnalyticsProviderKeysDestroyResponseSuccess =
    environmentsLlmAnalyticsProviderKeysDestroyResponse204 & {
        headers: Headers
    }
export type environmentsLlmAnalyticsProviderKeysDestroyResponse =
    environmentsLlmAnalyticsProviderKeysDestroyResponseSuccess

export const getEnvironmentsLlmAnalyticsProviderKeysDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/provider_keys/${id}/`
}

export const environmentsLlmAnalyticsProviderKeysDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsLlmAnalyticsProviderKeysDestroyResponse> => {
    return apiMutator<environmentsLlmAnalyticsProviderKeysDestroyResponse>(
        getEnvironmentsLlmAnalyticsProviderKeysDestroyUrl(projectId, id),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

export type environmentsLlmAnalyticsProviderKeysValidateCreateResponse200 = {
    data: LLMProviderKeyApi
    status: 200
}

export type environmentsLlmAnalyticsProviderKeysValidateCreateResponseSuccess =
    environmentsLlmAnalyticsProviderKeysValidateCreateResponse200 & {
        headers: Headers
    }
export type environmentsLlmAnalyticsProviderKeysValidateCreateResponse =
    environmentsLlmAnalyticsProviderKeysValidateCreateResponseSuccess

export const getEnvironmentsLlmAnalyticsProviderKeysValidateCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/provider_keys/${id}/validate/`
}

export const environmentsLlmAnalyticsProviderKeysValidateCreate = async (
    projectId: string,
    id: string,
    lLMProviderKeyApi: NonReadonly<LLMProviderKeyApi>,
    options?: RequestInit
): Promise<environmentsLlmAnalyticsProviderKeysValidateCreateResponse> => {
    return apiMutator<environmentsLlmAnalyticsProviderKeysValidateCreateResponse>(
        getEnvironmentsLlmAnalyticsProviderKeysValidateCreateUrl(projectId, id),
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
export type environmentsLlmAnalyticsSummarizationCreateResponse200 = {
    data: SummarizeResponseApi
    status: 200
}

export type environmentsLlmAnalyticsSummarizationCreateResponse400 = {
    data: EnvironmentsLlmAnalyticsSummarizationCreate400
    status: 400
}

export type environmentsLlmAnalyticsSummarizationCreateResponse403 = {
    data: EnvironmentsLlmAnalyticsSummarizationCreate403
    status: 403
}

export type environmentsLlmAnalyticsSummarizationCreateResponse500 = {
    data: EnvironmentsLlmAnalyticsSummarizationCreate500
    status: 500
}

export type environmentsLlmAnalyticsSummarizationCreateResponseSuccess =
    environmentsLlmAnalyticsSummarizationCreateResponse200 & {
        headers: Headers
    }
export type environmentsLlmAnalyticsSummarizationCreateResponseError = (
    | environmentsLlmAnalyticsSummarizationCreateResponse400
    | environmentsLlmAnalyticsSummarizationCreateResponse403
    | environmentsLlmAnalyticsSummarizationCreateResponse500
) & {
    headers: Headers
}

export type environmentsLlmAnalyticsSummarizationCreateResponse =
    | environmentsLlmAnalyticsSummarizationCreateResponseSuccess
    | environmentsLlmAnalyticsSummarizationCreateResponseError

export const getEnvironmentsLlmAnalyticsSummarizationCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/summarization/`
}

export const environmentsLlmAnalyticsSummarizationCreate = async (
    projectId: string,
    summarizeRequestApi: SummarizeRequestApi,
    options?: RequestInit
): Promise<environmentsLlmAnalyticsSummarizationCreateResponse> => {
    return apiMutator<environmentsLlmAnalyticsSummarizationCreateResponse>(
        getEnvironmentsLlmAnalyticsSummarizationCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(summarizeRequestApi),
        }
    )
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
export type environmentsLlmAnalyticsSummarizationBatchCheckCreateResponse200 = {
    data: BatchCheckResponseApi
    status: 200
}

export type environmentsLlmAnalyticsSummarizationBatchCheckCreateResponse400 = {
    data: EnvironmentsLlmAnalyticsSummarizationBatchCheckCreate400
    status: 400
}

export type environmentsLlmAnalyticsSummarizationBatchCheckCreateResponse403 = {
    data: EnvironmentsLlmAnalyticsSummarizationBatchCheckCreate403
    status: 403
}

export type environmentsLlmAnalyticsSummarizationBatchCheckCreateResponseSuccess =
    environmentsLlmAnalyticsSummarizationBatchCheckCreateResponse200 & {
        headers: Headers
    }
export type environmentsLlmAnalyticsSummarizationBatchCheckCreateResponseError = (
    | environmentsLlmAnalyticsSummarizationBatchCheckCreateResponse400
    | environmentsLlmAnalyticsSummarizationBatchCheckCreateResponse403
) & {
    headers: Headers
}

export type environmentsLlmAnalyticsSummarizationBatchCheckCreateResponse =
    | environmentsLlmAnalyticsSummarizationBatchCheckCreateResponseSuccess
    | environmentsLlmAnalyticsSummarizationBatchCheckCreateResponseError

export const getEnvironmentsLlmAnalyticsSummarizationBatchCheckCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/summarization/batch_check/`
}

export const environmentsLlmAnalyticsSummarizationBatchCheckCreate = async (
    projectId: string,
    batchCheckRequestApi: BatchCheckRequestApi,
    options?: RequestInit
): Promise<environmentsLlmAnalyticsSummarizationBatchCheckCreateResponse> => {
    return apiMutator<environmentsLlmAnalyticsSummarizationBatchCheckCreateResponse>(
        getEnvironmentsLlmAnalyticsSummarizationBatchCheckCreateUrl(projectId),
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
export type environmentsLlmAnalyticsTextReprCreateResponse200 = {
    data: TextReprResponseApi
    status: 200
}

export type environmentsLlmAnalyticsTextReprCreateResponse400 = {
    data: EnvironmentsLlmAnalyticsTextReprCreate400
    status: 400
}

export type environmentsLlmAnalyticsTextReprCreateResponse500 = {
    data: EnvironmentsLlmAnalyticsTextReprCreate500
    status: 500
}

export type environmentsLlmAnalyticsTextReprCreateResponse503 = {
    data: EnvironmentsLlmAnalyticsTextReprCreate503
    status: 503
}

export type environmentsLlmAnalyticsTextReprCreateResponseSuccess =
    environmentsLlmAnalyticsTextReprCreateResponse200 & {
        headers: Headers
    }
export type environmentsLlmAnalyticsTextReprCreateResponseError = (
    | environmentsLlmAnalyticsTextReprCreateResponse400
    | environmentsLlmAnalyticsTextReprCreateResponse500
    | environmentsLlmAnalyticsTextReprCreateResponse503
) & {
    headers: Headers
}

export type environmentsLlmAnalyticsTextReprCreateResponse =
    | environmentsLlmAnalyticsTextReprCreateResponseSuccess
    | environmentsLlmAnalyticsTextReprCreateResponseError

export const getEnvironmentsLlmAnalyticsTextReprCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/text_repr/`
}

export const environmentsLlmAnalyticsTextReprCreate = async (
    projectId: string,
    textReprRequestApi: TextReprRequestApi,
    options?: RequestInit
): Promise<environmentsLlmAnalyticsTextReprCreateResponse> => {
    return apiMutator<environmentsLlmAnalyticsTextReprCreateResponse>(
        getEnvironmentsLlmAnalyticsTextReprCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(textReprRequestApi),
        }
    )
}

/**
 * Translate text to target language.
 */
export type environmentsLlmAnalyticsTranslateCreateResponse201 = {
    data: void
    status: 201
}

export type environmentsLlmAnalyticsTranslateCreateResponseSuccess =
    environmentsLlmAnalyticsTranslateCreateResponse201 & {
        headers: Headers
    }
export type environmentsLlmAnalyticsTranslateCreateResponse = environmentsLlmAnalyticsTranslateCreateResponseSuccess

export const getEnvironmentsLlmAnalyticsTranslateCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/translate/`
}

export const environmentsLlmAnalyticsTranslateCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsLlmAnalyticsTranslateCreateResponse> => {
    return apiMutator<environmentsLlmAnalyticsTranslateCreateResponse>(
        getEnvironmentsLlmAnalyticsTranslateCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
        }
    )
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

/**
 * Manage default evaluation tags for a team
 */
export type environmentsDefaultEvaluationTagsRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsDefaultEvaluationTagsRetrieveResponseSuccess =
    environmentsDefaultEvaluationTagsRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsDefaultEvaluationTagsRetrieveResponse = environmentsDefaultEvaluationTagsRetrieveResponseSuccess

export const getEnvironmentsDefaultEvaluationTagsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/environments/${id}/default_evaluation_tags/`
}

export const environmentsDefaultEvaluationTagsRetrieve = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<environmentsDefaultEvaluationTagsRetrieveResponse> => {
    return apiMutator<environmentsDefaultEvaluationTagsRetrieveResponse>(
        getEnvironmentsDefaultEvaluationTagsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Manage default evaluation tags for a team
 */
export type environmentsDefaultEvaluationTagsCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsDefaultEvaluationTagsCreateResponseSuccess =
    environmentsDefaultEvaluationTagsCreateResponse200 & {
        headers: Headers
    }
export type environmentsDefaultEvaluationTagsCreateResponse = environmentsDefaultEvaluationTagsCreateResponseSuccess

export const getEnvironmentsDefaultEvaluationTagsCreateUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/environments/${id}/default_evaluation_tags/`
}

export const environmentsDefaultEvaluationTagsCreate = async (
    projectId: string,
    id: number,
    teamApi: NonReadonly<TeamApi>,
    options?: RequestInit
): Promise<environmentsDefaultEvaluationTagsCreateResponse> => {
    return apiMutator<environmentsDefaultEvaluationTagsCreateResponse>(
        getEnvironmentsDefaultEvaluationTagsCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(teamApi),
        }
    )
}

/**
 * Manage default evaluation tags for a team
 */
export type environmentsDefaultEvaluationTagsDestroyResponse204 = {
    data: void
    status: 204
}

export type environmentsDefaultEvaluationTagsDestroyResponseSuccess =
    environmentsDefaultEvaluationTagsDestroyResponse204 & {
        headers: Headers
    }
export type environmentsDefaultEvaluationTagsDestroyResponse = environmentsDefaultEvaluationTagsDestroyResponseSuccess

export const getEnvironmentsDefaultEvaluationTagsDestroyUrl = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/environments/${id}/default_evaluation_tags/`
}

export const environmentsDefaultEvaluationTagsDestroy = async (
    projectId: string,
    id: number,
    options?: RequestInit
): Promise<environmentsDefaultEvaluationTagsDestroyResponse> => {
    return apiMutator<environmentsDefaultEvaluationTagsDestroyResponse>(
        getEnvironmentsDefaultEvaluationTagsDestroyUrl(projectId, id),
        {
            ...options,
            method: 'DELETE',
        }
    )
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export type featureFlagsEvaluationReasonsRetrieveResponse200 = {
    data: void
    status: 200
}

export type featureFlagsEvaluationReasonsRetrieveResponseSuccess = featureFlagsEvaluationReasonsRetrieveResponse200 & {
    headers: Headers
}
export type featureFlagsEvaluationReasonsRetrieveResponse = featureFlagsEvaluationReasonsRetrieveResponseSuccess

export const getFeatureFlagsEvaluationReasonsRetrieveUrl = (
    projectId: string,
    params: FeatureFlagsEvaluationReasonsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/feature_flags/evaluation_reasons/?${stringifiedParams}`
        : `/api/projects/${projectId}/feature_flags/evaluation_reasons/`
}

export const featureFlagsEvaluationReasonsRetrieve = async (
    projectId: string,
    params: FeatureFlagsEvaluationReasonsRetrieveParams,
    options?: RequestInit
): Promise<featureFlagsEvaluationReasonsRetrieveResponse> => {
    return apiMutator<featureFlagsEvaluationReasonsRetrieveResponse>(
        getFeatureFlagsEvaluationReasonsRetrieveUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
 */
export type featureFlagsLocalEvaluationRetrieveResponse200 = {
    data: LocalEvaluationResponseApi
    status: 200
}

export type featureFlagsLocalEvaluationRetrieveResponse402 = {
    data: FeatureFlagsLocalEvaluationRetrieve402
    status: 402
}

export type featureFlagsLocalEvaluationRetrieveResponse500 = {
    data: FeatureFlagsLocalEvaluationRetrieve500
    status: 500
}

export type featureFlagsLocalEvaluationRetrieveResponseSuccess = featureFlagsLocalEvaluationRetrieveResponse200 & {
    headers: Headers
}
export type featureFlagsLocalEvaluationRetrieveResponseError = (
    | featureFlagsLocalEvaluationRetrieveResponse402
    | featureFlagsLocalEvaluationRetrieveResponse500
) & {
    headers: Headers
}

export type featureFlagsLocalEvaluationRetrieveResponse =
    | featureFlagsLocalEvaluationRetrieveResponseSuccess
    | featureFlagsLocalEvaluationRetrieveResponseError

export const getFeatureFlagsLocalEvaluationRetrieveUrl = (
    projectId: string,
    params?: FeatureFlagsLocalEvaluationRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/feature_flags/local_evaluation/?${stringifiedParams}`
        : `/api/projects/${projectId}/feature_flags/local_evaluation/`
}

export const featureFlagsLocalEvaluationRetrieve = async (
    projectId: string,
    params?: FeatureFlagsLocalEvaluationRetrieveParams,
    options?: RequestInit
): Promise<featureFlagsLocalEvaluationRetrieveResponse> => {
    return apiMutator<featureFlagsLocalEvaluationRetrieveResponse>(
        getFeatureFlagsLocalEvaluationRetrieveUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}
