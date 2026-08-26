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
export type VisionActionTriggerTypeEnumApi =
    (typeof VisionActionTriggerTypeEnumApi)[keyof typeof VisionActionTriggerTypeEnumApi]

export const VisionActionTriggerTypeEnumApi = {
    Schedule: 'schedule',
    Threshold: 'threshold',
} as const

/**
 * * `group_summary` - Group summary
 * * `alert` - Alert
 * * `per_observation` - Per observation
 */
export type VisionActionModeEnumApi = (typeof VisionActionModeEnumApi)[keyof typeof VisionActionModeEnumApi]

export const VisionActionModeEnumApi = {
    GroupSummary: 'group_summary',
    Alert: 'alert',
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
 * * `every_match` - Every new match
 * * `on_breach` - When a threshold is crossed
 */
export type AlertConfigFrequencyEnumApi = (typeof AlertConfigFrequencyEnumApi)[keyof typeof AlertConfigFrequencyEnumApi]

export const AlertConfigFrequencyEnumApi = {
    EveryMatch: 'every_match',
    OnBreach: 'on_breach',
} as const

/**
 * * `count` - Count of matching observations
 * * `avg_score` - Average score
 */
export type VisionAlertMetricEnumApi = (typeof VisionAlertMetricEnumApi)[keyof typeof VisionAlertMetricEnumApi]

export const VisionAlertMetricEnumApi = {
    Count: 'count',
    AvgScore: 'avg_score',
} as const

/**
 * * `above` - At or above
 * * `below` - At or below
 */
export type VisionAlertDirectionEnumApi = (typeof VisionAlertDirectionEnumApi)[keyof typeof VisionAlertDirectionEnumApi]

export const VisionAlertDirectionEnumApi = {
    Above: 'above',
    Below: 'below',
} as const

/**
 * * `1` - 1 day
 * * `3` - 3 days
 * * `7` - 7 days
 * * `14` - 14 days
 * * `30` - 30 days
 */
export type WindowDaysEnumApi = (typeof WindowDaysEnumApi)[keyof typeof WindowDaysEnumApi]

export const WindowDaysEnumApi = {
    Number1: 1,
    Number3: 3,
    Number7: 7,
    Number14: 14,
    Number30: 30,
} as const

/**
 * The alert condition for mode='alert', applied after `selection` targeting. 'every_match'
 * notifies about each new match since the previous check; 'on_breach' compares a metric to a
 * threshold over a rolling window and notifies on the transition into breach.
 */
export interface AlertConfigApi {
    /** 'every_match' notifies about every new matching observation (batched per check); 'on_breach' notifies once when the threshold condition starts holding. Defaults to 'on_breach'.
     *
     * * `every_match` - Every new match
     * * `on_breach` - When a threshold is crossed */
    frequency?: AlertConfigFrequencyEnumApi
    /** What to measure over the window: 'count' of targeted observations, or 'avg_score' (the mean scorer score; scorer scanners only). every_match supports 'count' only.
     *
     * * `count` - Count of matching observations
     * * `avg_score` - Average score */
    metric?: VisionAlertMetricEnumApi
    /** The alert fires when the metric is at or above ('above') or at or below ('below') this value, per 'direction'. Required for on_breach; ignored for every_match. */
    threshold?: number
    /** Which side of the threshold breaches: 'above' fires when the metric is at or above it, 'below' when at or below (e.g. an average score dropping under a floor). Both inclusive. Defaults to 'above'; ignored for every_match.
     *
     * * `above` - At or above
     * * `below` - At or below */
    direction?: VisionAlertDirectionEnumApi
    /** Rolling lookback window for on_breach conditions, ending at each check. Defaults to 1 day. every_match ignores it (each check covers what's new since the previous one).
     *
     * * `1` - 1 day
     * * `3` - 3 days
     * * `7` - 7 days
     * * `14` - 14 days
     * * `30` - 30 days */
    window_days?: WindowDaysEnumApi
    /** When true, each example line in the alert message includes the scanner's full reasoning for that observation, not just its verdict/score/tags. Useful when piping the message somewhere else to read or act on. Defaults to false. */
    include_reasoning?: boolean
}

/**
 * * `slack` - Slack
 * * `webhook` - Webhook
 */
export type DeliveryTargetTypeEnumApi = (typeof DeliveryTargetTypeEnumApi)[keyof typeof DeliveryTargetTypeEnumApi]

export const DeliveryTargetTypeEnumApi = {
    Slack: 'slack',
    Webhook: 'webhook',
} as const

/**
 * A single delivery destination: a Slack channel or an HTTP webhook URL.
 */
export interface DeliveryTargetApi {
    /** Destination type: 'slack' posts to a Slack channel; 'webhook' POSTs a JSON payload to a URL.
     *
     * * `slack` - Slack
     * * `webhook` - Webhook */
    type: DeliveryTargetTypeEnumApi
    /** ID of the Slack Integration on this team used to deliver. Required when type is 'slack'. */
    integration_id?: number
    /** Slack channel ID or name the summary is posted to. Required when type is 'slack'. */
    channel?: string
    /** HTTPS endpoint the summary is POSTed to as JSON. Required when type is 'webhook'. Redacted to scheme+host in responses for users without editor access to the scanner. */
    url?: string
}

/**
 * * `engineering` - Engineering
 * * `data` - Data
 * * `product` - Product Management
 * * `founder` - Founder
 * * `leadership` - Leadership
 * * `marketing` - Marketing
 * * `sales` - Sales / Success
 * * `student` - Student
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
    Student: 'student',
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

/**
 * A Replay Vision action: a scheduled "and then…" automation over a scanner's observations.
 */
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
    trigger_type?: VisionActionTriggerTypeEnumApi
    /** What the action produces. MVP supports 'group_summary' only.
     *
     * * `group_summary` - Group summary
     * * `alert` - Alert
     * * `per_observation` - Per observation */
    mode?: VisionActionModeEnumApi
    /** Trigger parameters. For schedule triggers: {rrule, timezone}. */
    trigger_config?: TriggerConfigApi
    /** Targeting predicate: which of the scanner's observations this action runs on. */
    selection?: SelectionApi
    /** Synthesis options for the group summary, e.g. {prompt_guide}. */
    synthesis_config?: SynthesisConfigApi
    /** Alert condition; required when mode is 'alert', ignored otherwise. */
    alert_config?: AlertConfigApi
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

/**
 * A Replay Vision action: a scheduled "and then…" automation over a scanner's observations.
 */
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
    trigger_type?: VisionActionTriggerTypeEnumApi
    /** What the action produces. MVP supports 'group_summary' only.
     *
     * * `group_summary` - Group summary
     * * `alert` - Alert
     * * `per_observation` - Per observation */
    mode?: VisionActionModeEnumApi
    /** Trigger parameters. For schedule triggers: {rrule, timezone}. */
    trigger_config?: TriggerConfigApi
    /** Targeting predicate: which of the scanner's observations this action runs on. */
    selection?: SelectionApi
    /** Synthesis options for the group summary, e.g. {prompt_guide}. */
    synthesis_config?: SynthesisConfigApi
    /** Alert condition; required when mode is 'alert', ignored otherwise. */
    alert_config?: AlertConfigApi
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
 * Async-accepted response for POST /vision/actions/{id}/run/.
 */
export interface RunActionResponseApi {
    /** Temporal workflow id for the run; the resulting run appears under the action's run history. */
    workflow_id: string
    /** True when a run for this action was already in progress (scheduled or manual), so this request coalesced onto it rather than starting a second run. */
    already_running: boolean
}

/**
 * The shape every Replay Vision error response uses, so generated clients read one key.
 */
export interface ReplayVisionErrorApi {
    /** Human-readable explanation of why the request was refused. */
    detail: string
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
    /** True for the run recording an alert's condition clearing after a breach (the recovery bookend in run history). False for alert firings and summaries. */
    readonly is_recovery: boolean
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
    /** True for the run recording an alert's condition clearing after a breach (the recovery bookend in run history). False for alert firings and summaries. */
    readonly is_recovery: boolean
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
 * * `backfill` - Backfill
 */
export type ObservationTriggerEnumApi = (typeof ObservationTriggerEnumApi)[keyof typeof ObservationTriggerEnumApi]

export const ObservationTriggerEnumApi = {
    Schedule: 'schedule',
    OnDemand: 'on_demand',
    Retry: 'retry',
    Backfill: 'backfill',
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
    /** Populated on terminal non-success statuses; formatted as `kind:human-readable message`. For `ineligible`, kind is one of no_recording / too_short / too_inactive / too_long / no_events / no_snapshots. For `failed`, kind is one of provider_transient / provider_rejected / rasterization_failed / validation_failed / infra_transient / internal_error / orphaned. */
    readonly error_reason: string
    /** Temporal workflow id for progress queries and debugging. Empty until the workflow starts. */
    readonly workflow_id: string
    /** Frozen view of the scanner at run time; scanner edits do not retroactively mutate this observation. */
    readonly scanner_snapshot: ScannerSnapshotApi | null
    /** Result data persisted on success; null until the observation succeeds. */
    readonly scanner_result: ScannerResultApi | null
    /** Whether this observation came from the schedule, an on-demand request, a retry of a failed or ineligible observation, or a historical backfill.
     *
     * * `schedule` - Schedule
     * * `on_demand` - On demand
     * * `retry` - Retry
     * * `backfill` - Backfill */
    readonly triggered_by: ObservationTriggerEnumApi
    /** User who triggered an on-demand observation; null for scheduled observations. */
    readonly triggered_by_user: UserBasicApi | null
    /**
     * Backfill that dispatched this observation; null for live, on-demand, and retry triggers.
     * @nullable
     */
    readonly backfill_id: string | null
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
 * The PostHog Task created from an observation.
 */
export interface CreateTaskFromObservationResponseApi {
    /** ID of the PostHog Task holding this observation's finding, created now (201) or by an earlier call (200). */
    task_id: string
}

/**
 * Async-accepted response for POST /vision/scanners/{id}/observations/{id}/retry/.
 */
export interface RetryResponseApi {
    /** Temporal workflow id for the re-run. The retried observation row is deleted; look up its replacement via GET /vision/scanners/{id}/observations/?session_id=<session_id>. */
    workflow_id: string
}

export interface ObservationSearchResultApi {
    /** The matching observation. */
    observation: ReplayObservationApi
    /** Cosine distance between the search text and the observation's closest embedding. Lower is a closer match. Only comparable to other results in the same response. */
    distance: number
    /** Excerpt of the observation text that best matched the search, truncated. Empty for observations analyzed before excerpts were stored. */
    matched_content: string
}

export interface ObservationSearchResponseApi {
    /** Matching observations, most relevant first. */
    results: ObservationSearchResultApi[]
    /** True when more matches may exist beyond `results`, so the response is a top slice rather than everything that matched. */
    truncated: boolean
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
    /** `scanners_monthly_credits` plus `backfills_committed_credits`. Kept as the single headline number; prefer the two components when pro-rating, since only the scanner half is a monthly rate. */
    readonly projected_monthly_credits: number
    /** Credit-weighted sum of enabled scanners' projected observations/month across the organization. A monthly rate: only the part falling in the days left of the period lands this period. Scanners without a computed estimate contribute 0. */
    readonly scanners_monthly_credits: number
    /** Committed-but-unspent credits of the organization's active backfills. A one-off charge rather than a rate, so it lands in full regardless of how much of the period is left. */
    readonly backfills_committed_credits: number
    /** Credits per period included for free. Already counted inside `credit_limit`; only credits beyond this number are billed. */
    readonly free_monthly_credits: number
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
 * * `gemini-3.5-flash-lite` - Gemini 3.5 Flash Lite
 * * `gemini-3-flash-preview` - Gemini 3 Flash
 * * `gemini-3.7-flash` - Gemini 3.7 Flash
 */
export type ScannerModelEnumApi = (typeof ScannerModelEnumApi)[keyof typeof ScannerModelEnumApi]

export const ScannerModelEnumApi = {
    Gemini35FlashLite: 'gemini-3.5-flash-lite',
    Gemini3FlashPreview: 'gemini-3-flash-preview',
    Gemini37Flash: 'gemini-3.7-flash',
} as const

/**
 * The experiment a scanner watches. Scans derive their person-scoped exposure filter from
 * this blob at query time, so it is the only place an experiment can enter a scanner's
 * targeting — which is what lets the write-side access check and read-side redaction cover it.
 */
export interface ScannerExperimentTargetingApi {
    /**
     * The experiment the scanner watches.
     * @minimum 1
     */
    experiment_id: number
    /**
     * Narrow to sessions of people exposed to this variant. Null means every variant.
     * @maxLength 400
     * @nullable
     */
    variant?: string | null
}

export interface FeedbackThemeSessionApi {
    /** Observation whose feedback comment backs this theme. */
    observation_id: string
    /** Session recording the feedback comment was about. */
    session_id: string
}

export interface FeedbackThemeApi {
    /** Short failure mode in sentence case, for example "Review page mistaken for confirmation". */
    theme: string
    /** How many feedback comments describe this failure mode. */
    count: number
    /** Up to two short representative quotes from the feedback comments. */
    examples: string[]
    /** The rated sessions whose feedback comments back this theme. Empty for summaries generated before session tracking. */
    sessions: FeedbackThemeSessionApi[]
}

export interface FeedbackThemesApi {
    /** Recurring failure modes, most frequent first. */
    themes: FeedbackThemeApi[]
    /** Number of thumbs-down feedback comments the summary was generated from. */
    feedback_count: number
    /** When the summary was generated. */
    generated_at: string
}

/**
 * A Replay Vision scanner: its type, targeting query, and AI configuration.
 */
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
    /**
     * Organizational tags for this scanner. Distinct from a classifier's categories in scanner_config. Tags cannot contain commas.
     * @maxItems 32
     * @items.maxLength 255
     */
    tags?: string[]
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
    /**
     * Optional cap on this scanner's own credit spend per billing period. Null means no scanner-level cap. When reached, this scanner stops scanning until the period resets. It stays enabled and does not scan the sessions it skipped.
     * @minimum 1
     * @maximum 2147483647
     * @nullable
     */
    credit_limit?: number | null
    /** LLM provider. v1 is Google-only.
     *
     * * `google` - Google */
    provider?: ScannerProviderEnumApi
    /** Concrete model to use for this scanner.
     *
     * * `gemini-3.5-flash-lite` - Gemini 3.5 Flash Lite
     * * `gemini-3-flash-preview` - Gemini 3 Flash
     * * `gemini-3.7-flash` - Gemini 3.7 Flash */
    model: ScannerModelEnumApi
    /** When false, the reconciler removes the scanner's Temporal schedule. On-demand triggers still work. */
    enabled?: boolean
    /** When true, the prompt is augmented with the Signal side mission and the scanner emits PostHog Signals. */
    emits_signals?: boolean
    /** The experiment this scanner's targeting watches, if any. Set null when the experiment targeting is removed. */
    experiment_targeting?: ScannerExperimentTargetingApi | null
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
    /** Credits this scanner's succeeded observations consumed in the current billing period (1 credit = $0.01). Matches the window of the org-wide quota meter. */
    readonly credits_this_month: number
    /** Succeeded observations this scanner produced in the current billing period. */
    readonly observations_this_month: number
    /** Credits counted against `credit_limit` for the current billing period: settled receipts plus in-flight observations and running prompt tests, priced from their frozen snapshot model. This is what the limit gate measures, so it includes work still in progress. It is not the same as `credits_this_month`, which counts only succeeded observations. */
    readonly credits_used_against_limit: number
    /** Whether this scanner has stopped because of its own credit limit. True when `credit_limit` is set and the budget left cannot cover one more observation, which is the same test the scanner's enforcement gates apply. Always false when no limit is set. */
    readonly limit_reached: boolean
    /** Watermark for the scanner's last scheduled fire. Mirrors Temporal schedule state for recovery. */
    readonly last_swept_at: string
    readonly created_at: string
    /** User who created the scanner. */
    readonly created_by: UserBasicApi | null
    readonly updated_at: string
    /** AI summary of the team's written thumbs-down feedback into recurring failure modes. Refreshed with prompt recommendations; null until enough feedback accumulates. */
    readonly feedback_themes: FeedbackThemesApi | null
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
}

export interface PaginatedReplayScannerListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ReplayScannerApi[]
}

/**
 * A Replay Vision scanner: its type, targeting query, and AI configuration.
 */
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
    /**
     * Organizational tags for this scanner. Distinct from a classifier's categories in scanner_config. Tags cannot contain commas.
     * @maxItems 32
     * @items.maxLength 255
     */
    tags?: string[]
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
    /**
     * Optional cap on this scanner's own credit spend per billing period. Null means no scanner-level cap. When reached, this scanner stops scanning until the period resets. It stays enabled and does not scan the sessions it skipped.
     * @minimum 1
     * @maximum 2147483647
     * @nullable
     */
    credit_limit?: number | null
    /** LLM provider. v1 is Google-only.
     *
     * * `google` - Google */
    provider?: ScannerProviderEnumApi
    /** Concrete model to use for this scanner.
     *
     * * `gemini-3.5-flash-lite` - Gemini 3.5 Flash Lite
     * * `gemini-3-flash-preview` - Gemini 3 Flash
     * * `gemini-3.7-flash` - Gemini 3.7 Flash */
    model?: ScannerModelEnumApi
    /** When false, the reconciler removes the scanner's Temporal schedule. On-demand triggers still work. */
    enabled?: boolean
    /** When true, the prompt is augmented with the Signal side mission and the scanner emits PostHog Signals. */
    emits_signals?: boolean
    /** The experiment this scanner's targeting watches, if any. Set null when the experiment targeting is removed. */
    experiment_targeting?: ScannerExperimentTargetingApi | null
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
    /** Credits this scanner's succeeded observations consumed in the current billing period (1 credit = $0.01). Matches the window of the org-wide quota meter. */
    readonly credits_this_month?: number
    /** Succeeded observations this scanner produced in the current billing period. */
    readonly observations_this_month?: number
    /** Credits counted against `credit_limit` for the current billing period: settled receipts plus in-flight observations and running prompt tests, priced from their frozen snapshot model. This is what the limit gate measures, so it includes work still in progress. It is not the same as `credits_this_month`, which counts only succeeded observations. */
    readonly credits_used_against_limit?: number
    /** Whether this scanner has stopped because of its own credit limit. True when `credit_limit` is set and the budget left cannot cover one more observation, which is the same test the scanner's enforcement gates apply. Always false when no limit is set. */
    readonly limit_reached?: boolean
    /** Watermark for the scanner's last scheduled fire. Mirrors Temporal schedule state for recovery. */
    readonly last_swept_at?: string
    readonly created_at?: string
    /** User who created the scanner. */
    readonly created_by?: UserBasicApi | null
    readonly updated_at?: string
    /** AI summary of the team's written thumbs-down feedback into recurring failure modes. Refreshed with prompt recommendations; null until enough feedback accumulates. */
    readonly feedback_themes?: FeedbackThemesApi | null
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level?: string | null
}

/**
 * Body of POST /vision/scanners/:id/affected_cohort/. Same qualifiers as the impact GET.
 */
export interface AffectedCohortRequestApi {
    /**
     * Trailing window of observations to count. Defaults to 30 days.
     * @minimum 1
     * @maximum 90
     */
    window_days?: number
    /**
     * Classifier scanners only, required for them: count sessions carrying this tag (fixed or freeform). Not applicable to other scanner types.
     * @maxLength 100
     * @nullable
     */
    tag?: string | null
    /**
     * Scorer scanners only: count sessions scoring at or above this value. Scorers require `min_score` and/or `max_score`. Not applicable to other scanner types.
     * @nullable
     */
    min_score?: number | null
    /**
     * Scorer scanners only: count sessions scoring at or below this value.
     * @nullable
     */
    max_score?: number | null
}

/**
 * The static cohort created from the scanner's affected users.
 */
export interface AffectedCohortResponseApi {
    /** ID of the created static cohort; usable anywhere cohorts are (funnels, surveys, experiments). */
    readonly cohort_id: number
    /** Generated cohort name, stamped with the creation date since the snapshot doesn't live-update. */
    readonly name: string
    /** Persons actually in the created cohort. Can be lower than `affected_users`: matched distinct IDs without a person profile are dropped, and merged persons deduplicate. */
    readonly users_in_cohort: number
    /** Trailing window the cohort was drawn from, in days. */
    readonly window_days: number
}

/**
 * Body of POST /vision/scanners/{id}/bulk_observe/.
 */
export interface BulkObserveRequestApi {
    /**
     * Session recording IDs to scan on demand, at most 200 per request. Scans start until the in-flight limit or monthly credit quota is reached; the rest are reported as skipped rather than failing the whole batch. Already-running sessions are a no-op.
     * @maxItems 200
     * @items.maxLength 128
     */
    session_ids: string[]
}

/**
 * * `started` - Started
 * * `already_running` - Already running
 * * `already_scanned` - Already scanned
 * * `skipped_limit` - Skipped, in-flight limit reached
 * * `skipped_quota` - Skipped, the org's credit quota for this period was reached
 * * `skipped_scanner_limit` - Skipped, scanner's own credit limit reached
 * * `failed` - Failed to start
 */
export type ScanOutcomeEnumApi = (typeof ScanOutcomeEnumApi)[keyof typeof ScanOutcomeEnumApi]

export const ScanOutcomeEnumApi = {
    Started: 'started',
    AlreadyRunning: 'already_running',
    AlreadyScanned: 'already_scanned',
    SkippedLimit: 'skipped_limit',
    SkippedQuota: 'skipped_quota',
    SkippedScannerLimit: 'skipped_scanner_limit',
    Failed: 'failed',
} as const

/**
 * Per-session outcome of a bulk scan trigger.
 */
export interface BulkObserveResultApi {
    /** The session recording this outcome is for. */
    session_id: string
    /** 'started' - a scan workflow was kicked off; 'already_running' - a scan for this session is already in flight (no-op, not recharged); 'already_scanned' - this scanner already has a finished observation for this session, so nothing was started and nothing was charged (read it back, or use the retry action to run it again); 'skipped_limit' - the in-flight cap was reached before this session; 'skipped_quota' - the org's credit quota for this period would be exceeded; 'skipped_scanner_limit' - this scanner's own credit limit would be exceeded; 'failed' - the workflow failed to start.
     *
     * * `started` - Started
     * * `already_running` - Already running
     * * `already_scanned` - Already scanned
     * * `skipped_limit` - Skipped, in-flight limit reached
     * * `skipped_quota` - Skipped, the org's credit quota for this period was reached
     * * `skipped_scanner_limit` - Skipped, scanner's own credit limit reached
     * * `failed` - Failed to start */
    scan_outcome: ScanOutcomeEnumApi
}

/**
 * Result of POST /vision/scanners/{id}/bulk_observe/ — partial success by design.
 */
export interface BulkObserveResponseApi {
    /** How many new scans were started. */
    started: number
    /** Per-session outcomes, in request order (deduplicated). */
    results: BulkObserveResultApi[]
}

/**
 * Who this scanner's findings affected in the window; counted from observations, not estimated.
 */
export interface ScannerImpactApi {
    /** Distinct sessions with an affected observation in the window. For monitors only verdict-yes observations count; for other scanner types every succeeded observation counts. */
    readonly affected_sessions: number
    /** Distinct users behind the affected sessions, by distinct ID. May include anonymous device IDs when the recorded sessions were not identified. */
    readonly affected_users: number
    /** Affected sessions whose recording carried no distinct ID at all. */
    readonly sessions_without_user: number
    /** Trailing window the counts cover, in days. */
    readonly window_days: number
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
 * 200 from POST /vision/scanners/{id}/observe/ - nothing started, the answer already exists.
 */
export interface ObserveAlreadyScannedApi {
    /** The settled observation this scanner already has for the session. Nothing was started and nothing was charged; read it from /vision/scanners/{id}/observations/, or use the retry action on it to scan the session again. */
    observation_id: string
}

/**
 * Async-accepted response for POST /vision/scanners/{id}/observe/.
 */
export interface ObserveResponseApi {
    /** Temporal workflow id for this scanner application. Look up the resulting ReplayObservation via GET /vision/scanners/{id}/observations/?session_id=<session_id>. */
    workflow_id: string
}

/**
 * Response of GET /vision/scanners/:id/self_driving_stats/.
 */
export interface ScannerSelfDrivingStatsApi {
    /** Signals this scanner has pushed into the Signals inbox, all time. */
    signals_emitted: number
    /** Signal reports that include at least one of this scanner's signals. Reports usually aggregate signals from several sources, so this counts contributions, not sole causes. */
    reports_contributed: number
    /** Implementation PRs opened by self-driving on those reports. */
    prs_opened: number
    /** Of the opened PRs, how many have merged. */
    prs_merged: number
}

/**
 * * `running` - Running
 * * `paused_quota` - Paused (quota)
 * * `completed` - Completed
 * * `cancelled` - Cancelled
 */
export type BackfillStatusEnumApi = (typeof BackfillStatusEnumApi)[keyof typeof BackfillStatusEnumApi]

export const BackfillStatusEnumApi = {
    Running: 'running',
    PausedQuota: 'paused_quota',
    Completed: 'completed',
    Cancelled: 'cancelled',
} as const

export interface ReplayScannerBackfillApi {
    readonly id: string
    readonly status: BackfillStatusEnumApi
    /** Inclusive lower bound of the historical window to scan. */
    readonly window_start: string
    /** Exclusive upper bound of the window; clamped to now at creation. */
    readonly window_end: string
    /** Unobserved candidates enumerated at creation; the ceiling is total_count x credits_per_observation. */
    readonly total_count: number
    readonly dispatched_count: number
    /** Candidates the walk stepped over because this scanner had already tried them. Counted at creation but never dispatched, so progress and remaining spend both have to account for them. */
    readonly skipped_count: number
    /** Per-observation credit price frozen at creation from the snapshot model. */
    readonly credits_per_observation: number
    /** Observations from this backfill that succeeded. */
    readonly succeeded_count: number
    /** Observations from this backfill that failed. */
    readonly failed_count: number
    /** Sessions that turned out ineligible (too short, expired recording, ...). */
    readonly ineligible_count: number
    /** Observations from this backfill still pending or running. */
    readonly in_flight_count: number
    readonly created_by: UserBasicApi | null
    readonly created_at: string
    /**
     * When the backfill reached a terminal status (completed or cancelled).
     * @nullable
     */
    readonly finished_at: string | null
}

export interface PaginatedReplayScannerBackfillListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ReplayScannerBackfillApi[]
}

export interface BackfillWindowApi {
    /** Inclusive lower bound of the historical window to scan. */
    window_start: string
    /** Exclusive upper bound of the window; clamped server-side to now. */
    window_end: string
}

export interface BackfillEstimateResponseApi {
    /** Upper bound on the sessions the backfill would scan, after sampling and quality filters and excluding sessions this scanner already reported an observation for. */
    total_sessions: number
    /** Cost ceiling in credits (1 credit = $0.01): total_sessions x credits_per_observation. Actual spend lands under it: sessions already tried, expired recordings, and failures are not billed. */
    total_credits: number
    /** Per-observation credit price at the scanner's current model. */
    credits_per_observation: number
    /**
     * Credits left in the org's monthly quota; null when the org is uncapped.
     * @nullable
     */
    credits_remaining: number | null
    /** The window lower bound the estimate covered. */
    window_start: string
    /** The window upper bound after clamping to now. */
    window_end: string
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
    /** The full type-specific config this version ran with (prompt plus, depending on scanner type, allow_inconclusive, tags, scale, or length), taken from the observation run snapshots. */
    scanner_config: unknown
    /**
     * The scanner type this version ran as.
     * @nullable
     */
    scanner_type: string | null
    /**
     * The model this version ran on.
     * @nullable
     */
    model: string | null
    /**
     * The provider this version ran on.
     * @nullable
     */
    provider: string | null
    /**
     * Whether this version emitted signals.
     * @nullable
     */
    emits_signals: boolean | null
    /** The `RecordingsQuery` recording filters this version ran with. */
    query: unknown
    /**
     * The 0..1 downsample this version ran with.
     * @nullable
     */
    sampling_rate: number | null
    /**
     * The session-coverage pre-filter this version ran with.
     * @nullable
     */
    sampling_mode: string | null
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
    /** Each scanner version that produced observations (all-time), with its first day, the config it ran with, and rating counts, for chart markers and the config version history. */
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

export interface FacetCountApi {
    /** The facet value as emitted by the summarizer (lowercased). */
    term: string
    /** Number of succeeded observations that emitted this value. */
    count: number
}

export interface SummarizerStatsApi {
    /** Top friction points by emission count. */
    friction_ranked: FacetCountApi[]
    /** Top keywords by emission count. */
    keyword_ranked: FacetCountApi[]
    /** Succeeded observations that emitted at least one friction point or keyword. */
    total_with_facets: number
    /** Succeeded observations that reported at least one friction point. */
    total_with_friction: number
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
    /** Summarizer-type facet aggregates; null when the scanner is not a summarizer. */
    summarizer: SummarizerStatsApi | null
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
    /** kept (up, unchanged), regressed (up, changed), fixed (down, changed), still_wrong (down, unchanged), error, or preview (scorer/summarizer: raw before/after, no classification). */
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
    /** The scanner config this suggestion was generated against. */
    readonly base_config: unknown
    /** The full proposed scanner config, ready to apply. */
    readonly suggested_config: unknown
    /** Typed per-field diff entries driving the change cards. */
    readonly changes: unknown
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

export interface ApplyPromptSuggestionRequestApi {
    /** The edited config to apply, assembled from the recommendation's approved fields. Omit to apply the full suggested config unchanged. */
    config?: unknown
}

export interface EvaluatePromptSuggestionRequestApi {
    /**
     * How many rated sessions to re-run, thumbs-down prioritized. Each successful re-run charges credits like a normal observation of the same model. Defaults to 10. The maximum is `evaluation_session_cap`.
     * @minimum 1
     * @maximum 100
     */
    session_limit?: number
    /** The edited config to test, assembled from the recommendation's approved fields. Omit to test the full suggested config. */
    config?: unknown
}

export interface CurrentPromptSuggestionApi {
    /** The newest suggestion for this scanner, or null when none has been generated yet. */
    suggestion: ReplayScannerPromptSuggestionApi | null
    /** True when the team's ratings changed since the newest suggestion was generated. */
    stale: boolean
    /** Number of rated (thumbs up or down) succeeded observations available to generate from. */
    rated_count: number
    /** Maximum rated sessions one suggestion test re-runs. Each successful re-run charges credits like a normal observation of the same model. */
    evaluation_session_cap: number
}

/**
 * * `small` - small
 * * `medium` - medium
 * * `large` - large
 */
export type SizeEnumApi = (typeof SizeEnumApi)[keyof typeof SizeEnumApi]

export const SizeEnumApi = {
    Small: 'small',
    Medium: 'medium',
    Large: 'large',
} as const

/**
 * One chart attached to a report — rendered in the inbox and referenceable from the summary.
 */
export interface ReportChartApi {
    /**
     * Stable slug for this chart within the report (lowercase letters, numbers, underscores, hyphens; must start with a letter or number). Reference it from `summary` as a markdown link with a `chart:` target — `[Daily signups](chart:signups-drop)` — to place the chart at that point in the body. A chart you don't reference still renders, below the summary.
     * @maxLength 100
     */
    chart_id: string
    /**
     * Short heading shown above the chart.
     * @maxLength 200
     */
    title: string
    /** The query node to render. `kind` must be `InsightVizNode` (an ad-hoc product analytics chart), `DataVisualizationNode` (a SQL series — a `HogQLQuery` source plus a `display`), or `SavedInsightNode` (an existing insight by `shortId`). Pin the window to absolute dates where the node supports it, so the reader sees the data you wrote about rather than whatever a relative range resolves to when they open the report. */
    query: unknown
    /**
     * Optional one-line note on what to look at in the chart.
     * @maxLength 500
     * @nullable
     */
    caption?: string | null
    /** How much height the chart gets: `small` for a single number or a short series, `medium` for an ordinary graph, `large` when there are rows or a grid to read (retention, paths, a wide breakdown). Leave it out unless the default looks wrong — the inbox sizes a chart from its query, and two charts referenced from the same paragraph sit side by side.
     *
     * * `small` - small
     * * `medium` - medium
     * * `large` - large */
    size?: SizeEnumApi | null
}

/**
 * One report a scanner's scout filed. Enough to read it in Replay Vision; the inbox owns the
 * full record (status, priority, reviewers, run trail).
 */
export interface ScoutReportApi {
    /** The report's id, as used by the Signals inbox. */
    report_id: string
    /** The scout that filed it, as its skill name. */
    skill_name: string
    /** When the run that filed this report started. Later edits do not move it. */
    filed_at: string
    /** The report's title. Empty when the scout left it unset. */
    title: string
    /** The report body, as markdown. Empty when the scout left it unset. */
    summary: string
    /** Charts the scout attached. The summary places one inline with a `[label](chart:<chart_id>)` link; any it does not place render after the body. */
    charts: ReportChartApi[]
}

export interface SignalScoutSlackDestinationApi {
    /**
     * ID of the Slack integration whose bot posts this scout's findings and reports.
     * @minimum 1
     */
    integration_id: number
    /**
     * Slack channel target in the channel picker's `channel_id|#channel-name` format. Null while choosing a channel; no messages are sent until it is set.
     * @maxLength 255
     * @nullable
     */
    channel?: string | null
    /** When true, post a report as a thread: a short lead in the channel and the rest split by the report's Markdown headings into replies. Keeps a long summary from being clipped at Slack's section limit. Off by default, and it does not change how findings post. */
    thread_reports?: boolean
}

export interface SignalScoutWebhookDestinationApi {
    /** Id of the CDP destination delivering this scout's reports. Set by the product that provisioned it, so it can find that destination again to update or remove it. */
    hog_function_id: string
}

export interface SignalScoutOutputDestinationsApi {
    /** Slack destination for each emitted scout finding or report. Null or omitted disables Slack delivery. */
    slack?: SignalScoutSlackDestinationApi | null
    /** The CDP destination another product provisioned for this scout's reports. Null or omitted means no webhook. Unlike Slack, Signals does not deliver this itself: the reference lives here so the owning product can manage the destination's lifecycle. */
    webhook?: SignalScoutWebhookDestinationApi | null
}

/**
 * * `trusted` - Trusted domains only
 * * `full` - Full
 */
export type ScoutConfigNetworkAccessEnumApi =
    (typeof ScoutConfigNetworkAccessEnumApi)[keyof typeof ScoutConfigNetworkAccessEnumApi]

export const ScoutConfigNetworkAccessEnumApi = {
    Trusted: 'trusted',
    Full: 'full',
} as const

/**
 * Optional JSON Schema (draft 2020-12) describing ONE structured record this scout produces via `scout-record-output` — e.g. a per-report quality judgment (`{"type": "object", "properties": {"verdict": {"enum": ["good", "bad", "unsure"]}, "reason": {"type": "string"}}, "required": ["verdict", "reason"]}`). The root must be `"type": "object"`. Setting a schema turns the structured-output channel on: the run prompt renders the schema and every submitted record is validated against it and recorded in the project as a `$scout_structured_output` event, queryable like any event. The channel also requires emit — a dry-run scout has nowhere to record to. Cardinality is the scout's call (one record per run, one per judged entity, ...). Null = channel off. Setting a schema requires skill-authoring authorization (the `llm_skill:write` scope and skill editor access) since the scout reads it verbatim in its prompt; clearing it needs only the config write. Records validate against the schema in force when the run was dispatched.
 * @nullable
 */
export type SignalScoutConfigOptionsApiStructuredOutputSchema = { [key: string]: unknown } | null

/**
 * Schedule, enablement, and delivery options accepted while creating a scout.
 */
export interface SignalScoutConfigOptionsApi {
    /** Whether this scout runs on its schedule. Defaults to true. */
    enabled?: boolean
    /** Whether the scout writes findings to the inbox. False = dry-run: it runs and logs but emits nothing. Defaults to true. */
    emit?: boolean
    /**
     * Minutes between runs (30–43200). Defaults to 1440 (every 24 hours).
     * @minimum 30
     * @maximum 43200
     */
    run_interval_minutes?: number
    /** Destinations that receive each finding or report this scout emits. Empty by default. */
    output_destinations?: SignalScoutOutputDestinationsApi
    /** What the scout's sandbox can reach over the network while it runs. Defaults to `trusted`, the platform's trusted-domain allowlist (PostHog, GitHub, common package registries). Set `full` to let this scout reach any site, for skills that read external sources such as documentation or papers.
     *
     * * `trusted` - Trusted domains only
     * * `full` - Full */
    network_access?: ScoutConfigNetworkAccessEnumApi
    /** Exempt this scout from the inactivity pause, which otherwise switches off a scout that goes a fortnight without surfacing anything anyone engages with. Set it on watchdog scouts whose value is staying quiet. Defaults to false. */
    auto_pause_exempt?: boolean
    /**
     * Optional five-field cron expression, e.g. '30 9 * * *' (daily at 09:30), '0 9,17 * * *' (twice daily), or '0 9 * * 1-5' (weekday mornings). Evaluated in the project timezone. Takes precedence over `run_interval_minutes`; occurrences must be at least 30 minutes apart.
     * @maxLength 100
     * @nullable
     */
    run_cron_schedule?: string | null
    /**
     * Optional model id this scout's runs are pinned to, e.g. `claude-opus-4-5`. Must be one of the platform's agent models; an invalid id is rejected with the available ones listed. Null keeps the default model, chosen by the platform. Early access: the pin can only be set on projects enrolled in the scout model preview, and only takes effect there. Set null to clear it.
     * @maxLength 200
     * @nullable
     */
    model?: string | null
    /**
     * Free-form labels for grouping the fleet, e.g. `["revenue", "on-call"]`. Normalized to lowercase kebab-case (`On Call` and `on_call` both become `on-call`), deduped, and stored sorted; at most 10 tags, each at most 50 characters once normalized. Pass the full desired set — a write replaces the existing tags rather than merging into them. Filter the config list with the `tags` query parameter.
     * @maxItems 10
     */
    tags?: string[]
    /**
     * Optional JSON Schema (draft 2020-12) describing ONE structured record this scout produces via `scout-record-output` — e.g. a per-report quality judgment (`{"type": "object", "properties": {"verdict": {"enum": ["good", "bad", "unsure"]}, "reason": {"type": "string"}}, "required": ["verdict", "reason"]}`). The root must be `"type": "object"`. Setting a schema turns the structured-output channel on: the run prompt renders the schema and every submitted record is validated against it and recorded in the project as a `$scout_structured_output` event, queryable like any event. The channel also requires emit — a dry-run scout has nowhere to record to. Cardinality is the scout's call (one record per run, one per judged entity, ...). Null = channel off. Setting a schema requires skill-authoring authorization (the `llm_skill:write` scope and skill editor access) since the scout reads it verbatim in its prompt; clearing it needs only the config write. Records validate against the schema in force when the run was dispatched.
     * @nullable
     */
    structured_output_schema?: SignalScoutConfigOptionsApiStructuredOutputSchema
    /**
     * MCP gateway servers (by id) this scout's runs may use, chosen from the connections members shared to the whole team. Selection is per scout: an empty list gives the scout no MCP servers. Applies from the scout's next run.
     * @maxItems 100
     */
    mcp_gateway_server_ids?: string[]
}

/**
 * A scout to stand up for this scanner. The scanner comes from the URL, never the body: it is
 * what the caller's access is checked against, and what the scout is recorded as belonging to.
 *
 * Inherits the Signals scout definition so a scout created here clears the same name and prompt-size
 * bars as one created through the generic endpoint.
 */
export interface ScannerScoutCreateApi {
    /**
     * Unique scout name. Must start with `signals-scout-` and contain only lowercase letters, numbers, and hyphens.
     * @maxLength 64
     */
    name: string
    /**
     * Short description of the signal or behavior this scout investigates.
     * @maxLength 4096
     */
    description: string
    /** Complete markdown prompt executed on every scout run. Include any project-specific signal names, thresholds, investigation steps, and report criteria here. */
    body: string
    /** Optional schedule, enablement, dry-run posture, and delivery settings. Defaults to an enabled, emitting scout on the daily interval with no external destination. */
    config?: SignalScoutConfigOptionsApi
}

export type ScoutOriginEnumApi = (typeof ScoutOriginEnumApi)[keyof typeof ScoutOriginEnumApi]

export const ScoutOriginEnumApi = {
    Canonical: 'canonical',
    Custom: 'custom',
} as const

/**
 * * `active` - Active
 * * `pending_pause` - Pending pause
 * * `paused_by_system` - Paused by system
 * * `paused_by_user` - Paused by user
 */
export type ScoutConfigStatusEnumApi = (typeof ScoutConfigStatusEnumApi)[keyof typeof ScoutConfigStatusEnumApi]

export const ScoutConfigStatusEnumApi = {
    Active: 'active',
    PendingPause: 'pending_pause',
    PausedBySystem: 'paused_by_system',
    PausedByUser: 'paused_by_user',
} as const

/**
 * * `no_output` - No output
 * * `ignored` - Ignored
 * * `repeated_failures` - Repeated failures
 */
export type ScoutConfigPauseReasonEnumApi =
    (typeof ScoutConfigPauseReasonEnumApi)[keyof typeof ScoutConfigPauseReasonEnumApi]

export const ScoutConfigPauseReasonEnumApi = {
    NoOutput: 'no_output',
    Ignored: 'ignored',
    RepeatedFailures: 'repeated_failures',
} as const

/**
 * Optional JSON Schema (draft 2020-12) describing ONE structured record this scout produces via `scout-record-output` — e.g. a per-report quality judgment (`{"type": "object", "properties": {"verdict": {"enum": ["good", "bad", "unsure"]}, "reason": {"type": "string"}}, "required": ["verdict", "reason"]}`). The root must be `"type": "object"`. Setting a schema turns the structured-output channel on: the run prompt renders the schema and every submitted record is validated against it and recorded in the project as a `$scout_structured_output` event, queryable like any event. The channel also requires emit — a dry-run scout has nowhere to record to. Cardinality is the scout's call (one record per run, one per judged entity, ...). Null = channel off. Setting a schema requires skill-authoring authorization (the `llm_skill:write` scope and skill editor access) since the scout reads it verbatim in its prompt; clearing it needs only the config write. Records validate against the schema in force when the run was dispatched.
 * @nullable
 */
export type SignalScoutConfigApiStructuredOutputSchema = { [key: string]: unknown } | null

/**
 * Read shape for a per-(team, skill) scout config.
 *
 * One row per `signals-scout-*` skill on the team. The coordinator auto-creates a row
 * when it discovers a scout skill; this serializer lets agents tune the row.
 */
export interface SignalScoutConfigApi {
    readonly id: string
    /** The `signals-scout-*` skill this config controls. Set at creation, not editable. */
    readonly skill_name: string
    /** Human-readable summary of what this scout investigates, sourced from the scout skill's `description` metadata. Use it for a quick steer on the scout's focus without loading the full skill body. Empty if the skill is not currently present on the team or carries no description. */
    readonly description: string
    /** Where this scout came from: `canonical` for a scout PostHog ships and maintains (seeded from `products/signals/skills/`), or `custom` for one a team hand-authored on this project. Use it to badge built-in vs custom scouts instead of a hardcoded name list. Defaults to `custom` if the skill is not currently present on the team. */
    readonly scout_origin: ScoutOriginEnumApi
    /** Whether this scout runs on its schedule. Disabled scouts are skipped by the coordinator. Derived from `status`: true for `active` and `pending_pause`, false for the paused statuses. */
    readonly enabled: boolean
    /** Lifecycle status. `active`: runs on its schedule. `pending_pause`: still running, but flagged by the system to pause soon unless something changes (any config edit clears it). `paused_by_system`: paused automatically, see `pause_reason`; set `enabled=true` to resume. `paused_by_user`: switched off by a person and never resumed automatically.
     *
     * * `active` - Active
     * * `pending_pause` - Pending pause
     * * `paused_by_system` - Paused by system
     * * `paused_by_user` - Paused by user */
    readonly status: ScoutConfigStatusEnumApi
    /** Why the system paused (or warned) this scout: `no_output` (it emitted nothing over the evaluation window), `ignored` (no person engaged with its reports — no view, rating, note, dismissal, or resolution), or `repeated_failures` (consecutive failed runs). Null unless `status` is `pending_pause` or `paused_by_system`.
     *
     * * `no_output` - No output
     * * `ignored` - Ignored
     * * `repeated_failures` - Repeated failures */
    readonly pause_reason: ScoutConfigPauseReasonEnumApi | null
    /** Whether the scout writes findings to the inbox. False = dry-run: it runs and logs but emits nothing. */
    readonly emit: boolean
    /**
     * Minutes between runs (30–43200). The scout runs once this interval has elapsed since its last run.
     * @minimum 30
     * @maximum 43200
     */
    readonly run_interval_minutes: number
    /**
     * Optional five-field cron expression evaluated in the project timezone, e.g. '30 9 * * *'. Takes precedence over `run_interval_minutes` when set. Null means the rolling interval schedule.
     * @nullable
     */
    readonly run_cron_schedule: string | null
    /** Destinations that receive each finding or report this scout emits. Empty when none is configured. */
    readonly output_destinations: SignalScoutOutputDestinationsApi
    /**
     * Optional JSON Schema (draft 2020-12) describing ONE structured record this scout produces via `scout-record-output` — e.g. a per-report quality judgment (`{"type": "object", "properties": {"verdict": {"enum": ["good", "bad", "unsure"]}, "reason": {"type": "string"}}, "required": ["verdict", "reason"]}`). The root must be `"type": "object"`. Setting a schema turns the structured-output channel on: the run prompt renders the schema and every submitted record is validated against it and recorded in the project as a `$scout_structured_output` event, queryable like any event. The channel also requires emit — a dry-run scout has nowhere to record to. Cardinality is the scout's call (one record per run, one per judged entity, ...). Null = channel off. Setting a schema requires skill-authoring authorization (the `llm_skill:write` scope and skill editor access) since the scout reads it verbatim in its prompt; clearing it needs only the config write. Records validate against the schema in force when the run was dispatched.
     * @nullable
     */
    readonly structured_output_schema: SignalScoutConfigApiStructuredOutputSchema
    /** What the scout's sandbox can reach over the network while it runs. `trusted` (the default) restricts runs to the platform's trusted-domain allowlist (PostHog, GitHub, common package registries). `full` lets the scout reach any site, for skills that read external sources such as documentation or papers.
     *
     * * `trusted` - Trusted domains only
     * * `full` - Full */
    readonly network_access: ScoutConfigNetworkAccessEnumApi
    /**
     * Optional model id this scout's runs are pinned to, e.g. `claude-opus-4-5`. Must be one of the platform's agent models; an invalid id is rejected with the available ones listed. Null keeps the default model, chosen by the platform. Early access: the pin can only be set on projects enrolled in the scout model preview, and only takes effect there. Set null to clear it.
     * @nullable
     */
    readonly model: string | null
    /**
     * MCP gateway servers (by id) this scout's runs may use, chosen from the connections members shared to the whole team. Selection is per scout: an empty list gives the scout no MCP servers. Applies from the scout's next run.
     * @maxItems 100
     */
    readonly mcp_gateway_server_ids: readonly string[]
    /**
     * When the coordinator last dispatched this scout. Null if it has never run.
     * @nullable
     */
    readonly last_run_at: string | null
    /** How many of this scout's runs have failed in a row. Back to 0 after a successful run or any config edit. At the failure limit the scout pauses itself (`status` becomes `paused_by_system` with `pause_reason` `repeated_failures`) and retries about once a day; a successful retry resumes it, and so does setting `enabled=true`. */
    readonly consecutive_failure_count: number
    /**
     * When `status` last changed. For `pending_pause` this is when the warning was issued (an `ignored` warning pauses about a week later unless someone engages with the scout's reports — opening one counts; a `no_output` warning only flags the scout); for the paused statuses it is when the scout was paused. Null if the status never changed.
     * @nullable
     */
    readonly status_changed_at: string | null
    /** Whether this scout is exempt from the inactivity sweep, meaning both the `ignored` pause and the `no_output` quiet warning. Set it on watchdog scouts whose value is staying quiet. Only ever set explicitly: re-enabling a swept scout instead grants a fresh grace window before the sweep may judge it again. */
    readonly auto_pause_exempt: boolean
    /** Free-form labels for grouping the fleet, e.g. `["revenue", "on-call"]`. Normalized to lowercase kebab-case (`On Call` and `on_call` both become `on-call`), deduped, and stored sorted; at most 10 tags, each at most 50 characters once normalized. Pass the full desired set — a write replaces the existing tags rather than merging into them. Filter the config list with the `tags` query parameter. */
    tags?: string[]
    /**
     * The product that stood this scout up for one of its own objects. Null when a person created it.
     * @nullable
     */
    readonly source_product: string | null
    /**
     * Id of the owning object in `source_product`, e.g. a Replay Vision scanner id.
     * @nullable
     */
    readonly source_id: string | null
    readonly created_at: string
}

/**
 * The scout that now watches this scanner.
 */
export interface ScannerScoutCreateResponseApi {
    /** False when a scout of this name already existed and the supplied config was applied to it. */
    created: boolean
    /** The scout's config, including the source recorded for it. */
    config: SignalScoutConfigApi
}

/**
 * Distinct creators across all scanners on the team — feeds the `Created by` filter dropdown.
 */
export interface ScannerCreatorsResponseApi {
    /** Users who created at least one scanner on this team. Returned regardless of pagination state so the dropdown stays stable across pages. */
    creators: UserBasicApi[]
}

/**
 * Body of POST /vision/scanners/draft/ — the user's goal, stated in their own words.
 */
export interface DraftScannerRequestApi {
    /**
     * What the user wants to accomplish, e.g. 'find out where users get stuck during onboarding'.
     * @maxLength 2000
     */
    goal: string
    /**
     * Goal-based flow only: how many replays a month the scanner may watch. The draft solves `sampling_mode` and `sampling_rate` so the projection lands on this number. Omitted on the legacy flow, and ignored while the goal-based flow's flag is off for the caller.
     * @minimum 1
     * @maximum 1000000
     */
    monthly_scan_budget?: number
}

/**
 * An AI-drafted scanner configuration, ready to seed the creation wizard. Nothing is persisted.
 */
export interface DraftScannerResponseApi {
    /** Drafted scanner name. */
    name: string
    /** Drafted one-sentence description. */
    description: string
    /** The scanner type the draft picked for the goal.
     *
     * * `monitor` - Monitor
     * * `classifier` - Classifier
     * * `scorer` - Scorer
     * * `summarizer` - Summarizer */
    scanner_type: ScannerTypeEnumApi
    /** Type-specific config for the drafted `scanner_type`; always includes `prompt`. */
    scanner_config: unknown
    /** Why the draft picked this scanner type and configuration, addressed to the user. */
    rationale: string
    /** `RecordingsQuery` narrowing which sessions get scanned; null when the draft targets every session. */
    query: unknown
    /** Goal-based flow only: the quality pre-filter the draft chose for the goal. Null on the legacy flow, and null when the costing estimate failed — the wizard keeps its defaults.
     *
     * * `focused` - Focused
     * * `balanced` - Balanced
     * * `comprehensive` - Comprehensive */
    sampling_mode: SamplingModeEnumApi | null
    /**
     * Goal-based flow only: the random sampling rate solved from `monthly_scan_budget`, 0..1. 1.0 when the budget covers every matching recording. Floored at the minimum rate, so a budget below that floor keeps the minimum. Null whenever `sampling_mode` is.
     * @nullable
     */
    sampling_rate: number | null
    /**
     * Goal-based flow only: recordings a month the drafted scanner is projected to watch under the solved dials. At or under `monthly_scan_budget`, except when the budget is below what the minimum sampling rate can reach, where this is the floor and exceeds the budget. Null whenever `sampling_mode` is.
     * @nullable
     */
    estimated_monthly_observations: number | null
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
     * * `gemini-3.5-flash-lite` - Gemini 3.5 Flash Lite
     * * `gemini-3-flash-preview` - Gemini 3 Flash
     * * `gemini-3.7-flash` - Gemini 3.7 Flash */
    model?: ScannerModelEnumApi
    /** Proposed experiment targeting, merged into the query as its exposure filter the same way a saved scanner derives it. The estimate then runs as the requesting user. */
    experiment_targeting?: ScannerExperimentTargetingApi | null
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
    /** Committed-but-unspent credits of the org's active backfills, the same figure the quota snapshot's projection carries. A one-off charge rather than a monthly rate, so the forecast shows it as its own segment instead of adding it to a per-month total. */
    active_backfill_credits: number
    /** Sampling rate applied to the projection. Echoed from the request. */
    sampling_rate: number
}

/**
 * Body of POST /vision/scanners/inline_scan/ - a prompt plus the sessions to point it at.
 */
export interface InlineScanRequestApi {
    /**
     * Session recording IDs to scan, at most 200 per request. Scans start until the in-flight limit or monthly credit quota is reached; the rest are reported as skipped rather than failing the whole batch.
     * @maxItems 200
     * @items.maxLength 128
     */
    session_ids: string[]
    /**
     * What to look for in these sessions, in plain language. The same instruction a saved scanner carries.
     * @maxLength 20000
     */
    prompt: string
    /** What the scan produces. Defaults to monitor, an open-ended observation against the prompt.
     *
     * * `monitor` - Monitor
     * * `classifier` - Classifier
     * * `scorer` - Scorer
     * * `summarizer` - Summarizer */
    scanner_type?: ScannerTypeEnumApi
    /** Type-specific configuration beyond the prompt: `tags` for a classifier, `scale` for a scorer, optional `length` for a summarizer. Omit it for a monitor. `prompt` belongs in the `prompt` field and is rejected here. */
    scanner_config?: unknown
    /** Model to scan with. Determines what each observation costs in credits.
     *
     * * `gemini-3.5-flash-lite` - Gemini 3.5 Flash Lite
     * * `gemini-3-flash-preview` - Gemini 3 Flash
     * * `gemini-3.7-flash` - Gemini 3.7 Flash */
    model?: ScannerModelEnumApi
}

/**
 * `bulk_observe`'s partial-success shape plus the id to read the results back through.
 */
export interface InlineScanResponseApi {
    /** How many new scans were started. */
    started: number
    /** Per-session outcomes, in request order (deduplicated). */
    results: BulkObserveResultApi[]
    /**
     * Read results from `/vision/scanners/{scan_id}/observations/`. Stable for a given prompt and model, so asking the same question again returns the same id. Null when nothing was started and nothing existed to read, which happens when the quota is already used up.
     * @nullable
     */
    scan_id: string | null
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
     * The categories already configured, so suggestions never duplicate one the user has.
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
     * Only observations dispatched by this backfill.
     */
    backfill_id?: string
    /**
     * Only observations created at or after this time. Accepts ISO 8601 or a relative date like `-7d`; values without an explicit offset are interpreted in the project's timezone.
     */
    date_from?: string
    /**
     * Only observations created at or before this time. Accepts ISO 8601 or a relative date like `-1d`; date-only values include the whole day, interpreted in the project's timezone.
     */
    date_to?: string
    /**
     * When true, return only observations that have a shared label (thumbs up or down); when false, only unlabeled observations.
     */
    labeled?: string
    /**
     * Filter scorer observations to those scoring at or below this value. Rows with no numeric score (other scanner types, failed or in-flight runs) are excluded.
     */
    max_score?: number
    /**
     * Filter scorer observations to those scoring at or above this value. Rows with no numeric score (other scanner types, failed or in-flight runs) are excluded.
     */
    min_score?: number
    /**
     * Sort observations. Plain keys: created_at, started_at, completed_at, status, recording_subject_email. JSONB keys: result_score (scorer), result_verdict (monitor), result_confidence, scanner_version. Prefix with `-` for descending; nullable keys sort nulls last either way.
     */
    order_by?: string
    /**
     * Filter to observations whose person email contains this value (case-insensitive).
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
     * Filter by trigger source (schedule, on_demand, retry, or backfill). Accepts a comma-separated list.
     */
    triggered_by?: string
    /**
     * Filter monitor observations by verdict. Accepts a comma-separated list (e.g. `yes,inconclusive`).
     */
    verdict?: string
}

export type VisionObservationsSearchRetrieveParams = {
    /**
     * Maximum number of results (default 20, at most 50).
     * @minimum 1
     * @maximum 50
     */
    limit?: number
    /**
     * Keep only scorer observations with a score at or below this value.
     */
    max_score?: number
    /**
     * Keep only scorer observations with a score at or above this value.
     */
    min_score?: number
    /**
     * Natural-language description of what to find, e.g. 'users confused by the pricing page'.
     * @minLength 1
     * @maxLength 2000
     */
    q: string
    /**
     * Search a single scanner's observations. Defaults to every scanner you can read.
     */
    scanner_id?: string
    /**
     * Comma-separated classifier tags to keep. Matching is case- and format-insensitive. Unlike `verdict`, tags are not validated against a fixed list, so an unknown tag matches nothing.
     * @minLength 1
     */
    tags?: string
    /**
     * Comma-separated monitor verdicts to keep, e.g. `yes,inconclusive`.
     * @minLength 1
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
     * Filter to scanners whose targeting watches the given experiment.
     */
    experiment_id?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Sort scanners by name, created_at, updated_at, scanner_type, enabled, sampling_rate, created_by, credits_this_month. Prefix with `-` for descending.
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
    /**
     * Filter to scanners carrying at least one of the given tags (comma-separated).
     */
    tags?: string
}

export type VisionScannersImpactRetrieveParams = {
    /**
     * Scorer scanners only: count sessions scoring at or below this value.
     * @nullable
     */
    max_score?: number | null
    /**
     * Scorer scanners only: count sessions scoring at or above this value. Scorers require `min_score` and/or `max_score`. Not applicable to other scanner types.
     * @nullable
     */
    min_score?: number | null
    /**
     * Classifier scanners only, required for them: count sessions carrying this tag (fixed or freeform). Not applicable to other scanner types.
     * @maxLength 100
     * @nullable
     */
    tag?: string | null
    /**
     * Trailing window of observations to count. Defaults to 30 days.
     * @minimum 1
     * @maximum 90
     */
    window_days?: number
}

export type VisionScannersBackfillsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type VisionScannersObservationsListParams = {
    /**
     * Only observations dispatched by this backfill.
     */
    backfill_id?: string
    /**
     * Only observations created at or after this time. Accepts ISO 8601 or a relative date like `-7d`; values without an explicit offset are interpreted in the project's timezone.
     */
    date_from?: string
    /**
     * Only observations created at or before this time. Accepts ISO 8601 or a relative date like `-1d`; date-only values include the whole day, interpreted in the project's timezone.
     */
    date_to?: string
    /**
     * When true, return only observations that have a shared label (thumbs up or down); when false, only unlabeled observations.
     */
    labeled?: boolean
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * Filter scorer observations to those scoring at or below this value. Rows with no numeric score (other scanner types, failed or in-flight runs) are excluded.
     */
    max_score?: number
    /**
     * Filter scorer observations to those scoring at or above this value. Rows with no numeric score (other scanner types, failed or in-flight runs) are excluded.
     */
    min_score?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Sort observations. Plain keys: created_at, started_at, completed_at, status, recording_subject_email. JSONB keys: result_score (scorer), result_verdict (monitor), result_confidence, scanner_version. Prefix with `-` for descending; nullable keys sort nulls last either way.
     */
    order_by?: string
    /**
     * Filter to observations whose person email contains this value (case-insensitive).
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
     * Filter by trigger source (schedule, on_demand, retry, or backfill). Accepts a comma-separated list.
     */
    triggered_by?: string
    /**
     * Filter monitor observations by verdict. Accepts a comma-separated list (e.g. `yes,inconclusive`).
     */
    verdict?: string
}

export type VisionScannersObservationsRetrieveParams = {
    /**
     * Only observations dispatched by this backfill.
     */
    backfill_id?: string
    /**
     * Only observations created at or after this time. Accepts ISO 8601 or a relative date like `-7d`; values without an explicit offset are interpreted in the project's timezone.
     */
    date_from?: string
    /**
     * Only observations created at or before this time. Accepts ISO 8601 or a relative date like `-1d`; date-only values include the whole day, interpreted in the project's timezone.
     */
    date_to?: string
    /**
     * When true, return only observations that have a shared label (thumbs up or down); when false, only unlabeled observations.
     */
    labeled?: string
    /**
     * Filter scorer observations to those scoring at or below this value. Rows with no numeric score (other scanner types, failed or in-flight runs) are excluded.
     */
    max_score?: number
    /**
     * Filter scorer observations to those scoring at or above this value. Rows with no numeric score (other scanner types, failed or in-flight runs) are excluded.
     */
    min_score?: number
    /**
     * Sort observations. Plain keys: created_at, started_at, completed_at, status, recording_subject_email. JSONB keys: result_score (scorer), result_verdict (monitor), result_confidence, scanner_version. Prefix with `-` for descending; nullable keys sort nulls last either way.
     */
    order_by?: string
    /**
     * Filter to observations whose person email contains this value (case-insensitive).
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
     * Filter by trigger source (schedule, on_demand, retry, or backfill). Accepts a comma-separated list.
     */
    triggered_by?: string
    /**
     * Filter monitor observations by verdict. Accepts a comma-separated list (e.g. `yes,inconclusive`).
     */
    verdict?: string
}

export type VisionScannersObservationsStatsRetrieveParams = {
    /**
     * Only observations dispatched by this backfill.
     */
    backfill_id?: string
    /**
     * Only observations created at or after this time. Accepts ISO 8601 or a relative date like `-7d`; values without an explicit offset are interpreted in the project's timezone.
     */
    date_from?: string
    /**
     * Only observations created at or before this time. Accepts ISO 8601 or a relative date like `-1d`; date-only values include the whole day, interpreted in the project's timezone.
     */
    date_to?: string
    /**
     * When true, return only observations that have a shared label (thumbs up or down); when false, only unlabeled observations.
     */
    labeled?: string
    /**
     * Filter scorer observations to those scoring at or below this value. Rows with no numeric score (other scanner types, failed or in-flight runs) are excluded.
     */
    max_score?: number
    /**
     * Filter scorer observations to those scoring at or above this value. Rows with no numeric score (other scanner types, failed or in-flight runs) are excluded.
     */
    min_score?: number
    /**
     * Window size in days for the coverage `recent_sessions` count. Clamped to [1, 365]. Defaults to 14 when omitted.
     */
    recent_days?: number
    /**
     * Filter to observations whose person email contains this value (case-insensitive).
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
     * Filter by trigger source (schedule, on_demand, retry, or backfill). Accepts a comma-separated list.
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
