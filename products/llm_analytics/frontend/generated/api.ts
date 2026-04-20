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
    BatchCheckRequestApi,
    BatchCheckResponseApi,
    ClusteringJobApi,
    ClusteringRunRequestApi,
    DatasetApi,
    DatasetItemApi,
    DatasetItemsListParams,
    DatasetsListParams,
    EvaluationApi,
    EvaluationReportApi,
    EvaluationSummaryRequestApi,
    EvaluationSummaryResponseApi,
    EvaluationsListParams,
    LLMPromptApi,
    LLMPromptDuplicateApi,
    LLMPromptPublicApi,
    LLMPromptResolveResponseApi,
    LLMProviderKeyApi,
    LLMSkillApi,
    LLMSkillDuplicateApi,
    LLMSkillFileApi,
    LLMSkillResolveResponseApi,
    LlmAnalyticsClusteringJobsListParams,
    LlmAnalyticsEvaluationReportsListParams,
    LlmAnalyticsEvaluationReportsRunsListParams,
    LlmAnalyticsProviderKeysListParams,
    LlmAnalyticsReviewQueueItemsListParams,
    LlmAnalyticsReviewQueuesListParams,
    LlmAnalyticsScoreDefinitionsListParams,
    LlmAnalyticsTraceReviewsListParams,
    LlmPromptsListParams,
    LlmPromptsNameRetrieveParams,
    LlmPromptsResolveNameRetrieveParams,
    LlmSkillsListParams,
    LlmSkillsNameRetrieveParams,
    LlmSkillsResolveNameRetrieveParams,
    PaginatedClusteringJobListApi,
    PaginatedDatasetItemListApi,
    PaginatedDatasetListApi,
    PaginatedEvaluationListApi,
    PaginatedEvaluationReportListApi,
    PaginatedEvaluationReportRunListApi,
    PaginatedLLMPromptListListApi,
    PaginatedLLMProviderKeyListApi,
    PaginatedLLMSkillListListApi,
    PaginatedReviewQueueItemListApi,
    PaginatedReviewQueueListApi,
    PaginatedScoreDefinitionListApi,
    PaginatedTraceReviewListApi,
    PatchedClusteringJobApi,
    PatchedDatasetApi,
    PatchedDatasetItemApi,
    PatchedEvaluationReportApi,
    PatchedLLMPromptPublishApi,
    PatchedLLMProviderKeyApi,
    PatchedLLMSkillPublishApi,
    PatchedReviewQueueItemUpdateApi,
    PatchedReviewQueueUpdateApi,
    PatchedScoreDefinitionMetadataApi,
    PatchedTraceReviewUpdateApi,
    ReviewQueueApi,
    ReviewQueueCreateApi,
    ReviewQueueItemApi,
    ReviewQueueItemCreateApi,
    ScoreDefinitionApi,
    ScoreDefinitionCreateApi,
    ScoreDefinitionNewVersionApi,
    SentimentBatchResponseApi,
    SentimentRequestApi,
    SummarizeRequestApi,
    SummarizeResponseApi,
    TextReprRequestApi,
    TextReprResponseApi,
    TraceReviewApi,
    TraceReviewCreateApi,
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

/**
 * Create a new evaluation run.

This endpoint validates the request and enqueues a Temporal workflow
to asynchronously execute the evaluation.
 */
export const getEvaluationRunsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/evaluation_runs/`
}

export const evaluationRunsCreate = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getEvaluationRunsCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

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
): Promise<PaginatedEvaluationListApi> => {
    return apiMutator<PaginatedEvaluationListApi>(getEvaluationsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getEvaluationsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/evaluations/`
}

export const evaluationsCreate = async (
    projectId: string,
    evaluationApi: NonReadonly<EvaluationApi>,
    options?: RequestInit
): Promise<EvaluationApi> => {
    return apiMutator<EvaluationApi>(getEvaluationsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(evaluationApi),
    })
}

/**
 * Test Hog evaluation code against sample events without saving.
 */
export const getEvaluationsTestHogCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/evaluations/test_hog/`
}

export const evaluationsTestHogCreate = async (
    projectId: string,
    evaluationApi: NonReadonly<EvaluationApi>,
    options?: RequestInit
): Promise<EvaluationApi> => {
    return apiMutator<EvaluationApi>(getEvaluationsTestHogCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(evaluationApi),
    })
}

/**
 * Team-level clustering configuration (event filters for automated pipelines).
 */
export const getLlmAnalyticsClusteringConfigRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/clustering_config/`
}

export const llmAnalyticsClusteringConfigRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getLlmAnalyticsClusteringConfigRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Team-level clustering configuration (event filters for automated pipelines).
 */
export const getLlmAnalyticsClusteringConfigSetEventFiltersCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/clustering_config/set_event_filters/`
}

export const llmAnalyticsClusteringConfigSetEventFiltersCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getLlmAnalyticsClusteringConfigSetEventFiltersCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

/**
 * CRUD for clustering job configurations (max 5 per team).
 */
export const getLlmAnalyticsClusteringJobsListUrl = (
    projectId: string,
    params?: LlmAnalyticsClusteringJobsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/llm_analytics/clustering_jobs/?${stringifiedParams}`
        : `/api/environments/${projectId}/llm_analytics/clustering_jobs/`
}

export const llmAnalyticsClusteringJobsList = async (
    projectId: string,
    params?: LlmAnalyticsClusteringJobsListParams,
    options?: RequestInit
): Promise<PaginatedClusteringJobListApi> => {
    return apiMutator<PaginatedClusteringJobListApi>(getLlmAnalyticsClusteringJobsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * CRUD for clustering job configurations (max 5 per team).
 */
export const getLlmAnalyticsClusteringJobsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/clustering_jobs/`
}

export const llmAnalyticsClusteringJobsCreate = async (
    projectId: string,
    clusteringJobApi: NonReadonly<ClusteringJobApi>,
    options?: RequestInit
): Promise<ClusteringJobApi> => {
    return apiMutator<ClusteringJobApi>(getLlmAnalyticsClusteringJobsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(clusteringJobApi),
    })
}

/**
 * CRUD for clustering job configurations (max 5 per team).
 */
export const getLlmAnalyticsClusteringJobsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/clustering_jobs/${id}/`
}

export const llmAnalyticsClusteringJobsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ClusteringJobApi> => {
    return apiMutator<ClusteringJobApi>(getLlmAnalyticsClusteringJobsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * CRUD for clustering job configurations (max 5 per team).
 */
export const getLlmAnalyticsClusteringJobsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/clustering_jobs/${id}/`
}

export const llmAnalyticsClusteringJobsUpdate = async (
    projectId: string,
    id: string,
    clusteringJobApi: NonReadonly<ClusteringJobApi>,
    options?: RequestInit
): Promise<ClusteringJobApi> => {
    return apiMutator<ClusteringJobApi>(getLlmAnalyticsClusteringJobsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(clusteringJobApi),
    })
}

/**
 * CRUD for clustering job configurations (max 5 per team).
 */
export const getLlmAnalyticsClusteringJobsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/clustering_jobs/${id}/`
}

export const llmAnalyticsClusteringJobsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedClusteringJobApi: NonReadonly<PatchedClusteringJobApi>,
    options?: RequestInit
): Promise<ClusteringJobApi> => {
    return apiMutator<ClusteringJobApi>(getLlmAnalyticsClusteringJobsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedClusteringJobApi),
    })
}

/**
 * CRUD for clustering job configurations (max 5 per team).
 */
export const getLlmAnalyticsClusteringJobsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/clustering_jobs/${id}/`
}

export const llmAnalyticsClusteringJobsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getLlmAnalyticsClusteringJobsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Trigger a new clustering workflow run.

This endpoint validates the request parameters and starts a Temporal workflow
to perform trace clustering with the specified configuration.
 */
export const getLlmAnalyticsClusteringRunsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/clustering_runs/`
}

export const llmAnalyticsClusteringRunsCreate = async (
    projectId: string,
    clusteringRunRequestApi: ClusteringRunRequestApi,
    options?: RequestInit
): Promise<ClusteringRunRequestApi> => {
    return apiMutator<ClusteringRunRequestApi>(getLlmAnalyticsClusteringRunsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(clusteringRunRequestApi),
    })
}

/**
 * Get the evaluation config for this team
 */
export const getLlmAnalyticsEvaluationConfigRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/evaluation_config/`
}

export const llmAnalyticsEvaluationConfigRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getLlmAnalyticsEvaluationConfigRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Set the active provider key for evaluations
 */
export const getLlmAnalyticsEvaluationConfigSetActiveKeyCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/evaluation_config/set_active_key/`
}

export const llmAnalyticsEvaluationConfigSetActiveKeyCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getLlmAnalyticsEvaluationConfigSetActiveKeyCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

/**
 * CRUD for evaluation report configurations + report run history.
 */
export const getLlmAnalyticsEvaluationReportsListUrl = (
    projectId: string,
    params?: LlmAnalyticsEvaluationReportsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/llm_analytics/evaluation_reports/?${stringifiedParams}`
        : `/api/environments/${projectId}/llm_analytics/evaluation_reports/`
}

export const llmAnalyticsEvaluationReportsList = async (
    projectId: string,
    params?: LlmAnalyticsEvaluationReportsListParams,
    options?: RequestInit
): Promise<PaginatedEvaluationReportListApi> => {
    return apiMutator<PaginatedEvaluationReportListApi>(getLlmAnalyticsEvaluationReportsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * CRUD for evaluation report configurations + report run history.
 */
export const getLlmAnalyticsEvaluationReportsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/evaluation_reports/`
}

export const llmAnalyticsEvaluationReportsCreate = async (
    projectId: string,
    evaluationReportApi: NonReadonly<EvaluationReportApi>,
    options?: RequestInit
): Promise<EvaluationReportApi> => {
    return apiMutator<EvaluationReportApi>(getLlmAnalyticsEvaluationReportsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(evaluationReportApi),
    })
}

/**
 * CRUD for evaluation report configurations + report run history.
 */
export const getLlmAnalyticsEvaluationReportsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/evaluation_reports/${id}/`
}

export const llmAnalyticsEvaluationReportsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<EvaluationReportApi> => {
    return apiMutator<EvaluationReportApi>(getLlmAnalyticsEvaluationReportsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * CRUD for evaluation report configurations + report run history.
 */
export const getLlmAnalyticsEvaluationReportsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/evaluation_reports/${id}/`
}

export const llmAnalyticsEvaluationReportsUpdate = async (
    projectId: string,
    id: string,
    evaluationReportApi: NonReadonly<EvaluationReportApi>,
    options?: RequestInit
): Promise<EvaluationReportApi> => {
    return apiMutator<EvaluationReportApi>(getLlmAnalyticsEvaluationReportsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(evaluationReportApi),
    })
}

/**
 * CRUD for evaluation report configurations + report run history.
 */
export const getLlmAnalyticsEvaluationReportsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/evaluation_reports/${id}/`
}

export const llmAnalyticsEvaluationReportsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedEvaluationReportApi: NonReadonly<PatchedEvaluationReportApi>,
    options?: RequestInit
): Promise<EvaluationReportApi> => {
    return apiMutator<EvaluationReportApi>(getLlmAnalyticsEvaluationReportsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedEvaluationReportApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const getLlmAnalyticsEvaluationReportsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/evaluation_reports/${id}/`
}

export const llmAnalyticsEvaluationReportsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<unknown> => {
    return apiMutator<unknown>(getLlmAnalyticsEvaluationReportsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Trigger immediate report generation.
 */
export const getLlmAnalyticsEvaluationReportsGenerateCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/evaluation_reports/${id}/generate/`
}

export const llmAnalyticsEvaluationReportsGenerateCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getLlmAnalyticsEvaluationReportsGenerateCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

/**
 * List report runs (history) for this report.
 */
export const getLlmAnalyticsEvaluationReportsRunsListUrl = (
    projectId: string,
    id: string,
    params?: LlmAnalyticsEvaluationReportsRunsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/llm_analytics/evaluation_reports/${id}/runs/?${stringifiedParams}`
        : `/api/environments/${projectId}/llm_analytics/evaluation_reports/${id}/runs/`
}

export const llmAnalyticsEvaluationReportsRunsList = async (
    projectId: string,
    id: string,
    params?: LlmAnalyticsEvaluationReportsRunsListParams,
    options?: RequestInit
): Promise<PaginatedEvaluationReportRunListApi> => {
    return apiMutator<PaginatedEvaluationReportRunListApi>(
        getLlmAnalyticsEvaluationReportsRunsListUrl(projectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

/**
 * 
Generate an AI-powered summary of evaluation results.

This endpoint analyzes evaluation runs and identifies patterns in passing
and failing evaluations, providing actionable recommendations.

Data is fetched server-side by evaluation ID to ensure data integrity.

**Use Cases:**
- Understand why evaluations are passing or failing
- Identify systematic issues in LLM responses
- Get recommendations for improving response quality
- Review patterns across many evaluation runs at once
        
 */
export const getLlmAnalyticsEvaluationSummaryCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/evaluation_summary/`
}

export const llmAnalyticsEvaluationSummaryCreate = async (
    projectId: string,
    evaluationSummaryRequestApi: EvaluationSummaryRequestApi,
    options?: RequestInit
): Promise<EvaluationSummaryResponseApi> => {
    return apiMutator<EvaluationSummaryResponseApi>(getLlmAnalyticsEvaluationSummaryCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(evaluationSummaryRequestApi),
    })
}

/**
 * List available models for a provider.
 */
export const getLlmAnalyticsModelsRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/models/`
}

export const llmAnalyticsModelsRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getLlmAnalyticsModelsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Validate LLM provider API keys without persisting them
 */
export const getLlmAnalyticsProviderKeyValidationsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/provider_key_validations/`
}

export const llmAnalyticsProviderKeyValidationsCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getLlmAnalyticsProviderKeyValidationsCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

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
): Promise<PaginatedLLMProviderKeyListApi> => {
    return apiMutator<PaginatedLLMProviderKeyListApi>(getLlmAnalyticsProviderKeysListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getLlmAnalyticsProviderKeysCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/provider_keys/`
}

export const llmAnalyticsProviderKeysCreate = async (
    projectId: string,
    lLMProviderKeyApi: NonReadonly<LLMProviderKeyApi>,
    options?: RequestInit
): Promise<LLMProviderKeyApi> => {
    return apiMutator<LLMProviderKeyApi>(getLlmAnalyticsProviderKeysCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(lLMProviderKeyApi),
    })
}

export const getLlmAnalyticsProviderKeysRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/provider_keys/${id}/`
}

export const llmAnalyticsProviderKeysRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<LLMProviderKeyApi> => {
    return apiMutator<LLMProviderKeyApi>(getLlmAnalyticsProviderKeysRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getLlmAnalyticsProviderKeysUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/provider_keys/${id}/`
}

export const llmAnalyticsProviderKeysUpdate = async (
    projectId: string,
    id: string,
    lLMProviderKeyApi: NonReadonly<LLMProviderKeyApi>,
    options?: RequestInit
): Promise<LLMProviderKeyApi> => {
    return apiMutator<LLMProviderKeyApi>(getLlmAnalyticsProviderKeysUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(lLMProviderKeyApi),
    })
}

export const getLlmAnalyticsProviderKeysPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/provider_keys/${id}/`
}

export const llmAnalyticsProviderKeysPartialUpdate = async (
    projectId: string,
    id: string,
    patchedLLMProviderKeyApi: NonReadonly<PatchedLLMProviderKeyApi>,
    options?: RequestInit
): Promise<LLMProviderKeyApi> => {
    return apiMutator<LLMProviderKeyApi>(getLlmAnalyticsProviderKeysPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedLLMProviderKeyApi),
    })
}

export const getLlmAnalyticsProviderKeysDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/provider_keys/${id}/`
}

export const llmAnalyticsProviderKeysDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getLlmAnalyticsProviderKeysDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Assign this key to evaluations and optionally re-enable them.
 */
export const getLlmAnalyticsProviderKeysAssignCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/provider_keys/${id}/assign/`
}

export const llmAnalyticsProviderKeysAssignCreate = async (
    projectId: string,
    id: string,
    lLMProviderKeyApi: NonReadonly<LLMProviderKeyApi>,
    options?: RequestInit
): Promise<LLMProviderKeyApi> => {
    return apiMutator<LLMProviderKeyApi>(getLlmAnalyticsProviderKeysAssignCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(lLMProviderKeyApi),
    })
}

/**
 * Get evaluations using this key and alternative keys for replacement.
 */
export const getLlmAnalyticsProviderKeysDependentConfigsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/provider_keys/${id}/dependent_configs/`
}

export const llmAnalyticsProviderKeysDependentConfigsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<LLMProviderKeyApi> => {
    return apiMutator<LLMProviderKeyApi>(getLlmAnalyticsProviderKeysDependentConfigsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getLlmAnalyticsProviderKeysValidateCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/provider_keys/${id}/validate/`
}

export const llmAnalyticsProviderKeysValidateCreate = async (
    projectId: string,
    id: string,
    lLMProviderKeyApi: NonReadonly<LLMProviderKeyApi>,
    options?: RequestInit
): Promise<LLMProviderKeyApi> => {
    return apiMutator<LLMProviderKeyApi>(getLlmAnalyticsProviderKeysValidateCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(lLMProviderKeyApi),
    })
}

/**
 * List enabled evaluations currently using trial credits for a given provider.
 */
export const getLlmAnalyticsProviderKeysTrialEvaluationsRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/provider_keys/trial_evaluations/`
}

export const llmAnalyticsProviderKeysTrialEvaluationsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<LLMProviderKeyApi> => {
    return apiMutator<LLMProviderKeyApi>(getLlmAnalyticsProviderKeysTrialEvaluationsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getLlmAnalyticsReviewQueueItemsListUrl = (
    projectId: string,
    params?: LlmAnalyticsReviewQueueItemsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/llm_analytics/review_queue_items/?${stringifiedParams}`
        : `/api/environments/${projectId}/llm_analytics/review_queue_items/`
}

export const llmAnalyticsReviewQueueItemsList = async (
    projectId: string,
    params?: LlmAnalyticsReviewQueueItemsListParams,
    options?: RequestInit
): Promise<PaginatedReviewQueueItemListApi> => {
    return apiMutator<PaginatedReviewQueueItemListApi>(getLlmAnalyticsReviewQueueItemsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getLlmAnalyticsReviewQueueItemsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/review_queue_items/`
}

export const llmAnalyticsReviewQueueItemsCreate = async (
    projectId: string,
    reviewQueueItemCreateApi: ReviewQueueItemCreateApi,
    options?: RequestInit
): Promise<ReviewQueueItemApi> => {
    return apiMutator<ReviewQueueItemApi>(getLlmAnalyticsReviewQueueItemsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(reviewQueueItemCreateApi),
    })
}

export const getLlmAnalyticsReviewQueueItemsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/review_queue_items/${id}/`
}

export const llmAnalyticsReviewQueueItemsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ReviewQueueItemApi> => {
    return apiMutator<ReviewQueueItemApi>(getLlmAnalyticsReviewQueueItemsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getLlmAnalyticsReviewQueueItemsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/review_queue_items/${id}/`
}

export const llmAnalyticsReviewQueueItemsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedReviewQueueItemUpdateApi: PatchedReviewQueueItemUpdateApi,
    options?: RequestInit
): Promise<ReviewQueueItemApi> => {
    return apiMutator<ReviewQueueItemApi>(getLlmAnalyticsReviewQueueItemsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedReviewQueueItemUpdateApi),
    })
}

export const getLlmAnalyticsReviewQueueItemsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/review_queue_items/${id}/`
}

export const llmAnalyticsReviewQueueItemsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getLlmAnalyticsReviewQueueItemsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getLlmAnalyticsReviewQueuesListUrl = (projectId: string, params?: LlmAnalyticsReviewQueuesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/llm_analytics/review_queues/?${stringifiedParams}`
        : `/api/environments/${projectId}/llm_analytics/review_queues/`
}

export const llmAnalyticsReviewQueuesList = async (
    projectId: string,
    params?: LlmAnalyticsReviewQueuesListParams,
    options?: RequestInit
): Promise<PaginatedReviewQueueListApi> => {
    return apiMutator<PaginatedReviewQueueListApi>(getLlmAnalyticsReviewQueuesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getLlmAnalyticsReviewQueuesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/review_queues/`
}

export const llmAnalyticsReviewQueuesCreate = async (
    projectId: string,
    reviewQueueCreateApi: ReviewQueueCreateApi,
    options?: RequestInit
): Promise<ReviewQueueApi> => {
    return apiMutator<ReviewQueueApi>(getLlmAnalyticsReviewQueuesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(reviewQueueCreateApi),
    })
}

export const getLlmAnalyticsReviewQueuesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/review_queues/${id}/`
}

export const llmAnalyticsReviewQueuesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ReviewQueueApi> => {
    return apiMutator<ReviewQueueApi>(getLlmAnalyticsReviewQueuesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getLlmAnalyticsReviewQueuesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/review_queues/${id}/`
}

export const llmAnalyticsReviewQueuesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedReviewQueueUpdateApi: PatchedReviewQueueUpdateApi,
    options?: RequestInit
): Promise<ReviewQueueApi> => {
    return apiMutator<ReviewQueueApi>(getLlmAnalyticsReviewQueuesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedReviewQueueUpdateApi),
    })
}

export const getLlmAnalyticsReviewQueuesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/review_queues/${id}/`
}

export const llmAnalyticsReviewQueuesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getLlmAnalyticsReviewQueuesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getLlmAnalyticsScoreDefinitionsListUrl = (
    projectId: string,
    params?: LlmAnalyticsScoreDefinitionsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/llm_analytics/score_definitions/?${stringifiedParams}`
        : `/api/environments/${projectId}/llm_analytics/score_definitions/`
}

export const llmAnalyticsScoreDefinitionsList = async (
    projectId: string,
    params?: LlmAnalyticsScoreDefinitionsListParams,
    options?: RequestInit
): Promise<PaginatedScoreDefinitionListApi> => {
    return apiMutator<PaginatedScoreDefinitionListApi>(getLlmAnalyticsScoreDefinitionsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getLlmAnalyticsScoreDefinitionsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/score_definitions/`
}

export const llmAnalyticsScoreDefinitionsCreate = async (
    projectId: string,
    scoreDefinitionCreateApi: ScoreDefinitionCreateApi,
    options?: RequestInit
): Promise<ScoreDefinitionApi> => {
    return apiMutator<ScoreDefinitionApi>(getLlmAnalyticsScoreDefinitionsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(scoreDefinitionCreateApi),
    })
}

export const getLlmAnalyticsScoreDefinitionsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/score_definitions/${id}/`
}

export const llmAnalyticsScoreDefinitionsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ScoreDefinitionApi> => {
    return apiMutator<ScoreDefinitionApi>(getLlmAnalyticsScoreDefinitionsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getLlmAnalyticsScoreDefinitionsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/score_definitions/${id}/`
}

export const llmAnalyticsScoreDefinitionsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedScoreDefinitionMetadataApi: PatchedScoreDefinitionMetadataApi,
    options?: RequestInit
): Promise<ScoreDefinitionApi> => {
    return apiMutator<ScoreDefinitionApi>(getLlmAnalyticsScoreDefinitionsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedScoreDefinitionMetadataApi),
    })
}

export const getLlmAnalyticsScoreDefinitionsNewVersionCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/score_definitions/${id}/new_version/`
}

export const llmAnalyticsScoreDefinitionsNewVersionCreate = async (
    projectId: string,
    id: string,
    scoreDefinitionNewVersionApi: ScoreDefinitionNewVersionApi,
    options?: RequestInit
): Promise<ScoreDefinitionApi> => {
    return apiMutator<ScoreDefinitionApi>(getLlmAnalyticsScoreDefinitionsNewVersionCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(scoreDefinitionNewVersionApi),
    })
}

export const getLlmAnalyticsSentimentCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/sentiment/`
}

export const llmAnalyticsSentimentCreate = async (
    projectId: string,
    sentimentRequestApi: SentimentRequestApi,
    options?: RequestInit
): Promise<SentimentBatchResponseApi> => {
    return apiMutator<SentimentBatchResponseApi>(getLlmAnalyticsSentimentCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sentimentRequestApi),
    })
}

/**
 * 
Generate an AI-powered summary of an LLM trace or event.

This endpoint analyzes the provided trace/event, generates a line-numbered text
representation, and uses an LLM to create a concise summary with line references.

**Two ways to use this endpoint:**

1. **By ID (recommended):** Pass `trace_id` or `generation_id` with an optional `date_from`/`date_to`.
   The backend fetches the data automatically. `summarize_type` is inferred.
2. **By data:** Pass the full trace/event data blob in `data` with `summarize_type`.
   This is how the frontend uses it.

**Summary Format:**
- Title (concise, max 10 words)
- Mermaid flow diagram showing the main flow
- 3-10 summary bullets with line references
- "Interesting Notes" section for failures, successes, or unusual patterns
- Line references in [L45] or [L45-52] format pointing to relevant sections

The response includes the structured summary, the text representation, and metadata.
        
 */
export const getLlmAnalyticsSummarizationCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/summarization/`
}

export const llmAnalyticsSummarizationCreate = async (
    projectId: string,
    summarizeRequestApi: SummarizeRequestApi,
    options?: RequestInit
): Promise<SummarizeResponseApi> => {
    return apiMutator<SummarizeResponseApi>(getLlmAnalyticsSummarizationCreateUrl(projectId), {
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
export const getLlmAnalyticsSummarizationBatchCheckCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/summarization/batch_check/`
}

export const llmAnalyticsSummarizationBatchCheckCreate = async (
    projectId: string,
    batchCheckRequestApi: BatchCheckRequestApi,
    options?: RequestInit
): Promise<BatchCheckResponseApi> => {
    return apiMutator<BatchCheckResponseApi>(getLlmAnalyticsSummarizationBatchCheckCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(batchCheckRequestApi),
    })
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
export const getLlmAnalyticsTextReprCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/text_repr/`
}

export const llmAnalyticsTextReprCreate = async (
    projectId: string,
    textReprRequestApi: TextReprRequestApi,
    options?: RequestInit
): Promise<TextReprResponseApi> => {
    return apiMutator<TextReprResponseApi>(getLlmAnalyticsTextReprCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(textReprRequestApi),
    })
}

export const getLlmAnalyticsTraceReviewsListUrl = (projectId: string, params?: LlmAnalyticsTraceReviewsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/llm_analytics/trace_reviews/?${stringifiedParams}`
        : `/api/environments/${projectId}/llm_analytics/trace_reviews/`
}

export const llmAnalyticsTraceReviewsList = async (
    projectId: string,
    params?: LlmAnalyticsTraceReviewsListParams,
    options?: RequestInit
): Promise<PaginatedTraceReviewListApi> => {
    return apiMutator<PaginatedTraceReviewListApi>(getLlmAnalyticsTraceReviewsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getLlmAnalyticsTraceReviewsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/trace_reviews/`
}

export const llmAnalyticsTraceReviewsCreate = async (
    projectId: string,
    traceReviewCreateApi: TraceReviewCreateApi,
    options?: RequestInit
): Promise<TraceReviewApi> => {
    return apiMutator<TraceReviewApi>(getLlmAnalyticsTraceReviewsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(traceReviewCreateApi),
    })
}

export const getLlmAnalyticsTraceReviewsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/trace_reviews/${id}/`
}

export const llmAnalyticsTraceReviewsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<TraceReviewApi> => {
    return apiMutator<TraceReviewApi>(getLlmAnalyticsTraceReviewsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getLlmAnalyticsTraceReviewsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/trace_reviews/${id}/`
}

export const llmAnalyticsTraceReviewsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedTraceReviewUpdateApi: PatchedTraceReviewUpdateApi,
    options?: RequestInit
): Promise<TraceReviewApi> => {
    return apiMutator<TraceReviewApi>(getLlmAnalyticsTraceReviewsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedTraceReviewUpdateApi),
    })
}

export const getLlmAnalyticsTraceReviewsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/trace_reviews/${id}/`
}

export const llmAnalyticsTraceReviewsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getLlmAnalyticsTraceReviewsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Translate text to target language.
 */
export const getLlmAnalyticsTranslateCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/translate/`
}

export const llmAnalyticsTranslateCreate = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getLlmAnalyticsTranslateCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export const getLlmPromptsListUrl = (projectId: string, params?: LlmPromptsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/llm_prompts/?${stringifiedParams}`
        : `/api/environments/${projectId}/llm_prompts/`
}

export const llmPromptsList = async (
    projectId: string,
    params?: LlmPromptsListParams,
    options?: RequestInit
): Promise<PaginatedLLMPromptListListApi> => {
    return apiMutator<PaginatedLLMPromptListListApi>(getLlmPromptsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getLlmPromptsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_prompts/`
}

export const llmPromptsCreate = async (
    projectId: string,
    lLMPromptApi: NonReadonly<LLMPromptApi>,
    options?: RequestInit
): Promise<LLMPromptApi> => {
    return apiMutator<LLMPromptApi>(getLlmPromptsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(lLMPromptApi),
    })
}

export const getLlmPromptsNameRetrieveUrl = (
    projectId: string,
    promptName: string,
    params?: LlmPromptsNameRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/llm_prompts/name/${promptName}/?${stringifiedParams}`
        : `/api/environments/${projectId}/llm_prompts/name/${promptName}/`
}

export const llmPromptsNameRetrieve = async (
    projectId: string,
    promptName: string,
    params?: LlmPromptsNameRetrieveParams,
    options?: RequestInit
): Promise<LLMPromptPublicApi> => {
    return apiMutator<LLMPromptPublicApi>(getLlmPromptsNameRetrieveUrl(projectId, promptName, params), {
        ...options,
        method: 'GET',
    })
}

export const getLlmPromptsNamePartialUpdateUrl = (projectId: string, promptName: string) => {
    return `/api/environments/${projectId}/llm_prompts/name/${promptName}/`
}

export const llmPromptsNamePartialUpdate = async (
    projectId: string,
    promptName: string,
    patchedLLMPromptPublishApi: PatchedLLMPromptPublishApi,
    options?: RequestInit
): Promise<LLMPromptApi> => {
    return apiMutator<LLMPromptApi>(getLlmPromptsNamePartialUpdateUrl(projectId, promptName), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedLLMPromptPublishApi),
    })
}

export const getLlmPromptsNameArchiveCreateUrl = (projectId: string, promptName: string) => {
    return `/api/environments/${projectId}/llm_prompts/name/${promptName}/archive/`
}

export const llmPromptsNameArchiveCreate = async (
    projectId: string,
    promptName: string,
    lLMPromptApi: NonReadonly<LLMPromptApi>,
    options?: RequestInit
): Promise<LLMPromptApi> => {
    return apiMutator<LLMPromptApi>(getLlmPromptsNameArchiveCreateUrl(projectId, promptName), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(lLMPromptApi),
    })
}

export const getLlmPromptsNameDuplicateCreateUrl = (projectId: string, promptName: string) => {
    return `/api/environments/${projectId}/llm_prompts/name/${promptName}/duplicate/`
}

export const llmPromptsNameDuplicateCreate = async (
    projectId: string,
    promptName: string,
    lLMPromptDuplicateApi: LLMPromptDuplicateApi,
    options?: RequestInit
): Promise<LLMPromptApi> => {
    return apiMutator<LLMPromptApi>(getLlmPromptsNameDuplicateCreateUrl(projectId, promptName), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(lLMPromptDuplicateApi),
    })
}

export const getLlmPromptsResolveNameRetrieveUrl = (
    projectId: string,
    promptName: string,
    params?: LlmPromptsResolveNameRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/llm_prompts/resolve/name/${promptName}/?${stringifiedParams}`
        : `/api/environments/${projectId}/llm_prompts/resolve/name/${promptName}/`
}

export const llmPromptsResolveNameRetrieve = async (
    projectId: string,
    promptName: string,
    params?: LlmPromptsResolveNameRetrieveParams,
    options?: RequestInit
): Promise<LLMPromptResolveResponseApi> => {
    return apiMutator<LLMPromptResolveResponseApi>(getLlmPromptsResolveNameRetrieveUrl(projectId, promptName, params), {
        ...options,
        method: 'GET',
    })
}

export const getLlmSkillsListUrl = (projectId: string, params?: LlmSkillsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/llm_skills/?${stringifiedParams}`
        : `/api/environments/${projectId}/llm_skills/`
}

export const llmSkillsList = async (
    projectId: string,
    params?: LlmSkillsListParams,
    options?: RequestInit
): Promise<PaginatedLLMSkillListListApi> => {
    return apiMutator<PaginatedLLMSkillListListApi>(getLlmSkillsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getLlmSkillsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_skills/`
}

export const llmSkillsCreate = async (
    projectId: string,
    lLMSkillApi: NonReadonly<LLMSkillApi>,
    options?: RequestInit
): Promise<LLMSkillApi> => {
    return apiMutator<LLMSkillApi>(getLlmSkillsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(lLMSkillApi),
    })
}

export const getLlmSkillsNameRetrieveUrl = (
    projectId: string,
    skillName: string,
    params?: LlmSkillsNameRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/llm_skills/name/${skillName}/?${stringifiedParams}`
        : `/api/environments/${projectId}/llm_skills/name/${skillName}/`
}

export const llmSkillsNameRetrieve = async (
    projectId: string,
    skillName: string,
    params?: LlmSkillsNameRetrieveParams,
    options?: RequestInit
): Promise<LLMSkillApi> => {
    return apiMutator<LLMSkillApi>(getLlmSkillsNameRetrieveUrl(projectId, skillName, params), {
        ...options,
        method: 'GET',
    })
}

export const getLlmSkillsNamePartialUpdateUrl = (projectId: string, skillName: string) => {
    return `/api/environments/${projectId}/llm_skills/name/${skillName}/`
}

export const llmSkillsNamePartialUpdate = async (
    projectId: string,
    skillName: string,
    patchedLLMSkillPublishApi: PatchedLLMSkillPublishApi,
    options?: RequestInit
): Promise<LLMSkillApi> => {
    return apiMutator<LLMSkillApi>(getLlmSkillsNamePartialUpdateUrl(projectId, skillName), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedLLMSkillPublishApi),
    })
}

export const getLlmSkillsNameArchiveCreateUrl = (projectId: string, skillName: string) => {
    return `/api/environments/${projectId}/llm_skills/name/${skillName}/archive/`
}

export const llmSkillsNameArchiveCreate = async (
    projectId: string,
    skillName: string,
    lLMSkillApi: NonReadonly<LLMSkillApi>,
    options?: RequestInit
): Promise<LLMSkillApi> => {
    return apiMutator<LLMSkillApi>(getLlmSkillsNameArchiveCreateUrl(projectId, skillName), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(lLMSkillApi),
    })
}

export const getLlmSkillsNameDuplicateCreateUrl = (projectId: string, skillName: string) => {
    return `/api/environments/${projectId}/llm_skills/name/${skillName}/duplicate/`
}

export const llmSkillsNameDuplicateCreate = async (
    projectId: string,
    skillName: string,
    lLMSkillDuplicateApi: LLMSkillDuplicateApi,
    options?: RequestInit
): Promise<LLMSkillApi> => {
    return apiMutator<LLMSkillApi>(getLlmSkillsNameDuplicateCreateUrl(projectId, skillName), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(lLMSkillDuplicateApi),
    })
}

export const getLlmSkillsNameFilesRetrieveUrl = (projectId: string, skillName: string, filePath: string) => {
    return `/api/environments/${projectId}/llm_skills/name/${skillName}/files/${filePath}/`
}

export const llmSkillsNameFilesRetrieve = async (
    projectId: string,
    skillName: string,
    filePath: string,
    options?: RequestInit
): Promise<LLMSkillFileApi> => {
    return apiMutator<LLMSkillFileApi>(getLlmSkillsNameFilesRetrieveUrl(projectId, skillName, filePath), {
        ...options,
        method: 'GET',
    })
}

export const getLlmSkillsResolveNameRetrieveUrl = (
    projectId: string,
    skillName: string,
    params?: LlmSkillsResolveNameRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/llm_skills/resolve/name/${skillName}/?${stringifiedParams}`
        : `/api/environments/${projectId}/llm_skills/resolve/name/${skillName}/`
}

export const llmSkillsResolveNameRetrieve = async (
    projectId: string,
    skillName: string,
    params?: LlmSkillsResolveNameRetrieveParams,
    options?: RequestInit
): Promise<LLMSkillResolveResponseApi> => {
    return apiMutator<LLMSkillResolveResponseApi>(getLlmSkillsResolveNameRetrieveUrl(projectId, skillName, params), {
        ...options,
        method: 'GET',
    })
}

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
): Promise<PaginatedDatasetItemListApi> => {
    return apiMutator<PaginatedDatasetItemListApi>(getDatasetItemsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDatasetItemsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/dataset_items/`
}

export const datasetItemsCreate = async (
    projectId: string,
    datasetItemApi: NonReadonly<DatasetItemApi>,
    options?: RequestInit
): Promise<DatasetItemApi> => {
    return apiMutator<DatasetItemApi>(getDatasetItemsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(datasetItemApi),
    })
}

export const getDatasetItemsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/dataset_items/${id}/`
}

export const datasetItemsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DatasetItemApi> => {
    return apiMutator<DatasetItemApi>(getDatasetItemsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getDatasetItemsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/dataset_items/${id}/`
}

export const datasetItemsUpdate = async (
    projectId: string,
    id: string,
    datasetItemApi: NonReadonly<DatasetItemApi>,
    options?: RequestInit
): Promise<DatasetItemApi> => {
    return apiMutator<DatasetItemApi>(getDatasetItemsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(datasetItemApi),
    })
}

export const getDatasetItemsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/dataset_items/${id}/`
}

export const datasetItemsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedDatasetItemApi: NonReadonly<PatchedDatasetItemApi>,
    options?: RequestInit
): Promise<DatasetItemApi> => {
    return apiMutator<DatasetItemApi>(getDatasetItemsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDatasetItemApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const getDatasetItemsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/dataset_items/${id}/`
}

export const datasetItemsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<unknown> => {
    return apiMutator<unknown>(getDatasetItemsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

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
): Promise<PaginatedDatasetListApi> => {
    return apiMutator<PaginatedDatasetListApi>(getDatasetsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDatasetsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/datasets/`
}

export const datasetsCreate = async (
    projectId: string,
    datasetApi: NonReadonly<DatasetApi>,
    options?: RequestInit
): Promise<DatasetApi> => {
    return apiMutator<DatasetApi>(getDatasetsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(datasetApi),
    })
}

export const getDatasetsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/datasets/${id}/`
}

export const datasetsRetrieve = async (projectId: string, id: string, options?: RequestInit): Promise<DatasetApi> => {
    return apiMutator<DatasetApi>(getDatasetsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getDatasetsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/datasets/${id}/`
}

export const datasetsUpdate = async (
    projectId: string,
    id: string,
    datasetApi: NonReadonly<DatasetApi>,
    options?: RequestInit
): Promise<DatasetApi> => {
    return apiMutator<DatasetApi>(getDatasetsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(datasetApi),
    })
}

export const getDatasetsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/datasets/${id}/`
}

export const datasetsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedDatasetApi: NonReadonly<PatchedDatasetApi>,
    options?: RequestInit
): Promise<DatasetApi> => {
    return apiMutator<DatasetApi>(getDatasetsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDatasetApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const getDatasetsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/datasets/${id}/`
}

export const datasetsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<unknown> => {
    return apiMutator<unknown>(getDatasetsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}
