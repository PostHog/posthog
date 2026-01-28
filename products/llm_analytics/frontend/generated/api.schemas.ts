/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `engineering` - Engineering
 * `data` - Data
 * `product` - Product Management
 * `founder` - Founder
 * `leadership` - Leadership
 * `marketing` - Marketing
 * `sales` - Sales / Success
 * `other` - Other
 */
export type RoleAtOrganizationEnumApi = (typeof RoleAtOrganizationEnumApi)[keyof typeof RoleAtOrganizationEnumApi]

export const RoleAtOrganizationEnumApi = {
    engineering: 'engineering',
    data: 'data',
    product: 'product',
    founder: 'founder',
    leadership: 'leadership',
    marketing: 'marketing',
    sales: 'sales',
    other: 'other',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

export type NullEnumApi = (typeof NullEnumApi)[keyof typeof NullEnumApi]

export const NullEnumApi = {} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null | null

export interface UserBasicApi {
    readonly id: number
    readonly uuid: string
    /**
     * @maxLength 200
     * @nullable
     */
    distinct_id?: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email: string
    /** @nullable */
    is_email_verified?: boolean | null
    /** @nullable */
    readonly hedgehog_config: UserBasicApiHedgehogConfig
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | NullEnumApi | null
}

export interface DatasetItemApi {
    readonly id: string
    dataset: string
    input?: unknown | null
    output?: unknown | null
    metadata?: unknown | null
    /**
     * @maxLength 255
     * @nullable
     */
    ref_trace_id?: string | null
    /** @nullable */
    ref_timestamp?: string | null
    /**
     * @maxLength 255
     * @nullable
     */
    ref_source_id?: string | null
    /** @nullable */
    deleted?: boolean | null
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
    readonly created_by: UserBasicApi
    readonly team: number
}

export interface PaginatedDatasetItemListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: DatasetItemApi[]
}

export interface PatchedDatasetItemApi {
    readonly id?: string
    dataset?: string
    input?: unknown | null
    output?: unknown | null
    metadata?: unknown | null
    /**
     * @maxLength 255
     * @nullable
     */
    ref_trace_id?: string | null
    /** @nullable */
    ref_timestamp?: string | null
    /**
     * @maxLength 255
     * @nullable
     */
    ref_source_id?: string | null
    /** @nullable */
    deleted?: boolean | null
    readonly created_at?: string
    /** @nullable */
    readonly updated_at?: string | null
    readonly created_by?: UserBasicApi
    readonly team?: number
}

export interface DatasetApi {
    readonly id: string
    /** @maxLength 400 */
    name: string
    /** @nullable */
    description?: string | null
    metadata?: unknown | null
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
    /** @nullable */
    deleted?: boolean | null
    readonly created_by: UserBasicApi
    readonly team: number
}

export interface PaginatedDatasetListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: DatasetApi[]
}

export interface PatchedDatasetApi {
    readonly id?: string
    /** @maxLength 400 */
    name?: string
    /** @nullable */
    description?: string | null
    metadata?: unknown | null
    readonly created_at?: string
    /** @nullable */
    readonly updated_at?: string | null
    /** @nullable */
    deleted?: boolean | null
    readonly created_by?: UserBasicApi
    readonly team?: number
}

/**
 * * `llm_judge` - LLM as a judge
 */
export type EvaluationTypeEnumApi = (typeof EvaluationTypeEnumApi)[keyof typeof EvaluationTypeEnumApi]

export const EvaluationTypeEnumApi = {
    llm_judge: 'llm_judge',
} as const

/**
 * * `boolean` - Boolean (Pass/Fail)
 */
export type OutputTypeEnumApi = (typeof OutputTypeEnumApi)[keyof typeof OutputTypeEnumApi]

export const OutputTypeEnumApi = {
    boolean: 'boolean',
} as const

/**
 * * `openai` - Openai
 * `anthropic` - Anthropic
 * `gemini` - Gemini
 */
export type Provider53dEnumApi = (typeof Provider53dEnumApi)[keyof typeof Provider53dEnumApi]

export const Provider53dEnumApi = {
    openai: 'openai',
    anthropic: 'anthropic',
    gemini: 'gemini',
} as const

/**
 * Nested serializer for model configuration.
 */
export interface ModelConfigurationApi {
    provider: Provider53dEnumApi
    /** @maxLength 100 */
    model: string
    /** @nullable */
    provider_key_id?: string | null
    /** @nullable */
    readonly provider_key_name: string | null
}

export interface EvaluationApi {
    readonly id: string
    /** @maxLength 400 */
    name: string
    description?: string
    enabled?: boolean
    evaluation_type: EvaluationTypeEnumApi
    evaluation_config?: unknown
    output_type: OutputTypeEnumApi
    output_config?: unknown
    conditions?: unknown
    model_configuration?: ModelConfigurationApi | null
    readonly created_at: string
    readonly updated_at: string
    readonly created_by: UserBasicApi
    deleted?: boolean
}

export interface PaginatedEvaluationListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: EvaluationApi[]
}

export type ClusteringRunRequestApiTraceFiltersItem = { [key: string]: unknown }

/**
 * * `none` - none
 * `l2` - l2
 */
export type EmbeddingNormalizationEnumApi =
    (typeof EmbeddingNormalizationEnumApi)[keyof typeof EmbeddingNormalizationEnumApi]

export const EmbeddingNormalizationEnumApi = {
    none: 'none',
    l2: 'l2',
} as const

/**
 * * `none` - none
 * `umap` - umap
 * `pca` - pca
 */
export type DimensionalityReductionMethodEnumApi =
    (typeof DimensionalityReductionMethodEnumApi)[keyof typeof DimensionalityReductionMethodEnumApi]

export const DimensionalityReductionMethodEnumApi = {
    none: 'none',
    umap: 'umap',
    pca: 'pca',
} as const

/**
 * * `hdbscan` - hdbscan
 * `kmeans` - kmeans
 */
export type ClusteringMethodEnumApi = (typeof ClusteringMethodEnumApi)[keyof typeof ClusteringMethodEnumApi]

export const ClusteringMethodEnumApi = {
    hdbscan: 'hdbscan',
    kmeans: 'kmeans',
} as const

/**
 * * `umap` - umap
 * `pca` - pca
 * `tsne` - tsne
 */
export type VisualizationMethodEnumApi = (typeof VisualizationMethodEnumApi)[keyof typeof VisualizationMethodEnumApi]

export const VisualizationMethodEnumApi = {
    umap: 'umap',
    pca: 'pca',
    tsne: 'tsne',
} as const

/**
 * Serializer for clustering workflow request parameters.
 */
export interface ClusteringRunRequestApi {
    /**
     * Number of days to look back for traces
     * @minimum 1
     * @maximum 90
     */
    lookback_days?: number
    /**
     * Maximum number of traces to sample for clustering
     * @minimum 20
     * @maximum 10000
     */
    max_samples?: number
    /** Embedding normalization method: 'none' (raw embeddings) or 'l2' (L2 normalize before clustering)

* `none` - none
* `l2` - l2 */
    embedding_normalization?: EmbeddingNormalizationEnumApi
    /** Dimensionality reduction method: 'none' (cluster on raw), 'umap', or 'pca'

* `none` - none
* `umap` - umap
* `pca` - pca */
    dimensionality_reduction_method?: DimensionalityReductionMethodEnumApi
    /**
     * Target dimensions for dimensionality reduction (ignored if method is 'none')
     * @minimum 2
     * @maximum 500
     */
    dimensionality_reduction_ndims?: number
    /** Clustering algorithm: 'hdbscan' (density-based, auto-determines k) or 'kmeans' (centroid-based)

* `hdbscan` - hdbscan
* `kmeans` - kmeans */
    clustering_method?: ClusteringMethodEnumApi
    /**
     * Minimum cluster size as fraction of total samples (e.g., 0.05 = 5%)
     * @minimum 0.01
     * @maximum 0.5
     */
    min_cluster_size_fraction?: number
    /**
     * HDBSCAN min_samples parameter (higher = more conservative clustering)
     * @minimum 1
     * @maximum 100
     */
    hdbscan_min_samples?: number
    /**
     * Minimum number of clusters to try for k-means
     * @minimum 2
     * @maximum 50
     */
    kmeans_min_k?: number
    /**
     * Maximum number of clusters to try for k-means
     * @minimum 2
     * @maximum 100
     */
    kmeans_max_k?: number
    /**
     * Optional label/tag for the clustering run (used as suffix in run_id for tracking experiments)
     * @maxLength 50
     */
    run_label?: string
    /** Method for 2D scatter plot visualization: 'umap', 'pca', or 'tsne'

* `umap` - umap
* `pca` - pca
* `tsne` - tsne */
    visualization_method?: VisualizationMethodEnumApi
    /** Property filters to scope which traces are included in clustering (PostHog standard format) */
    trace_filters?: ClusteringRunRequestApiTraceFiltersItem[]
}

/**
 * * `unknown` - Unknown
 * `ok` - Ok
 * `invalid` - Invalid
 * `error` - Error
 */
export type LLMProviderKeyStateEnumApi = (typeof LLMProviderKeyStateEnumApi)[keyof typeof LLMProviderKeyStateEnumApi]

export const LLMProviderKeyStateEnumApi = {
    unknown: 'unknown',
    ok: 'ok',
    invalid: 'invalid',
    error: 'error',
} as const

export interface LLMProviderKeyApi {
    readonly id: string
    provider: Provider53dEnumApi
    /** @maxLength 255 */
    name: string
    readonly state: LLMProviderKeyStateEnumApi
    /** @nullable */
    readonly error_message: string | null
    api_key?: string
    readonly api_key_masked: string
    set_as_active?: boolean
    readonly created_at: string
    readonly created_by: UserBasicApi
    /** @nullable */
    readonly last_used_at: string | null
}

export interface PaginatedLLMProviderKeyListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: LLMProviderKeyApi[]
}

export interface PatchedLLMProviderKeyApi {
    readonly id?: string
    provider?: Provider53dEnumApi
    /** @maxLength 255 */
    name?: string
    readonly state?: LLMProviderKeyStateEnumApi
    /** @nullable */
    readonly error_message?: string | null
    api_key?: string
    readonly api_key_masked?: string
    set_as_active?: boolean
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    /** @nullable */
    readonly last_used_at?: string | null
}

/**
 * * `trace` - trace
 * `event` - event
 */
export type SummarizeTypeEnumApi = (typeof SummarizeTypeEnumApi)[keyof typeof SummarizeTypeEnumApi]

export const SummarizeTypeEnumApi = {
    trace: 'trace',
    event: 'event',
} as const

/**
 * * `minimal` - minimal
 * `detailed` - detailed
 */
export type ModeEnumApi = (typeof ModeEnumApi)[keyof typeof ModeEnumApi]

export const ModeEnumApi = {
    minimal: 'minimal',
    detailed: 'detailed',
} as const

/**
 * * `openai` - openai
 * `gemini` - gemini
 */
export type Provider1b4EnumApi = (typeof Provider1b4EnumApi)[keyof typeof Provider1b4EnumApi]

export const Provider1b4EnumApi = {
    openai: 'openai',
    gemini: 'gemini',
} as const

export interface SummarizeRequestApi {
    /** Type of entity to summarize

* `trace` - trace
* `event` - event */
    summarize_type: SummarizeTypeEnumApi
    /** Summary detail level: 'minimal' for 3-5 points, 'detailed' for 5-10 points

* `minimal` - minimal
* `detailed` - detailed */
    mode?: ModeEnumApi
    /** Data to summarize. For traces: {trace, hierarchy}. For events: {event}. */
    data: unknown
    /** Force regenerate summary, bypassing cache */
    force_refresh?: boolean
    /** LLM provider to use (defaults to 'openai')

* `openai` - openai
* `gemini` - gemini */
    provider?: Provider1b4EnumApi | NullEnumApi | null
    /**
     * LLM model to use (defaults based on provider)
     * @nullable
     */
    model?: string | null
}

export interface SummaryBulletApi {
    text: string
    line_refs: string
}

export interface InterestingNoteApi {
    text: string
    line_refs: string
}

export interface StructuredSummaryApi {
    /** Concise title (no longer than 10 words) summarizing the trace/event */
    title: string
    /** Mermaid flowchart code showing the main flow */
    flow_diagram: string
    /** Main summary bullets */
    summary_bullets: SummaryBulletApi[]
    /** Interesting notes (0-2 for minimal, more for detailed) */
    interesting_notes: InterestingNoteApi[]
}

export interface SummarizeResponseApi {
    /** Structured AI-generated summary with flow, bullets, and optional notes */
    summary: StructuredSummaryApi
    /** Line-numbered text representation that the summary references */
    text_repr: string
    /** Metadata about the summarization */
    metadata?: unknown
}

export interface BatchCheckRequestApi {
    /**
     * List of trace IDs to check for cached summaries
     * @maxItems 100
     */
    trace_ids: string[]
    /** Summary detail level to check for

* `minimal` - minimal
* `detailed` - detailed */
    mode?: ModeEnumApi
    /** LLM provider to check for (defaults to 'openai')

* `openai` - openai
* `gemini` - gemini */
    provider?: Provider1b4EnumApi | NullEnumApi | null
    /**
     * LLM model to check for (defaults based on provider)
     * @nullable
     */
    model?: string | null
}

export interface CachedSummaryApi {
    trace_id: string
    title: string
    cached?: boolean
}

export interface BatchCheckResponseApi {
    summaries: CachedSummaryApi[]
}

/**
 * * `$ai_generation` - $ai_generation
 * `$ai_span` - $ai_span
 * `$ai_embedding` - $ai_embedding
 * `$ai_trace` - $ai_trace
 */
export type EventTypeEnumApi = (typeof EventTypeEnumApi)[keyof typeof EventTypeEnumApi]

export const EventTypeEnumApi = {
    $ai_generation: '$ai_generation',
    $ai_span: '$ai_span',
    $ai_embedding: '$ai_embedding',
    $ai_trace: '$ai_trace',
} as const

export interface TextReprOptionsApi {
    /** Maximum length of generated text (default: 2000000) */
    max_length?: number
    /** Use truncation for long content within events (default: true) */
    truncated?: boolean
    /** Characters to show at start/end when truncating (default: 1000) */
    truncate_buffer?: number
    /** Use interactive markers for frontend vs plain text for backend/LLM (default: true) */
    include_markers?: boolean
    /** Show summary vs full tree hierarchy for traces (default: false) */
    collapsed?: boolean
    /** Include metadata in response */
    include_metadata?: boolean
    /** Include hierarchy information (for traces) */
    include_hierarchy?: boolean
    /** Maximum depth for hierarchical rendering */
    max_depth?: number
    /** Number of tools before collapsing the list (default: 5) */
    tools_collapse_threshold?: number
    /** Prefix each line with line number (default: false) */
    include_line_numbers?: boolean
}

export interface TextReprRequestApi {
    /** Type of LLM event to stringify

* `$ai_generation` - $ai_generation
* `$ai_span` - $ai_span
* `$ai_embedding` - $ai_embedding
* `$ai_trace` - $ai_trace */
    event_type: EventTypeEnumApi
    /** Event data to stringify. For traces, should include 'trace' and 'hierarchy' fields. */
    data: unknown
    /** Optional configuration for text generation */
    options?: TextReprOptionsApi
}

export interface TextReprMetadataApi {
    event_type?: string
    event_id?: string
    trace_id?: string
    rendering: string
    char_count: number
    truncated: boolean
    error?: string
}

export interface TextReprResponseApi {
    /** Generated text representation of the event */
    text: string
    /** Metadata about the text representation */
    metadata: TextReprMetadataApi
}

export type DatasetItemsListParams = {
    /**
     * Filter by dataset ID
     */
    dataset?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type DatasetsListParams = {
    /**
     * Multiple values may be separated by commas.
     */
    id__in?: string[]
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
 * Ordering

* `created_at` - Created At
* `-created_at` - Created At (descending)
* `updated_at` - Updated At
* `-updated_at` - Updated At (descending)
 */
    order_by?: DatasetsListOrderByItem[]
    /**
     * Search in name, description, or metadata
     */
    search?: string
}

export type DatasetsListOrderByItem = (typeof DatasetsListOrderByItem)[keyof typeof DatasetsListOrderByItem]

export const DatasetsListOrderByItem = {
    '-created_at': '-created_at',
    '-updated_at': '-updated_at',
    created_at: 'created_at',
    updated_at: 'updated_at',
} as const

export type EvaluationsListParams = {
    /**
     * Filter by enabled status
     */
    enabled?: boolean
    /**
     * Multiple values may be separated by commas.
     */
    id__in?: string[]
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
 * Ordering

* `created_at` - Created At
* `-created_at` - Created At (descending)
* `updated_at` - Updated At
* `-updated_at` - Updated At (descending)
* `name` - Name
* `-name` - Name (descending)
 */
    order_by?: EvaluationsListOrderByItem[]
    /**
     * Search in name or description
     */
    search?: string
}

export type EvaluationsListOrderByItem = (typeof EvaluationsListOrderByItem)[keyof typeof EvaluationsListOrderByItem]

export const EvaluationsListOrderByItem = {
    '-created_at': '-created_at',
    '-name': '-name',
    '-updated_at': '-updated_at',
    created_at: 'created_at',
    name: 'name',
    updated_at: 'updated_at',
} as const

export type LlmAnalyticsProviderKeysListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type LlmAnalyticsSummarizationCreate400 = { [key: string]: unknown }

export type LlmAnalyticsSummarizationCreate403 = { [key: string]: unknown }

export type LlmAnalyticsSummarizationCreate500 = { [key: string]: unknown }

export type LlmAnalyticsSummarizationBatchCheckCreate400 = { [key: string]: unknown }

export type LlmAnalyticsSummarizationBatchCheckCreate403 = { [key: string]: unknown }

export type LlmAnalyticsTextReprCreate400 = { [key: string]: unknown }

export type LlmAnalyticsTextReprCreate500 = { [key: string]: unknown }

export type LlmAnalyticsTextReprCreate503 = { [key: string]: unknown }

export type DatasetItemsList2Params = {
    /**
     * Filter by dataset ID
     */
    dataset?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type DatasetsList2Params = {
    /**
     * Multiple values may be separated by commas.
     */
    id__in?: string[]
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
 * Ordering

* `created_at` - Created At
* `-created_at` - Created At (descending)
* `updated_at` - Updated At
* `-updated_at` - Updated At (descending)
 */
    order_by?: DatasetsList2OrderByItem[]
    /**
     * Search in name, description, or metadata
     */
    search?: string
}

export type DatasetsList2OrderByItem = (typeof DatasetsList2OrderByItem)[keyof typeof DatasetsList2OrderByItem]

export const DatasetsList2OrderByItem = {
    '-created_at': '-created_at',
    '-updated_at': '-updated_at',
    created_at: 'created_at',
    updated_at: 'updated_at',
} as const
