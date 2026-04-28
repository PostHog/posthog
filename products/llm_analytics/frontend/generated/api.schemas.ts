/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface EvaluationRunRequestApi {
    /** UUID of the evaluation to run. */
    evaluation_id: string
    /** UUID of the $ai_generation event to evaluate. */
    target_event_id: string
    /** ISO 8601 timestamp of the target event (needed for efficient ClickHouse lookup). */
    timestamp: string
    /** Event name. Defaults to '$ai_generation'. */
    event?: string
    /**
     * Distinct ID of the event (optional, improves lookup performance).
     * @nullable
     */
    distinct_id?: string | null
}

/**
 * * `active` - Active
 * `paused` - Paused
 * `error` - Error
 */
export type EvaluationStatusEnumApi = (typeof EvaluationStatusEnumApi)[keyof typeof EvaluationStatusEnumApi]

export const EvaluationStatusEnumApi = {
    Active: 'active',
    Paused: 'paused',
    Error: 'error',
} as const

/**
 * * `trial_limit_reached` - Trial evaluation limit reached
 * `model_not_allowed` - Model not available on the trial plan
 * `provider_key_deleted` - Provider API key was deleted
 */
export type StatusReasonEnumApi = (typeof StatusReasonEnumApi)[keyof typeof StatusReasonEnumApi]

export const StatusReasonEnumApi = {
    TrialLimitReached: 'trial_limit_reached',
    ModelNotAllowed: 'model_not_allowed',
    ProviderKeyDeleted: 'provider_key_deleted',
} as const

export type NullEnumApi = (typeof NullEnumApi)[keyof typeof NullEnumApi]

export const NullEnumApi = {} as const

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
 * `azure_openai` - Azure OpenAI
 * `together_ai` - Together AI
 */
export type LLMProviderEnumApi = (typeof LLMProviderEnumApi)[keyof typeof LLMProviderEnumApi]

export const LLMProviderEnumApi = {
    Openai: 'openai',
    Anthropic: 'anthropic',
    Gemini: 'gemini',
    Openrouter: 'openrouter',
    Fireworks: 'fireworks',
    AzureOpenai: 'azure_openai',
    TogetherAi: 'together_ai',
} as const

/**
 * Nested serializer for model configuration.
 */
export interface ModelConfigurationApi {
    provider: LLMProviderEnumApi
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

/**
 * Configuration dict. For 'llm_judge': {prompt}. For 'hog': {source}.
 */
export type EvaluationApiEvaluationConfig =
    | {
          /**
           * Evaluation criteria for the LLM judge. Describe what makes a good vs bad response.
           * @minLength 1
           */
          prompt: string
      }
    | {
          /**
           * Hog source code. Must return true (pass), false (fail), or null for N/A.
           * @minLength 1
           */
          source: string
      }

/**
 * Output config. For 'boolean' output_type: {allows_na} to permit N/A results.
 */
export type EvaluationApiOutputConfig = {
    /** Whether the evaluation can return N/A for non-applicable generations. */
    allows_na?: boolean
}

export interface EvaluationApi {
    readonly id: string
    /**
     * Name of the evaluation.
     * @maxLength 400
     */
    name: string
    /** Optional description of what this evaluation checks. */
    description?: string
    /** Whether the evaluation runs automatically on new $ai_generation events. */
    enabled?: boolean
    readonly status: EvaluationStatusEnumApi
    readonly status_reason: StatusReasonEnumApi | NullEnumApi | null
    /** 'llm_judge' uses an LLM to score outputs against a prompt; 'hog' runs deterministic Hog code.

* `llm_judge` - LLM as a judge
* `hog` - Hog */
    evaluation_type: EvaluationTypeEnumApi
    /** Configuration dict. For 'llm_judge': {prompt}. For 'hog': {source}. */
    evaluation_config?: EvaluationApiEvaluationConfig
    /** Output format. Currently only 'boolean' is supported.

* `boolean` - Boolean (Pass/Fail) */
    output_type: OutputTypeEnumApi
    /** Output config. For 'boolean' output_type: {allows_na} to permit N/A results. */
    output_config?: EvaluationApiOutputConfig
    /** Optional trigger conditions to filter which events are evaluated. OR between condition sets, AND within each. */
    conditions?: unknown
    model_configuration?: ModelConfigurationApi | null
    readonly created_at: string
    readonly updated_at: string
    readonly created_by: UserBasicApi
    /** Set to true to soft-delete the evaluation. */
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
 * Configuration dict. For 'llm_judge': {prompt}. For 'hog': {source}.
 */
export type PatchedEvaluationApiEvaluationConfig =
    | {
          /**
           * Evaluation criteria for the LLM judge. Describe what makes a good vs bad response.
           * @minLength 1
           */
          prompt: string
      }
    | {
          /**
           * Hog source code. Must return true (pass), false (fail), or null for N/A.
           * @minLength 1
           */
          source: string
      }

/**
 * Output config. For 'boolean' output_type: {allows_na} to permit N/A results.
 */
export type PatchedEvaluationApiOutputConfig = {
    /** Whether the evaluation can return N/A for non-applicable generations. */
    allows_na?: boolean
}

export interface PatchedEvaluationApi {
    readonly id?: string
    /**
     * Name of the evaluation.
     * @maxLength 400
     */
    name?: string
    /** Optional description of what this evaluation checks. */
    description?: string
    /** Whether the evaluation runs automatically on new $ai_generation events. */
    enabled?: boolean
    readonly status?: EvaluationStatusEnumApi
    readonly status_reason?: StatusReasonEnumApi | NullEnumApi | null
    /** 'llm_judge' uses an LLM to score outputs against a prompt; 'hog' runs deterministic Hog code.

* `llm_judge` - LLM as a judge
* `hog` - Hog */
    evaluation_type?: EvaluationTypeEnumApi
    /** Configuration dict. For 'llm_judge': {prompt}. For 'hog': {source}. */
    evaluation_config?: PatchedEvaluationApiEvaluationConfig
    /** Output format. Currently only 'boolean' is supported.

* `boolean` - Boolean (Pass/Fail) */
    output_type?: OutputTypeEnumApi
    /** Output config. For 'boolean' output_type: {allows_na} to permit N/A results. */
    output_config?: PatchedEvaluationApiOutputConfig
    /** Optional trigger conditions to filter which events are evaluated. OR between condition sets, AND within each. */
    conditions?: unknown
    model_configuration?: ModelConfigurationApi | null
    readonly created_at?: string
    readonly updated_at?: string
    readonly created_by?: UserBasicApi
    /** Set to true to soft-delete the evaluation. */
    deleted?: boolean
}

export type TestHogRequestApiConditionsItem = { [key: string]: unknown }

export interface TestHogRequestApi {
    /**
     * Hog source code to test. Must return a boolean (true = pass, false = fail) or null for N/A.
     * @minLength 1
     */
    source: string
    /**
     * Number of recent $ai_generation events to test against (1–10, default 5).
     * @minimum 1
     * @maximum 10
     */
    sample_count?: number
    /** Whether the evaluation can return N/A for non-applicable generations. */
    allows_na?: boolean
    /** Optional trigger conditions to filter which events are sampled. */
    conditions?: TestHogRequestApiConditionsItem[]
}

export interface TestHogResultItemApi {
    /** UUID of the $ai_generation event. */
    event_uuid: string
    /**
     * Trace ID if available.
     * @nullable
     */
    trace_id?: string | null
    /** First 200 chars of the generation input. */
    input_preview: string
    /** First 200 chars of the generation output. */
    output_preview: string
    /**
     * True = pass, False = fail, null = N/A or error.
     * @nullable
     */
    result: boolean | null
    /**
     * Hog evaluation reasoning string, if any.
     * @nullable
     */
    reasoning: string | null
    /**
     * Error message if the Hog code raised an exception.
     * @nullable
     */
    error: string | null
}

export interface TestHogResponseApi {
    results: TestHogResultItemApi[]
    /** Optional message, e.g. when no recent events were found. */
    message?: string
}

/**
 * * `trace` - trace
 * `generation` - generation
 * `evaluation` - evaluation
 */
export type ClusteringJobAnalysisLevelEnumApi =
    (typeof ClusteringJobAnalysisLevelEnumApi)[keyof typeof ClusteringJobAnalysisLevelEnumApi]

export const ClusteringJobAnalysisLevelEnumApi = {
    Trace: 'trace',
    Generation: 'generation',
    Evaluation: 'evaluation',
} as const

export interface ClusteringJobApi {
    readonly id: string
    /** @maxLength 100 */
    name: string
    analysis_level: ClusteringJobAnalysisLevelEnumApi
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
    analysis_level?: ClusteringJobAnalysisLevelEnumApi
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
 * * `scheduled` - Scheduled
 * `every_n` - Every N
 */
export type EvaluationReportFrequencyEnumApi =
    (typeof EvaluationReportFrequencyEnumApi)[keyof typeof EvaluationReportFrequencyEnumApi]

export const EvaluationReportFrequencyEnumApi = {
    Scheduled: 'scheduled',
    EveryN: 'every_n',
} as const

export interface EvaluationReportApi {
    readonly id: string
    /** UUID of the evaluation this report config belongs to. */
    evaluation: string
    /** 'every_n' triggers a report after N evaluations run; 'scheduled' uses an rrule schedule.

* `scheduled` - Scheduled
* `every_n` - Every N */
    frequency?: EvaluationReportFrequencyEnumApi
    /** RFC 5545 recurrence rule string. Required when frequency is 'scheduled'. */
    rrule?: string
    /**
     * Schedule start datetime (ISO 8601). Required when frequency is 'scheduled'.
     * @nullable
     */
    starts_at?: string | null
    /**
     * IANA timezone name for scheduled delivery (e.g. 'America/New_York').
     * @maxLength 64
     */
    timezone_name?: string
    /** @nullable */
    readonly next_delivery_date: string | null
    /** List of delivery targets. Each is {type: 'email', value: '...'} or {type: 'slack', integration_id: N, channel: '...'}. */
    delivery_targets?: unknown
    /**
     * Max number of evaluation runs included in each report. Defaults to 100.
     * @minimum -2147483648
     * @maximum 2147483647
     */
    max_sample_size?: number
    /** Whether report delivery is active. */
    enabled?: boolean
    /** Set to true to soft-delete this report config. */
    deleted?: boolean
    /** @nullable */
    readonly last_delivered_at: string | null
    /** Optional custom instructions injected into the AI report prompt to focus analysis. */
    report_prompt_guidance?: string
    /**
     * Number of evaluation runs that trigger a report (every_n mode). Min 10, max 1000.
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    trigger_threshold?: number | null
    /**
     * Minimum minutes between reports in every_n mode to prevent spam. Min 60, max 1440 (24 hours).
     * @minimum -2147483648
     * @maximum 2147483647
     */
    cooldown_minutes?: number
    /**
     * Max reports generated per day. Defaults to 3.
     * @minimum -2147483648
     * @maximum 2147483647
     */
    daily_run_cap?: number
    /** @nullable */
    readonly created_by: number | null
    readonly created_at: string
}

export interface PaginatedEvaluationReportListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: EvaluationReportApi[]
}

export interface PatchedEvaluationReportApi {
    readonly id?: string
    /** UUID of the evaluation this report config belongs to. */
    evaluation?: string
    /** 'every_n' triggers a report after N evaluations run; 'scheduled' uses an rrule schedule.

* `scheduled` - Scheduled
* `every_n` - Every N */
    frequency?: EvaluationReportFrequencyEnumApi
    /** RFC 5545 recurrence rule string. Required when frequency is 'scheduled'. */
    rrule?: string
    /**
     * Schedule start datetime (ISO 8601). Required when frequency is 'scheduled'.
     * @nullable
     */
    starts_at?: string | null
    /**
     * IANA timezone name for scheduled delivery (e.g. 'America/New_York').
     * @maxLength 64
     */
    timezone_name?: string
    /** @nullable */
    readonly next_delivery_date?: string | null
    /** List of delivery targets. Each is {type: 'email', value: '...'} or {type: 'slack', integration_id: N, channel: '...'}. */
    delivery_targets?: unknown
    /**
     * Max number of evaluation runs included in each report. Defaults to 100.
     * @minimum -2147483648
     * @maximum 2147483647
     */
    max_sample_size?: number
    /** Whether report delivery is active. */
    enabled?: boolean
    /** Set to true to soft-delete this report config. */
    deleted?: boolean
    /** @nullable */
    readonly last_delivered_at?: string | null
    /** Optional custom instructions injected into the AI report prompt to focus analysis. */
    report_prompt_guidance?: string
    /**
     * Number of evaluation runs that trigger a report (every_n mode). Min 10, max 1000.
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    trigger_threshold?: number | null
    /**
     * Minimum minutes between reports in every_n mode to prevent spam. Min 60, max 1440 (24 hours).
     * @minimum -2147483648
     * @maximum 2147483647
     */
    cooldown_minutes?: number
    /**
     * Max reports generated per day. Defaults to 3.
     * @minimum -2147483648
     * @maximum 2147483647
     */
    daily_run_cap?: number
    /** @nullable */
    readonly created_by?: number | null
    readonly created_at?: string
}

/**
 * * `pending` - Pending
 * `delivered` - Delivered
 * `partial_failure` - Partial Failure
 * `failed` - Failed
 */
export type DeliveryStatusEnumApi = (typeof DeliveryStatusEnumApi)[keyof typeof DeliveryStatusEnumApi]

export const DeliveryStatusEnumApi = {
    Pending: 'pending',
    Delivered: 'delivered',
    PartialFailure: 'partial_failure',
    Failed: 'failed',
} as const

export interface EvaluationReportRunApi {
    /** UUID of this report run. */
    readonly id: string
    /** UUID of the report config that generated this run. */
    readonly report: string
    /** Generated report content (markdown or structured text). */
    readonly content: unknown
    /** Run metadata including model used, token counts, and generation stats. */
    readonly metadata: unknown
    /** Start of the evaluation window covered by this report. */
    readonly period_start: string
    /** End of the evaluation window covered by this report. */
    readonly period_end: string
    /** 'pending', 'delivered', or 'failed'.

* `pending` - Pending
* `delivered` - Delivered
* `partial_failure` - Partial Failure
* `failed` - Failed */
    readonly delivery_status: DeliveryStatusEnumApi
    /** List of delivery error messages if delivery failed. */
    readonly delivery_errors: unknown
    readonly created_at: string
}

export interface PaginatedEvaluationReportRunListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: EvaluationReportRunApi[]
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
    provider: LLMProviderEnumApi
    /** @maxLength 255 */
    name: string
    readonly state: LLMProviderKeyStateEnumApi
    /** @nullable */
    readonly error_message: string | null
    api_key?: string
    readonly api_key_masked: string
    /** Azure OpenAI endpoint URL */
    azure_endpoint?: string
    /**
     * Azure OpenAI API version
     * @maxLength 20
     */
    api_version?: string
    /**
     * Azure endpoint (read-only, for display)
     * @nullable
     */
    readonly azure_endpoint_display: string | null
    /**
     * Azure API version (read-only, for display)
     * @nullable
     */
    readonly api_version_display: string | null
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
    provider?: LLMProviderEnumApi
    /** @maxLength 255 */
    name?: string
    readonly state?: LLMProviderKeyStateEnumApi
    /** @nullable */
    readonly error_message?: string | null
    api_key?: string
    readonly api_key_masked?: string
    /** Azure OpenAI endpoint URL */
    azure_endpoint?: string
    /**
     * Azure OpenAI API version
     * @maxLength 20
     */
    api_version?: string
    /**
     * Azure endpoint (read-only, for display)
     * @nullable
     */
    readonly azure_endpoint_display?: string | null
    /**
     * Azure API version (read-only, for display)
     * @nullable
     */
    readonly api_version_display?: string | null
    set_as_active?: boolean
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    /** @nullable */
    readonly last_used_at?: string | null
}

export interface ReviewQueueItemApi {
    readonly id: string
    /** Review queue ID that currently owns this pending trace. */
    readonly queue_id: string
    /** Human-readable name of the queue that currently owns this pending trace. */
    readonly queue_name: string
    /** Trace ID currently pending human review. */
    readonly trace_id: string
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
    /** User who queued this trace. */
    readonly created_by: UserBasicApi
    readonly team: number
}

export interface PaginatedReviewQueueItemListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ReviewQueueItemApi[]
}

export interface ReviewQueueItemCreateApi {
    /** Review queue ID that should own this pending trace. */
    queue_id: string
    /**
     * Trace ID to add to the selected review queue.
     * @maxLength 255
     */
    trace_id: string
}

export interface PatchedReviewQueueItemUpdateApi {
    /** Review queue ID that should own this pending trace. */
    queue_id?: string
}

export interface ReviewQueueApi {
    readonly id: string
    /** Human-readable queue name. */
    readonly name: string
    /** Number of pending traces currently assigned to this queue. */
    readonly pending_item_count: number
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
    /** User who created this review queue. */
    readonly created_by: UserBasicApi
    readonly team: number
}

export interface PaginatedReviewQueueListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ReviewQueueApi[]
}

export interface ReviewQueueCreateApi {
    /**
     * Human-readable queue name.
     * @maxLength 255
     */
    name: string
}

export interface PatchedReviewQueueUpdateApi {
    /**
     * Human-readable queue name.
     * @maxLength 255
     */
    name?: string
}

/**
 * * `categorical` - categorical
 * `numeric` - numeric
 * `boolean` - boolean
 */
export type ExperimentMetricKindEnumApi = (typeof ExperimentMetricKindEnumApi)[keyof typeof ExperimentMetricKindEnumApi]

export const ExperimentMetricKindEnumApi = {
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
    readonly kind: ExperimentMetricKindEnumApi
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
    kind: ExperimentMetricKindEnumApi
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

/**
 * * `trace` - trace
 * `generation` - generation
 */
export type SentimentRequestAnalysisLevelEnumApi =
    (typeof SentimentRequestAnalysisLevelEnumApi)[keyof typeof SentimentRequestAnalysisLevelEnumApi]

export const SentimentRequestAnalysisLevelEnumApi = {
    Trace: 'trace',
    Generation: 'generation',
} as const

export interface SentimentRequestApi {
    /**
     * Trace IDs or generation IDs to classify, depending on analysis_level.
     * @minItems 1
     * @maxItems 5
     */
    ids: string[]
    /** Whether the IDs are 'trace' IDs or 'generation' IDs.

* `trace` - trace
* `generation` - generation */
    analysis_level?: SentimentRequestAnalysisLevelEnumApi
    /** If true, bypass cache and reclassify. */
    force_refresh?: boolean
    /**
     * Start of date range for the lookup (e.g. '-7d' or '2026-01-01'). Defaults to -30d.
     * @nullable
     */
    date_from?: string | null
    /**
     * End of date range for the lookup. Defaults to now.
     * @nullable
     */
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
export type DetailModeValueEnumApi = (typeof DetailModeValueEnumApi)[keyof typeof DetailModeValueEnumApi]

export const DetailModeValueEnumApi = {
    Minimal: 'minimal',
    Detailed: 'detailed',
} as const

export interface SummarizeRequestApi {
    /** Type of entity to summarize. Inferred automatically when using trace_id or generation_id.

* `trace` - trace
* `event` - event */
    summarize_type?: SummarizeTypeEnumApi
    /** Summary detail level: 'minimal' for 3-5 points, 'detailed' for 5-10 points

* `minimal` - minimal
* `detailed` - detailed */
    mode?: DetailModeValueEnumApi
    /** Data to summarize. For traces: {trace, hierarchy}. For events: {event}. Not required when using trace_id or generation_id. */
    data?: unknown
    /** Force regenerate summary, bypassing cache */
    force_refresh?: boolean
    /**
     * LLM model to use (defaults based on provider)
     * @nullable
     */
    model?: string | null
    /** Trace ID to summarize. The backend fetches the trace data automatically. Requires date_from for efficient lookup. */
    trace_id?: string
    /** Generation event UUID to summarize. The backend fetches the event data automatically. Requires date_from for efficient lookup. */
    generation_id?: string
    /**
     * Start of date range for ID-based lookup (e.g. '-7d' or '2026-01-01'). Defaults to -30d.
     * @nullable
     */
    date_from?: string | null
    /**
     * End of date range for ID-based lookup. Defaults to now.
     * @nullable
     */
    date_to?: string | null
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
    mode?: DetailModeValueEnumApi
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
    /**
     * Optional review queue ID for queue-context saves. When provided, the matching pending queue item is cleared after the review is saved. If omitted, any pending queue item for the same trace is cleared.
     * @nullable
     */
    queue_id?: string | null
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
    /**
     * Optional review queue ID for queue-context saves. When provided, the matching pending queue item is cleared after the review is saved. If omitted, any pending queue item for the same trace is cleared.
     * @nullable
     */
    queue_id?: string | null
}

export interface TranslateRequestApi {
    /**
     * The text to translate
     * @maxLength 10000
     */
    text: string
    /**
     * Target language code (default: 'en' for English)
     * @maxLength 10
     */
    target_language?: string
}

export interface LLMPromptOutlineEntryApi {
    /**
     * Markdown heading level (1-6).
     * @minimum 1
     * @maximum 6
     */
    level: number
    /** Heading text with markdown link syntax preserved. */
    text: string
}

export interface LLMPromptListApi {
    readonly id: string
    /** Unique prompt name using letters, numbers, hyphens, and underscores only. */
    readonly name: string
    /** Prompt payload as JSON or string data. */
    readonly prompt: unknown
    readonly version: number
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly updated_at: string
    readonly deleted: boolean
    readonly is_latest: boolean
    readonly latest_version: number
    readonly version_count: number
    readonly first_version_created_at: string
    readonly outline: readonly LLMPromptOutlineEntryApi[]
    readonly prompt_preview: string
    readonly prompt_size_bytes: number
}

export interface PaginatedLLMPromptListListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: LLMPromptListApi[]
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
    readonly outline: readonly LLMPromptOutlineEntryApi[]
}

export interface LLMPromptPublicApi {
    id: string
    name: string
    /** Full prompt content. Omitted when 'content=preview' or 'content=none'. */
    prompt?: unknown
    /** First 160 characters of the prompt. Only present when 'content=preview'. */
    prompt_preview?: string
    /** Flat list of markdown headings parsed from the prompt. Useful as a lightweight table of contents. */
    outline: LLMPromptOutlineEntryApi[]
    version: number
    created_at: string
    updated_at: string
    deleted: boolean
    is_latest: boolean
    latest_version: number
    version_count: number
    first_version_created_at: string
}

export interface LLMPromptEditOperationApi {
    /** Text to find in the current prompt. Must match exactly once. */
    old: string
    /** Replacement text. */
    new: string
}

export interface PatchedLLMPromptPublishApi {
    /** Full prompt payload to publish as a new version. Mutually exclusive with edits. */
    prompt?: unknown
    /** List of find/replace operations to apply to the current prompt version. Each edit's 'old' text must match exactly once. Edits are applied sequentially. Mutually exclusive with prompt. */
    edits?: LLMPromptEditOperationApi[]
    /**
     * Latest version you are editing from. Used for optimistic concurrency checks.
     * @minimum 1
     */
    base_version?: number
}

export interface LLMPromptDuplicateApi {
    /**
     * Name for the duplicated prompt. Must be unique and use only letters, numbers, hyphens, and underscores.
     * @maxLength 255
     */
    new_name: string
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

export interface LLMSkillOutlineEntryApi {
    /**
     * Markdown heading level (1-6).
     * @minimum 1
     * @maximum 6
     */
    level: number
    /** Heading text. */
    text: string
}

/**
 * Arbitrary key-value metadata.
 */
export type LLMSkillListApiMetadata = { [key: string]: unknown }

/**
 * List serializer that omits body and file manifest — progressive disclosure (Level 1).
 */
export interface LLMSkillListApi {
    readonly id: string
    /**
     * Unique skill name. Lowercase letters, numbers, and hyphens only. Max 64 characters.
     * @maxLength 64
     */
    name: string
    /**
     * What this skill does and when to use it. Max 4096 characters.
     * @maxLength 4096
     */
    description: string
    /**
     * License name or reference to a bundled license file.
     * @maxLength 255
     */
    license?: string
    /**
     * Environment requirements (intended product, system packages, network access, etc.).
     * @maxLength 500
     */
    compatibility?: string
    /** List of pre-approved tools the skill may use. */
    allowed_tools?: string[]
    /** Arbitrary key-value metadata. */
    metadata?: LLMSkillListApiMetadata
    /** Flat list of markdown headings parsed from the skill body. Useful as a lightweight table of contents. */
    readonly outline: readonly LLMSkillOutlineEntryApi[]
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

export interface PaginatedLLMSkillListListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: LLMSkillListApi[]
}

/**
 * Arbitrary key-value metadata.
 */
export type LLMSkillCreateApiMetadata = { [key: string]: unknown }

export interface LLMSkillFileInputApi {
    /**
     * File path relative to skill root, e.g. 'scripts/setup.sh' or 'references/guide.md'.
     * @maxLength 500
     */
    path: string
    /** Text content of the file. */
    content: string
    /**
     * MIME type of the file content.
     * @maxLength 100
     */
    content_type?: string
}

/**
 * Create serializer — accepts bundled files as write-only input on POST.
 */
export interface LLMSkillCreateApi {
    readonly id: string
    /**
     * Unique skill name. Lowercase letters, numbers, and hyphens only. Max 64 characters.
     * @maxLength 64
     */
    name: string
    /**
     * What this skill does and when to use it. Max 4096 characters.
     * @maxLength 4096
     */
    description: string
    /** The SKILL.md instruction content (markdown). */
    body: string
    /**
     * License name or reference to a bundled license file.
     * @maxLength 255
     */
    license?: string
    /**
     * Environment requirements (intended product, system packages, network access, etc.).
     * @maxLength 500
     */
    compatibility?: string
    /** List of pre-approved tools the skill may use. */
    allowed_tools?: string[]
    /** Arbitrary key-value metadata. */
    metadata?: LLMSkillCreateApiMetadata
    /** Bundled files to include with the initial version (scripts, references, assets). */
    files?: LLMSkillFileInputApi[]
    /** Flat list of markdown headings parsed from the skill body. Useful as a lightweight table of contents. */
    readonly outline: readonly LLMSkillOutlineEntryApi[]
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

/**
 * Arbitrary key-value metadata.
 */
export type LLMSkillApiMetadata = { [key: string]: unknown }

export interface LLMSkillFileManifestApi {
    /** @maxLength 500 */
    path: string
    /** @maxLength 100 */
    content_type?: string
}

export interface LLMSkillApi {
    readonly id: string
    /**
     * Unique skill name. Lowercase letters, numbers, and hyphens only. Max 64 characters.
     * @maxLength 64
     */
    name: string
    /**
     * What this skill does and when to use it. Max 4096 characters.
     * @maxLength 4096
     */
    description: string
    /** The SKILL.md instruction content (markdown). */
    body: string
    /**
     * License name or reference to a bundled license file.
     * @maxLength 255
     */
    license?: string
    /**
     * Environment requirements (intended product, system packages, network access, etc.).
     * @maxLength 500
     */
    compatibility?: string
    /** List of pre-approved tools the skill may use. */
    allowed_tools?: string[]
    /** Arbitrary key-value metadata. */
    metadata?: LLMSkillApiMetadata
    /** Bundled files manifest. Each entry is path + content_type only; fetch content via /llm_skills/name/{name}/files/{path}/. */
    readonly files: readonly LLMSkillFileManifestApi[]
    /** Flat list of markdown headings parsed from the skill body. Useful as a lightweight table of contents. */
    readonly outline: readonly LLMSkillOutlineEntryApi[]
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

/**
 * Arbitrary key-value metadata.
 */
export type PatchedLLMSkillPublishApiMetadata = { [key: string]: unknown }

export interface LLMSkillEditOperationApi {
    /** Text to find in the target content. Must match exactly once. */
    old: string
    /** Replacement text. */
    new: string
}

export interface LLMSkillFileEditApi {
    /**
     * Path of the bundled file to edit. Must match an existing file on the current skill version.
     * @maxLength 500
     */
    path: string
    /** Sequential find/replace operations to apply to this file's content. */
    edits: LLMSkillEditOperationApi[]
}

export interface PatchedLLMSkillPublishApi {
    /** Full skill body (SKILL.md instruction content) to publish as a new version. Mutually exclusive with edits. */
    body?: string
    /** List of find/replace operations to apply to the current skill body. Each edit's 'old' text must match exactly once. Edits are applied sequentially. Mutually exclusive with body. */
    edits?: LLMSkillEditOperationApi[]
    /**
     * Updated description for the new version.
     * @maxLength 4096
     */
    description?: string
    /**
     * License name or reference.
     * @maxLength 255
     */
    license?: string
    /**
     * Environment requirements.
     * @maxLength 500
     */
    compatibility?: string
    /** List of pre-approved tools the skill may use. */
    allowed_tools?: string[]
    /** Arbitrary key-value metadata. */
    metadata?: PatchedLLMSkillPublishApiMetadata
    /** Bundled files to include with this version. Replaces all files from the previous version. Mutually exclusive with file_edits. */
    files?: LLMSkillFileInputApi[]
    /** Per-file find/replace updates. Each entry targets one existing file by path and applies sequential edits to its content. Non-targeted files carry forward unchanged. Cannot add, remove, or rename files — use 'files' for that. Mutually exclusive with files. */
    file_edits?: LLMSkillFileEditApi[]
    /**
     * Latest version you are editing from. Used for optimistic concurrency checks.
     * @minimum 1
     */
    base_version?: number
}

export interface LLMSkillDuplicateApi {
    /**
     * Name for the duplicated skill. Must be unique.
     * @maxLength 64
     */
    new_name: string
}

export interface LLMSkillFileCreateApi {
    /**
     * File path relative to skill root, e.g. 'scripts/setup.sh' or 'references/guide.md'.
     * @maxLength 500
     */
    path: string
    /** Text content of the file. */
    content: string
    /**
     * MIME type of the file content.
     * @maxLength 100
     */
    content_type?: string
    /**
     * Latest version you are editing from. If provided, the request fails with 409 when another write has landed in the meantime.
     * @minimum 1
     */
    base_version?: number
}

export interface LLMSkillFileRenameApi {
    /**
     * Current file path to rename.
     * @maxLength 500
     */
    old_path: string
    /**
     * New file path. Must not already exist in the skill.
     * @maxLength 500
     */
    new_path: string
    /**
     * Latest version you are editing from. If provided, the request fails with 409 when another write has landed in the meantime.
     * @minimum 1
     */
    base_version?: number
}

export interface LLMSkillFileApi {
    /** @maxLength 500 */
    path: string
    content: string
    /** @maxLength 100 */
    content_type?: string
}

export interface LLMSkillVersionSummaryApi {
    readonly id: string
    readonly version: number
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly is_latest: boolean
}

export interface LLMSkillResolveResponseApi {
    skill: LLMSkillApi
    versions: LLMSkillVersionSummaryApi[]
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

export type EvaluationRunsCreate200 = { [key: string]: unknown }

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

export type LlmAnalyticsClusteringConfigRetrieve200 = { [key: string]: unknown }

export type LlmAnalyticsClusteringConfigSetEventFiltersCreate200 = { [key: string]: unknown }

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

export type LlmAnalyticsEvaluationConfigRetrieve200 = { [key: string]: unknown }

export type LlmAnalyticsEvaluationConfigSetActiveKeyCreate200 = { [key: string]: unknown }

export type LlmAnalyticsEvaluationReportsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type LlmAnalyticsEvaluationReportsRunsListParams = {
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

export type LlmAnalyticsModelsRetrieve200 = { [key: string]: unknown }

export type LlmAnalyticsProviderKeyValidationsCreate200 = { [key: string]: unknown }

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

export type LlmAnalyticsReviewQueueItemsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Order by `created_at` or `updated_at`.
     */
    order_by?: string
    /**
     * Filter by a specific review queue ID.
     */
    queue_id?: string
    /**
     * Search pending trace IDs.
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

export type LlmAnalyticsReviewQueuesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    name?: string
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Order by `name`, `updated_at`, or `created_at`.
     */
    order_by?: string
    /**
     * Search review queue names.
     */
    search?: string
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

export type LlmAnalyticsTranslateCreate200 = { [key: string]: unknown }

export type LlmPromptsListParams = {
    /**
 * Controls how much prompt content is included in the response. 'full' includes the full prompt, 'preview' includes a short prompt_preview, and 'none' omits prompt content entirely. The outline field is always included.

* `full` - full
* `preview` - preview
* `none` - none
 * @minLength 1
 */
    content?: LlmPromptsListContent
    /**
     * Filter prompts by the ID of the user who created them.
     */
    created_by_id?: number
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

export type LlmPromptsListContent = (typeof LlmPromptsListContent)[keyof typeof LlmPromptsListContent]

export const LlmPromptsListContent = {
    Full: 'full',
    Preview: 'preview',
    None: 'none',
} as const

export type LlmPromptsNameRetrieveParams = {
    /**
 * Controls how much prompt content is included in the response. 'full' includes the full prompt, 'preview' includes a short prompt_preview, and 'none' omits prompt content entirely. The outline field is always included.

* `full` - full
* `preview` - preview
* `none` - none
 * @minLength 1
 */
    content?: LlmPromptsNameRetrieveContent
    /**
     * Specific prompt version to fetch. If omitted, the latest version is returned.
     * @minimum 1
     */
    version?: number
}

export type LlmPromptsNameRetrieveContent =
    (typeof LlmPromptsNameRetrieveContent)[keyof typeof LlmPromptsNameRetrieveContent]

export const LlmPromptsNameRetrieveContent = {
    Full: 'full',
    Preview: 'preview',
    None: 'none',
} as const

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

export type LlmSkillsListParams = {
    /**
     * Filter skills by the ID of the user who created them.
     */
    created_by_id?: number
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Optional substring filter applied to skill names and descriptions.
     */
    search?: string
}

export type LlmSkillsNameRetrieveParams = {
    /**
     * Specific skill version to fetch. If omitted, the latest version is returned.
     * @minimum 1
     */
    version?: number
}

export type LlmSkillsNameFilesRetrieveParams = {
    /**
     * Specific skill version to fetch. If omitted, the latest version is returned.
     * @minimum 1
     */
    version?: number
}

export type LlmSkillsNameFilesDestroyParams = {
    /**
     * Latest version you are editing from. If provided, the request fails with 409 when another write has landed in the meantime.
     * @minimum 1
     */
    base_version?: number
}

export type LlmSkillsResolveNameRetrieveParams = {
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
     * Specific skill version to fetch. If omitted, the latest version is returned.
     * @minimum 1
     */
    version?: number
    /**
     * Exact skill version UUID to resolve.
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
