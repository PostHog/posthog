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
 * * `monitor` - Monitor
 * `classifier` - Classifier
 * `scorer` - Scorer
 * `summarizer` - Summarizer
 * `indexer` - Indexer
 */
export type LensTypeEnumApi = (typeof LensTypeEnumApi)[keyof typeof LensTypeEnumApi]

export const LensTypeEnumApi = {
    Monitor: 'monitor',
    Classifier: 'classifier',
    Scorer: 'scorer',
    Summarizer: 'summarizer',
    Indexer: 'indexer',
} as const

/**
 * * `google` - Google
 */
export type LensProviderEnumApi = (typeof LensProviderEnumApi)[keyof typeof LensProviderEnumApi]

export const LensProviderEnumApi = {
    Google: 'google',
} as const

/**
 * * `gemini-3-flash` - Gemini 3 Flash
 * `gemini-3-flash-lite` - Gemini 3 Flash Lite
 */
export type LensModelEnumApi = (typeof LensModelEnumApi)[keyof typeof LensModelEnumApi]

export const LensModelEnumApi = {
    Gemini3Flash: 'gemini-3-flash',
    Gemini3FlashLite: 'gemini-3-flash-lite',
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

export interface ReplayLensApi {
    readonly id: string
    /**
     * Human-readable lens name. Unique within the team.
     * @maxLength 255
     */
    name: string
    /** Free-form description shown in the lens management UI. */
    description?: string
    /** What the lens does: monitor, classifier, scorer, summarizer, or indexer.

  * `monitor` - Monitor
  * `classifier` - Classifier
  * `scorer` - Scorer
  * `summarizer` - Summarizer
  * `indexer` - Indexer */
    lens_type: LensTypeEnumApi
    /** Type-specific configuration. Always includes `prompt`; classifiers add `tags`, scorers add `scale`, etc. */
    lens_config: unknown
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
    provider?: LensProviderEnumApi
    /** Concrete model to use for this lens.

  * `gemini-3-flash` - Gemini 3 Flash
  * `gemini-3-flash-lite` - Gemini 3 Flash Lite */
    model: LensModelEnumApi
    /** When false, the reconciler removes the lens's Temporal schedule. On-demand triggers still work. */
    enabled?: boolean
    /** When true, the prompt is augmented with the Signal side mission and the lens emits PostHog Signals. */
    emits_signals?: boolean
    /** Increments on every config-changing save. Observations snapshot this value. */
    readonly lens_version: number
    /** Watermark for the lens's last scheduled fire. Mirrors Temporal schedule state for recovery. */
    readonly last_swept_at: string
    readonly created_at: string
    /** User who created the lens. */
    readonly created_by: UserBasicApi | null
    readonly updated_at: string
}

export interface PaginatedReplayLensListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ReplayLensApi[]
}

/**
 * * `pending` - Pending
 * `running` - Running
 * `succeeded` - Succeeded
 * `failed` - Failed
 */
export type ObservationStatusEnumApi = (typeof ObservationStatusEnumApi)[keyof typeof ObservationStatusEnumApi]

export const ObservationStatusEnumApi = {
    Pending: 'pending',
    Running: 'running',
    Succeeded: 'succeeded',
    Failed: 'failed',
} as const

/**
 * * `schedule` - Schedule
 * `on_demand` - On demand
 */
export type ObservationTriggerEnumApi = (typeof ObservationTriggerEnumApi)[keyof typeof ObservationTriggerEnumApi]

export const ObservationTriggerEnumApi = {
    Schedule: 'schedule',
    OnDemand: 'on_demand',
} as const

export interface ReplayObservationApi {
    readonly id: string
    /** The lens that produced this observation. */
    readonly lens_id: string
    /** Session recording id this lens was applied to. */
    readonly session_id: string
    /** Observation status (pending, running, succeeded, failed).

  * `pending` - Pending
  * `running` - Running
  * `succeeded` - Succeeded
  * `failed` - Failed */
    readonly status: ObservationStatusEnumApi
    /** Populated on failure. Includes the malformed model response when validation fails. */
    readonly error_reason: string
    /** Temporal workflow id for progress queries and debugging. Empty until the workflow starts. */
    readonly workflow_id: string
    /** The `ReplayLens.lens_version` value at the moment the workflow ran. */
    readonly lens_version: number
    /** Snapshot of `ReplayLens.lens_config` at run time. Lens edits do not retroactively mutate observations. */
    readonly lens_config_snapshot: unknown
    /** Concrete model that ran the observation. */
    readonly model_used: string
    /** Concrete provider that ran the observation. */
    readonly provider_used: string
    /** Whether this observation came from the schedule or an on-demand request.

  * `schedule` - Schedule
  * `on_demand` - On demand */
    readonly triggered_by: ObservationTriggerEnumApi
    /** User who triggered an on-demand observation. Null for scheduled observations. */
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

export interface PatchedReplayLensApi {
    readonly id?: string
    /**
     * Human-readable lens name. Unique within the team.
     * @maxLength 255
     */
    name?: string
    /** Free-form description shown in the lens management UI. */
    description?: string
    /** What the lens does: monitor, classifier, scorer, summarizer, or indexer.

  * `monitor` - Monitor
  * `classifier` - Classifier
  * `scorer` - Scorer
  * `summarizer` - Summarizer
  * `indexer` - Indexer */
    lens_type?: LensTypeEnumApi
    /** Type-specific configuration. Always includes `prompt`; classifiers add `tags`, scorers add `scale`, etc. */
    lens_config?: unknown
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
    provider?: LensProviderEnumApi
    /** Concrete model to use for this lens.

  * `gemini-3-flash` - Gemini 3 Flash
  * `gemini-3-flash-lite` - Gemini 3 Flash Lite */
    model?: LensModelEnumApi
    /** When false, the reconciler removes the lens's Temporal schedule. On-demand triggers still work. */
    enabled?: boolean
    /** When true, the prompt is augmented with the Signal side mission and the lens emits PostHog Signals. */
    emits_signals?: boolean
    /** Increments on every config-changing save. Observations snapshot this value. */
    readonly lens_version?: number
    /** Watermark for the lens's last scheduled fire. Mirrors Temporal schedule state for recovery. */
    readonly last_swept_at?: string
    readonly created_at?: string
    /** User who created the lens. */
    readonly created_by?: UserBasicApi | null
    readonly updated_at?: string
}

/**
 * Body of POST /vision/lenses/{id}/observe/.
 */
export interface ObserveRequestApi {
    /**
     * ID of the session recording to apply the lens to.
     * @maxLength 128
     */
    session_id: string
}

/**
 * Async-accepted response for POST /vision/lenses/{id}/observe/.
 */
export interface ObserveResponseApi {
    /** Temporal workflow id for this lens application. Look up the resulting ReplayObservation via GET /vision/lenses/{id}/observations/?session_id=<session_id>. */
    workflow_id: string
}

export type VisionLensesListParams = {
    /**
     * Filter to lenses that emit Signals.
     */
    emits_signals?: boolean
    /**
     * Filter to enabled vs disabled lenses.
     */
    enabled?: boolean
    /**
 * Filter by lens type (monitor, classifier, scorer, summarizer, indexer).

* `monitor` - Monitor
* `classifier` - Classifier
* `scorer` - Scorer
* `summarizer` - Summarizer
* `indexer` - Indexer
 */
    lens_type?: VisionLensesListLensType
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
 * Sort lenses by name, created_at, updated_at, or lens_type. Prefix with `-` for descending.

* `name` - Name
* `-name` - Name (descending)
* `created_at` - Created at
* `-created_at` - Created at (descending)
* `updated_at` - Updated at
* `-updated_at` - Updated at (descending)
* `lens_type` - Lens type
* `-lens_type` - Lens type (descending)
 */
    order_by?: string[]
}

export type VisionLensesListLensType = (typeof VisionLensesListLensType)[keyof typeof VisionLensesListLensType]

export const VisionLensesListLensType = {
    Classifier: 'classifier',
    Indexer: 'indexer',
    Monitor: 'monitor',
    Scorer: 'scorer',
    Summarizer: 'summarizer',
} as const

export type VisionLensesObservationsListParams = {
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
 */
    status?: VisionLensesObservationsListStatus
    /**
 * Filter by trigger source (schedule or on_demand).

* `schedule` - Schedule
* `on_demand` - On demand
 */
    triggered_by?: VisionLensesObservationsListTriggeredBy
}

export type VisionLensesObservationsListStatus =
    (typeof VisionLensesObservationsListStatus)[keyof typeof VisionLensesObservationsListStatus]

export const VisionLensesObservationsListStatus = {
    Failed: 'failed',
    Pending: 'pending',
    Running: 'running',
    Succeeded: 'succeeded',
} as const

export type VisionLensesObservationsListTriggeredBy =
    (typeof VisionLensesObservationsListTriggeredBy)[keyof typeof VisionLensesObservationsListTriggeredBy]

export const VisionLensesObservationsListTriggeredBy = {
    OnDemand: 'on_demand',
    Schedule: 'schedule',
} as const
