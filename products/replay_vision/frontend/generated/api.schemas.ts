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
 * * `schedule` - Schedule
 * * `threshold` - Threshold
 */
export type TriggerTypeEnumApi = (typeof TriggerTypeEnumApi)[keyof typeof TriggerTypeEnumApi]

export const TriggerTypeEnumApi = {
    Schedule: 'schedule',
    Threshold: 'threshold',
} as const

/**
 * * `group_summary` - Group summary
 * * `per_observation` - Per observation
 */
export type VisionActionModeEnumApi = (typeof VisionActionModeEnumApi)[keyof typeof VisionActionModeEnumApi]

export const VisionActionModeEnumApi = {
    GroupSummary: 'group_summary',
    PerObservation: 'per_observation',
} as const

/**
 * Schedule trigger parameters. Threshold triggers are reserved and rejected at the API for now.
 */
export interface TriggerConfigApi {
    /** iCal RRULE string controlling the schedule cadence (no DTSTART — the start is managed separately). */
    rrule?: string
    /** IANA timezone name the RRULE is expanded in, e.g. 'Europe/Prague'. Defaults to 'UTC'. */
    timezone?: string
}

/**
 * Observation filter applied at synthesis time. All keys optional; this typed shape is the
 * allowlist, so unknown input keys are dropped rather than persisted.
 */
export interface SelectionApi {
    /** Filter observations by scanner type (monitor/classifier/scorer/summarizer). */
    scanner_type?: string
    /** Restrict to observations produced by these scanner IDs. */
    scanner_ids?: string[]
    /** Filter to observations with this monitor verdict. */
    verdict?: string
    /** Filter to observations carrying any of these classifier tags. */
    tags?: string[]
    /** Lower bound (inclusive) on scorer score. */
    min_score?: number
    /** Upper bound (inclusive) on scorer score. */
    max_score?: number
    /** Filter to observations with this processing status. */
    status?: string
    /** Lookback window in days for the observations gathered at synthesis time. */
    window_days?: number
}

/**
 * Options for the group-summary synthesis step.
 */
export interface SynthesisConfigApi {
    /**
     * Free-form guidance steering how the group summary is written.
     * @maxLength 500
     */
    prompt_guide?: string
}

/**
 * * `slack` - Slack
 */
export type DeliveryTargetTypeEnumApi = (typeof DeliveryTargetTypeEnumApi)[keyof typeof DeliveryTargetTypeEnumApi]

export const DeliveryTargetTypeEnumApi = {
    Slack: 'slack',
} as const

/**
 * A single delivery destination. MVP supports Slack only.
 */
export interface DeliveryTargetApi {
    /** Destination channel type. MVP supports 'slack' only.
     *
     * * `slack` - Slack */
    type: DeliveryTargetTypeEnumApi
    /** ID of the Slack Integration on this team used to deliver the summary. */
    integration_id: number
    /** Slack channel ID or name the summary is posted to. */
    channel: string
}

/**
 * * `engineering` - Engineering
 * * `data` - Data
 * * `product` - Product Management
 * * `founder` - Founder
 * * `leadership` - Leadership
 * * `marketing` - Marketing
 * * `sales` - Sales / Success
 * * `other` - Other
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

export interface VisionActionApi {
    readonly id: string
    /**
     * Human-readable action name. Unique within the team.
     * @maxLength 255
     */
    name: string
    /** Scanner whose observations this action operates on. Must belong to the same team. */
    scanner: string
    /** When false, the scheduler skips this action. */
    enabled?: boolean
    /** What fires the action. MVP supports 'schedule' only.
     *
     * * `schedule` - Schedule
     * * `threshold` - Threshold */
    trigger_type?: TriggerTypeEnumApi
    /** What the action produces. MVP supports 'group_summary' only.
     *
     * * `group_summary` - Group summary
     * * `per_observation` - Per observation */
    mode?: VisionActionModeEnumApi
    /** Trigger parameters. For schedule triggers: {rrule, timezone}. */
    trigger_config?: TriggerConfigApi
    /** Observation filter applied at synthesis time. */
    selection?: SelectionApi
    /** Synthesis options for the group summary, e.g. {prompt_guide}. */
    synthesis_config?: SynthesisConfigApi
    /** List of delivery destinations the synthesized summary is sent to. */
    delivery_config?: DeliveryTargetApi[]
    /**
     * Computed next fire time for schedule triggers; the scheduler scans this.
     * @nullable
     */
    readonly next_run_at: string | null
    /**
     * Timestamp of the most recent run, or null if it has never run.
     * @nullable
     */
    readonly last_run_at: string | null
    /**
     * ID of the delivery flow provisioned for this action. Null until delivery is wired up.
     * @nullable
     */
    readonly hog_flow_id: string | null
    readonly created_at: string
    /** User who created the action. */
    readonly created_by: UserBasicApi | null
    readonly updated_at: string
}

export interface PaginatedVisionActionListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: VisionActionApi[]
}

export interface PatchedVisionActionApi {
    readonly id?: string
    /**
     * Human-readable action name. Unique within the team.
     * @maxLength 255
     */
    name?: string
    /** Scanner whose observations this action operates on. Must belong to the same team. */
    scanner?: string
    /** When false, the scheduler skips this action. */
    enabled?: boolean
    /** What fires the action. MVP supports 'schedule' only.
     *
     * * `schedule` - Schedule
     * * `threshold` - Threshold */
    trigger_type?: TriggerTypeEnumApi
    /** What the action produces. MVP supports 'group_summary' only.
     *
     * * `group_summary` - Group summary
     * * `per_observation` - Per observation */
    mode?: VisionActionModeEnumApi
    /** Trigger parameters. For schedule triggers: {rrule, timezone}. */
    trigger_config?: TriggerConfigApi
    /** Observation filter applied at synthesis time. */
    selection?: SelectionApi
    /** Synthesis options for the group summary, e.g. {prompt_guide}. */
    synthesis_config?: SynthesisConfigApi
    /** List of delivery destinations the synthesized summary is sent to. */
    delivery_config?: DeliveryTargetApi[]
    /**
     * Computed next fire time for schedule triggers; the scheduler scans this.
     * @nullable
     */
    readonly next_run_at?: string | null
    /**
     * Timestamp of the most recent run, or null if it has never run.
     * @nullable
     */
    readonly last_run_at?: string | null
    /**
     * ID of the delivery flow provisioned for this action. Null until delivery is wired up.
     * @nullable
     */
    readonly hog_flow_id?: string | null
    readonly created_at?: string
    /** User who created the action. */
    readonly created_by?: UserBasicApi | null
    readonly updated_at?: string
}

/**
 * * `running` - Running
 * * `completed` - Completed
 * * `failed` - Failed
 * * `skipped` - Skipped
 */
export type VisionActionRunStatusEnumApi =
    (typeof VisionActionRunStatusEnumApi)[keyof typeof VisionActionRunStatusEnumApi]

export const VisionActionRunStatusEnumApi = {
    Running: 'running',
    Completed: 'completed',
    Failed: 'failed',
    Skipped: 'skipped',
} as const

/**
 * Lightweight run row for the per-action run list (no report body — that's fetched on retrieve).
 */
export interface VisionActionRunListApi {
    readonly id: string
    /** Run outcome: running, completed, failed, or skipped.
     *
     * * `running` - Running
     * * `completed` - Completed
     * * `failed` - Failed
     * * `skipped` - Skipped */
    readonly status: VisionActionRunStatusEnumApi
    /**
     * The scheduled fire time this run was claimed for.
     * @nullable
     */
    readonly scheduled_at: string | null
    /** Number of observations that fed this run's summary. */
    readonly observation_count: number
    /**
     * Short human-readable reason a run skipped or failed; null on success.
     * @nullable
     */
    readonly error_reason: string | null
    readonly created_at: string
    readonly updated_at: string
}

export interface PaginatedVisionActionRunListListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: VisionActionRunListApi[]
}

/**
 * One recording an action run included in its summary — the 'recordings included' list on the run detail view.
 */
export interface RunObservationApi {
    /** Observation id; links to the observation detail view. */
    readonly id: string
    /** Session recording id this observation was made on. */
    readonly session_id: string
    /**
     * Email of the person in the recorded session, captured at scan time; null if unidentified.
     * @nullable
     */
    readonly recording_subject_email: string | null
    /**
     * Short title from the observation's summary; null if the observation had none.
     * @nullable
     */
    readonly title: string | null
    /** When the observation was produced. */
    readonly created_at: string
}

/**
 * Full run detail: the list fields plus the synthesized report and the recordings it summarized.
 */
export interface VisionActionRunApi {
    readonly id: string
    /** Run outcome: running, completed, failed, or skipped.
     *
     * * `running` - Running
     * * `completed` - Completed
     * * `failed` - Failed
     * * `skipped` - Skipped */
    readonly status: VisionActionRunStatusEnumApi
    /**
     * The scheduled fire time this run was claimed for.
     * @nullable
     */
    readonly scheduled_at: string | null
    /** Number of observations that fed this run's summary. */
    readonly observation_count: number
    /**
     * Short human-readable reason a run skipped or failed; null on success.
     * @nullable
     */
    readonly error_reason: string | null
    readonly created_at: string
    readonly updated_at: string
    /** The synthesized group-summary report in Markdown. Empty until a run completes successfully. */
    readonly synthesized_markdown: string
    /** Recordings this run included in its summary, in summary order. Empty for runs recorded before this was tracked, and for skipped/failed runs. */
    readonly observations: readonly RunObservationApi[]
}

/**
 * * `pending` - Pending
 * * `running` - Running
 * * `succeeded` - Succeeded
 * * `failed` - Failed
 * * `ineligible` - Ineligible
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
 * * `classifier` - Classifier
 * * `scorer` - Scorer
 * * `summarizer` - Summarizer
 */
export type ScannerTypeEnumApi = (typeof ScannerTypeEnumApi)[keyof typeof ScannerTypeEnumApi]

export const ScannerTypeEnumApi = {
    Monitor: 'monitor',
    Classifier: 'classifier',
    Scorer: 'scorer',
    Summarizer: 'summarizer',
} as const

/**
 * * `gemini-3-flash-preview` - Gemini 3 Flash
 * * `gemini-3.1-flash-lite-preview` - Gemini 3 Flash Lite
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
    /** Scanner type (monitor, classifier, scorer, summarizer) at run time.
     *
     * * `monitor` - Monitor
     * * `classifier` - Classifier
     * * `scorer` - Scorer
     * * `summarizer` - Summarizer */
    scanner_type: ScannerTypeEnumApi
    /** The `ReplayScanner.scanner_version` value at the moment the workflow ran. */
    scanner_version: number
    /** Concrete model that ran the observation.
     *
     * * `gemini-3-flash-preview` - Gemini 3 Flash
     * * `gemini-3.1-flash-lite-preview` - Gemini 3 Flash Lite */
    model: ScannerModelEnumApi
    /** Concrete provider that ran the observation.
     *
     * * `google` - Google */
    provider: ScannerProviderEnumApi
    /** Whether the observation was run with Signal emission enabled. */
    emits_signals: boolean
    /** Scanner-type-specific configuration at run time (prompt, tags, scale, etc.). */
    scanner_config: unknown
}

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
}

/**
 * * `schedule` - Schedule
 * * `on_demand` - On demand
 */
export type ObservationTriggerEnumApi = (typeof ObservationTriggerEnumApi)[keyof typeof ObservationTriggerEnumApi]

export const ObservationTriggerEnumApi = {
    Schedule: 'schedule',
    OnDemand: 'on_demand',
} as const

export interface ReplayObservationApi {
    readonly id: string
    /** The scanner that produced this observation. */
    readonly scanner_id: string
    /** Session recording id this scanner was applied to. */
    readonly session_id: string
    /** Observation status (pending, running, succeeded, failed, ineligible).
     *
     * * `pending` - Pending
     * * `running` - Running
     * * `succeeded` - Succeeded
     * * `failed` - Failed
     * * `ineligible` - Ineligible */
    readonly status: ObservationStatusEnumApi
    /** Populated on terminal non-success statuses; formatted as `kind:human-readable message`. For `ineligible`, kind is one of no_recording / too_short / too_inactive / too_long / no_events. For `failed`, kind is one of provider_transient / provider_rejected / rasterization_failed / validation_failed / internal_error / orphaned. */
    readonly error_reason: string
    /** Temporal workflow id for progress queries and debugging. Empty until the workflow starts. */
    readonly workflow_id: string
    /** Frozen view of the scanner at run time; scanner edits do not retroactively mutate this observation. */
    readonly scanner_snapshot: ScannerSnapshotApi | null
    /** Result data persisted on success; null until the observation succeeds. */
    readonly scanner_result: ScannerResultApi | null
    /** Whether this observation came from the schedule or an on-demand request.
     *
     * * `schedule` - Schedule
     * * `on_demand` - On demand */
    readonly triggered_by: ObservationTriggerEnumApi
    /** User who triggered an on-demand observation; null for scheduled observations. */
    readonly triggered_by_user: UserBasicApi | null
    /**
     * Distinct id of the person in the recorded session (the subject being watched); null if unknown.
     * @nullable
     */
    readonly distinct_id: string | null
    /**
     * Email of the person in the recorded session (the subject being watched, not the user who triggered the observation), captured at scan time. Null when the session had no identified person.
     * @nullable
     */
    readonly recording_subject_email: string | null
    /**
     * Id of the newer sibling observation for the same scanner (prev/next nav); only set on retrieve, null at the start.
     * @nullable
     */
    readonly previous_observation_id: string | null
    /**
     * Id of the older sibling observation for the same scanner (prev/next nav); only set on retrieve, null at the end.
     * @nullable
     */
    readonly next_observation_id: string | null
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

export interface VisionQuotaApi {
    /** Total observations the org may complete per calendar month. */
    readonly monthly_quota: number
    /** Observations created this month that are in flight or have succeeded, counted against the quota. */
    readonly usage_this_month: number
    /** `monthly_quota - usage_this_month`, floored at 0. */
    readonly remaining: number
    /** True when `usage_this_month >= monthly_quota`; further observations are skipped until next period. */
    readonly exhausted: boolean
    /** First moment of the current quota period (UTC). */
    readonly period_start: string
    /** First moment of the next quota period (UTC); the current period's exclusive upper bound. */
    readonly period_end: string
    /** Sum of enabled scanners' projected observations/month across the organization. Scanners without a computed estimate contribute 0. */
    readonly projected_monthly_observations: number
}

export interface ReplayScannerApi {
    readonly id: string
    /**
     * Human-readable scanner name. Unique within the team.
     * @maxLength 255
     */
    name: string
    /**
     * Free-form description shown in the scanner management UI.
     * @maxLength 1000
     */
    description?: string
    /** What the scanner does: monitor, classifier, scorer, or summarizer.
     *
     * * `monitor` - Monitor
     * * `classifier` - Classifier
     * * `scorer` - Scorer
     * * `summarizer` - Summarizer */
    scanner_type: ScannerTypeEnumApi
    /** Type-specific configuration. All scanner types require `prompt`; monitors add optional `allow_inconclusive`, classifiers add `tags`, scorers add `scale`, summarizers add optional `length`. */
    scanner_config: unknown
    /** Persisted `RecordingsQuery` shape used to pick candidate sessions. `date_from`/`date_to` are stripped on save — the schedule controls time, not the user. */
    query?: unknown
    /**
     * 0..1 random downsample applied after the query matches. Defaults to 1.0 (no downsampling). Use exactly 0 to pause scanning; non-zero rates below 0.0001 (0.01%) are rejected as below the sampling precision.
     * @minimum 0
     * @maximum 1
     */
    sampling_rate?: number
    /** LLM provider. v1 is Google-only.
     *
     * * `google` - Google */
    provider?: ScannerProviderEnumApi
    /** Concrete model to use for this scanner.
     *
     * * `gemini-3-flash-preview` - Gemini 3 Flash
     * * `gemini-3.1-flash-lite-preview` - Gemini 3 Flash Lite */
    model: ScannerModelEnumApi
    /** When false, the reconciler removes the scanner's Temporal schedule. On-demand triggers still work. */
    enabled?: boolean
    /** When true, the prompt is augmented with the Signal side mission and the scanner emits PostHog Signals. */
    emits_signals?: boolean
    /** Increments on every config-changing save. Observations snapshot this value. */
    readonly scanner_version: number
    /**
     * Latest projected observations/month for this scanner. Null until first computed.
     * @nullable
     */
    readonly estimated_monthly_observations: number | null
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
    /**
     * Free-form description shown in the scanner management UI.
     * @maxLength 1000
     */
    description?: string
    /** What the scanner does: monitor, classifier, scorer, or summarizer.
     *
     * * `monitor` - Monitor
     * * `classifier` - Classifier
     * * `scorer` - Scorer
     * * `summarizer` - Summarizer */
    scanner_type?: ScannerTypeEnumApi
    /** Type-specific configuration. All scanner types require `prompt`; monitors add optional `allow_inconclusive`, classifiers add `tags`, scorers add `scale`, summarizers add optional `length`. */
    scanner_config?: unknown
    /** Persisted `RecordingsQuery` shape used to pick candidate sessions. `date_from`/`date_to` are stripped on save — the schedule controls time, not the user. */
    query?: unknown
    /**
     * 0..1 random downsample applied after the query matches. Defaults to 1.0 (no downsampling). Use exactly 0 to pause scanning; non-zero rates below 0.0001 (0.01%) are rejected as below the sampling precision.
     * @minimum 0
     * @maximum 1
     */
    sampling_rate?: number
    /** LLM provider. v1 is Google-only.
     *
     * * `google` - Google */
    provider?: ScannerProviderEnumApi
    /** Concrete model to use for this scanner.
     *
     * * `gemini-3-flash-preview` - Gemini 3 Flash
     * * `gemini-3.1-flash-lite-preview` - Gemini 3 Flash Lite */
    model?: ScannerModelEnumApi
    /** When false, the reconciler removes the scanner's Temporal schedule. On-demand triggers still work. */
    enabled?: boolean
    /** When true, the prompt is augmented with the Signal side mission and the scanner emits PostHog Signals. */
    emits_signals?: boolean
    /** Increments on every config-changing save. Observations snapshot this value. */
    readonly scanner_version?: number
    /**
     * Latest projected observations/month for this scanner. Null until first computed.
     * @nullable
     */
    readonly estimated_monthly_observations?: number | null
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

export interface ObservationStatusCountsApi {
    /** Total observations in the filtered set. */
    total: number
    /** Observations with `status=succeeded`. */
    succeeded: number
    /** Observations with `status=failed`. */
    failed: number
    /** Observations with `status=ineligible`. */
    ineligible: number
    /** Observations not yet in a terminal status. */
    in_flight: number
    /**
     * Percentage of (succeeded + failed) observations that succeeded; ineligible rows are excluded. Null when no observations have completed.
     * @nullable
     */
    success_rate: number | null
}

export interface CoverageStatsApi {
    /** Distinct sessions observed within the last `recent_days` days. */
    recent_sessions: number
    /** Distinct sessions observed overall. */
    total_sessions: number
    /** Window size in days used for `recent_sessions`. */
    recent_days: number
}

export interface MonitorStatsApi {
    /** Succeeded observations whose verdict was `yes`. */
    yes_total: number
    /** Succeeded observations whose verdict was `no`. */
    no_total: number
    /** Succeeded observations whose verdict was `inconclusive`. */
    inconclusive_total: number
}

export interface TagCountApi {
    /** The tag value. */
    tag: string
    /** Number of succeeded observations carrying this tag. */
    count: number
}

export interface ClassifierStatsApi {
    /** Top fixed-vocabulary tags by emission count. */
    fixed_ranked: TagCountApi[]
    /** Top freeform tags by emission count. */
    freeform_ranked: TagCountApi[]
    /** Succeeded observations that emitted at least one tag. */
    total_with_tags: number
}

export interface ScorerSummaryApi {
    /** Minimum observed score. */
    min: number
    /** 25th-percentile score. */
    p25: number
    /** Median score. */
    median: number
    /** Mean score. */
    mean: number
    /** 75th-percentile score. */
    p75: number
    /** Maximum observed score. */
    max: number
    /** Number of scored observations summarized. */
    count: number
}

export interface ScorerHistogramApi {
    /** Bucket labels (one per histogram bar) spanning the scanner's configured scale. */
    labels: string[]
    /** Observation count per bucket; same length as `labels`. */
    counts: number[]
}

export interface ScorerStatsApi {
    /** Score quantile summary; null when no observations have been scored. */
    summary: ScorerSummaryApi | null
    /** Score histogram; null when no observations have been scored. */
    histogram: ScorerHistogramApi | null
}

export interface ObservationStatsApi {
    /** Counts of observations by terminal status. */
    status_counts: ObservationStatusCountsApi
    /** Session-level scanner coverage. */
    coverage: CoverageStatsApi
    /** All distinct tags (fixed + freeform) emitted by succeeded observations in the filtered set. */
    available_tags: string[]
    /** Monitor-type aggregates; null when the scanner is not a monitor. */
    monitor: MonitorStatsApi | null
    /** Classifier-type aggregates; null when the scanner is not a classifier. */
    classifier: ClassifierStatsApi | null
    /** Scorer-type aggregates; null when the scanner is not a scorer. */
    scorer: ScorerStatsApi | null
}

/**
 * Distinct creators across all scanners on the team — feeds the `Created by` filter dropdown.
 */
export interface ScannerCreatorsResponseApi {
    /** Users who created at least one scanner on this team. Returned regardless of pagination state so the dropdown stays stable across pages. */
    creators: UserBasicApi[]
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
    /**
     * The scanner being edited, excluded from `other_enabled_scanners_monthly` so its stored estimate isn't double-counted in the forecast. Omit (or null) when estimating a brand-new scanner.
     * @nullable
     */
    scanner_id?: string | null
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
    /** Summed projected monthly observations of the org's other enabled scanners (excluding `scanner_id`), from their cached estimates. Read from the same snapshot as this estimate so the forecast can't double-count the edited scanner. */
    other_enabled_scanners_monthly: number
    /** Sampling rate applied to the projection. Echoed from the request. */
    sampling_rate: number
}

/**
 * Per-scanner-type count of enabled vs total scanners.
 */
export interface ScannerTypeStatsApi {
    /** Number of enabled scanners of this type. */
    enabled: number
    /** Number of scanners of this type (enabled + disabled). */
    total: number
}

/**
 * One `ScannerTypeStats` per scanner type — explicit fields give callers a typed shape, not `Record<string, …>`.
 */
export interface ScannerStatsByTypeApi {
    monitor: ScannerTypeStatsApi
    classifier: ScannerTypeStatsApi
    scorer: ScannerTypeStatsApi
    summarizer: ScannerTypeStatsApi
}

/**
 * Team-wide scanner counts independent of any list-filter state.
 */
export interface ScannerStatsResponseApi {
    /** Total scanners on the team. */
    total: number
    /** Number of enabled scanners on the team. */
    enabled: number
    /** Per-scanner-type breakdown (monitor / classifier / scorer / summarizer). */
    by_type: ScannerStatsByTypeApi
}

/**
 * Body of POST /vision/scanners/suggest_tags/ — the classifier config currently being edited.
 */
export interface SuggestTagsRequestApi {
    /**
     * The classifier's instruction prompt — the single dimension to categorize sessions by.
     * @maxLength 10000
     */
    prompt: string
    /**
     * The current tag vocabulary, so suggestions never duplicate a tag the user already has.
     * @maxItems 200
     * @items.maxLength 200
     */
    tags?: string[]
    /** Whether the classifier assigns multiple tags per session. */
    multi_label?: boolean
    /** Whether the classifier may emit tags outside the fixed vocabulary. */
    allow_freeform_tags?: boolean
    /**
     * Existing scanner to ground suggestions in its own observations (the tags and reasoning it has already produced on real recordings). Omit for an unsaved scanner.
     * @nullable
     */
    scanner_id?: string | null
}

/**
 * * `observed` - observed
 * * `product` - product
 * * `prompt` - prompt
 */
export type TagSuggestionSourceEnumApi = (typeof TagSuggestionSourceEnumApi)[keyof typeof TagSuggestionSourceEnumApi]

export const TagSuggestionSourceEnumApi = {
    Observed: 'observed',
    Product: 'product',
    Prompt: 'prompt',
} as const

/**
 * One grounded tag suggestion.
 */
export interface TagSuggestionApi {
    /** Suggested tag to add to the vocabulary, normalized to lowercase. */
    tag: string
    /** One sentence explaining the specific evidence this tag is grounded in. */
    rationale: string
    /** Primary grounding: observed=a category this scanner already emitted on recordings; product=the org's events/screens; prompt=the scanner's stated goal.
     *
     * * `observed` - observed
     * * `product` - product
     * * `prompt` - prompt */
    source: TagSuggestionSourceEnumApi
}

/**
 * Grounded tag suggestions for the classifier config editor.
 */
export interface SuggestTagsResponseApi {
    /** Suggested tags to add, most relevant first. May be empty when the evidence is too thin. */
    suggestions: TagSuggestionApi[]
}

export type VisionActionsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Filter to the actions belonging to one scanner.
     */
    scanner?: string
}

export type VisionActionsRunsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
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
     * Sort observations. Plain keys: created_at, started_at, completed_at, status, recording_subject_email. JSONB keys: result_score (scorer), result_verdict (monitor), scanner_version. Prefix with `-` for descending; nullable keys sort nulls last either way.
     */
    order_by?: string
    /**
     * Session recording id to return observations for.
     */
    session_id: string
}

export type VisionScannersListParams = {
    /**
     * Filter to scanners created by the given user IDs (comma-separated).
     */
    created_by?: string
    /**
     * Filter to scanners that emit Signals.
     */
    emits_signals?: boolean
    /**
     * Filter by enabled state. Accepts a comma-separated list of `enabled`/`disabled`.
     */
    enabled?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Sort scanners by name, created_at, updated_at, scanner_type, enabled, sampling_rate, or created_by. Prefix with `-` for descending.
     */
    order_by?: string
    /**
     * Filter by scanner type (monitor, classifier, scorer, summarizer). Accepts a comma-separated list.
     */
    scanner_type?: string
    /**
     * Case-insensitive substring match across name, description, and the prompt in scanner_config.
     */
    search?: string
}

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
     * Sort observations. Plain keys: created_at, started_at, completed_at, status, recording_subject_email. JSONB keys: result_score (scorer), result_verdict (monitor), scanner_version. Prefix with `-` for descending; nullable keys sort nulls last either way.
     */
    order_by?: string
    /**
     * Filter to observations whose recording subject email contains this value (case-insensitive).
     */
    recording_subject?: string
    /**
     * Filter to observations of one or more session recordings. Accepts a comma-separated list.
     */
    session_id?: string
    /**
     * Filter by observation status. Accepts a comma-separated list.
     */
    status?: string
    /**
     * Filter classifier observations whose fixed or freeform tags include any of the given values (comma-separated). Matches if the tag appears in either `tags` or `tags_freeform`.
     */
    tags?: string
    /**
     * Filter by trigger source (schedule or on_demand). Accepts a comma-separated list.
     */
    triggered_by?: string
    /**
     * Filter monitor observations by verdict. Accepts a comma-separated list (e.g. `yes,inconclusive`).
     */
    verdict?: string
}

export type VisionScannersObservationsStatsRetrieveParams = {
    /**
     * Window size in days for the coverage `recent_sessions` count. Clamped to [1, 365]. Defaults to 14 when omitted.
     */
    recent_days?: number
    /**
     * Filter to observations whose recording subject email contains this value (case-insensitive).
     */
    recording_subject?: string
    /**
     * Filter to observations of one or more session recordings. Accepts a comma-separated list.
     */
    session_id?: string
    /**
     * Filter by observation status. Accepts a comma-separated list.
     */
    status?: string
    /**
     * Filter classifier observations whose fixed or freeform tags include any of the given values (comma-separated). Matches if the tag appears in either `tags` or `tags_freeform`.
     */
    tags?: string
    /**
     * Filter by trigger source (schedule or on_demand). Accepts a comma-separated list.
     */
    triggered_by?: string
    /**
     * Filter monitor observations by verdict. Accepts a comma-separated list (e.g. `yes,inconclusive`).
     */
    verdict?: string
}
