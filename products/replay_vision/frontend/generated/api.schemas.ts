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
 * * `yes` - yes
 * * `no` - no
 * * `inconclusive` - inconclusive
 */
export type VerdictEnumApi = (typeof VerdictEnumApi)[keyof typeof VerdictEnumApi]

export const VerdictEnumApi = {
    Yes: 'yes',
    No: 'no',
    Inconclusive: 'inconclusive',
} as const

/**
 * The action's targeting predicate ("run this on…") applied when gathering observations. All keys
 * optional; this typed shape is the allowlist, so unknown input keys are dropped rather than persisted.
 */
export interface SelectionApi {
    /** Restrict to observations produced by these scanner IDs. Defaults to the bound scanner. */
    scanner_ids?: string[]
    /** Only run on monitor observations with one of these verdicts (yes/no/inconclusive). */
    verdict?: VerdictEnumApi[]
    /** Only run on classifier observations carrying any of these tags (fixed or freeform). */
    tags?: string[]
    /** Only run on scorer observations with a score at or above this value (inclusive). */
    min_score?: number
    /** Only run on scorer observations with a score at or below this value (inclusive). */
    max_score?: number
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
    /** Marks this action as the scanner's built-in daily digest, the one summary surfaced on the scanner overview. At most one digest per scanner. */
    is_scanner_digest?: boolean
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
    /** Targeting predicate: which of the scanner's observations this action runs on. */
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
    /** Marks this action as the scanner's built-in daily digest, the one summary surfaced on the scanner overview. At most one digest per scanner. */
    is_scanner_digest?: boolean
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
    /** Targeting predicate: which of the scanner's observations this action runs on. */
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
    /** 1-based reference number of this observation in the summary, stable across deletions. The synthesized report cites observations by this number (rendered like `[3]`), so consumers use it to resolve a citation to its observation. */
    readonly index: number
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
    /** Concrete model that ran the observation; historical rows may carry since-retired model ids. */
    model: string
    /** Concrete provider that ran the observation; historical rows may carry since-retired providers. */
    provider: string
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
 * * `retry` - Retry
 */
export type ObservationTriggerEnumApi = (typeof ObservationTriggerEnumApi)[keyof typeof ObservationTriggerEnumApi]

export const ObservationTriggerEnumApi = {
    Schedule: 'schedule',
    OnDemand: 'on_demand',
    Retry: 'retry',
} as const

/**
 * The team's shared judgement on whether the scanner scored this session correctly.
 */
export interface ReplayObservationLabelApi {
    /** True if the scanner scored this session correctly, false if not. */
    is_correct: boolean
    /**
     * Optional written context on the rating, for thumbs-up and thumbs-down alike: what the scanner got right or wrong, or what it should have concluded.
     * @maxLength 5000
     */
    feedback?: string
}

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
    /** Whether this observation came from the schedule, an on-demand request, or a retry of a failed observation.
     *
     * * `schedule` - Schedule
     * * `on_demand` - On demand
     * * `retry` - Retry */
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
     * Id of the preceding sibling observation for the same scanner (prev/next nav), honoring any list filters and ordering passed to retrieve; only set on retrieve, null at the start of the set.
     * @nullable
     */
    readonly previous_observation_id: string | null
    /**
     * Id of the following sibling observation for the same scanner (prev/next nav), honoring any list filters and ordering passed to retrieve; only set on retrieve, null at the end of the set.
     * @nullable
     */
    readonly next_observation_id: string | null
    /** The team's shared label on this observation (correct/incorrect + feedback), or null if unlabeled. */
    readonly label: ReplayObservationLabelApi | null
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

/**
 * Async-accepted response for POST /vision/scanners/{id}/observations/{id}/retry/.
 */
export interface RetryResponseApi {
    /** Temporal workflow id for the re-run. The retried observation row is deleted; look up its replacement via GET /vision/scanners/{id}/observations/?session_id=<session_id>. */
    workflow_id: string
}

export interface VisionQuotaApi {
    /**
     * Credits the org may spend per billing period (1 credit = $0.01). Null when billing has synced the product with no spend limit: uncapped.
     * @nullable
     */
    readonly credit_limit: number | null
    /** Credits spent this period: succeeded observations from the receipt ledger plus reserved in-flight observations. */
    readonly credits_used: number
    /**
     * `credit_limit - credits_used`, floored at 0. Null when uncapped.
     * @nullable
     */
    readonly remaining: number | null
    /** True when `credits_used >= credit_limit`; further observations are skipped until next period. Always false when uncapped. */
    readonly exhausted: boolean
    /** First moment of the current quota period (UTC). */
    readonly period_start: string
    /** First moment of the next quota period (UTC); the current period's exclusive upper bound. */
    readonly period_end: string
    /** Credit-weighted sum of enabled scanners' projected observations/month across the organization. Scanners without a computed estimate contribute 0. */
    readonly projected_monthly_credits: number
}

/**
 * * `focused` - Focused
 * * `balanced` - Balanced
 * * `comprehensive` - Comprehensive
 */
export type SamplingModeEnumApi = (typeof SamplingModeEnumApi)[keyof typeof SamplingModeEnumApi]

export const SamplingModeEnumApi = {
    Focused: 'focused',
    Balanced: 'balanced',
    Comprehensive: 'comprehensive',
} as const

/**
 * * `google` - Google
 */
export type ScannerProviderEnumApi = (typeof ScannerProviderEnumApi)[keyof typeof ScannerProviderEnumApi]

export const ScannerProviderEnumApi = {
    Google: 'google',
} as const

/**
 * * `gemini-2.5-flash` - Gemini 2.5 Flash
 * * `gemini-3-flash-preview` - Gemini 3 Flash
 * * `gemini-3.5-flash` - Gemini 3.5 Flash
 */
export type ScannerModelEnumApi = (typeof ScannerModelEnumApi)[keyof typeof ScannerModelEnumApi]

export const ScannerModelEnumApi = {
    Gemini25Flash: 'gemini-2.5-flash',
    Gemini3FlashPreview: 'gemini-3-flash-preview',
    Gemini35Flash: 'gemini-3.5-flash',
} as const

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
    /** Quality pre-filter applied before random sampling. focused = top sessions only, balanced = drops the lowest-quality, comprehensive = no filter (default).
     *
     * * `focused` - Focused
     * * `balanced` - Balanced
     * * `comprehensive` - Comprehensive */
    sampling_mode?: SamplingModeEnumApi
    /** LLM provider. v1 is Google-only.
     *
     * * `google` - Google */
    provider?: ScannerProviderEnumApi
    /** Concrete model to use for this scanner.
     *
     * * `gemini-2.5-flash` - Gemini 2.5 Flash
     * * `gemini-3-flash-preview` - Gemini 3 Flash
     * * `gemini-3.5-flash` - Gemini 3.5 Flash */
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
    /** Credits one observation by this scanner costs (1 credit = $0.01), derived from `model`. */
    readonly credits_per_observation: number
    /**
     * `estimated_monthly_observations` priced at `credits_per_observation`. Null until the estimate is first computed.
     * @nullable
     */
    readonly estimated_monthly_credits: number | null
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
    /** Quality pre-filter applied before random sampling. focused = top sessions only, balanced = drops the lowest-quality, comprehensive = no filter (default).
     *
     * * `focused` - Focused
     * * `balanced` - Balanced
     * * `comprehensive` - Comprehensive */
    sampling_mode?: SamplingModeEnumApi
    /** LLM provider. v1 is Google-only.
     *
     * * `google` - Google */
    provider?: ScannerProviderEnumApi
    /** Concrete model to use for this scanner.
     *
     * * `gemini-2.5-flash` - Gemini 2.5 Flash
     * * `gemini-3-flash-preview` - Gemini 3 Flash
     * * `gemini-3.5-flash` - Gemini 3.5 Flash */
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
    /** Credits one observation by this scanner costs (1 credit = $0.01), derived from `model`. */
    readonly credits_per_observation?: number
    /**
     * `estimated_monthly_observations` priced at `credits_per_observation`. Null until the estimate is first computed.
     * @nullable
     */
    readonly estimated_monthly_credits?: number | null
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

export interface ObservationLabelDayCountApi {
    /** Day (UTC) the observed sessions were scanned. */
    date: string
    /** Observations scanned this day labeled correct (thumbs up). */
    up: number
    /** Observations scanned this day labeled incorrect (thumbs down). */
    down: number
}

export interface ObservationVersionMarkerApi {
    /** First day (UTC) this prompt version produced observations. */
    date: string
    /** The scanner (prompt) version number. */
    version: number
    /** The prompt text this version ran with, taken from the observation run snapshots. */
    prompt: string
    /** Thumbs-up ratings on this version's observations. */
    up: number
    /** Thumbs-down ratings on this version's observations. */
    down: number
    /** Succeeded (ratable) observations this version produced, rated or not. */
    total: number
}

export interface ObservationLabelStatsApi {
    /** Observations in the filtered set labeled correct (thumbs up). */
    up_total: number
    /** Observations in the filtered set labeled incorrect (thumbs down). */
    down_total: number
    /** Daily label counts over the last `recent_days` days, bucketed by the day the session was scanned so the series tracks scanner quality over time. Days without labels are omitted. */
    by_day: ObservationLabelDayCountApi[]
    /** Daily label counts over the last `recent_days` days, bucketed by the day the rating was last set or changed: the team's rating activity. Days without rating changes are omitted. */
    by_rating_day: ObservationLabelDayCountApi[]
    /** Each scanner (prompt) version that produced observations (all-time), with its first day, prompt, and rating counts, for chart markers and the prompt version history. */
    version_markers: ObservationVersionMarkerApi[]
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
    /** Team label (thumbs up/down) aggregates over the filtered set. */
    labels: ObservationLabelStatsApi
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
 * * `pending` - Pending
 * * `applied` - Applied
 * * `dismissed` - Dismissed
 * * `superseded` - Superseded
 * * `no_change` - No change
 */
export type ReplayScannerPromptSuggestionStatusEnumApi =
    (typeof ReplayScannerPromptSuggestionStatusEnumApi)[keyof typeof ReplayScannerPromptSuggestionStatusEnumApi]

export const ReplayScannerPromptSuggestionStatusEnumApi = {
    Pending: 'pending',
    Applied: 'applied',
    Dismissed: 'dismissed',
    Superseded: 'superseded',
    NoChange: 'no_change',
} as const

export interface PromptEvaluationResultApi {
    /** The rated session that was re-run with the suggested prompt. */
    session_id: string
    /** The original rated observation the comparison is against. */
    observation_id: string
    /** The team's rating of the original output (thumbs up = true). */
    rated_correct: boolean
    /**
     * The original output's primary outcome.
     * @nullable
     */
    before: string | null
    /**
     * The suggested prompt's outcome for the same session. Null when the run errored or returned no discrete outcome (e.g. a classifier with no tags).
     * @nullable
     */
    after: string | null
    /** kept (up, unchanged), regressed (up, changed), fixed (down, changed), still_wrong (down, unchanged), or error. */
    outcome: string
    /**
     * Why this session's re-run failed, when it did.
     * @nullable
     */
    error: string | null
}

export interface PromptEvaluationSummaryApi {
    /** Thumbs-up sessions whose output is unchanged. */
    kept: number
    /** Thumbs-up sessions whose output changed. */
    regressed: number
    /** Thumbs-down sessions whose output changed. */
    fixed: number
    /** Thumbs-down sessions whose output is unchanged. */
    still_wrong: number
    /** Sessions whose re-run failed. */
    errors: number
}

export interface PromptSuggestionEvaluationApi {
    /** running, succeeded, or failed. */
    status: string
    /** When the evaluation started. */
    started_at: string
    /**
     * When the evaluation finished, if it has.
     * @nullable
     */
    finished_at: string | null
    /** How many rated sessions are being re-run. */
    total: number
    /** The rated set the evaluation ran against. */
    labels_fingerprint: string
    /** Per-session outcomes, in completion order. */
    results: PromptEvaluationResultApi[]
    /** Outcome counts. Null while the evaluation is running. */
    summary: PromptEvaluationSummaryApi | null
}

export interface ReplayScannerPromptSuggestionApi {
    readonly id: string
    /** pending (current), applied, dismissed, or superseded by a newer suggestion.
     *
     * * `pending` - Pending
     * * `applied` - Applied
     * * `dismissed` - Dismissed
     * * `superseded` - Superseded
     * * `no_change` - No change */
    readonly status: ReplayScannerPromptSuggestionStatusEnumApi
    /** The full rewritten prompt, ready to apply to the scanner. */
    readonly suggested_prompt: string
    /** The scanner prompt this suggestion was generated against, for diffing. */
    readonly base_prompt: string
    /** What the rewrite changed and why, grounded in the ratings. */
    readonly rationale: string
    /** Thumbs-up ratings the suggestion was based on. */
    readonly based_on_up: number
    /** Thumbs-down ratings the suggestion was based on. */
    readonly based_on_down: number
    /** The scanner version whose prompt this suggestion was generated against. */
    readonly scanner_version: number
    readonly created_at: string
    /** User who requested this suggestion; null for automatic refreshes. */
    readonly created_by: UserBasicApi | null
    /** @nullable */
    readonly applied_at: string | null
    /** User who applied this suggestion to the scanner; null unless applied. */
    readonly applied_by: UserBasicApi | null
    /** Test-before-apply results: the suggested prompt re-run against rated sessions. */
    readonly evaluation: PromptSuggestionEvaluationApi | null
}

export interface PaginatedReplayScannerPromptSuggestionListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ReplayScannerPromptSuggestionApi[]
}

export interface EvaluatePromptSuggestionRequestApi {
    /**
     * How many rated sessions to re-run, thumbs-down prioritized. Each successful re-run consumes one observation of the monthly Replay Vision quota. Defaults to `evaluation_session_cap`, which is also the maximum.
     * @minimum 1
     * @maximum 10
     */
    session_limit?: number
}

export interface CurrentPromptSuggestionApi {
    /** The newest suggestion for this scanner, or null when none has been generated yet. */
    suggestion: ReplayScannerPromptSuggestionApi | null
    /** True when the team's ratings changed since the newest suggestion was generated. */
    stale: boolean
    /** Number of rated (thumbs up or down) succeeded observations available to generate from. */
    rated_count: number
    /** Maximum rated sessions one suggestion test re-runs. Each successful re-run consumes one observation of the monthly Replay Vision quota. */
    evaluation_session_cap: number
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
    /** Quality pre-filter applied to the matched-session count, mirroring the sweep's candidate query. Defaults to comprehensive (no filter).
     *
     * * `focused` - Focused
     * * `balanced` - Balanced
     * * `comprehensive` - Comprehensive */
    sampling_mode?: SamplingModeEnumApi
    /**
     * The scanner being edited, excluded from `other_enabled_scanners_monthly_credits` so its stored estimate isn't double-counted in the forecast. Omit (or null) when estimating a brand-new scanner.
     * @nullable
     */
    scanner_id?: string | null
    /** Proposed model; determines `credits_per_observation` in the response.
     *
     * * `gemini-2.5-flash` - Gemini 2.5 Flash
     * * `gemini-3-flash-preview` - Gemini 3 Flash
     * * `gemini-3.5-flash` - Gemini 3.5 Flash */
    model?: ScannerModelEnumApi
}

/**
 * Forward-looking volume and credit-cost estimate for a proposed scanner.
 */
export interface EstimateResponseApi {
    /** Distinct sessions matching the query within the 30-day lookback, after the sampling_mode quality filter but before random sampling. */
    matched_sessions_in_window: number
    /** Lookback window the estimate is based on. Normally 30; smaller when the team has fewer days of recordings. */
    window_days: number
    /** Projected monthly observations: quality-filtered matched sessions scaled to 30 days, times sampling_rate. */
    estimated_observations_per_month: number
    /** Credits one observation costs at the proposed `model` (1 credit = $0.01). */
    credits_per_observation: number
    /** `estimated_observations_per_month` priced at `credits_per_observation`. */
    estimated_credits_per_month: number
    /** Credit-weighted projected monthly spend of the org's other enabled scanners (excluding `scanner_id`), from their cached estimates. Read from the same snapshot as this estimate so the forecast can't double-count the edited scanner. */
    other_enabled_scanners_monthly_credits: number
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
     * Sort observations. Plain keys: created_at, started_at, completed_at, status, recording_subject_email. JSONB keys: result_score (scorer), result_verdict (monitor), result_confidence, scanner_version. Prefix with `-` for descending; nullable keys sort nulls last either way.
     */
    order_by?: string
    /**
     * Session recording id to return observations for.
     */
    session_id: string
}

export type VisionObservationsRetrieveParams = {
    /**
     * When true, return only observations that have a shared label (thumbs up or down); when false, only unlabeled observations.
     */
    labeled?: string
    /**
     * Sort observations. Plain keys: created_at, started_at, completed_at, status, recording_subject_email. JSONB keys: result_score (scorer), result_verdict (monitor), result_confidence, scanner_version. Prefix with `-` for descending; nullable keys sort nulls last either way.
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
     * Filter by trigger source (schedule, on_demand, or retry). Accepts a comma-separated list.
     */
    triggered_by?: string
    /**
     * Filter monitor observations by verdict. Accepts a comma-separated list (e.g. `yes,inconclusive`).
     */
    verdict?: string
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
     * When true, return only observations that have a shared label (thumbs up or down); when false, only unlabeled observations.
     */
    labeled?: boolean
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Sort observations. Plain keys: created_at, started_at, completed_at, status, recording_subject_email. JSONB keys: result_score (scorer), result_verdict (monitor), result_confidence, scanner_version. Prefix with `-` for descending; nullable keys sort nulls last either way.
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
     * Filter by trigger source (schedule, on_demand, or retry). Accepts a comma-separated list.
     */
    triggered_by?: string
    /**
     * Filter monitor observations by verdict. Accepts a comma-separated list (e.g. `yes,inconclusive`).
     */
    verdict?: string
}

export type VisionScannersObservationsRetrieveParams = {
    /**
     * When true, return only observations that have a shared label (thumbs up or down); when false, only unlabeled observations.
     */
    labeled?: string
    /**
     * Sort observations. Plain keys: created_at, started_at, completed_at, status, recording_subject_email. JSONB keys: result_score (scorer), result_verdict (monitor), result_confidence, scanner_version. Prefix with `-` for descending; nullable keys sort nulls last either way.
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
     * Filter by trigger source (schedule, on_demand, or retry). Accepts a comma-separated list.
     */
    triggered_by?: string
    /**
     * Filter monitor observations by verdict. Accepts a comma-separated list (e.g. `yes,inconclusive`).
     */
    verdict?: string
}

export type VisionScannersObservationsStatsRetrieveParams = {
    /**
     * When true, return only observations that have a shared label (thumbs up or down); when false, only unlabeled observations.
     */
    labeled?: string
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
     * Filter by trigger source (schedule, on_demand, or retry). Accepts a comma-separated list.
     */
    triggered_by?: string
    /**
     * Filter monitor observations by verdict. Accepts a comma-separated list (e.g. `yes,inconclusive`).
     */
    verdict?: string
}

export type VisionScannersPromptSuggestionsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
