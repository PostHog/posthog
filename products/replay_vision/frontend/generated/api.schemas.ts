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
 * * `pending` - Pending
 * `running` - Running
 * `succeeded` - Succeeded
 * `failed` - Failed
 * `ineligible` - Ineligible
 */
export type ObservationStatusEnumApi = (typeof ObservationStatusEnumApi)[keyof typeof ObservationStatusEnumApi]

export const ObservationStatusEnumApi = {
    Pending: 'pending',
    Running: 'running',
    Succeeded: 'succeeded',
    Failed: 'failed',
    Ineligible: 'ineligible',
} as const

/**
 * * `monitor` - Monitor
 * `classifier` - Classifier
 * `scorer` - Scorer
 * `summarizer` - Summarizer
 * `indexer` - Indexer
 */
export type ScannerTypeEnumApi = (typeof ScannerTypeEnumApi)[keyof typeof ScannerTypeEnumApi]

export const ScannerTypeEnumApi = {
    Monitor: 'monitor',
    Classifier: 'classifier',
    Scorer: 'scorer',
    Summarizer: 'summarizer',
    Indexer: 'indexer',
} as const

/**
 * * `gemini-3-flash-preview` - Gemini 3 Flash
 * `gemini-3.1-flash-lite-preview` - Gemini 3 Flash Lite
 */
export type ScannerModelEnumApi = (typeof ScannerModelEnumApi)[keyof typeof ScannerModelEnumApi]

export const ScannerModelEnumApi = {
    Gemini3FlashPreview: 'gemini-3-flash-preview',
    Gemini31FlashLitePreview: 'gemini-3.1-flash-lite-preview',
} as const

/**
 * * `google` - Google
 */
export type ScannerProviderEnumApi = (typeof ScannerProviderEnumApi)[keyof typeof ScannerProviderEnumApi]

export const ScannerProviderEnumApi = {
    Google: 'google',
} as const

/**
 * Mirrors `temporal.types.ScannerSnapshot` for OpenAPI generation.
 */
export interface ScannerSnapshotApi {
    /** Scanner name at run time. */
    name: string
    /** Scanner type (monitor, classifier, scorer, summarizer, indexer) at run time.

  * `monitor` - Monitor
  * `classifier` - Classifier
  * `scorer` - Scorer
  * `summarizer` - Summarizer
  * `indexer` - Indexer */
    scanner_type: ScannerTypeEnumApi
    /** The `ReplayScanner.scanner_version` value at the moment the workflow ran. */
    scanner_version: number
    /** Concrete model that ran the observation.

  * `gemini-3-flash-preview` - Gemini 3 Flash
  * `gemini-3.1-flash-lite-preview` - Gemini 3 Flash Lite */
    model: ScannerModelEnumApi
    /** Concrete provider that ran the observation.

  * `google` - Google */
    provider: ScannerProviderEnumApi
    /** Whether the observation was run with Signal emission enabled. */
    emits_signals: boolean
    /** Scanner-type-specific configuration at run time (prompt, tags, scale, etc.). */
    scanner_config: unknown
}

/**
 * Maps the short `event_id` the LLM cites in `model_output.reasoning` to citation metadata: `{uuid, timestamp_ms}`. Only includes hashes the LLM actually cited.
 */
export type ScannerResultApiEventIdMapping = { [key: string]: unknown }

/**
 * Mirrors `temporal.types.ScannerResult` for OpenAPI generation.
 */
export interface ScannerResultApi {
    /** Validated scanner output. Shape depends on `scanner_snapshot.scanner_type`; always carries `confidence` and `scanner_type`. */
    model_output: unknown
    /**
     * Number of PostHog Signals emitted from this observation.
     * @minimum 0
     */
    signals_count: number
    /** Maps the short `event_id` the LLM cites in `model_output.reasoning` to citation metadata: `{uuid, timestamp_ms}`. Only includes hashes the LLM actually cited. */
    event_id_mapping: ScannerResultApiEventIdMapping
}

/**
 * * `schedule` - Schedule
 * `on_demand` - On demand
 */
export type ObservationTriggerEnumApi = (typeof ObservationTriggerEnumApi)[keyof typeof ObservationTriggerEnumApi]

export const ObservationTriggerEnumApi = {
    Schedule: 'schedule',
    OnDemand: 'on_demand',
} as const

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
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null

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
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | null
}

export interface ReplayObservationApi {
    readonly id: string
    /** The scanner that produced this observation. */
    readonly scanner_id: string
    /** Session recording id this scanner was applied to. */
    readonly session_id: string
    /** Observation status (pending, running, succeeded, failed, ineligible).

  * `pending` - Pending
  * `running` - Running
  * `succeeded` - Succeeded
  * `failed` - Failed
  * `ineligible` - Ineligible */
    readonly status: ObservationStatusEnumApi
    /** Populated on terminal non-success statuses; formatted as `kind:human-readable message`. For `ineligible`, kind is one of no_recording / too_short / too_inactive / too_long / no_events. For `failed`, kind is one of provider_transient / provider_rejected / rasterization_failed / validation_failed / internal_error. */
    readonly error_reason: string
    /** Temporal workflow id for progress queries and debugging. Empty until the workflow starts. */
    readonly workflow_id: string
    /** Frozen view of the scanner at run time; scanner edits do not retroactively mutate this observation. */
    readonly scanner_snapshot: ScannerSnapshotApi | null
    /** Result data persisted on success; null until the observation succeeds. */
    readonly scanner_result: ScannerResultApi | null
    /** Whether this observation came from the schedule or an on-demand request.

  * `schedule` - Schedule
  * `on_demand` - On demand */
    readonly triggered_by: ObservationTriggerEnumApi
    /** User who triggered an on-demand observation; null for scheduled observations. */
    readonly triggered_by_user: UserBasicApi | null
    /** @nullable */
    started_at?: string | null
    /** @nullable */
    completed_at?: string | null
    readonly created_at: string
}

export interface PaginatedReplayObservationListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ReplayObservationApi[]
}

export interface ReplayScannerApi {
    readonly id: string
    /**
     * Human-readable scanner name. Unique within the team.
     * @maxLength 255
     */
    name: string
    /** Free-form description shown in the scanner management UI. */
    description?: string
    /** What the scanner does: monitor, classifier, scorer, summarizer, or indexer.

  * `monitor` - Monitor
  * `classifier` - Classifier
  * `scorer` - Scorer
  * `summarizer` - Summarizer
  * `indexer` - Indexer */
    scanner_type: ScannerTypeEnumApi
    /** Type-specific configuration. Monitor/classifier/scorer/summarizer require `prompt`; classifiers add `tags`, scorers add `scale`. Indexer is fixed-task and rejects `prompt`. */
    scanner_config: unknown
    /** Persisted `RecordingsQuery` shape used to pick candidate sessions. `date_from`/`date_to` are stripped on save — the schedule controls time, not the user. */
    query?: unknown
    /**
     * 0..1 random downsample applied after the query matches. Defaults to 1.0 (no downsampling).
     * @minimum 0
     * @maximum 1
     */
    sampling_rate?: number
    /** LLM provider. v1 is Google-only.

  * `google` - Google */
    provider?: ScannerProviderEnumApi
    /** Concrete model to use for this scanner.

  * `gemini-3-flash-preview` - Gemini 3 Flash
  * `gemini-3.1-flash-lite-preview` - Gemini 3 Flash Lite */
    model: ScannerModelEnumApi
    /** When false, the reconciler removes the scanner's Temporal schedule. On-demand triggers still work. */
    enabled?: boolean
    /** When true, the prompt is augmented with the Signal side mission and the scanner emits PostHog Signals. */
    emits_signals?: boolean
    /** Increments on every config-changing save. Observations snapshot this value. */
    readonly scanner_version: number
    /** Watermark for the scanner's last scheduled fire. Mirrors Temporal schedule state for recovery. */
    readonly last_swept_at: string
    readonly created_at: string
    /** User who created the scanner. */
    readonly created_by: UserBasicApi | null
    readonly updated_at: string
}

export interface PaginatedReplayScannerListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ReplayScannerApi[]
}

export interface PatchedReplayScannerApi {
    readonly id?: string
    /**
     * Human-readable scanner name. Unique within the team.
     * @maxLength 255
     */
    name?: string
    /** Free-form description shown in the scanner management UI. */
    description?: string
    /** What the scanner does: monitor, classifier, scorer, summarizer, or indexer.

  * `monitor` - Monitor
  * `classifier` - Classifier
  * `scorer` - Scorer
  * `summarizer` - Summarizer
  * `indexer` - Indexer */
    scanner_type?: ScannerTypeEnumApi
    /** Type-specific configuration. Monitor/classifier/scorer/summarizer require `prompt`; classifiers add `tags`, scorers add `scale`. Indexer is fixed-task and rejects `prompt`. */
    scanner_config?: unknown
    /** Persisted `RecordingsQuery` shape used to pick candidate sessions. `date_from`/`date_to` are stripped on save — the schedule controls time, not the user. */
    query?: unknown
    /**
     * 0..1 random downsample applied after the query matches. Defaults to 1.0 (no downsampling).
     * @minimum 0
     * @maximum 1
     */
    sampling_rate?: number
    /** LLM provider. v1 is Google-only.

  * `google` - Google */
    provider?: ScannerProviderEnumApi
    /** Concrete model to use for this scanner.

  * `gemini-3-flash-preview` - Gemini 3 Flash
  * `gemini-3.1-flash-lite-preview` - Gemini 3 Flash Lite */
    model?: ScannerModelEnumApi
    /** When false, the reconciler removes the scanner's Temporal schedule. On-demand triggers still work. */
    enabled?: boolean
    /** When true, the prompt is augmented with the Signal side mission and the scanner emits PostHog Signals. */
    emits_signals?: boolean
    /** Increments on every config-changing save. Observations snapshot this value. */
    readonly scanner_version?: number
    /** Watermark for the scanner's last scheduled fire. Mirrors Temporal schedule state for recovery. */
    readonly last_swept_at?: string
    readonly created_at?: string
    /** User who created the scanner. */
    readonly created_by?: UserBasicApi | null
    readonly updated_at?: string
}

/**
 * Body of POST /vision/scanners/{id}/observe/.
 */
export interface ObserveRequestApi {
    /**
     * ID of the session recording to apply the scanner to.
     * @maxLength 128
     */
    session_id: string
}

/**
 * Async-accepted response for POST /vision/scanners/{id}/observe/.
 */
export interface ObserveResponseApi {
    /** Temporal workflow id for this scanner application. Look up the resulting ReplayObservation via GET /vision/scanners/{id}/observations/?session_id=<session_id>. */
    workflow_id: string
}

/**
 * Body of POST /vision/scanners/estimate/ — a proposed, unsaved scanner config.
 */
export interface EstimateRequestApi {
    /** Proposed `RecordingsQuery` for the candidate filter. `date_from`/`date_to` are ignored — the estimate always uses a fixed 30-day lookback. Omit to estimate against all recordings. */
    query?: unknown
    /**
     * 0..1 downsample applied to matched sessions. Defaults to 1.0 (no downsampling).
     * @minimum 0
     * @maximum 1
     */
    sampling_rate?: number
}

/**
 * Forward-looking observation-volume estimate for a proposed scanner. Pricing-agnostic.
 */
export interface EstimateResponseApi {
    /** Distinct sessions matching the query within the 30-day lookback, before sampling. */
    matched_sessions_in_window: number
    /** Lookback window the estimate is based on. Normally 30; smaller when the team has fewer days of recordings. */
    window_days: number
    /** Projected monthly observations: matched sessions scaled to 30 days, times sampling_rate. */
    estimated_observations_per_month: number
    /** Sampling rate applied to the projection. Echoed from the request. */
    sampling_rate: number
}

export type VisionObservationsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Session recording id to return observations for.
     */
    session_id: string
}

export type VisionScannersListParams = {
    /**
     * Filter to scanners that emit Signals.
     */
    emits_signals?: boolean
    /**
     * Filter to enabled vs disabled scanners.
     */
    enabled?: boolean
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
 * Sort scanners by name, created_at, updated_at, or scanner_type. Prefix with `-` for descending.

* `name` - Name
* `-name` - Name (descending)
* `created_at` - Created at
* `-created_at` - Created at (descending)
* `updated_at` - Updated at
* `-updated_at` - Updated at (descending)
* `scanner_type` - Scanner type
* `-scanner_type` - Scanner type (descending)
 */
    order_by?: string[]
    /**
 * Filter by scanner type (monitor, classifier, scorer, summarizer, indexer).

* `monitor` - Monitor
* `classifier` - Classifier
* `scorer` - Scorer
* `summarizer` - Summarizer
* `indexer` - Indexer
 */
    scanner_type?: VisionScannersListScannerType
}

export type VisionScannersListScannerType =
    (typeof VisionScannersListScannerType)[keyof typeof VisionScannersListScannerType]

export const VisionScannersListScannerType = {
    Classifier: 'classifier',
    Indexer: 'indexer',
    Monitor: 'monitor',
    Scorer: 'scorer',
    Summarizer: 'summarizer',
} as const

export type VisionScannersObservationsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
 * Sort observations by created_at, started_at, completed_at, or status. Prefix with `-` for descending.

* `created_at` - Created at
* `-created_at` - Created at (descending)
* `started_at` - Started at
* `-started_at` - Started at (descending)
* `completed_at` - Completed at
* `-completed_at` - Completed at (descending)
* `status` - Status
* `-status` - Status (descending)
 */
    order_by?: string[]
    /**
     * Filter to observations of a specific session recording.
     */
    session_id?: string
    /**
 * Filter by observation status.

* `pending` - Pending
* `running` - Running
* `succeeded` - Succeeded
* `failed` - Failed
* `ineligible` - Ineligible
 */
    status?: VisionScannersObservationsListStatus
    /**
 * Filter by trigger source (schedule or on_demand).

* `schedule` - Schedule
* `on_demand` - On demand
 */
    triggered_by?: VisionScannersObservationsListTriggeredBy
}

export type VisionScannersObservationsListStatus =
    (typeof VisionScannersObservationsListStatus)[keyof typeof VisionScannersObservationsListStatus]

export const VisionScannersObservationsListStatus = {
    Failed: 'failed',
    Ineligible: 'ineligible',
    Pending: 'pending',
    Running: 'running',
    Succeeded: 'succeeded',
} as const

export type VisionScannersObservationsListTriggeredBy =
    (typeof VisionScannersObservationsListTriggeredBy)[keyof typeof VisionScannersObservationsListTriggeredBy]

export const VisionScannersObservationsListTriggeredBy = {
    OnDemand: 'on_demand',
    Schedule: 'schedule',
} as const
