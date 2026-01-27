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
    EnvironmentsLlmAnalyticsProviderKeysListParams,
    LLMProviderKeyApi,
    PaginatedDatasetItemListApi,
    PaginatedDatasetListApi,
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
): Promise<PaginatedDatasetItemListApi> => {
    return apiMutator<PaginatedDatasetItemListApi>(getEnvironmentsDatasetItemsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getEnvironmentsDatasetItemsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/dataset_items/`
}

export const environmentsDatasetItemsCreate = async (
    projectId: string,
    datasetItemApi: NonReadonly<DatasetItemApi>,
    options?: RequestInit
): Promise<DatasetItemApi> => {
    return apiMutator<DatasetItemApi>(getEnvironmentsDatasetItemsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(datasetItemApi),
    })
}

export const getEnvironmentsDatasetItemsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/dataset_items/${id}/`
}

export const environmentsDatasetItemsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DatasetItemApi> => {
    return apiMutator<DatasetItemApi>(getEnvironmentsDatasetItemsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getEnvironmentsDatasetItemsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/dataset_items/${id}/`
}

export const environmentsDatasetItemsUpdate = async (
    projectId: string,
    id: string,
    datasetItemApi: NonReadonly<DatasetItemApi>,
    options?: RequestInit
): Promise<DatasetItemApi> => {
    return apiMutator<DatasetItemApi>(getEnvironmentsDatasetItemsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(datasetItemApi),
    })
}

export const getEnvironmentsDatasetItemsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/dataset_items/${id}/`
}

export const environmentsDatasetItemsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedDatasetItemApi: NonReadonly<PatchedDatasetItemApi>,
    options?: RequestInit
): Promise<DatasetItemApi> => {
    return apiMutator<DatasetItemApi>(getEnvironmentsDatasetItemsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDatasetItemApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const getEnvironmentsDatasetItemsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/dataset_items/${id}/`
}

export const environmentsDatasetItemsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<unknown> => {
    return apiMutator<unknown>(getEnvironmentsDatasetItemsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

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
): Promise<PaginatedDatasetListApi> => {
    return apiMutator<PaginatedDatasetListApi>(getEnvironmentsDatasetsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getEnvironmentsDatasetsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/datasets/`
}

export const environmentsDatasetsCreate = async (
    projectId: string,
    datasetApi: NonReadonly<DatasetApi>,
    options?: RequestInit
): Promise<DatasetApi> => {
    return apiMutator<DatasetApi>(getEnvironmentsDatasetsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(datasetApi),
    })
}

export const getEnvironmentsDatasetsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/datasets/${id}/`
}

export const environmentsDatasetsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DatasetApi> => {
    return apiMutator<DatasetApi>(getEnvironmentsDatasetsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getEnvironmentsDatasetsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/datasets/${id}/`
}

export const environmentsDatasetsUpdate = async (
    projectId: string,
    id: string,
    datasetApi: NonReadonly<DatasetApi>,
    options?: RequestInit
): Promise<DatasetApi> => {
    return apiMutator<DatasetApi>(getEnvironmentsDatasetsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(datasetApi),
    })
}

export const getEnvironmentsDatasetsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/datasets/${id}/`
}

export const environmentsDatasetsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedDatasetApi: NonReadonly<PatchedDatasetApi>,
    options?: RequestInit
): Promise<DatasetApi> => {
    return apiMutator<DatasetApi>(getEnvironmentsDatasetsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDatasetApi),
    })
}

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const getEnvironmentsDatasetsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/datasets/${id}/`
}

export const environmentsDatasetsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<unknown> => {
    return apiMutator<unknown>(getEnvironmentsDatasetsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Trigger a new clustering workflow run.

This endpoint validates the request parameters and starts a Temporal workflow
to perform trace clustering with the specified configuration.
 */
export const getEnvironmentsLlmAnalyticsClusteringRunsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/clustering_runs/`
}

export const environmentsLlmAnalyticsClusteringRunsCreate = async (
    projectId: string,
    clusteringRunRequestApi: ClusteringRunRequestApi,
    options?: RequestInit
): Promise<ClusteringRunRequestApi> => {
    return apiMutator<ClusteringRunRequestApi>(getEnvironmentsLlmAnalyticsClusteringRunsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(clusteringRunRequestApi),
    })
}

/**
 * Get the evaluation config for this team
 */
export const getEnvironmentsLlmAnalyticsEvaluationConfigRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/evaluation_config/`
}

export const environmentsLlmAnalyticsEvaluationConfigRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsLlmAnalyticsEvaluationConfigRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Set the active provider key for evaluations
 */
export const getEnvironmentsLlmAnalyticsEvaluationConfigSetActiveKeyCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/evaluation_config/set_active_key/`
}

export const environmentsLlmAnalyticsEvaluationConfigSetActiveKeyCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsLlmAnalyticsEvaluationConfigSetActiveKeyCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

/**
 * Validate LLM provider API keys without persisting them
 */
export const getEnvironmentsLlmAnalyticsProviderKeyValidationsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/provider_key_validations/`
}

export const environmentsLlmAnalyticsProviderKeyValidationsCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsLlmAnalyticsProviderKeyValidationsCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

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
): Promise<PaginatedLLMProviderKeyListApi> => {
    return apiMutator<PaginatedLLMProviderKeyListApi>(
        getEnvironmentsLlmAnalyticsProviderKeysListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getEnvironmentsLlmAnalyticsProviderKeysCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/provider_keys/`
}

export const environmentsLlmAnalyticsProviderKeysCreate = async (
    projectId: string,
    lLMProviderKeyApi: NonReadonly<LLMProviderKeyApi>,
    options?: RequestInit
): Promise<LLMProviderKeyApi> => {
    return apiMutator<LLMProviderKeyApi>(getEnvironmentsLlmAnalyticsProviderKeysCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(lLMProviderKeyApi),
    })
}

export const getEnvironmentsLlmAnalyticsProviderKeysRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/provider_keys/${id}/`
}

export const environmentsLlmAnalyticsProviderKeysRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<LLMProviderKeyApi> => {
    return apiMutator<LLMProviderKeyApi>(getEnvironmentsLlmAnalyticsProviderKeysRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getEnvironmentsLlmAnalyticsProviderKeysUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/provider_keys/${id}/`
}

export const environmentsLlmAnalyticsProviderKeysUpdate = async (
    projectId: string,
    id: string,
    lLMProviderKeyApi: NonReadonly<LLMProviderKeyApi>,
    options?: RequestInit
): Promise<LLMProviderKeyApi> => {
    return apiMutator<LLMProviderKeyApi>(getEnvironmentsLlmAnalyticsProviderKeysUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(lLMProviderKeyApi),
    })
}

export const getEnvironmentsLlmAnalyticsProviderKeysPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/provider_keys/${id}/`
}

export const environmentsLlmAnalyticsProviderKeysPartialUpdate = async (
    projectId: string,
    id: string,
    patchedLLMProviderKeyApi: NonReadonly<PatchedLLMProviderKeyApi>,
    options?: RequestInit
): Promise<LLMProviderKeyApi> => {
    return apiMutator<LLMProviderKeyApi>(getEnvironmentsLlmAnalyticsProviderKeysPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedLLMProviderKeyApi),
    })
}

export const getEnvironmentsLlmAnalyticsProviderKeysDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/provider_keys/${id}/`
}

export const environmentsLlmAnalyticsProviderKeysDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsLlmAnalyticsProviderKeysDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getEnvironmentsLlmAnalyticsProviderKeysValidateCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/llm_analytics/provider_keys/${id}/validate/`
}

export const environmentsLlmAnalyticsProviderKeysValidateCreate = async (
    projectId: string,
    id: string,
    lLMProviderKeyApi: NonReadonly<LLMProviderKeyApi>,
    options?: RequestInit
): Promise<LLMProviderKeyApi> => {
    return apiMutator<LLMProviderKeyApi>(getEnvironmentsLlmAnalyticsProviderKeysValidateCreateUrl(projectId, id), {
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
export const getEnvironmentsLlmAnalyticsSummarizationCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/summarization/`
}

export const environmentsLlmAnalyticsSummarizationCreate = async (
    projectId: string,
    summarizeRequestApi: SummarizeRequestApi,
    options?: RequestInit
): Promise<SummarizeResponseApi> => {
    return apiMutator<SummarizeResponseApi>(getEnvironmentsLlmAnalyticsSummarizationCreateUrl(projectId), {
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
export const getEnvironmentsLlmAnalyticsSummarizationBatchCheckCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/summarization/batch_check/`
}

export const environmentsLlmAnalyticsSummarizationBatchCheckCreate = async (
    projectId: string,
    batchCheckRequestApi: BatchCheckRequestApi,
    options?: RequestInit
): Promise<BatchCheckResponseApi> => {
    return apiMutator<BatchCheckResponseApi>(getEnvironmentsLlmAnalyticsSummarizationBatchCheckCreateUrl(projectId), {
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
export const getEnvironmentsLlmAnalyticsTextReprCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/text_repr/`
}

export const environmentsLlmAnalyticsTextReprCreate = async (
    projectId: string,
    textReprRequestApi: TextReprRequestApi,
    options?: RequestInit
): Promise<TextReprResponseApi> => {
    return apiMutator<TextReprResponseApi>(getEnvironmentsLlmAnalyticsTextReprCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(textReprRequestApi),
    })
}

/**
 * Translate text to target language.
 */
export const getEnvironmentsLlmAnalyticsTranslateCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/llm_analytics/translate/`
}

export const environmentsLlmAnalyticsTranslateCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEnvironmentsLlmAnalyticsTranslateCreateUrl(projectId), {
        ...options,
        method: 'POST',
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
