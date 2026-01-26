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

export interface PatchedEvaluationApi {
    readonly id?: string
    /** @maxLength 400 */
    name?: string
    description?: string
    enabled?: boolean
    evaluation_type?: EvaluationTypeEnumApi
    evaluation_config?: unknown
    output_type?: OutputTypeEnumApi
    output_config?: unknown
    conditions?: unknown
    readonly created_at?: string
    readonly updated_at?: string
    readonly created_by?: UserBasicApi
    deleted?: boolean
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
 * * `openai` - Openai
 */
export type LLMProviderKeyProviderEnumApi =
    (typeof LLMProviderKeyProviderEnumApi)[keyof typeof LLMProviderKeyProviderEnumApi]

export const LLMProviderKeyProviderEnumApi = {
    openai: 'openai',
} as const

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
    provider: LLMProviderKeyProviderEnumApi
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
    provider?: LLMProviderKeyProviderEnumApi
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

export type TeamApiDefaultModifiers = { [key: string]: unknown }

export type TeamApiGroupTypesItem = { [key: string]: unknown }

/**
 * * `Africa/Abidjan` - Africa/Abidjan
 * `Africa/Accra` - Africa/Accra
 * `Africa/Addis_Ababa` - Africa/Addis_Ababa
 * `Africa/Algiers` - Africa/Algiers
 * `Africa/Asmara` - Africa/Asmara
 * `Africa/Asmera` - Africa/Asmera
 * `Africa/Bamako` - Africa/Bamako
 * `Africa/Bangui` - Africa/Bangui
 * `Africa/Banjul` - Africa/Banjul
 * `Africa/Bissau` - Africa/Bissau
 * `Africa/Blantyre` - Africa/Blantyre
 * `Africa/Brazzaville` - Africa/Brazzaville
 * `Africa/Bujumbura` - Africa/Bujumbura
 * `Africa/Cairo` - Africa/Cairo
 * `Africa/Casablanca` - Africa/Casablanca
 * `Africa/Ceuta` - Africa/Ceuta
 * `Africa/Conakry` - Africa/Conakry
 * `Africa/Dakar` - Africa/Dakar
 * `Africa/Dar_es_Salaam` - Africa/Dar_es_Salaam
 * `Africa/Djibouti` - Africa/Djibouti
 * `Africa/Douala` - Africa/Douala
 * `Africa/El_Aaiun` - Africa/El_Aaiun
 * `Africa/Freetown` - Africa/Freetown
 * `Africa/Gaborone` - Africa/Gaborone
 * `Africa/Harare` - Africa/Harare
 * `Africa/Johannesburg` - Africa/Johannesburg
 * `Africa/Juba` - Africa/Juba
 * `Africa/Kampala` - Africa/Kampala
 * `Africa/Khartoum` - Africa/Khartoum
 * `Africa/Kigali` - Africa/Kigali
 * `Africa/Kinshasa` - Africa/Kinshasa
 * `Africa/Lagos` - Africa/Lagos
 * `Africa/Libreville` - Africa/Libreville
 * `Africa/Lome` - Africa/Lome
 * `Africa/Luanda` - Africa/Luanda
 * `Africa/Lubumbashi` - Africa/Lubumbashi
 * `Africa/Lusaka` - Africa/Lusaka
 * `Africa/Malabo` - Africa/Malabo
 * `Africa/Maputo` - Africa/Maputo
 * `Africa/Maseru` - Africa/Maseru
 * `Africa/Mbabane` - Africa/Mbabane
 * `Africa/Mogadishu` - Africa/Mogadishu
 * `Africa/Monrovia` - Africa/Monrovia
 * `Africa/Nairobi` - Africa/Nairobi
 * `Africa/Ndjamena` - Africa/Ndjamena
 * `Africa/Niamey` - Africa/Niamey
 * `Africa/Nouakchott` - Africa/Nouakchott
 * `Africa/Ouagadougou` - Africa/Ouagadougou
 * `Africa/Porto-Novo` - Africa/Porto-Novo
 * `Africa/Sao_Tome` - Africa/Sao_Tome
 * `Africa/Timbuktu` - Africa/Timbuktu
 * `Africa/Tripoli` - Africa/Tripoli
 * `Africa/Tunis` - Africa/Tunis
 * `Africa/Windhoek` - Africa/Windhoek
 * `America/Adak` - America/Adak
 * `America/Anchorage` - America/Anchorage
 * `America/Anguilla` - America/Anguilla
 * `America/Antigua` - America/Antigua
 * `America/Araguaina` - America/Araguaina
 * `America/Argentina/Buenos_Aires` - America/Argentina/Buenos_Aires
 * `America/Argentina/Catamarca` - America/Argentina/Catamarca
 * `America/Argentina/ComodRivadavia` - America/Argentina/ComodRivadavia
 * `America/Argentina/Cordoba` - America/Argentina/Cordoba
 * `America/Argentina/Jujuy` - America/Argentina/Jujuy
 * `America/Argentina/La_Rioja` - America/Argentina/La_Rioja
 * `America/Argentina/Mendoza` - America/Argentina/Mendoza
 * `America/Argentina/Rio_Gallegos` - America/Argentina/Rio_Gallegos
 * `America/Argentina/Salta` - America/Argentina/Salta
 * `America/Argentina/San_Juan` - America/Argentina/San_Juan
 * `America/Argentina/San_Luis` - America/Argentina/San_Luis
 * `America/Argentina/Tucuman` - America/Argentina/Tucuman
 * `America/Argentina/Ushuaia` - America/Argentina/Ushuaia
 * `America/Aruba` - America/Aruba
 * `America/Asuncion` - America/Asuncion
 * `America/Atikokan` - America/Atikokan
 * `America/Atka` - America/Atka
 * `America/Bahia` - America/Bahia
 * `America/Bahia_Banderas` - America/Bahia_Banderas
 * `America/Barbados` - America/Barbados
 * `America/Belem` - America/Belem
 * `America/Belize` - America/Belize
 * `America/Blanc-Sablon` - America/Blanc-Sablon
 * `America/Boa_Vista` - America/Boa_Vista
 * `America/Bogota` - America/Bogota
 * `America/Boise` - America/Boise
 * `America/Buenos_Aires` - America/Buenos_Aires
 * `America/Cambridge_Bay` - America/Cambridge_Bay
 * `America/Campo_Grande` - America/Campo_Grande
 * `America/Cancun` - America/Cancun
 * `America/Caracas` - America/Caracas
 * `America/Catamarca` - America/Catamarca
 * `America/Cayenne` - America/Cayenne
 * `America/Cayman` - America/Cayman
 * `America/Chicago` - America/Chicago
 * `America/Chihuahua` - America/Chihuahua
 * `America/Ciudad_Juarez` - America/Ciudad_Juarez
 * `America/Coral_Harbour` - America/Coral_Harbour
 * `America/Cordoba` - America/Cordoba
 * `America/Costa_Rica` - America/Costa_Rica
 * `America/Creston` - America/Creston
 * `America/Cuiaba` - America/Cuiaba
 * `America/Curacao` - America/Curacao
 * `America/Danmarkshavn` - America/Danmarkshavn
 * `America/Dawson` - America/Dawson
 * `America/Dawson_Creek` - America/Dawson_Creek
 * `America/Denver` - America/Denver
 * `America/Detroit` - America/Detroit
 * `America/Dominica` - America/Dominica
 * `America/Edmonton` - America/Edmonton
 * `America/Eirunepe` - America/Eirunepe
 * `America/El_Salvador` - America/El_Salvador
 * `America/Ensenada` - America/Ensenada
 * `America/Fort_Nelson` - America/Fort_Nelson
 * `America/Fort_Wayne` - America/Fort_Wayne
 * `America/Fortaleza` - America/Fortaleza
 * `America/Glace_Bay` - America/Glace_Bay
 * `America/Godthab` - America/Godthab
 * `America/Goose_Bay` - America/Goose_Bay
 * `America/Grand_Turk` - America/Grand_Turk
 * `America/Grenada` - America/Grenada
 * `America/Guadeloupe` - America/Guadeloupe
 * `America/Guatemala` - America/Guatemala
 * `America/Guayaquil` - America/Guayaquil
 * `America/Guyana` - America/Guyana
 * `America/Halifax` - America/Halifax
 * `America/Havana` - America/Havana
 * `America/Hermosillo` - America/Hermosillo
 * `America/Indiana/Indianapolis` - America/Indiana/Indianapolis
 * `America/Indiana/Knox` - America/Indiana/Knox
 * `America/Indiana/Marengo` - America/Indiana/Marengo
 * `America/Indiana/Petersburg` - America/Indiana/Petersburg
 * `America/Indiana/Tell_City` - America/Indiana/Tell_City
 * `America/Indiana/Vevay` - America/Indiana/Vevay
 * `America/Indiana/Vincennes` - America/Indiana/Vincennes
 * `America/Indiana/Winamac` - America/Indiana/Winamac
 * `America/Indianapolis` - America/Indianapolis
 * `America/Inuvik` - America/Inuvik
 * `America/Iqaluit` - America/Iqaluit
 * `America/Jamaica` - America/Jamaica
 * `America/Jujuy` - America/Jujuy
 * `America/Juneau` - America/Juneau
 * `America/Kentucky/Louisville` - America/Kentucky/Louisville
 * `America/Kentucky/Monticello` - America/Kentucky/Monticello
 * `America/Knox_IN` - America/Knox_IN
 * `America/Kralendijk` - America/Kralendijk
 * `America/La_Paz` - America/La_Paz
 * `America/Lima` - America/Lima
 * `America/Los_Angeles` - America/Los_Angeles
 * `America/Louisville` - America/Louisville
 * `America/Lower_Princes` - America/Lower_Princes
 * `America/Maceio` - America/Maceio
 * `America/Managua` - America/Managua
 * `America/Manaus` - America/Manaus
 * `America/Marigot` - America/Marigot
 * `America/Martinique` - America/Martinique
 * `America/Matamoros` - America/Matamoros
 * `America/Mazatlan` - America/Mazatlan
 * `America/Mendoza` - America/Mendoza
 * `America/Menominee` - America/Menominee
 * `America/Merida` - America/Merida
 * `America/Metlakatla` - America/Metlakatla
 * `America/Mexico_City` - America/Mexico_City
 * `America/Miquelon` - America/Miquelon
 * `America/Moncton` - America/Moncton
 * `America/Monterrey` - America/Monterrey
 * `America/Montevideo` - America/Montevideo
 * `America/Montreal` - America/Montreal
 * `America/Montserrat` - America/Montserrat
 * `America/Nassau` - America/Nassau
 * `America/New_York` - America/New_York
 * `America/Nipigon` - America/Nipigon
 * `America/Nome` - America/Nome
 * `America/Noronha` - America/Noronha
 * `America/North_Dakota/Beulah` - America/North_Dakota/Beulah
 * `America/North_Dakota/Center` - America/North_Dakota/Center
 * `America/North_Dakota/New_Salem` - America/North_Dakota/New_Salem
 * `America/Nuuk` - America/Nuuk
 * `America/Ojinaga` - America/Ojinaga
 * `America/Panama` - America/Panama
 * `America/Pangnirtung` - America/Pangnirtung
 * `America/Paramaribo` - America/Paramaribo
 * `America/Phoenix` - America/Phoenix
 * `America/Port-au-Prince` - America/Port-au-Prince
 * `America/Port_of_Spain` - America/Port_of_Spain
 * `America/Porto_Acre` - America/Porto_Acre
 * `America/Porto_Velho` - America/Porto_Velho
 * `America/Puerto_Rico` - America/Puerto_Rico
 * `America/Punta_Arenas` - America/Punta_Arenas
 * `America/Rainy_River` - America/Rainy_River
 * `America/Rankin_Inlet` - America/Rankin_Inlet
 * `America/Recife` - America/Recife
 * `America/Regina` - America/Regina
 * `America/Resolute` - America/Resolute
 * `America/Rio_Branco` - America/Rio_Branco
 * `America/Rosario` - America/Rosario
 * `America/Santa_Isabel` - America/Santa_Isabel
 * `America/Santarem` - America/Santarem
 * `America/Santiago` - America/Santiago
 * `America/Santo_Domingo` - America/Santo_Domingo
 * `America/Sao_Paulo` - America/Sao_Paulo
 * `America/Scoresbysund` - America/Scoresbysund
 * `America/Shiprock` - America/Shiprock
 * `America/Sitka` - America/Sitka
 * `America/St_Barthelemy` - America/St_Barthelemy
 * `America/St_Johns` - America/St_Johns
 * `America/St_Kitts` - America/St_Kitts
 * `America/St_Lucia` - America/St_Lucia
 * `America/St_Thomas` - America/St_Thomas
 * `America/St_Vincent` - America/St_Vincent
 * `America/Swift_Current` - America/Swift_Current
 * `America/Tegucigalpa` - America/Tegucigalpa
 * `America/Thule` - America/Thule
 * `America/Thunder_Bay` - America/Thunder_Bay
 * `America/Tijuana` - America/Tijuana
 * `America/Toronto` - America/Toronto
 * `America/Tortola` - America/Tortola
 * `America/Vancouver` - America/Vancouver
 * `America/Virgin` - America/Virgin
 * `America/Whitehorse` - America/Whitehorse
 * `America/Winnipeg` - America/Winnipeg
 * `America/Yakutat` - America/Yakutat
 * `America/Yellowknife` - America/Yellowknife
 * `Antarctica/Casey` - Antarctica/Casey
 * `Antarctica/Davis` - Antarctica/Davis
 * `Antarctica/DumontDUrville` - Antarctica/DumontDUrville
 * `Antarctica/Macquarie` - Antarctica/Macquarie
 * `Antarctica/Mawson` - Antarctica/Mawson
 * `Antarctica/McMurdo` - Antarctica/McMurdo
 * `Antarctica/Palmer` - Antarctica/Palmer
 * `Antarctica/Rothera` - Antarctica/Rothera
 * `Antarctica/South_Pole` - Antarctica/South_Pole
 * `Antarctica/Syowa` - Antarctica/Syowa
 * `Antarctica/Troll` - Antarctica/Troll
 * `Antarctica/Vostok` - Antarctica/Vostok
 * `Arctic/Longyearbyen` - Arctic/Longyearbyen
 * `Asia/Aden` - Asia/Aden
 * `Asia/Almaty` - Asia/Almaty
 * `Asia/Amman` - Asia/Amman
 * `Asia/Anadyr` - Asia/Anadyr
 * `Asia/Aqtau` - Asia/Aqtau
 * `Asia/Aqtobe` - Asia/Aqtobe
 * `Asia/Ashgabat` - Asia/Ashgabat
 * `Asia/Ashkhabad` - Asia/Ashkhabad
 * `Asia/Atyrau` - Asia/Atyrau
 * `Asia/Baghdad` - Asia/Baghdad
 * `Asia/Bahrain` - Asia/Bahrain
 * `Asia/Baku` - Asia/Baku
 * `Asia/Bangkok` - Asia/Bangkok
 * `Asia/Barnaul` - Asia/Barnaul
 * `Asia/Beirut` - Asia/Beirut
 * `Asia/Bishkek` - Asia/Bishkek
 * `Asia/Brunei` - Asia/Brunei
 * `Asia/Calcutta` - Asia/Calcutta
 * `Asia/Chita` - Asia/Chita
 * `Asia/Choibalsan` - Asia/Choibalsan
 * `Asia/Chongqing` - Asia/Chongqing
 * `Asia/Chungking` - Asia/Chungking
 * `Asia/Colombo` - Asia/Colombo
 * `Asia/Dacca` - Asia/Dacca
 * `Asia/Damascus` - Asia/Damascus
 * `Asia/Dhaka` - Asia/Dhaka
 * `Asia/Dili` - Asia/Dili
 * `Asia/Dubai` - Asia/Dubai
 * `Asia/Dushanbe` - Asia/Dushanbe
 * `Asia/Famagusta` - Asia/Famagusta
 * `Asia/Gaza` - Asia/Gaza
 * `Asia/Harbin` - Asia/Harbin
 * `Asia/Hebron` - Asia/Hebron
 * `Asia/Ho_Chi_Minh` - Asia/Ho_Chi_Minh
 * `Asia/Hong_Kong` - Asia/Hong_Kong
 * `Asia/Hovd` - Asia/Hovd
 * `Asia/Irkutsk` - Asia/Irkutsk
 * `Asia/Istanbul` - Asia/Istanbul
 * `Asia/Jakarta` - Asia/Jakarta
 * `Asia/Jayapura` - Asia/Jayapura
 * `Asia/Jerusalem` - Asia/Jerusalem
 * `Asia/Kabul` - Asia/Kabul
 * `Asia/Kamchatka` - Asia/Kamchatka
 * `Asia/Karachi` - Asia/Karachi
 * `Asia/Kashgar` - Asia/Kashgar
 * `Asia/Kathmandu` - Asia/Kathmandu
 * `Asia/Katmandu` - Asia/Katmandu
 * `Asia/Khandyga` - Asia/Khandyga
 * `Asia/Kolkata` - Asia/Kolkata
 * `Asia/Krasnoyarsk` - Asia/Krasnoyarsk
 * `Asia/Kuala_Lumpur` - Asia/Kuala_Lumpur
 * `Asia/Kuching` - Asia/Kuching
 * `Asia/Kuwait` - Asia/Kuwait
 * `Asia/Macao` - Asia/Macao
 * `Asia/Macau` - Asia/Macau
 * `Asia/Magadan` - Asia/Magadan
 * `Asia/Makassar` - Asia/Makassar
 * `Asia/Manila` - Asia/Manila
 * `Asia/Muscat` - Asia/Muscat
 * `Asia/Nicosia` - Asia/Nicosia
 * `Asia/Novokuznetsk` - Asia/Novokuznetsk
 * `Asia/Novosibirsk` - Asia/Novosibirsk
 * `Asia/Omsk` - Asia/Omsk
 * `Asia/Oral` - Asia/Oral
 * `Asia/Phnom_Penh` - Asia/Phnom_Penh
 * `Asia/Pontianak` - Asia/Pontianak
 * `Asia/Pyongyang` - Asia/Pyongyang
 * `Asia/Qatar` - Asia/Qatar
 * `Asia/Qostanay` - Asia/Qostanay
 * `Asia/Qyzylorda` - Asia/Qyzylorda
 * `Asia/Rangoon` - Asia/Rangoon
 * `Asia/Riyadh` - Asia/Riyadh
 * `Asia/Saigon` - Asia/Saigon
 * `Asia/Sakhalin` - Asia/Sakhalin
 * `Asia/Samarkand` - Asia/Samarkand
 * `Asia/Seoul` - Asia/Seoul
 * `Asia/Shanghai` - Asia/Shanghai
 * `Asia/Singapore` - Asia/Singapore
 * `Asia/Srednekolymsk` - Asia/Srednekolymsk
 * `Asia/Taipei` - Asia/Taipei
 * `Asia/Tashkent` - Asia/Tashkent
 * `Asia/Tbilisi` - Asia/Tbilisi
 * `Asia/Tehran` - Asia/Tehran
 * `Asia/Tel_Aviv` - Asia/Tel_Aviv
 * `Asia/Thimbu` - Asia/Thimbu
 * `Asia/Thimphu` - Asia/Thimphu
 * `Asia/Tokyo` - Asia/Tokyo
 * `Asia/Tomsk` - Asia/Tomsk
 * `Asia/Ujung_Pandang` - Asia/Ujung_Pandang
 * `Asia/Ulaanbaatar` - Asia/Ulaanbaatar
 * `Asia/Ulan_Bator` - Asia/Ulan_Bator
 * `Asia/Urumqi` - Asia/Urumqi
 * `Asia/Ust-Nera` - Asia/Ust-Nera
 * `Asia/Vientiane` - Asia/Vientiane
 * `Asia/Vladivostok` - Asia/Vladivostok
 * `Asia/Yakutsk` - Asia/Yakutsk
 * `Asia/Yangon` - Asia/Yangon
 * `Asia/Yekaterinburg` - Asia/Yekaterinburg
 * `Asia/Yerevan` - Asia/Yerevan
 * `Atlantic/Azores` - Atlantic/Azores
 * `Atlantic/Bermuda` - Atlantic/Bermuda
 * `Atlantic/Canary` - Atlantic/Canary
 * `Atlantic/Cape_Verde` - Atlantic/Cape_Verde
 * `Atlantic/Faeroe` - Atlantic/Faeroe
 * `Atlantic/Faroe` - Atlantic/Faroe
 * `Atlantic/Jan_Mayen` - Atlantic/Jan_Mayen
 * `Atlantic/Madeira` - Atlantic/Madeira
 * `Atlantic/Reykjavik` - Atlantic/Reykjavik
 * `Atlantic/South_Georgia` - Atlantic/South_Georgia
 * `Atlantic/St_Helena` - Atlantic/St_Helena
 * `Atlantic/Stanley` - Atlantic/Stanley
 * `Australia/ACT` - Australia/ACT
 * `Australia/Adelaide` - Australia/Adelaide
 * `Australia/Brisbane` - Australia/Brisbane
 * `Australia/Broken_Hill` - Australia/Broken_Hill
 * `Australia/Canberra` - Australia/Canberra
 * `Australia/Currie` - Australia/Currie
 * `Australia/Darwin` - Australia/Darwin
 * `Australia/Eucla` - Australia/Eucla
 * `Australia/Hobart` - Australia/Hobart
 * `Australia/LHI` - Australia/LHI
 * `Australia/Lindeman` - Australia/Lindeman
 * `Australia/Lord_Howe` - Australia/Lord_Howe
 * `Australia/Melbourne` - Australia/Melbourne
 * `Australia/NSW` - Australia/NSW
 * `Australia/North` - Australia/North
 * `Australia/Perth` - Australia/Perth
 * `Australia/Queensland` - Australia/Queensland
 * `Australia/South` - Australia/South
 * `Australia/Sydney` - Australia/Sydney
 * `Australia/Tasmania` - Australia/Tasmania
 * `Australia/Victoria` - Australia/Victoria
 * `Australia/West` - Australia/West
 * `Australia/Yancowinna` - Australia/Yancowinna
 * `Brazil/Acre` - Brazil/Acre
 * `Brazil/DeNoronha` - Brazil/DeNoronha
 * `Brazil/East` - Brazil/East
 * `Brazil/West` - Brazil/West
 * `CET` - CET
 * `CST6CDT` - CST6CDT
 * `Canada/Atlantic` - Canada/Atlantic
 * `Canada/Central` - Canada/Central
 * `Canada/Eastern` - Canada/Eastern
 * `Canada/Mountain` - Canada/Mountain
 * `Canada/Newfoundland` - Canada/Newfoundland
 * `Canada/Pacific` - Canada/Pacific
 * `Canada/Saskatchewan` - Canada/Saskatchewan
 * `Canada/Yukon` - Canada/Yukon
 * `Chile/Continental` - Chile/Continental
 * `Chile/EasterIsland` - Chile/EasterIsland
 * `Cuba` - Cuba
 * `EET` - EET
 * `EST` - EST
 * `EST5EDT` - EST5EDT
 * `Egypt` - Egypt
 * `Eire` - Eire
 * `Etc/GMT` - Etc/GMT
 * `Etc/GMT+0` - Etc/GMT+0
 * `Etc/GMT+1` - Etc/GMT+1
 * `Etc/GMT+10` - Etc/GMT+10
 * `Etc/GMT+11` - Etc/GMT+11
 * `Etc/GMT+12` - Etc/GMT+12
 * `Etc/GMT+2` - Etc/GMT+2
 * `Etc/GMT+3` - Etc/GMT+3
 * `Etc/GMT+4` - Etc/GMT+4
 * `Etc/GMT+5` - Etc/GMT+5
 * `Etc/GMT+6` - Etc/GMT+6
 * `Etc/GMT+7` - Etc/GMT+7
 * `Etc/GMT+8` - Etc/GMT+8
 * `Etc/GMT+9` - Etc/GMT+9
 * `Etc/GMT-0` - Etc/GMT-0
 * `Etc/GMT-1` - Etc/GMT-1
 * `Etc/GMT-10` - Etc/GMT-10
 * `Etc/GMT-11` - Etc/GMT-11
 * `Etc/GMT-12` - Etc/GMT-12
 * `Etc/GMT-13` - Etc/GMT-13
 * `Etc/GMT-14` - Etc/GMT-14
 * `Etc/GMT-2` - Etc/GMT-2
 * `Etc/GMT-3` - Etc/GMT-3
 * `Etc/GMT-4` - Etc/GMT-4
 * `Etc/GMT-5` - Etc/GMT-5
 * `Etc/GMT-6` - Etc/GMT-6
 * `Etc/GMT-7` - Etc/GMT-7
 * `Etc/GMT-8` - Etc/GMT-8
 * `Etc/GMT-9` - Etc/GMT-9
 * `Etc/GMT0` - Etc/GMT0
 * `Etc/Greenwich` - Etc/Greenwich
 * `Etc/UCT` - Etc/UCT
 * `Etc/UTC` - Etc/UTC
 * `Etc/Universal` - Etc/Universal
 * `Etc/Zulu` - Etc/Zulu
 * `Europe/Amsterdam` - Europe/Amsterdam
 * `Europe/Andorra` - Europe/Andorra
 * `Europe/Astrakhan` - Europe/Astrakhan
 * `Europe/Athens` - Europe/Athens
 * `Europe/Belfast` - Europe/Belfast
 * `Europe/Belgrade` - Europe/Belgrade
 * `Europe/Berlin` - Europe/Berlin
 * `Europe/Bratislava` - Europe/Bratislava
 * `Europe/Brussels` - Europe/Brussels
 * `Europe/Bucharest` - Europe/Bucharest
 * `Europe/Budapest` - Europe/Budapest
 * `Europe/Busingen` - Europe/Busingen
 * `Europe/Chisinau` - Europe/Chisinau
 * `Europe/Copenhagen` - Europe/Copenhagen
 * `Europe/Dublin` - Europe/Dublin
 * `Europe/Gibraltar` - Europe/Gibraltar
 * `Europe/Guernsey` - Europe/Guernsey
 * `Europe/Helsinki` - Europe/Helsinki
 * `Europe/Isle_of_Man` - Europe/Isle_of_Man
 * `Europe/Istanbul` - Europe/Istanbul
 * `Europe/Jersey` - Europe/Jersey
 * `Europe/Kaliningrad` - Europe/Kaliningrad
 * `Europe/Kiev` - Europe/Kiev
 * `Europe/Kirov` - Europe/Kirov
 * `Europe/Kyiv` - Europe/Kyiv
 * `Europe/Lisbon` - Europe/Lisbon
 * `Europe/Ljubljana` - Europe/Ljubljana
 * `Europe/London` - Europe/London
 * `Europe/Luxembourg` - Europe/Luxembourg
 * `Europe/Madrid` - Europe/Madrid
 * `Europe/Malta` - Europe/Malta
 * `Europe/Mariehamn` - Europe/Mariehamn
 * `Europe/Minsk` - Europe/Minsk
 * `Europe/Monaco` - Europe/Monaco
 * `Europe/Moscow` - Europe/Moscow
 * `Europe/Nicosia` - Europe/Nicosia
 * `Europe/Oslo` - Europe/Oslo
 * `Europe/Paris` - Europe/Paris
 * `Europe/Podgorica` - Europe/Podgorica
 * `Europe/Prague` - Europe/Prague
 * `Europe/Riga` - Europe/Riga
 * `Europe/Rome` - Europe/Rome
 * `Europe/Samara` - Europe/Samara
 * `Europe/San_Marino` - Europe/San_Marino
 * `Europe/Sarajevo` - Europe/Sarajevo
 * `Europe/Saratov` - Europe/Saratov
 * `Europe/Simferopol` - Europe/Simferopol
 * `Europe/Skopje` - Europe/Skopje
 * `Europe/Sofia` - Europe/Sofia
 * `Europe/Stockholm` - Europe/Stockholm
 * `Europe/Tallinn` - Europe/Tallinn
 * `Europe/Tirane` - Europe/Tirane
 * `Europe/Tiraspol` - Europe/Tiraspol
 * `Europe/Ulyanovsk` - Europe/Ulyanovsk
 * `Europe/Uzhgorod` - Europe/Uzhgorod
 * `Europe/Vaduz` - Europe/Vaduz
 * `Europe/Vatican` - Europe/Vatican
 * `Europe/Vienna` - Europe/Vienna
 * `Europe/Vilnius` - Europe/Vilnius
 * `Europe/Volgograd` - Europe/Volgograd
 * `Europe/Warsaw` - Europe/Warsaw
 * `Europe/Zagreb` - Europe/Zagreb
 * `Europe/Zaporozhye` - Europe/Zaporozhye
 * `Europe/Zurich` - Europe/Zurich
 * `GB` - GB
 * `GB-Eire` - GB-Eire
 * `GMT` - GMT
 * `GMT+0` - GMT+0
 * `GMT-0` - GMT-0
 * `GMT0` - GMT0
 * `Greenwich` - Greenwich
 * `HST` - HST
 * `Hongkong` - Hongkong
 * `Iceland` - Iceland
 * `Indian/Antananarivo` - Indian/Antananarivo
 * `Indian/Chagos` - Indian/Chagos
 * `Indian/Christmas` - Indian/Christmas
 * `Indian/Cocos` - Indian/Cocos
 * `Indian/Comoro` - Indian/Comoro
 * `Indian/Kerguelen` - Indian/Kerguelen
 * `Indian/Mahe` - Indian/Mahe
 * `Indian/Maldives` - Indian/Maldives
 * `Indian/Mauritius` - Indian/Mauritius
 * `Indian/Mayotte` - Indian/Mayotte
 * `Indian/Reunion` - Indian/Reunion
 * `Iran` - Iran
 * `Israel` - Israel
 * `Jamaica` - Jamaica
 * `Japan` - Japan
 * `Kwajalein` - Kwajalein
 * `Libya` - Libya
 * `MET` - MET
 * `MST` - MST
 * `MST7MDT` - MST7MDT
 * `Mexico/BajaNorte` - Mexico/BajaNorte
 * `Mexico/BajaSur` - Mexico/BajaSur
 * `Mexico/General` - Mexico/General
 * `NZ` - NZ
 * `NZ-CHAT` - NZ-CHAT
 * `Navajo` - Navajo
 * `PRC` - PRC
 * `PST8PDT` - PST8PDT
 * `Pacific/Apia` - Pacific/Apia
 * `Pacific/Auckland` - Pacific/Auckland
 * `Pacific/Bougainville` - Pacific/Bougainville
 * `Pacific/Chatham` - Pacific/Chatham
 * `Pacific/Chuuk` - Pacific/Chuuk
 * `Pacific/Easter` - Pacific/Easter
 * `Pacific/Efate` - Pacific/Efate
 * `Pacific/Enderbury` - Pacific/Enderbury
 * `Pacific/Fakaofo` - Pacific/Fakaofo
 * `Pacific/Fiji` - Pacific/Fiji
 * `Pacific/Funafuti` - Pacific/Funafuti
 * `Pacific/Galapagos` - Pacific/Galapagos
 * `Pacific/Gambier` - Pacific/Gambier
 * `Pacific/Guadalcanal` - Pacific/Guadalcanal
 * `Pacific/Guam` - Pacific/Guam
 * `Pacific/Honolulu` - Pacific/Honolulu
 * `Pacific/Johnston` - Pacific/Johnston
 * `Pacific/Kanton` - Pacific/Kanton
 * `Pacific/Kiritimati` - Pacific/Kiritimati
 * `Pacific/Kosrae` - Pacific/Kosrae
 * `Pacific/Kwajalein` - Pacific/Kwajalein
 * `Pacific/Majuro` - Pacific/Majuro
 * `Pacific/Marquesas` - Pacific/Marquesas
 * `Pacific/Midway` - Pacific/Midway
 * `Pacific/Nauru` - Pacific/Nauru
 * `Pacific/Niue` - Pacific/Niue
 * `Pacific/Norfolk` - Pacific/Norfolk
 * `Pacific/Noumea` - Pacific/Noumea
 * `Pacific/Pago_Pago` - Pacific/Pago_Pago
 * `Pacific/Palau` - Pacific/Palau
 * `Pacific/Pitcairn` - Pacific/Pitcairn
 * `Pacific/Pohnpei` - Pacific/Pohnpei
 * `Pacific/Ponape` - Pacific/Ponape
 * `Pacific/Port_Moresby` - Pacific/Port_Moresby
 * `Pacific/Rarotonga` - Pacific/Rarotonga
 * `Pacific/Saipan` - Pacific/Saipan
 * `Pacific/Samoa` - Pacific/Samoa
 * `Pacific/Tahiti` - Pacific/Tahiti
 * `Pacific/Tarawa` - Pacific/Tarawa
 * `Pacific/Tongatapu` - Pacific/Tongatapu
 * `Pacific/Truk` - Pacific/Truk
 * `Pacific/Wake` - Pacific/Wake
 * `Pacific/Wallis` - Pacific/Wallis
 * `Pacific/Yap` - Pacific/Yap
 * `Poland` - Poland
 * `Portugal` - Portugal
 * `ROC` - ROC
 * `ROK` - ROK
 * `Singapore` - Singapore
 * `Turkey` - Turkey
 * `UCT` - UCT
 * `US/Alaska` - US/Alaska
 * `US/Aleutian` - US/Aleutian
 * `US/Arizona` - US/Arizona
 * `US/Central` - US/Central
 * `US/East-Indiana` - US/East-Indiana
 * `US/Eastern` - US/Eastern
 * `US/Hawaii` - US/Hawaii
 * `US/Indiana-Starke` - US/Indiana-Starke
 * `US/Michigan` - US/Michigan
 * `US/Mountain` - US/Mountain
 * `US/Pacific` - US/Pacific
 * `US/Samoa` - US/Samoa
 * `UTC` - UTC
 * `Universal` - Universal
 * `W-SU` - W-SU
 * `WET` - WET
 * `Zulu` - Zulu
 */
export type TimezoneEnumApi = (typeof TimezoneEnumApi)[keyof typeof TimezoneEnumApi]

export const TimezoneEnumApi = {
    'Africa/Abidjan': 'Africa/Abidjan',
    'Africa/Accra': 'Africa/Accra',
    'Africa/Addis_Ababa': 'Africa/Addis_Ababa',
    'Africa/Algiers': 'Africa/Algiers',
    'Africa/Asmara': 'Africa/Asmara',
    'Africa/Asmera': 'Africa/Asmera',
    'Africa/Bamako': 'Africa/Bamako',
    'Africa/Bangui': 'Africa/Bangui',
    'Africa/Banjul': 'Africa/Banjul',
    'Africa/Bissau': 'Africa/Bissau',
    'Africa/Blantyre': 'Africa/Blantyre',
    'Africa/Brazzaville': 'Africa/Brazzaville',
    'Africa/Bujumbura': 'Africa/Bujumbura',
    'Africa/Cairo': 'Africa/Cairo',
    'Africa/Casablanca': 'Africa/Casablanca',
    'Africa/Ceuta': 'Africa/Ceuta',
    'Africa/Conakry': 'Africa/Conakry',
    'Africa/Dakar': 'Africa/Dakar',
    'Africa/Dar_es_Salaam': 'Africa/Dar_es_Salaam',
    'Africa/Djibouti': 'Africa/Djibouti',
    'Africa/Douala': 'Africa/Douala',
    'Africa/El_Aaiun': 'Africa/El_Aaiun',
    'Africa/Freetown': 'Africa/Freetown',
    'Africa/Gaborone': 'Africa/Gaborone',
    'Africa/Harare': 'Africa/Harare',
    'Africa/Johannesburg': 'Africa/Johannesburg',
    'Africa/Juba': 'Africa/Juba',
    'Africa/Kampala': 'Africa/Kampala',
    'Africa/Khartoum': 'Africa/Khartoum',
    'Africa/Kigali': 'Africa/Kigali',
    'Africa/Kinshasa': 'Africa/Kinshasa',
    'Africa/Lagos': 'Africa/Lagos',
    'Africa/Libreville': 'Africa/Libreville',
    'Africa/Lome': 'Africa/Lome',
    'Africa/Luanda': 'Africa/Luanda',
    'Africa/Lubumbashi': 'Africa/Lubumbashi',
    'Africa/Lusaka': 'Africa/Lusaka',
    'Africa/Malabo': 'Africa/Malabo',
    'Africa/Maputo': 'Africa/Maputo',
    'Africa/Maseru': 'Africa/Maseru',
    'Africa/Mbabane': 'Africa/Mbabane',
    'Africa/Mogadishu': 'Africa/Mogadishu',
    'Africa/Monrovia': 'Africa/Monrovia',
    'Africa/Nairobi': 'Africa/Nairobi',
    'Africa/Ndjamena': 'Africa/Ndjamena',
    'Africa/Niamey': 'Africa/Niamey',
    'Africa/Nouakchott': 'Africa/Nouakchott',
    'Africa/Ouagadougou': 'Africa/Ouagadougou',
    'Africa/Porto-Novo': 'Africa/Porto-Novo',
    'Africa/Sao_Tome': 'Africa/Sao_Tome',
    'Africa/Timbuktu': 'Africa/Timbuktu',
    'Africa/Tripoli': 'Africa/Tripoli',
    'Africa/Tunis': 'Africa/Tunis',
    'Africa/Windhoek': 'Africa/Windhoek',
    'America/Adak': 'America/Adak',
    'America/Anchorage': 'America/Anchorage',
    'America/Anguilla': 'America/Anguilla',
    'America/Antigua': 'America/Antigua',
    'America/Araguaina': 'America/Araguaina',
    'America/Argentina/Buenos_Aires': 'America/Argentina/Buenos_Aires',
    'America/Argentina/Catamarca': 'America/Argentina/Catamarca',
    'America/Argentina/ComodRivadavia': 'America/Argentina/ComodRivadavia',
    'America/Argentina/Cordoba': 'America/Argentina/Cordoba',
    'America/Argentina/Jujuy': 'America/Argentina/Jujuy',
    'America/Argentina/La_Rioja': 'America/Argentina/La_Rioja',
    'America/Argentina/Mendoza': 'America/Argentina/Mendoza',
    'America/Argentina/Rio_Gallegos': 'America/Argentina/Rio_Gallegos',
    'America/Argentina/Salta': 'America/Argentina/Salta',
    'America/Argentina/San_Juan': 'America/Argentina/San_Juan',
    'America/Argentina/San_Luis': 'America/Argentina/San_Luis',
    'America/Argentina/Tucuman': 'America/Argentina/Tucuman',
    'America/Argentina/Ushuaia': 'America/Argentina/Ushuaia',
    'America/Aruba': 'America/Aruba',
    'America/Asuncion': 'America/Asuncion',
    'America/Atikokan': 'America/Atikokan',
    'America/Atka': 'America/Atka',
    'America/Bahia': 'America/Bahia',
    'America/Bahia_Banderas': 'America/Bahia_Banderas',
    'America/Barbados': 'America/Barbados',
    'America/Belem': 'America/Belem',
    'America/Belize': 'America/Belize',
    'America/Blanc-Sablon': 'America/Blanc-Sablon',
    'America/Boa_Vista': 'America/Boa_Vista',
    'America/Bogota': 'America/Bogota',
    'America/Boise': 'America/Boise',
    'America/Buenos_Aires': 'America/Buenos_Aires',
    'America/Cambridge_Bay': 'America/Cambridge_Bay',
    'America/Campo_Grande': 'America/Campo_Grande',
    'America/Cancun': 'America/Cancun',
    'America/Caracas': 'America/Caracas',
    'America/Catamarca': 'America/Catamarca',
    'America/Cayenne': 'America/Cayenne',
    'America/Cayman': 'America/Cayman',
    'America/Chicago': 'America/Chicago',
    'America/Chihuahua': 'America/Chihuahua',
    'America/Ciudad_Juarez': 'America/Ciudad_Juarez',
    'America/Coral_Harbour': 'America/Coral_Harbour',
    'America/Cordoba': 'America/Cordoba',
    'America/Costa_Rica': 'America/Costa_Rica',
    'America/Creston': 'America/Creston',
    'America/Cuiaba': 'America/Cuiaba',
    'America/Curacao': 'America/Curacao',
    'America/Danmarkshavn': 'America/Danmarkshavn',
    'America/Dawson': 'America/Dawson',
    'America/Dawson_Creek': 'America/Dawson_Creek',
    'America/Denver': 'America/Denver',
    'America/Detroit': 'America/Detroit',
    'America/Dominica': 'America/Dominica',
    'America/Edmonton': 'America/Edmonton',
    'America/Eirunepe': 'America/Eirunepe',
    'America/El_Salvador': 'America/El_Salvador',
    'America/Ensenada': 'America/Ensenada',
    'America/Fort_Nelson': 'America/Fort_Nelson',
    'America/Fort_Wayne': 'America/Fort_Wayne',
    'America/Fortaleza': 'America/Fortaleza',
    'America/Glace_Bay': 'America/Glace_Bay',
    'America/Godthab': 'America/Godthab',
    'America/Goose_Bay': 'America/Goose_Bay',
    'America/Grand_Turk': 'America/Grand_Turk',
    'America/Grenada': 'America/Grenada',
    'America/Guadeloupe': 'America/Guadeloupe',
    'America/Guatemala': 'America/Guatemala',
    'America/Guayaquil': 'America/Guayaquil',
    'America/Guyana': 'America/Guyana',
    'America/Halifax': 'America/Halifax',
    'America/Havana': 'America/Havana',
    'America/Hermosillo': 'America/Hermosillo',
    'America/Indiana/Indianapolis': 'America/Indiana/Indianapolis',
    'America/Indiana/Knox': 'America/Indiana/Knox',
    'America/Indiana/Marengo': 'America/Indiana/Marengo',
    'America/Indiana/Petersburg': 'America/Indiana/Petersburg',
    'America/Indiana/Tell_City': 'America/Indiana/Tell_City',
    'America/Indiana/Vevay': 'America/Indiana/Vevay',
    'America/Indiana/Vincennes': 'America/Indiana/Vincennes',
    'America/Indiana/Winamac': 'America/Indiana/Winamac',
    'America/Indianapolis': 'America/Indianapolis',
    'America/Inuvik': 'America/Inuvik',
    'America/Iqaluit': 'America/Iqaluit',
    'America/Jamaica': 'America/Jamaica',
    'America/Jujuy': 'America/Jujuy',
    'America/Juneau': 'America/Juneau',
    'America/Kentucky/Louisville': 'America/Kentucky/Louisville',
    'America/Kentucky/Monticello': 'America/Kentucky/Monticello',
    'America/Knox_IN': 'America/Knox_IN',
    'America/Kralendijk': 'America/Kralendijk',
    'America/La_Paz': 'America/La_Paz',
    'America/Lima': 'America/Lima',
    'America/Los_Angeles': 'America/Los_Angeles',
    'America/Louisville': 'America/Louisville',
    'America/Lower_Princes': 'America/Lower_Princes',
    'America/Maceio': 'America/Maceio',
    'America/Managua': 'America/Managua',
    'America/Manaus': 'America/Manaus',
    'America/Marigot': 'America/Marigot',
    'America/Martinique': 'America/Martinique',
    'America/Matamoros': 'America/Matamoros',
    'America/Mazatlan': 'America/Mazatlan',
    'America/Mendoza': 'America/Mendoza',
    'America/Menominee': 'America/Menominee',
    'America/Merida': 'America/Merida',
    'America/Metlakatla': 'America/Metlakatla',
    'America/Mexico_City': 'America/Mexico_City',
    'America/Miquelon': 'America/Miquelon',
    'America/Moncton': 'America/Moncton',
    'America/Monterrey': 'America/Monterrey',
    'America/Montevideo': 'America/Montevideo',
    'America/Montreal': 'America/Montreal',
    'America/Montserrat': 'America/Montserrat',
    'America/Nassau': 'America/Nassau',
    'America/New_York': 'America/New_York',
    'America/Nipigon': 'America/Nipigon',
    'America/Nome': 'America/Nome',
    'America/Noronha': 'America/Noronha',
    'America/North_Dakota/Beulah': 'America/North_Dakota/Beulah',
    'America/North_Dakota/Center': 'America/North_Dakota/Center',
    'America/North_Dakota/New_Salem': 'America/North_Dakota/New_Salem',
    'America/Nuuk': 'America/Nuuk',
    'America/Ojinaga': 'America/Ojinaga',
    'America/Panama': 'America/Panama',
    'America/Pangnirtung': 'America/Pangnirtung',
    'America/Paramaribo': 'America/Paramaribo',
    'America/Phoenix': 'America/Phoenix',
    'America/Port-au-Prince': 'America/Port-au-Prince',
    'America/Port_of_Spain': 'America/Port_of_Spain',
    'America/Porto_Acre': 'America/Porto_Acre',
    'America/Porto_Velho': 'America/Porto_Velho',
    'America/Puerto_Rico': 'America/Puerto_Rico',
    'America/Punta_Arenas': 'America/Punta_Arenas',
    'America/Rainy_River': 'America/Rainy_River',
    'America/Rankin_Inlet': 'America/Rankin_Inlet',
    'America/Recife': 'America/Recife',
    'America/Regina': 'America/Regina',
    'America/Resolute': 'America/Resolute',
    'America/Rio_Branco': 'America/Rio_Branco',
    'America/Rosario': 'America/Rosario',
    'America/Santa_Isabel': 'America/Santa_Isabel',
    'America/Santarem': 'America/Santarem',
    'America/Santiago': 'America/Santiago',
    'America/Santo_Domingo': 'America/Santo_Domingo',
    'America/Sao_Paulo': 'America/Sao_Paulo',
    'America/Scoresbysund': 'America/Scoresbysund',
    'America/Shiprock': 'America/Shiprock',
    'America/Sitka': 'America/Sitka',
    'America/St_Barthelemy': 'America/St_Barthelemy',
    'America/St_Johns': 'America/St_Johns',
    'America/St_Kitts': 'America/St_Kitts',
    'America/St_Lucia': 'America/St_Lucia',
    'America/St_Thomas': 'America/St_Thomas',
    'America/St_Vincent': 'America/St_Vincent',
    'America/Swift_Current': 'America/Swift_Current',
    'America/Tegucigalpa': 'America/Tegucigalpa',
    'America/Thule': 'America/Thule',
    'America/Thunder_Bay': 'America/Thunder_Bay',
    'America/Tijuana': 'America/Tijuana',
    'America/Toronto': 'America/Toronto',
    'America/Tortola': 'America/Tortola',
    'America/Vancouver': 'America/Vancouver',
    'America/Virgin': 'America/Virgin',
    'America/Whitehorse': 'America/Whitehorse',
    'America/Winnipeg': 'America/Winnipeg',
    'America/Yakutat': 'America/Yakutat',
    'America/Yellowknife': 'America/Yellowknife',
    'Antarctica/Casey': 'Antarctica/Casey',
    'Antarctica/Davis': 'Antarctica/Davis',
    'Antarctica/DumontDUrville': 'Antarctica/DumontDUrville',
    'Antarctica/Macquarie': 'Antarctica/Macquarie',
    'Antarctica/Mawson': 'Antarctica/Mawson',
    'Antarctica/McMurdo': 'Antarctica/McMurdo',
    'Antarctica/Palmer': 'Antarctica/Palmer',
    'Antarctica/Rothera': 'Antarctica/Rothera',
    'Antarctica/South_Pole': 'Antarctica/South_Pole',
    'Antarctica/Syowa': 'Antarctica/Syowa',
    'Antarctica/Troll': 'Antarctica/Troll',
    'Antarctica/Vostok': 'Antarctica/Vostok',
    'Arctic/Longyearbyen': 'Arctic/Longyearbyen',
    'Asia/Aden': 'Asia/Aden',
    'Asia/Almaty': 'Asia/Almaty',
    'Asia/Amman': 'Asia/Amman',
    'Asia/Anadyr': 'Asia/Anadyr',
    'Asia/Aqtau': 'Asia/Aqtau',
    'Asia/Aqtobe': 'Asia/Aqtobe',
    'Asia/Ashgabat': 'Asia/Ashgabat',
    'Asia/Ashkhabad': 'Asia/Ashkhabad',
    'Asia/Atyrau': 'Asia/Atyrau',
    'Asia/Baghdad': 'Asia/Baghdad',
    'Asia/Bahrain': 'Asia/Bahrain',
    'Asia/Baku': 'Asia/Baku',
    'Asia/Bangkok': 'Asia/Bangkok',
    'Asia/Barnaul': 'Asia/Barnaul',
    'Asia/Beirut': 'Asia/Beirut',
    'Asia/Bishkek': 'Asia/Bishkek',
    'Asia/Brunei': 'Asia/Brunei',
    'Asia/Calcutta': 'Asia/Calcutta',
    'Asia/Chita': 'Asia/Chita',
    'Asia/Choibalsan': 'Asia/Choibalsan',
    'Asia/Chongqing': 'Asia/Chongqing',
    'Asia/Chungking': 'Asia/Chungking',
    'Asia/Colombo': 'Asia/Colombo',
    'Asia/Dacca': 'Asia/Dacca',
    'Asia/Damascus': 'Asia/Damascus',
    'Asia/Dhaka': 'Asia/Dhaka',
    'Asia/Dili': 'Asia/Dili',
    'Asia/Dubai': 'Asia/Dubai',
    'Asia/Dushanbe': 'Asia/Dushanbe',
    'Asia/Famagusta': 'Asia/Famagusta',
    'Asia/Gaza': 'Asia/Gaza',
    'Asia/Harbin': 'Asia/Harbin',
    'Asia/Hebron': 'Asia/Hebron',
    'Asia/Ho_Chi_Minh': 'Asia/Ho_Chi_Minh',
    'Asia/Hong_Kong': 'Asia/Hong_Kong',
    'Asia/Hovd': 'Asia/Hovd',
    'Asia/Irkutsk': 'Asia/Irkutsk',
    'Asia/Istanbul': 'Asia/Istanbul',
    'Asia/Jakarta': 'Asia/Jakarta',
    'Asia/Jayapura': 'Asia/Jayapura',
    'Asia/Jerusalem': 'Asia/Jerusalem',
    'Asia/Kabul': 'Asia/Kabul',
    'Asia/Kamchatka': 'Asia/Kamchatka',
    'Asia/Karachi': 'Asia/Karachi',
    'Asia/Kashgar': 'Asia/Kashgar',
    'Asia/Kathmandu': 'Asia/Kathmandu',
    'Asia/Katmandu': 'Asia/Katmandu',
    'Asia/Khandyga': 'Asia/Khandyga',
    'Asia/Kolkata': 'Asia/Kolkata',
    'Asia/Krasnoyarsk': 'Asia/Krasnoyarsk',
    'Asia/Kuala_Lumpur': 'Asia/Kuala_Lumpur',
    'Asia/Kuching': 'Asia/Kuching',
    'Asia/Kuwait': 'Asia/Kuwait',
    'Asia/Macao': 'Asia/Macao',
    'Asia/Macau': 'Asia/Macau',
    'Asia/Magadan': 'Asia/Magadan',
    'Asia/Makassar': 'Asia/Makassar',
    'Asia/Manila': 'Asia/Manila',
    'Asia/Muscat': 'Asia/Muscat',
    'Asia/Nicosia': 'Asia/Nicosia',
    'Asia/Novokuznetsk': 'Asia/Novokuznetsk',
    'Asia/Novosibirsk': 'Asia/Novosibirsk',
    'Asia/Omsk': 'Asia/Omsk',
    'Asia/Oral': 'Asia/Oral',
    'Asia/Phnom_Penh': 'Asia/Phnom_Penh',
    'Asia/Pontianak': 'Asia/Pontianak',
    'Asia/Pyongyang': 'Asia/Pyongyang',
    'Asia/Qatar': 'Asia/Qatar',
    'Asia/Qostanay': 'Asia/Qostanay',
    'Asia/Qyzylorda': 'Asia/Qyzylorda',
    'Asia/Rangoon': 'Asia/Rangoon',
    'Asia/Riyadh': 'Asia/Riyadh',
    'Asia/Saigon': 'Asia/Saigon',
    'Asia/Sakhalin': 'Asia/Sakhalin',
    'Asia/Samarkand': 'Asia/Samarkand',
    'Asia/Seoul': 'Asia/Seoul',
    'Asia/Shanghai': 'Asia/Shanghai',
    'Asia/Singapore': 'Asia/Singapore',
    'Asia/Srednekolymsk': 'Asia/Srednekolymsk',
    'Asia/Taipei': 'Asia/Taipei',
    'Asia/Tashkent': 'Asia/Tashkent',
    'Asia/Tbilisi': 'Asia/Tbilisi',
    'Asia/Tehran': 'Asia/Tehran',
    'Asia/Tel_Aviv': 'Asia/Tel_Aviv',
    'Asia/Thimbu': 'Asia/Thimbu',
    'Asia/Thimphu': 'Asia/Thimphu',
    'Asia/Tokyo': 'Asia/Tokyo',
    'Asia/Tomsk': 'Asia/Tomsk',
    'Asia/Ujung_Pandang': 'Asia/Ujung_Pandang',
    'Asia/Ulaanbaatar': 'Asia/Ulaanbaatar',
    'Asia/Ulan_Bator': 'Asia/Ulan_Bator',
    'Asia/Urumqi': 'Asia/Urumqi',
    'Asia/Ust-Nera': 'Asia/Ust-Nera',
    'Asia/Vientiane': 'Asia/Vientiane',
    'Asia/Vladivostok': 'Asia/Vladivostok',
    'Asia/Yakutsk': 'Asia/Yakutsk',
    'Asia/Yangon': 'Asia/Yangon',
    'Asia/Yekaterinburg': 'Asia/Yekaterinburg',
    'Asia/Yerevan': 'Asia/Yerevan',
    'Atlantic/Azores': 'Atlantic/Azores',
    'Atlantic/Bermuda': 'Atlantic/Bermuda',
    'Atlantic/Canary': 'Atlantic/Canary',
    'Atlantic/Cape_Verde': 'Atlantic/Cape_Verde',
    'Atlantic/Faeroe': 'Atlantic/Faeroe',
    'Atlantic/Faroe': 'Atlantic/Faroe',
    'Atlantic/Jan_Mayen': 'Atlantic/Jan_Mayen',
    'Atlantic/Madeira': 'Atlantic/Madeira',
    'Atlantic/Reykjavik': 'Atlantic/Reykjavik',
    'Atlantic/South_Georgia': 'Atlantic/South_Georgia',
    'Atlantic/St_Helena': 'Atlantic/St_Helena',
    'Atlantic/Stanley': 'Atlantic/Stanley',
    'Australia/ACT': 'Australia/ACT',
    'Australia/Adelaide': 'Australia/Adelaide',
    'Australia/Brisbane': 'Australia/Brisbane',
    'Australia/Broken_Hill': 'Australia/Broken_Hill',
    'Australia/Canberra': 'Australia/Canberra',
    'Australia/Currie': 'Australia/Currie',
    'Australia/Darwin': 'Australia/Darwin',
    'Australia/Eucla': 'Australia/Eucla',
    'Australia/Hobart': 'Australia/Hobart',
    'Australia/LHI': 'Australia/LHI',
    'Australia/Lindeman': 'Australia/Lindeman',
    'Australia/Lord_Howe': 'Australia/Lord_Howe',
    'Australia/Melbourne': 'Australia/Melbourne',
    'Australia/NSW': 'Australia/NSW',
    'Australia/North': 'Australia/North',
    'Australia/Perth': 'Australia/Perth',
    'Australia/Queensland': 'Australia/Queensland',
    'Australia/South': 'Australia/South',
    'Australia/Sydney': 'Australia/Sydney',
    'Australia/Tasmania': 'Australia/Tasmania',
    'Australia/Victoria': 'Australia/Victoria',
    'Australia/West': 'Australia/West',
    'Australia/Yancowinna': 'Australia/Yancowinna',
    'Brazil/Acre': 'Brazil/Acre',
    'Brazil/DeNoronha': 'Brazil/DeNoronha',
    'Brazil/East': 'Brazil/East',
    'Brazil/West': 'Brazil/West',
    CET: 'CET',
    CST6CDT: 'CST6CDT',
    'Canada/Atlantic': 'Canada/Atlantic',
    'Canada/Central': 'Canada/Central',
    'Canada/Eastern': 'Canada/Eastern',
    'Canada/Mountain': 'Canada/Mountain',
    'Canada/Newfoundland': 'Canada/Newfoundland',
    'Canada/Pacific': 'Canada/Pacific',
    'Canada/Saskatchewan': 'Canada/Saskatchewan',
    'Canada/Yukon': 'Canada/Yukon',
    'Chile/Continental': 'Chile/Continental',
    'Chile/EasterIsland': 'Chile/EasterIsland',
    Cuba: 'Cuba',
    EET: 'EET',
    EST: 'EST',
    EST5EDT: 'EST5EDT',
    Egypt: 'Egypt',
    Eire: 'Eire',
    'Etc/GMT': 'Etc/GMT',
    'Etc/GMT+0': 'Etc/GMT+0',
    'Etc/GMT+1': 'Etc/GMT+1',
    'Etc/GMT+10': 'Etc/GMT+10',
    'Etc/GMT+11': 'Etc/GMT+11',
    'Etc/GMT+12': 'Etc/GMT+12',
    'Etc/GMT+2': 'Etc/GMT+2',
    'Etc/GMT+3': 'Etc/GMT+3',
    'Etc/GMT+4': 'Etc/GMT+4',
    'Etc/GMT+5': 'Etc/GMT+5',
    'Etc/GMT+6': 'Etc/GMT+6',
    'Etc/GMT+7': 'Etc/GMT+7',
    'Etc/GMT+8': 'Etc/GMT+8',
    'Etc/GMT+9': 'Etc/GMT+9',
    'Etc/GMT-0': 'Etc/GMT-0',
    'Etc/GMT-1': 'Etc/GMT-1',
    'Etc/GMT-10': 'Etc/GMT-10',
    'Etc/GMT-11': 'Etc/GMT-11',
    'Etc/GMT-12': 'Etc/GMT-12',
    'Etc/GMT-13': 'Etc/GMT-13',
    'Etc/GMT-14': 'Etc/GMT-14',
    'Etc/GMT-2': 'Etc/GMT-2',
    'Etc/GMT-3': 'Etc/GMT-3',
    'Etc/GMT-4': 'Etc/GMT-4',
    'Etc/GMT-5': 'Etc/GMT-5',
    'Etc/GMT-6': 'Etc/GMT-6',
    'Etc/GMT-7': 'Etc/GMT-7',
    'Etc/GMT-8': 'Etc/GMT-8',
    'Etc/GMT-9': 'Etc/GMT-9',
    'Etc/GMT0': 'Etc/GMT0',
    'Etc/Greenwich': 'Etc/Greenwich',
    'Etc/UCT': 'Etc/UCT',
    'Etc/UTC': 'Etc/UTC',
    'Etc/Universal': 'Etc/Universal',
    'Etc/Zulu': 'Etc/Zulu',
    'Europe/Amsterdam': 'Europe/Amsterdam',
    'Europe/Andorra': 'Europe/Andorra',
    'Europe/Astrakhan': 'Europe/Astrakhan',
    'Europe/Athens': 'Europe/Athens',
    'Europe/Belfast': 'Europe/Belfast',
    'Europe/Belgrade': 'Europe/Belgrade',
    'Europe/Berlin': 'Europe/Berlin',
    'Europe/Bratislava': 'Europe/Bratislava',
    'Europe/Brussels': 'Europe/Brussels',
    'Europe/Bucharest': 'Europe/Bucharest',
    'Europe/Budapest': 'Europe/Budapest',
    'Europe/Busingen': 'Europe/Busingen',
    'Europe/Chisinau': 'Europe/Chisinau',
    'Europe/Copenhagen': 'Europe/Copenhagen',
    'Europe/Dublin': 'Europe/Dublin',
    'Europe/Gibraltar': 'Europe/Gibraltar',
    'Europe/Guernsey': 'Europe/Guernsey',
    'Europe/Helsinki': 'Europe/Helsinki',
    'Europe/Isle_of_Man': 'Europe/Isle_of_Man',
    'Europe/Istanbul': 'Europe/Istanbul',
    'Europe/Jersey': 'Europe/Jersey',
    'Europe/Kaliningrad': 'Europe/Kaliningrad',
    'Europe/Kiev': 'Europe/Kiev',
    'Europe/Kirov': 'Europe/Kirov',
    'Europe/Kyiv': 'Europe/Kyiv',
    'Europe/Lisbon': 'Europe/Lisbon',
    'Europe/Ljubljana': 'Europe/Ljubljana',
    'Europe/London': 'Europe/London',
    'Europe/Luxembourg': 'Europe/Luxembourg',
    'Europe/Madrid': 'Europe/Madrid',
    'Europe/Malta': 'Europe/Malta',
    'Europe/Mariehamn': 'Europe/Mariehamn',
    'Europe/Minsk': 'Europe/Minsk',
    'Europe/Monaco': 'Europe/Monaco',
    'Europe/Moscow': 'Europe/Moscow',
    'Europe/Nicosia': 'Europe/Nicosia',
    'Europe/Oslo': 'Europe/Oslo',
    'Europe/Paris': 'Europe/Paris',
    'Europe/Podgorica': 'Europe/Podgorica',
    'Europe/Prague': 'Europe/Prague',
    'Europe/Riga': 'Europe/Riga',
    'Europe/Rome': 'Europe/Rome',
    'Europe/Samara': 'Europe/Samara',
    'Europe/San_Marino': 'Europe/San_Marino',
    'Europe/Sarajevo': 'Europe/Sarajevo',
    'Europe/Saratov': 'Europe/Saratov',
    'Europe/Simferopol': 'Europe/Simferopol',
    'Europe/Skopje': 'Europe/Skopje',
    'Europe/Sofia': 'Europe/Sofia',
    'Europe/Stockholm': 'Europe/Stockholm',
    'Europe/Tallinn': 'Europe/Tallinn',
    'Europe/Tirane': 'Europe/Tirane',
    'Europe/Tiraspol': 'Europe/Tiraspol',
    'Europe/Ulyanovsk': 'Europe/Ulyanovsk',
    'Europe/Uzhgorod': 'Europe/Uzhgorod',
    'Europe/Vaduz': 'Europe/Vaduz',
    'Europe/Vatican': 'Europe/Vatican',
    'Europe/Vienna': 'Europe/Vienna',
    'Europe/Vilnius': 'Europe/Vilnius',
    'Europe/Volgograd': 'Europe/Volgograd',
    'Europe/Warsaw': 'Europe/Warsaw',
    'Europe/Zagreb': 'Europe/Zagreb',
    'Europe/Zaporozhye': 'Europe/Zaporozhye',
    'Europe/Zurich': 'Europe/Zurich',
    GB: 'GB',
    'GB-Eire': 'GB-Eire',
    GMT: 'GMT',
    'GMT+0': 'GMT+0',
    'GMT-0': 'GMT-0',
    GMT0: 'GMT0',
    Greenwich: 'Greenwich',
    HST: 'HST',
    Hongkong: 'Hongkong',
    Iceland: 'Iceland',
    'Indian/Antananarivo': 'Indian/Antananarivo',
    'Indian/Chagos': 'Indian/Chagos',
    'Indian/Christmas': 'Indian/Christmas',
    'Indian/Cocos': 'Indian/Cocos',
    'Indian/Comoro': 'Indian/Comoro',
    'Indian/Kerguelen': 'Indian/Kerguelen',
    'Indian/Mahe': 'Indian/Mahe',
    'Indian/Maldives': 'Indian/Maldives',
    'Indian/Mauritius': 'Indian/Mauritius',
    'Indian/Mayotte': 'Indian/Mayotte',
    'Indian/Reunion': 'Indian/Reunion',
    Iran: 'Iran',
    Israel: 'Israel',
    Jamaica: 'Jamaica',
    Japan: 'Japan',
    Kwajalein: 'Kwajalein',
    Libya: 'Libya',
    MET: 'MET',
    MST: 'MST',
    MST7MDT: 'MST7MDT',
    'Mexico/BajaNorte': 'Mexico/BajaNorte',
    'Mexico/BajaSur': 'Mexico/BajaSur',
    'Mexico/General': 'Mexico/General',
    NZ: 'NZ',
    'NZ-CHAT': 'NZ-CHAT',
    Navajo: 'Navajo',
    PRC: 'PRC',
    PST8PDT: 'PST8PDT',
    'Pacific/Apia': 'Pacific/Apia',
    'Pacific/Auckland': 'Pacific/Auckland',
    'Pacific/Bougainville': 'Pacific/Bougainville',
    'Pacific/Chatham': 'Pacific/Chatham',
    'Pacific/Chuuk': 'Pacific/Chuuk',
    'Pacific/Easter': 'Pacific/Easter',
    'Pacific/Efate': 'Pacific/Efate',
    'Pacific/Enderbury': 'Pacific/Enderbury',
    'Pacific/Fakaofo': 'Pacific/Fakaofo',
    'Pacific/Fiji': 'Pacific/Fiji',
    'Pacific/Funafuti': 'Pacific/Funafuti',
    'Pacific/Galapagos': 'Pacific/Galapagos',
    'Pacific/Gambier': 'Pacific/Gambier',
    'Pacific/Guadalcanal': 'Pacific/Guadalcanal',
    'Pacific/Guam': 'Pacific/Guam',
    'Pacific/Honolulu': 'Pacific/Honolulu',
    'Pacific/Johnston': 'Pacific/Johnston',
    'Pacific/Kanton': 'Pacific/Kanton',
    'Pacific/Kiritimati': 'Pacific/Kiritimati',
    'Pacific/Kosrae': 'Pacific/Kosrae',
    'Pacific/Kwajalein': 'Pacific/Kwajalein',
    'Pacific/Majuro': 'Pacific/Majuro',
    'Pacific/Marquesas': 'Pacific/Marquesas',
    'Pacific/Midway': 'Pacific/Midway',
    'Pacific/Nauru': 'Pacific/Nauru',
    'Pacific/Niue': 'Pacific/Niue',
    'Pacific/Norfolk': 'Pacific/Norfolk',
    'Pacific/Noumea': 'Pacific/Noumea',
    'Pacific/Pago_Pago': 'Pacific/Pago_Pago',
    'Pacific/Palau': 'Pacific/Palau',
    'Pacific/Pitcairn': 'Pacific/Pitcairn',
    'Pacific/Pohnpei': 'Pacific/Pohnpei',
    'Pacific/Ponape': 'Pacific/Ponape',
    'Pacific/Port_Moresby': 'Pacific/Port_Moresby',
    'Pacific/Rarotonga': 'Pacific/Rarotonga',
    'Pacific/Saipan': 'Pacific/Saipan',
    'Pacific/Samoa': 'Pacific/Samoa',
    'Pacific/Tahiti': 'Pacific/Tahiti',
    'Pacific/Tarawa': 'Pacific/Tarawa',
    'Pacific/Tongatapu': 'Pacific/Tongatapu',
    'Pacific/Truk': 'Pacific/Truk',
    'Pacific/Wake': 'Pacific/Wake',
    'Pacific/Wallis': 'Pacific/Wallis',
    'Pacific/Yap': 'Pacific/Yap',
    Poland: 'Poland',
    Portugal: 'Portugal',
    ROC: 'ROC',
    ROK: 'ROK',
    Singapore: 'Singapore',
    Turkey: 'Turkey',
    UCT: 'UCT',
    'US/Alaska': 'US/Alaska',
    'US/Aleutian': 'US/Aleutian',
    'US/Arizona': 'US/Arizona',
    'US/Central': 'US/Central',
    'US/East-Indiana': 'US/East-Indiana',
    'US/Eastern': 'US/Eastern',
    'US/Hawaii': 'US/Hawaii',
    'US/Indiana-Starke': 'US/Indiana-Starke',
    'US/Michigan': 'US/Michigan',
    'US/Mountain': 'US/Mountain',
    'US/Pacific': 'US/Pacific',
    'US/Samoa': 'US/Samoa',
    UTC: 'UTC',
    Universal: 'Universal',
    'W-SU': 'W-SU',
    WET: 'WET',
    Zulu: 'Zulu',
} as const

/**
 * * `30d` - 30 Days
 * `90d` - 90 Days
 * `1y` - 1 Year
 * `5y` - 5 Years
 */
export type SessionRecordingRetentionPeriodEnumApi =
    (typeof SessionRecordingRetentionPeriodEnumApi)[keyof typeof SessionRecordingRetentionPeriodEnumApi]

export const SessionRecordingRetentionPeriodEnumApi = {
    '30d': '30d',
    '90d': '90d',
    '1y': '1y',
    '5y': '5y',
} as const

/**
 * * `0` - Sunday
 * `1` - Monday
 */
export type WeekStartDayEnumApi = (typeof WeekStartDayEnumApi)[keyof typeof WeekStartDayEnumApi]

export const WeekStartDayEnumApi = {
    NUMBER_0: 0,
    NUMBER_1: 1,
} as const

/**
 * * `0` - Disabled
 * `1` - Stateless
 * `2` - Stateful
 */
export type CookielessServerHashModeEnumApi =
    (typeof CookielessServerHashModeEnumApi)[keyof typeof CookielessServerHashModeEnumApi]

export const CookielessServerHashModeEnumApi = {
    NUMBER_0: 0,
    NUMBER_1: 1,
    NUMBER_2: 2,
} as const

/**
 * * `AED` - AED
 * `AFN` - AFN
 * `ALL` - ALL
 * `AMD` - AMD
 * `ANG` - ANG
 * `AOA` - AOA
 * `ARS` - ARS
 * `AUD` - AUD
 * `AWG` - AWG
 * `AZN` - AZN
 * `BAM` - BAM
 * `BBD` - BBD
 * `BDT` - BDT
 * `BGN` - BGN
 * `BHD` - BHD
 * `BIF` - BIF
 * `BMD` - BMD
 * `BND` - BND
 * `BOB` - BOB
 * `BRL` - BRL
 * `BSD` - BSD
 * `BTC` - BTC
 * `BTN` - BTN
 * `BWP` - BWP
 * `BYN` - BYN
 * `BZD` - BZD
 * `CAD` - CAD
 * `CDF` - CDF
 * `CHF` - CHF
 * `CLP` - CLP
 * `CNY` - CNY
 * `COP` - COP
 * `CRC` - CRC
 * `CVE` - CVE
 * `CZK` - CZK
 * `DJF` - DJF
 * `DKK` - DKK
 * `DOP` - DOP
 * `DZD` - DZD
 * `EGP` - EGP
 * `ERN` - ERN
 * `ETB` - ETB
 * `EUR` - EUR
 * `FJD` - FJD
 * `GBP` - GBP
 * `GEL` - GEL
 * `GHS` - GHS
 * `GIP` - GIP
 * `GMD` - GMD
 * `GNF` - GNF
 * `GTQ` - GTQ
 * `GYD` - GYD
 * `HKD` - HKD
 * `HNL` - HNL
 * `HRK` - HRK
 * `HTG` - HTG
 * `HUF` - HUF
 * `IDR` - IDR
 * `ILS` - ILS
 * `INR` - INR
 * `IQD` - IQD
 * `IRR` - IRR
 * `ISK` - ISK
 * `JMD` - JMD
 * `JOD` - JOD
 * `JPY` - JPY
 * `KES` - KES
 * `KGS` - KGS
 * `KHR` - KHR
 * `KMF` - KMF
 * `KRW` - KRW
 * `KWD` - KWD
 * `KYD` - KYD
 * `KZT` - KZT
 * `LAK` - LAK
 * `LBP` - LBP
 * `LKR` - LKR
 * `LRD` - LRD
 * `LTL` - LTL
 * `LVL` - LVL
 * `LSL` - LSL
 * `LYD` - LYD
 * `MAD` - MAD
 * `MDL` - MDL
 * `MGA` - MGA
 * `MKD` - MKD
 * `MMK` - MMK
 * `MNT` - MNT
 * `MOP` - MOP
 * `MRU` - MRU
 * `MTL` - MTL
 * `MUR` - MUR
 * `MVR` - MVR
 * `MWK` - MWK
 * `MXN` - MXN
 * `MYR` - MYR
 * `MZN` - MZN
 * `NAD` - NAD
 * `NGN` - NGN
 * `NIO` - NIO
 * `NOK` - NOK
 * `NPR` - NPR
 * `NZD` - NZD
 * `OMR` - OMR
 * `PAB` - PAB
 * `PEN` - PEN
 * `PGK` - PGK
 * `PHP` - PHP
 * `PKR` - PKR
 * `PLN` - PLN
 * `PYG` - PYG
 * `QAR` - QAR
 * `RON` - RON
 * `RSD` - RSD
 * `RUB` - RUB
 * `RWF` - RWF
 * `SAR` - SAR
 * `SBD` - SBD
 * `SCR` - SCR
 * `SDG` - SDG
 * `SEK` - SEK
 * `SGD` - SGD
 * `SRD` - SRD
 * `SSP` - SSP
 * `STN` - STN
 * `SYP` - SYP
 * `SZL` - SZL
 * `THB` - THB
 * `TJS` - TJS
 * `TMT` - TMT
 * `TND` - TND
 * `TOP` - TOP
 * `TRY` - TRY
 * `TTD` - TTD
 * `TWD` - TWD
 * `TZS` - TZS
 * `UAH` - UAH
 * `UGX` - UGX
 * `USD` - USD
 * `UYU` - UYU
 * `UZS` - UZS
 * `VES` - VES
 * `VND` - VND
 * `VUV` - VUV
 * `WST` - WST
 * `XAF` - XAF
 * `XCD` - XCD
 * `XOF` - XOF
 * `XPF` - XPF
 * `YER` - YER
 * `ZAR` - ZAR
 * `ZMW` - ZMW
 */
export type BaseCurrencyEnumApi = (typeof BaseCurrencyEnumApi)[keyof typeof BaseCurrencyEnumApi]

export const BaseCurrencyEnumApi = {
    AED: 'AED',
    AFN: 'AFN',
    ALL: 'ALL',
    AMD: 'AMD',
    ANG: 'ANG',
    AOA: 'AOA',
    ARS: 'ARS',
    AUD: 'AUD',
    AWG: 'AWG',
    AZN: 'AZN',
    BAM: 'BAM',
    BBD: 'BBD',
    BDT: 'BDT',
    BGN: 'BGN',
    BHD: 'BHD',
    BIF: 'BIF',
    BMD: 'BMD',
    BND: 'BND',
    BOB: 'BOB',
    BRL: 'BRL',
    BSD: 'BSD',
    BTC: 'BTC',
    BTN: 'BTN',
    BWP: 'BWP',
    BYN: 'BYN',
    BZD: 'BZD',
    CAD: 'CAD',
    CDF: 'CDF',
    CHF: 'CHF',
    CLP: 'CLP',
    CNY: 'CNY',
    COP: 'COP',
    CRC: 'CRC',
    CVE: 'CVE',
    CZK: 'CZK',
    DJF: 'DJF',
    DKK: 'DKK',
    DOP: 'DOP',
    DZD: 'DZD',
    EGP: 'EGP',
    ERN: 'ERN',
    ETB: 'ETB',
    EUR: 'EUR',
    FJD: 'FJD',
    GBP: 'GBP',
    GEL: 'GEL',
    GHS: 'GHS',
    GIP: 'GIP',
    GMD: 'GMD',
    GNF: 'GNF',
    GTQ: 'GTQ',
    GYD: 'GYD',
    HKD: 'HKD',
    HNL: 'HNL',
    HRK: 'HRK',
    HTG: 'HTG',
    HUF: 'HUF',
    IDR: 'IDR',
    ILS: 'ILS',
    INR: 'INR',
    IQD: 'IQD',
    IRR: 'IRR',
    ISK: 'ISK',
    JMD: 'JMD',
    JOD: 'JOD',
    JPY: 'JPY',
    KES: 'KES',
    KGS: 'KGS',
    KHR: 'KHR',
    KMF: 'KMF',
    KRW: 'KRW',
    KWD: 'KWD',
    KYD: 'KYD',
    KZT: 'KZT',
    LAK: 'LAK',
    LBP: 'LBP',
    LKR: 'LKR',
    LRD: 'LRD',
    LTL: 'LTL',
    LVL: 'LVL',
    LSL: 'LSL',
    LYD: 'LYD',
    MAD: 'MAD',
    MDL: 'MDL',
    MGA: 'MGA',
    MKD: 'MKD',
    MMK: 'MMK',
    MNT: 'MNT',
    MOP: 'MOP',
    MRU: 'MRU',
    MTL: 'MTL',
    MUR: 'MUR',
    MVR: 'MVR',
    MWK: 'MWK',
    MXN: 'MXN',
    MYR: 'MYR',
    MZN: 'MZN',
    NAD: 'NAD',
    NGN: 'NGN',
    NIO: 'NIO',
    NOK: 'NOK',
    NPR: 'NPR',
    NZD: 'NZD',
    OMR: 'OMR',
    PAB: 'PAB',
    PEN: 'PEN',
    PGK: 'PGK',
    PHP: 'PHP',
    PKR: 'PKR',
    PLN: 'PLN',
    PYG: 'PYG',
    QAR: 'QAR',
    RON: 'RON',
    RSD: 'RSD',
    RUB: 'RUB',
    RWF: 'RWF',
    SAR: 'SAR',
    SBD: 'SBD',
    SCR: 'SCR',
    SDG: 'SDG',
    SEK: 'SEK',
    SGD: 'SGD',
    SRD: 'SRD',
    SSP: 'SSP',
    STN: 'STN',
    SYP: 'SYP',
    SZL: 'SZL',
    THB: 'THB',
    TJS: 'TJS',
    TMT: 'TMT',
    TND: 'TND',
    TOP: 'TOP',
    TRY: 'TRY',
    TTD: 'TTD',
    TWD: 'TWD',
    TZS: 'TZS',
    UAH: 'UAH',
    UGX: 'UGX',
    USD: 'USD',
    UYU: 'UYU',
    UZS: 'UZS',
    VES: 'VES',
    VND: 'VND',
    VUV: 'VUV',
    WST: 'WST',
    XAF: 'XAF',
    XCD: 'XCD',
    XOF: 'XOF',
    XPF: 'XPF',
    YER: 'YER',
    ZAR: 'ZAR',
    ZMW: 'ZMW',
} as const

export interface TeamRevenueAnalyticsConfigApi {
    base_currency?: BaseCurrencyEnumApi
    events?: unknown
    goals?: unknown
    filter_test_accounts?: boolean
}

/**
 * * `first_touch` - First Touch
 * `last_touch` - Last Touch
 */
export type AttributionModeEnumApi = (typeof AttributionModeEnumApi)[keyof typeof AttributionModeEnumApi]

export const AttributionModeEnumApi = {
    first_touch: 'first_touch',
    last_touch: 'last_touch',
} as const

export interface TeamMarketingAnalyticsConfigApi {
    sources_map?: unknown
    conversion_goals?: unknown
    /**
     * @minimum 1
     * @maximum 90
     */
    attribution_window_days?: number
    attribution_mode?: AttributionModeEnumApi
    campaign_name_mappings?: unknown
    custom_source_mappings?: unknown
    campaign_field_preferences?: unknown
}

export interface TeamCustomerAnalyticsConfigApi {
    activity_event?: unknown
    signup_pageview_event?: unknown
    signup_event?: unknown
    subscription_event?: unknown
    payment_event?: unknown
}

/**
 * * `b2b` - B2B
 * `b2c` - B2C
 * `other` - Other
 */
export type BusinessModelEnumApi = (typeof BusinessModelEnumApi)[keyof typeof BusinessModelEnumApi]

export const BusinessModelEnumApi = {
    b2b: 'b2b',
    b2c: 'b2c',
    other: 'other',
} as const

export type EffectiveMembershipLevelEnumApi =
    (typeof EffectiveMembershipLevelEnumApi)[keyof typeof EffectiveMembershipLevelEnumApi]

export const EffectiveMembershipLevelEnumApi = {
    NUMBER_1: 1,
    NUMBER_8: 8,
    NUMBER_15: 15,
} as const

export interface TeamApi {
    readonly id: number
    readonly uuid: string
    /**
     * @minLength 1
     * @maxLength 200
     */
    name?: string
    access_control?: boolean
    readonly organization: string
    /**
     * @minimum -9223372036854776000
     * @maximum 9223372036854776000
     */
    readonly project_id: number
    readonly api_token: string
    /** @nullable */
    readonly secret_api_token: string | null
    /** @nullable */
    readonly secret_api_token_backup: string | null
    readonly created_at: string
    readonly updated_at: string
    readonly ingested_event: boolean
    readonly default_modifiers: TeamApiDefaultModifiers
    readonly person_on_events_querying_enabled: boolean
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
    app_urls?: (string | null)[]
    /**
     * @maxLength 500
     * @nullable
     */
    slack_incoming_webhook?: string | null
    anonymize_ips?: boolean
    completed_snippet_onboarding?: boolean
    test_account_filters?: unknown
    /** @nullable */
    test_account_filters_default_checked?: boolean | null
    path_cleaning_filters?: unknown | null
    is_demo?: boolean
    timezone?: TimezoneEnumApi
    data_attributes?: unknown
    /** @nullable */
    person_display_name_properties?: string[] | null
    correlation_config?: unknown | null
    /** @nullable */
    autocapture_opt_out?: boolean | null
    /** @nullable */
    autocapture_exceptions_opt_in?: boolean | null
    /** @nullable */
    autocapture_web_vitals_opt_in?: boolean | null
    autocapture_web_vitals_allowed_metrics?: unknown | null
    autocapture_exceptions_errors_to_ignore?: unknown | null
    /** @nullable */
    capture_console_log_opt_in?: boolean | null
    logs_settings?: unknown | null
    /** @nullable */
    capture_performance_opt_in?: boolean | null
    session_recording_opt_in?: boolean
    /**
     * @nullable
     * @pattern ^-?\d{0,1}(?:\.\d{0,2})?$
     */
    session_recording_sample_rate?: string | null
    /**
     * @minimum 0
     * @maximum 30000
     * @nullable
     */
    session_recording_minimum_duration_milliseconds?: number | null
    session_recording_linked_flag?: unknown | null
    session_recording_network_payload_capture_config?: unknown | null
    session_recording_masking_config?: unknown | null
    /** @nullable */
    session_recording_url_trigger_config?: (unknown | null)[] | null
    /** @nullable */
    session_recording_url_blocklist_config?: (unknown | null)[] | null
    /** @nullable */
    session_recording_event_trigger_config?: (string | null)[] | null
    /**
     * @maxLength 24
     * @nullable
     */
    session_recording_trigger_match_type_config?: string | null
    session_recording_retention_period?: SessionRecordingRetentionPeriodEnumApi
    session_replay_config?: unknown | null
    survey_config?: unknown | null
    /**
     * @minimum -32768
     * @maximum 32767
     */
    week_start_day?: WeekStartDayEnumApi | NullEnumApi | null
    /** @nullable */
    primary_dashboard?: number | null
    /** @nullable */
    live_events_columns?: string[] | null
    /** @nullable */
    recording_domains?: (string | null)[] | null
    /**
     * @minimum -32768
     * @maximum 32767
     */
    cookieless_server_hash_mode?: CookielessServerHashModeEnumApi | NullEnumApi | null
    /** @nullable */
    human_friendly_comparison_periods?: boolean | null
    /** @nullable */
    inject_web_apps?: boolean | null
    extra_settings?: unknown | null
    modifiers?: unknown | null
    has_completed_onboarding_for?: unknown | null
    /** @nullable */
    surveys_opt_in?: boolean | null
    /** @nullable */
    heatmaps_opt_in?: boolean | null
    /** @nullable */
    flags_persistence_default?: boolean | null
    /** @nullable */
    feature_flag_confirmation_enabled?: boolean | null
    /** @nullable */
    feature_flag_confirmation_message?: string | null
    /**
     * Whether to automatically apply default evaluation contexts to new feature flags
     * @nullable
     */
    default_evaluation_contexts_enabled?: boolean | null
    /**
     * Whether to require at least one evaluation context tag when creating new feature flags
     * @nullable
     */
    require_evaluation_contexts?: boolean | null
    /** @nullable */
    capture_dead_clicks?: boolean | null
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    default_data_theme?: number | null
    revenue_analytics_config?: TeamRevenueAnalyticsConfigApi
    marketing_analytics_config?: TeamMarketingAnalyticsConfigApi
    customer_analytics_config?: TeamCustomerAnalyticsConfigApi
    onboarding_tasks?: unknown | null
    base_currency?: BaseCurrencyEnumApi
    /** @nullable */
    web_analytics_pre_aggregated_tables_enabled?: boolean | null
    /**
     * Time of day (UTC) when experiment metrics should be recalculated. If not set, uses the default recalculation time.
     * @nullable
     */
    experiment_recalculation_time?: string | null
    /**
     * Default confidence level for new experiments in this environment. Valid values: 0.90, 0.95, 0.99.
     * @nullable
     * @pattern ^-?\d{0,1}(?:\.\d{0,2})?$
     */
    default_experiment_confidence_level?: string | null
    /** @nullable */
    receive_org_level_activity_logs?: boolean | null
    /** Whether this project serves B2B or B2C customers, used to optimize the UI layout.

* `b2b` - B2B
* `b2c` - B2C
* `other` - Other */
    business_model?: BusinessModelEnumApi | BlankEnumApi | NullEnumApi | null
    /** @nullable */
    conversations_enabled?: boolean | null
    conversations_settings?: unknown | null
    readonly effective_membership_level: EffectiveMembershipLevelEnumApi | null
    readonly has_group_types: boolean
    readonly group_types: readonly TeamApiGroupTypesItem[]
    /** @nullable */
    readonly live_events_token: string | null
    readonly product_intents: string
    readonly managed_viewsets: string
}

export type LocalEvaluationResponseApiGroupTypeMapping = { [key: string]: string }

/**
 * Cohort definitions keyed by cohort ID. Each value is a property group structure with 'type' (OR/AND) and 'values' (array of property groups or property filters).
 */
export type LocalEvaluationResponseApiCohorts = { [key: string]: unknown }

/**
 * * `server` - Server
 * `client` - Client
 * `all` - All
 */
export type EvaluationRuntimeEnumApi = (typeof EvaluationRuntimeEnumApi)[keyof typeof EvaluationRuntimeEnumApi]

export const EvaluationRuntimeEnumApi = {
    server: 'server',
    client: 'client',
    all: 'all',
} as const

/**
 * * `distinct_id` - User ID (default)
 * `device_id` - Device ID
 */
export type BucketingIdentifierEnumApi = (typeof BucketingIdentifierEnumApi)[keyof typeof BucketingIdentifierEnumApi]

export const BucketingIdentifierEnumApi = {
    distinct_id: 'distinct_id',
    device_id: 'device_id',
} as const

export type MinimalFeatureFlagApiFilters = { [key: string]: unknown }

export interface MinimalFeatureFlagApi {
    readonly id: number
    readonly team_id: number
    name?: string
    /** @maxLength 400 */
    key: string
    filters?: MinimalFeatureFlagApiFilters
    deleted?: boolean
    active?: boolean
    /** @nullable */
    ensure_experience_continuity?: boolean | null
    /** @nullable */
    has_encrypted_payloads?: boolean | null
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    version?: number | null
    /** Specifies where this feature flag should be evaluated

* `server` - Server
* `client` - Client
* `all` - All */
    evaluation_runtime?: EvaluationRuntimeEnumApi | BlankEnumApi | NullEnumApi | null
    /** Identifier used for bucketing users into rollout and variants

* `distinct_id` - User ID (default)
* `device_id` - Device ID */
    bucketing_identifier?: BucketingIdentifierEnumApi | BlankEnumApi | NullEnumApi | null
    readonly evaluation_tags: readonly string[]
}

export interface LocalEvaluationResponseApi {
    flags: MinimalFeatureFlagApi[]
    group_type_mapping: LocalEvaluationResponseApiGroupTypeMapping
    /** Cohort definitions keyed by cohort ID. Each value is a property group structure with 'type' (OR/AND) and 'values' (array of property groups or property filters). */
    cohorts: LocalEvaluationResponseApiCohorts
}

export type EnvironmentsDatasetItemsListParams = {
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

export type EnvironmentsDatasetsListParams = {
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
    order_by?: EnvironmentsDatasetsListOrderByItem[]
    /**
     * Search in name, description, or metadata
     */
    search?: string
}

export type EnvironmentsDatasetsListOrderByItem =
    (typeof EnvironmentsDatasetsListOrderByItem)[keyof typeof EnvironmentsDatasetsListOrderByItem]

export const EnvironmentsDatasetsListOrderByItem = {
    '-created_at': '-created_at',
    '-updated_at': '-updated_at',
    created_at: 'created_at',
    updated_at: 'updated_at',
} as const

export type EnvironmentsEvaluationsListParams = {
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
    order_by?: EnvironmentsEvaluationsListOrderByItem[]
    /**
     * Search in name or description
     */
    search?: string
}

export type EnvironmentsEvaluationsListOrderByItem =
    (typeof EnvironmentsEvaluationsListOrderByItem)[keyof typeof EnvironmentsEvaluationsListOrderByItem]

export const EnvironmentsEvaluationsListOrderByItem = {
    '-created_at': '-created_at',
    '-name': '-name',
    '-updated_at': '-updated_at',
    created_at: 'created_at',
    name: 'name',
    updated_at: 'updated_at',
} as const

export type EnvironmentsLlmAnalyticsProviderKeysListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type EnvironmentsLlmAnalyticsSummarizationCreate400 = { [key: string]: unknown }

export type EnvironmentsLlmAnalyticsSummarizationCreate403 = { [key: string]: unknown }

export type EnvironmentsLlmAnalyticsSummarizationCreate500 = { [key: string]: unknown }

export type EnvironmentsLlmAnalyticsSummarizationBatchCheckCreate400 = { [key: string]: unknown }

export type EnvironmentsLlmAnalyticsSummarizationBatchCheckCreate403 = { [key: string]: unknown }

export type EnvironmentsLlmAnalyticsTextReprCreate400 = { [key: string]: unknown }

export type EnvironmentsLlmAnalyticsTextReprCreate500 = { [key: string]: unknown }

export type EnvironmentsLlmAnalyticsTextReprCreate503 = { [key: string]: unknown }

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

export type FeatureFlagsEvaluationReasonsRetrieveParams = {
    /**
     * User distinct ID
     * @minLength 1
     */
    distinct_id: string
    /**
     * Groups for feature flag evaluation (JSON object string)
     */
    groups?: string
}

export type FeatureFlagsLocalEvaluationRetrieveParams = {
    /**
     * Include cohorts in response
     * @nullable
     */
    send_cohorts?: boolean | null
}

/**
 * Unspecified response body
 */
export type FeatureFlagsLocalEvaluationRetrieve402 = { [key: string]: unknown }

/**
 * Unspecified response body
 */
export type FeatureFlagsLocalEvaluationRetrieve500 = { [key: string]: unknown }
