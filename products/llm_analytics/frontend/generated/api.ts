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
): Promise<PaginatedDatasetItemListApi> => {
    return apiMutator<PaginatedDatasetItemListApi>(getDatasetItemsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDatasetItemsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/dataset_items/`
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
    return `/api/environments/${projectId}/dataset_items/${id}/`
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
    return `/api/environments/${projectId}/dataset_items/${id}/`
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
    return `/api/environments/${projectId}/dataset_items/${id}/`
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
    return `/api/environments/${projectId}/dataset_items/${id}/`
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
        ? `/api/environments/${projectId}/datasets/?${stringifiedParams}`
        : `/api/environments/${projectId}/datasets/`
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
    return `/api/environments/${projectId}/datasets/`
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
    return `/api/environments/${projectId}/datasets/${id}/`
}

export const datasetsRetrieve = async (projectId: string, id: string, options?: RequestInit): Promise<DatasetApi> => {
    return apiMutator<DatasetApi>(getDatasetsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getDatasetsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/datasets/${id}/`
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
    return `/api/environments/${projectId}/datasets/${id}/`
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
    return `/api/environments/${projectId}/datasets/${id}/`
}

export const datasetsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<unknown> => {
    return apiMutator<unknown>(getDatasetsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

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
): Promise<PaginatedDatasetItemListApi> => {
    return apiMutator<PaginatedDatasetItemListApi>(getDatasetItemsList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDatasetItemsCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/dataset_items/`
}

export const datasetItemsCreate2 = async (
    projectId: string,
    datasetItemApi: NonReadonly<DatasetItemApi>,
    options?: RequestInit
): Promise<DatasetItemApi> => {
    return apiMutator<DatasetItemApi>(getDatasetItemsCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(datasetItemApi),
    })
}

export const getDatasetItemsRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/dataset_items/${id}/`
}

export const datasetItemsRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DatasetItemApi> => {
    return apiMutator<DatasetItemApi>(getDatasetItemsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getDatasetItemsUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/dataset_items/${id}/`
}

export const datasetItemsUpdate2 = async (
    projectId: string,
    id: string,
    datasetItemApi: NonReadonly<DatasetItemApi>,
    options?: RequestInit
): Promise<DatasetItemApi> => {
    return apiMutator<DatasetItemApi>(getDatasetItemsUpdate2Url(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(datasetItemApi),
    })
}

export const getDatasetItemsPartialUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/dataset_items/${id}/`
}

export const datasetItemsPartialUpdate2 = async (
    projectId: string,
    id: string,
    patchedDatasetItemApi: NonReadonly<PatchedDatasetItemApi>,
    options?: RequestInit
): Promise<DatasetItemApi> => {
    return apiMutator<DatasetItemApi>(getDatasetItemsPartialUpdate2Url(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDatasetItemApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const getDatasetItemsDestroy2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/dataset_items/${id}/`
}

export const datasetItemsDestroy2 = async (projectId: string, id: string, options?: RequestInit): Promise<unknown> => {
    return apiMutator<unknown>(getDatasetItemsDestroy2Url(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

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
): Promise<PaginatedDatasetListApi> => {
    return apiMutator<PaginatedDatasetListApi>(getDatasetsList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getDatasetsCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/datasets/`
}

export const datasetsCreate2 = async (
    projectId: string,
    datasetApi: NonReadonly<DatasetApi>,
    options?: RequestInit
): Promise<DatasetApi> => {
    return apiMutator<DatasetApi>(getDatasetsCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(datasetApi),
    })
}

export const getDatasetsRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/datasets/${id}/`
}

export const datasetsRetrieve2 = async (projectId: string, id: string, options?: RequestInit): Promise<DatasetApi> => {
    return apiMutator<DatasetApi>(getDatasetsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getDatasetsUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/datasets/${id}/`
}

export const datasetsUpdate2 = async (
    projectId: string,
    id: string,
    datasetApi: NonReadonly<DatasetApi>,
    options?: RequestInit
): Promise<DatasetApi> => {
    return apiMutator<DatasetApi>(getDatasetsUpdate2Url(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(datasetApi),
    })
}

export const getDatasetsPartialUpdate2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/datasets/${id}/`
}

export const datasetsPartialUpdate2 = async (
    projectId: string,
    id: string,
    patchedDatasetApi: NonReadonly<PatchedDatasetApi>,
    options?: RequestInit
): Promise<DatasetApi> => {
    return apiMutator<DatasetApi>(getDatasetsPartialUpdate2Url(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDatasetApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const getDatasetsDestroy2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/datasets/${id}/`
}

export const datasetsDestroy2 = async (projectId: string, id: string, options?: RequestInit): Promise<unknown> => {
    return apiMutator<unknown>(getDatasetsDestroy2Url(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}
