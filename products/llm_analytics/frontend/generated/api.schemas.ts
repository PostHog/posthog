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
 * * `llm_judge` - LLM as a judge
 * `hog` - Hog
 */
export type EvaluationTypeEnumApi = (typeof EvaluationTypeEnumApi)[keyof typeof EvaluationTypeEnumApi]

export const EvaluationTypeEnumApi = {
    LlmJudge: 'llm_judge',
    Hog: 'hog',
} as const

/**
 * * `boolean` - Boolean (Pass/Fail)
 */
export type OutputTypeEnumApi = (typeof OutputTypeEnumApi)[keyof typeof OutputTypeEnumApi]

export const OutputTypeEnumApi = {
    Boolean: 'boolean',
} as const

/**
 * * `openai` - Openai
 * `anthropic` - Anthropic
 * `gemini` - Gemini
 * `openrouter` - Openrouter
 * `fireworks` - Fireworks
 */
export type ProviderEnumApi = (typeof ProviderEnumApi)[keyof typeof ProviderEnumApi]

export const ProviderEnumApi = {
    Openai: 'openai',
    Anthropic: 'anthropic',
    Gemini: 'gemini',
    Openrouter: 'openrouter',
    Fireworks: 'fireworks',
} as const

/**
 * Nested serializer for model configuration.
 */
export interface ModelConfigurationApi {
    provider: ProviderEnumApi
    /** @maxLength 100 */
    model: string
    /** @nullable */
    provider_key_id?: string | null
    /** @nullable */
    readonly provider_key_name: string | null
}

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
    Engineering: 'engineering',
    Data: 'data',
    Product: 'product',
    Founder: 'founder',
    Leadership: 'leadership',
    Marketing: 'marketing',
    Sales: 'sales',
    Other: 'other',
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

/**
 * * `trace` - trace
 * `generation` - generation
 */
export type AnalysisLevelEnumApi = (typeof AnalysisLevelEnumApi)[keyof typeof AnalysisLevelEnumApi]

export const AnalysisLevelEnumApi = {
    Trace: 'trace',
    Generation: 'generation',
} as const

export interface ClusteringJobApi {
    readonly id: string
    /** @maxLength 100 */
    name: string
    analysis_level: AnalysisLevelEnumApi
    event_filters?: unknown
    enabled?: boolean
    readonly created_at: string
    readonly updated_at: string
}

export interface PaginatedClusteringJobListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ClusteringJobApi[]
}

export interface PatchedClusteringJobApi {
    readonly id?: string
    /** @maxLength 100 */
    name?: string
    analysis_level?: AnalysisLevelEnumApi
    event_filters?: unknown
    enabled?: boolean
    readonly created_at?: string
    readonly updated_at?: string
}

export type ClusteringRunRequestApiEventFiltersItem = { [key: string]: unknown }

/**
 * * `none` - none
 * `l2` - l2
 */
export type EmbeddingNormalizationEnumApi =
    (typeof EmbeddingNormalizationEnumApi)[keyof typeof EmbeddingNormalizationEnumApi]

export const EmbeddingNormalizationEnumApi = {
    None: 'none',
    L2: 'l2',
} as const

/**
 * * `none` - none
 * `umap` - umap
 * `pca` - pca
 */
export type DimensionalityReductionMethodEnumApi =
    (typeof DimensionalityReductionMethodEnumApi)[keyof typeof DimensionalityReductionMethodEnumApi]

export const DimensionalityReductionMethodEnumApi = {
    None: 'none',
    Umap: 'umap',
    Pca: 'pca',
} as const

/**
 * * `hdbscan` - hdbscan
 * `kmeans` - kmeans
 */
export type ClusteringMethodEnumApi = (typeof ClusteringMethodEnumApi)[keyof typeof ClusteringMethodEnumApi]

export const ClusteringMethodEnumApi = {
    Hdbscan: 'hdbscan',
    Kmeans: 'kmeans',
} as const

/**
 * * `umap` - umap
 * `pca` - pca
 * `tsne` - tsne
 */
export type VisualizationMethodEnumApi = (typeof VisualizationMethodEnumApi)[keyof typeof VisualizationMethodEnumApi]

export const VisualizationMethodEnumApi = {
    Umap: 'umap',
    Pca: 'pca',
    Tsne: 'tsne',
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
     * Minimum cluster size as fraction of total samples (e.g., 0.02 = 2%)
     * @minimum 0.02
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
    event_filters?: ClusteringRunRequestApiEventFiltersItem[]
    /**
     * If provided, use this clustering job's analysis_level and event_filters instead of request params
     * @nullable
     */
    clustering_job_id?: string | null
}

/**
 * * `all` - all
 * `pass` - pass
 * `fail` - fail
 * `na` - na
 */
export type FilterEnumApi = (typeof FilterEnumApi)[keyof typeof FilterEnumApi]

export const FilterEnumApi = {
    All: 'all',
    Pass: 'pass',
    Fail: 'fail',
    Na: 'na',
} as const

/**
 * Request serializer for evaluation summary - accepts IDs only, fetches data server-side.
 */
export interface EvaluationSummaryRequestApi {
    /** UUID of the evaluation config to summarize */
    evaluation_id: string
    /** Filter type to apply ('all', 'pass', 'fail', or 'na')

* `all` - all
* `pass` - pass
* `fail` - fail
* `na` - na */
    filter?: FilterEnumApi
    /**
     * Optional: specific generation IDs to include in summary (max 250)
     * @maxItems 250
     */
    generation_ids?: string[]
    /** If true, bypass cache and generate a fresh summary */
    force_refresh?: boolean
}

export interface EvaluationPatternApi {
    title: string
    description: string
    frequency: string
    example_generation_ids: string[]
}

export interface EvaluationSummaryStatisticsApi {
    total_analyzed: number
    pass_count: number
    fail_count: number
    na_count: number
}

export interface EvaluationSummaryResponseApi {
    overall_assessment: string
    pass_patterns: EvaluationPatternApi[]
    fail_patterns: EvaluationPatternApi[]
    na_patterns: EvaluationPatternApi[]
    recommendations: string[]
    statistics: EvaluationSummaryStatisticsApi
}

/**
 * * `unknown` - Unknown
 * `ok` - Ok
 * `invalid` - Invalid
 * `error` - Error
 */
export type LLMProviderKeyStateEnumApi = (typeof LLMProviderKeyStateEnumApi)[keyof typeof LLMProviderKeyStateEnumApi]

export const LLMProviderKeyStateEnumApi = {
    Unknown: 'unknown',
    Ok: 'ok',
    Invalid: 'invalid',
    Error: 'error',
} as const

export interface LLMProviderKeyApi {
    readonly id: string
    provider: ProviderEnumApi
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
    provider?: ProviderEnumApi
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
 * * `categorical` - categorical
 * `numeric` - numeric
 * `boolean` - boolean
 */
export type Kind01eEnumApi = (typeof Kind01eEnumApi)[keyof typeof Kind01eEnumApi]

export const Kind01eEnumApi = {
    Categorical: 'categorical',
    Numeric: 'numeric',
    Boolean: 'boolean',
} as const

export interface CategoricalScoreOptionApi {
    /**
     * Stable option key. Use lowercase letters, numbers, underscores, or hyphens.
     * @maxLength 128
     */
    key: string
    /**
     * Human-readable option label.
     * @maxLength 256
     */
    label: string
}

/**
 * * `single` - single
 * `multiple` - multiple
 */
export type SelectionModeEnumApi = (typeof SelectionModeEnumApi)[keyof typeof SelectionModeEnumApi]

export const SelectionModeEnumApi = {
    Single: 'single',
    Multiple: 'multiple',
} as const

export interface CategoricalScoreDefinitionConfigApi {
    /** Ordered categorical options available to the scorer. */
    options: CategoricalScoreOptionApi[]
    /** Whether reviewers can select one option or multiple options. Defaults to `single`.

* `single` - single
* `multiple` - multiple */
    selection_mode?: SelectionModeEnumApi
    /**
     * Optional minimum number of options that can be selected when `selection_mode` is `multiple`.
     * @minimum 1
     * @nullable
     */
    min_selections?: number | null
    /**
     * Optional maximum number of options that can be selected when `selection_mode` is `multiple`.
     * @minimum 1
     * @nullable
     */
    max_selections?: number | null
}

export interface NumericScoreDefinitionConfigApi {
    /**
     * Optional inclusive minimum score.
     * @nullable
     */
    min?: number | null
    /**
     * Optional inclusive maximum score.
     * @nullable
     */
    max?: number | null
    /**
     * Optional increment step for numeric input, for example 1 or 0.5.
     * @nullable
     */
    step?: number | null
}

export interface BooleanScoreDefinitionConfigApi {
    /** Optional label for a true value. */
    true_label?: string
    /** Optional label for a false value. */
    false_label?: string
}

export type ScoreDefinitionConfigApi =
    | CategoricalScoreDefinitionConfigApi
    | NumericScoreDefinitionConfigApi
    | BooleanScoreDefinitionConfigApi

export interface ScoreDefinitionApi {
    readonly id: string
    readonly name: string
    readonly description: string
    readonly kind: Kind01eEnumApi
    readonly archived: boolean
    /** Current immutable configuration version number. */
    readonly current_version: number
    /** Current immutable scorer configuration. */
    readonly config: ScoreDefinitionConfigApi
    /** User who created the scorer. */
    readonly created_by: UserBasicApi | null
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
    readonly team: number
}

export interface PaginatedScoreDefinitionListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ScoreDefinitionApi[]
}

export interface ScoreDefinitionCreateApi {
    /**
     * Human-readable scorer name.
     * @maxLength 255
     */
    name: string
    /**
     * Optional human-readable description.
     * @nullable
     */
    description?: string | null
    /** Scorer kind. This cannot be changed after creation.

* `categorical` - categorical
* `numeric` - numeric
* `boolean` - boolean */
    kind: Kind01eEnumApi
    /** New scorers are always created as active. */
    archived?: boolean
    /** Initial immutable scorer configuration. */
    config: ScoreDefinitionConfigApi
}

export interface PatchedScoreDefinitionMetadataApi {
    /**
     * Updated scorer name.
     * @maxLength 255
     */
    name?: string
    /**
     * Updated scorer description.
     * @nullable
     */
    description?: string | null
    /** Whether the scorer is archived. */
    archived?: boolean
}

export interface ScoreDefinitionNewVersionApi {
    /** Next immutable scorer configuration. */
    config: ScoreDefinitionConfigApi
}

export interface SentimentRequestApi {
    /**
     * @minItems 1
     * @maxItems 5
     */
    ids: string[]
    analysis_level?: AnalysisLevelEnumApi
    force_refresh?: boolean
    /** @nullable */
    date_from?: string | null
    /** @nullable */
    date_to?: string | null
}

export type MessageSentimentApiScores = { [key: string]: number }

export interface MessageSentimentApi {
    label: string
    score: number
    scores: MessageSentimentApiScores
}

export type SentimentResultApiScores = { [key: string]: number }

export type SentimentResultApiMessages = { [key: string]: MessageSentimentApi }

export interface SentimentResultApi {
    label: string
    score: number
    scores: SentimentResultApiScores
    messages: SentimentResultApiMessages
    message_count: number
}

export type SentimentBatchResponseApiResults = { [key: string]: SentimentResultApi }

export interface SentimentBatchResponseApi {
    results: SentimentBatchResponseApiResults
}

/**
 * * `trace` - trace
 * `event` - event
 */
export type SummarizeTypeEnumApi = (typeof SummarizeTypeEnumApi)[keyof typeof SummarizeTypeEnumApi]

export const SummarizeTypeEnumApi = {
    Trace: 'trace',
    Event: 'event',
} as const

/**
 * * `minimal` - minimal
 * `detailed` - detailed
 */
export type Mode02aEnumApi = (typeof Mode02aEnumApi)[keyof typeof Mode02aEnumApi]

export const Mode02aEnumApi = {
    Minimal: 'minimal',
    Detailed: 'detailed',
} as const

export interface SummarizeRequestApi {
    /** Type of entity to summarize

* `trace` - trace
* `event` - event */
    summarize_type: SummarizeTypeEnumApi
    /** Summary detail level: 'minimal' for 3-5 points, 'detailed' for 5-10 points

* `minimal` - minimal
* `detailed` - detailed */
    mode?: Mode02aEnumApi
    /** Data to summarize. For traces: {trace, hierarchy}. For events: {event}. */
    data: unknown
    /** Force regenerate summary, bypassing cache */
    force_refresh?: boolean
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
    mode?: Mode02aEnumApi
    /**
     * LLM model used for cached summaries
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
    AiGeneration: '$ai_generation',
    AiSpan: '$ai_span',
    AiEmbedding: '$ai_embedding',
    AiTrace: '$ai_trace',
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

export interface TraceReviewScoreApi {
    readonly id: string
    /** Stable scorer definition ID. */
    readonly definition_id: string
    /** Human-readable scorer name. */
    readonly definition_name: string
    /** Scorer kind for this saved score. */
    readonly definition_kind: string
    /** Whether the scorer is currently archived. */
    readonly definition_archived: boolean
    /** Immutable scorer version ID used to validate this score. */
    readonly definition_version_id: string
    /** Immutable scorer version number used to validate this score. */
    readonly definition_version: number
    /** Immutable scorer configuration snapshot used to validate this score. */
    readonly definition_config: ScoreDefinitionConfigApi
    /**
     * Categorical option keys selected for this score.
     * @nullable
     */
    readonly categorical_values: readonly string[] | null
    /**
     * @nullable
     * @pattern ^-?\d{0,6}(?:\.\d{0,6})?$
     */
    readonly numeric_value: string | null
    /** @nullable */
    readonly boolean_value: boolean | null
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
}

export interface TraceReviewApi {
    readonly id: string
    /** Trace ID for the review. */
    readonly trace_id: string
    /**
     * Optional human comment or reasoning for the review.
     * @nullable
     */
    readonly comment: string | null
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
    readonly created_by: UserBasicApi
    /** User who last saved this review. */
    readonly reviewed_by: UserBasicApi
    /** Saved scorer values for this review. */
    readonly scores: readonly TraceReviewScoreApi[]
    readonly team: number
}

export interface PaginatedTraceReviewListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: TraceReviewApi[]
}

export interface TraceReviewScoreWriteApi {
    /** Stable scorer definition ID. */
    definition_id: string
    /**
     * Optional immutable scorer version ID. Defaults to the scorer's current version.
     * @nullable
     */
    definition_version_id?: string | null
    /**
     * Categorical option keys selected for this score.
     * @minItems 1
     * @nullable
     */
    categorical_values?: string[] | null
    /**
     * Numeric value selected for this score.
     * @nullable
     * @pattern ^-?\d{0,6}(?:\.\d{0,6})?$
     */
    numeric_value?: string | null
    /**
     * Boolean value selected for this score.
     * @nullable
     */
    boolean_value?: boolean | null
}

export interface TraceReviewCreateApi {
    /**
     * Trace ID for the review. Only one active review can exist per trace and team.
     * @maxLength 255
     */
    trace_id: string
    /**
     * Optional human comment or reasoning for the review.
     * @nullable
     */
    comment?: string | null
    /** Full desired score set for this review. Omit scorers you want to leave blank. */
    scores?: TraceReviewScoreWriteApi[]
}

export interface PatchedTraceReviewUpdateApi {
    /**
     * Trace ID for the review. Only one active review can exist per trace and team.
     * @maxLength 255
     */
    trace_id?: string
    /**
     * Optional human comment or reasoning for the review.
     * @nullable
     */
    comment?: string | null
    /** Full desired score set for this review. Omit scorers you want to leave blank. */
    scores?: TraceReviewScoreWriteApi[]
}

export interface LLMPromptApi {
    readonly id: string
    /**
     * Unique prompt name using letters, numbers, hyphens, and underscores only.
     * @maxLength 255
     */
    name: string
    /** Prompt payload as JSON or string data. */
    prompt: unknown
    readonly version: number
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly updated_at: string
    readonly deleted: boolean
    readonly is_latest: boolean
    readonly latest_version: number
    readonly version_count: number
    readonly first_version_created_at: string
}

export interface PaginatedLLMPromptListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: LLMPromptApi[]
}

export interface LLMPromptPublicApi {
    id: string
    name: string
    prompt: unknown
    version: number
    created_at: string
    updated_at: string
    deleted: boolean
    is_latest: boolean
    latest_version: number
    version_count: number
    first_version_created_at: string
}

export interface PatchedLLMPromptPublishApi {
    /** Prompt payload to publish as a new version. */
    prompt?: unknown
    /**
     * Latest version you are editing from. Used for optimistic concurrency checks.
     * @minimum 1
     */
    base_version?: number
}

export interface LLMPromptVersionSummaryApi {
    readonly id: string
    readonly version: number
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly is_latest: boolean
}

export interface LLMPromptResolveResponseApi {
    prompt: LLMPromptApi
    versions: LLMPromptVersionSummaryApi[]
    has_more: boolean
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
    order_by?: string[]
    /**
     * Search in name or description
     */
    search?: string
}

export type LlmAnalyticsClusteringJobsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type LlmAnalyticsEvaluationSummaryCreate400 = { [key: string]: unknown }

export type LlmAnalyticsEvaluationSummaryCreate403 = { [key: string]: unknown }

export type LlmAnalyticsEvaluationSummaryCreate404 = { [key: string]: unknown }

export type LlmAnalyticsEvaluationSummaryCreate500 = { [key: string]: unknown }

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

export type LlmAnalyticsScoreDefinitionsListParams = {
    /**
     * Filter by archived state.
     */
    archived?: boolean
    /**
     * Filter by scorer kind.
     */
    kind?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Sort by name, kind, created_at, updated_at, or current_version.
     */
    order_by?: string
    /**
     * Search scorers by name or description.
     */
    search?: string
}

export type LlmAnalyticsSentimentCreate400 = { [key: string]: unknown }

export type LlmAnalyticsSentimentCreate500 = { [key: string]: unknown }

export type LlmAnalyticsSummarizationCreate400 = { [key: string]: unknown }

export type LlmAnalyticsSummarizationCreate403 = { [key: string]: unknown }

export type LlmAnalyticsSummarizationCreate500 = { [key: string]: unknown }

export type LlmAnalyticsSummarizationBatchCheckCreate400 = { [key: string]: unknown }

export type LlmAnalyticsSummarizationBatchCheckCreate403 = { [key: string]: unknown }

export type LlmAnalyticsTextReprCreate400 = { [key: string]: unknown }

export type LlmAnalyticsTextReprCreate500 = { [key: string]: unknown }

export type LlmAnalyticsTextReprCreate503 = { [key: string]: unknown }

export type LlmAnalyticsTraceReviewsListParams = {
    /**
     * Filter by a stable scorer definition ID.
     */
    definition_id?: string
    /**
     * Filter by multiple scorer definition IDs separated by commas.
     */
    definition_id__in?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Order by `updated_at` or `created_at`.
     */
    order_by?: string
    /**
     * Search trace IDs and comments.
     */
    search?: string
    /**
     * Filter by an exact trace ID.
     */
    trace_id?: string
    /**
     * Filter by multiple trace IDs separated by commas.
     */
    trace_id__in?: string
}

export type LlmPromptsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Optional substring filter applied to prompt names and prompt content.
     */
    search?: string
}

export type LlmPromptsNameRetrieveParams = {
    /**
     * Specific prompt version to fetch. If omitted, the latest version is returned.
     * @minimum 1
     */
    version?: number
}

export type LlmPromptsResolveNameRetrieveParams = {
    /**
     * Return versions older than this version number. Mutually exclusive with offset.
     * @minimum 1
     */
    before_version?: number
    /**
     * Maximum number of versions to return per page (1-100).
     * @minimum 1
     * @maximum 100
     */
    limit?: number
    /**
     * Zero-based offset into version history for pagination. Mutually exclusive with before_version.
     * @minimum 0
     */
    offset?: number
    /**
     * Specific prompt version to fetch. If omitted, the latest version is returned.
     * @minimum 1
     */
    version?: number
    /**
     * Exact prompt version UUID to resolve. Can be used together with version for extra safety.
     */
    version_id?: string
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
    order_by?: string[]
    /**
     * Search in name, description, or metadata
     */
    search?: string
}
