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
 * * `generating` - Generating
 * * `delivered` - Delivered
 * * `failed` - Failed
 */
export type PulseDigestStatusEnumApi = (typeof PulseDigestStatusEnumApi)[keyof typeof PulseDigestStatusEnumApi]

export const PulseDigestStatusEnumApi = {
    Pending: 'pending',
    Generating: 'generating',
    Delivered: 'delivered',
    Failed: 'failed',
} as const

export interface PulseDigestListApi {
    readonly id: string
    readonly period_start: string
    readonly period_end: string
    /** Lifecycle of this scan run (pending, generating, delivered, failed).
     *
     * * `pending` - Pending
     * * `generating` - Generating
     * * `delivered` - Delivered
     * * `failed` - Failed */
    readonly status: PulseDigestStatusEnumApi
    /** Error payload (with a `message`) if the scan run failed, otherwise null. */
    readonly error: unknown
    readonly created_at: string
    /** Number of findings in this digest. */
    readonly finding_count: number
    /** Digest-level big-picture synthesis across findings (LLM-written, may be empty). */
    readonly summary: string
}

export interface PaginatedPulseDigestListListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: PulseDigestListApi[]
}

export interface PulseFindingApi {
    readonly id: string
    readonly digest: string
    /** Human-readable name of the metric this finding is about. */
    readonly metric_label: string
    /** Opaque descriptor (source, label, query) Pulse re-evaluates. */
    readonly metric_descriptor: unknown
    /** Metric value for the current period. */
    readonly current_value: number
    /** Baseline median over the configured baseline window. */
    readonly baseline_value: number
    /** Fractional change vs baseline median, e.g. 0.5 means +50%. */
    readonly change_pct: number
    /** Robust z-score (median/MAD based). Secondary signal only, never a sole trigger. */
    readonly robust_z: number
    /** Ranking score: abs(change_pct) * sqrt(baseline_median). */
    readonly impact: number
    /** Breakdown segment that best explains the change, e.g. {'$browser': 'Safari'}, or null. */
    readonly attribution_breakdown: unknown
    /** Supporting evidence: {'series': [...]} recent weekly values, {'daily_series': [...]} daily values across the period for the finding chart, {'session_ids': [...]} for example replays, and/or {'references': [{type, label, timestamp, id?, change?}]} for the related changes (feature flags, experiments, annotations) the narrative tied to this finding — each timestamped so it can be placed on the finding's timeline, or null. */
    readonly evidence: unknown
    /** LLM-generated explanation of the change. */
    readonly narrative: string
    readonly chart_thumbnail_url: string
    readonly rank: number
    readonly created_at: string
}

export interface PulseDigestApi {
    readonly id: string
    readonly period_start: string
    readonly period_end: string
    /** Lifecycle of this scan run (pending, generating, delivered, failed).
     *
     * * `pending` - Pending
     * * `generating` - Generating
     * * `delivered` - Delivered
     * * `failed` - Failed */
    readonly status: PulseDigestStatusEnumApi
    /** Temporal workflow run id that produced this digest. */
    readonly workflow_run_id: string
    /** Error payload if the scan run failed, otherwise null. */
    readonly error: unknown
    /** Digest-level big-picture synthesis across findings (LLM-written, may be empty). */
    readonly summary: string
    readonly created_at: string
    readonly finding_count: number
    readonly findings: readonly PulseFindingApi[]
}

/**
 * Per-run scan tuning knobs for a manual staff trigger.
 *
 * Every field is optional; omitted knobs fall back to the built-in defaults (the production
 * constants), so a partial override is "defaults plus the knobs you set". Nothing is persisted —
 * the resolved config rides along with the one-off scan that started it.
 */
export interface PulseScanConfigApi {
    /**
     * Cap on total metrics scanned per run.
     * @minimum 1
     * @maximum 1000
     */
    max_candidates?: number
    /**
     * Lookback window for recently-accessed dashboards and recently-viewed insights.
     * @minimum 1
     * @maximum 365
     */
    recent_days?: number
    /**
     * Minimum distinct viewers for the recently-viewed-insights source to include an insight.
     * @minimum 1
     * @maximum 100
     */
    min_viewers_for_recent_insight?: number
    /**
     * Max insights from pinned/recent dashboards (0 = off).
     * @minimum 0
     * @maximum 200
     */
    dashboard_tile_limit?: number
    /**
     * Max recently-viewed insights (0 = off).
     * @minimum 0
     * @maximum 500
     */
    recent_insight_limit?: number
    /**
     * Max recently-edited saved Trends insights (0 = off).
     * @minimum 0
     * @maximum 200
     */
    saved_insight_limit?: number
    /**
     * Max highest-volume events (0 = off).
     * @minimum 0
     * @maximum 500
     */
    top_event_limit?: number
    /**
     * Volume floor: skip metrics whose baseline median is below this (the top noise lever).
     * @minimum 0
     * @maximum 1000000
     */
    min_baseline_value?: number
    /**
     * Primary gate: minimum absolute fractional change to flag (0.25 = 25%).
     * @minimum 0.01
     * @maximum 10
     */
    min_change_pct?: number
    /**
     * Secondary informational threshold for the robust z-score. Never a sole trigger.
     * @minimum 0.1
     * @maximum 10
     */
    robust_z_threshold?: number
    /**
     * Completed weeks used to compute the baseline median.
     * @minimum 3
     * @maximum 12
     */
    baseline_weeks?: number
    /**
     * Maximum findings surfaced per digest.
     * @minimum 1
     * @maximum 50
     */
    max_findings?: number
}

export interface TriggerScanResponseApi {
    workflow_id: string
}

export interface PaginatedPulseFindingListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: PulseFindingApi[]
}

/**
 * * `weekly` - Weekly
 * * `daily` - Daily
 */
export type PulseSubscriptionFrequencyEnumApi =
    (typeof PulseSubscriptionFrequencyEnumApi)[keyof typeof PulseSubscriptionFrequencyEnumApi]

export const PulseSubscriptionFrequencyEnumApi = {
    Weekly: 'weekly',
    Daily: 'daily',
} as const

/**
 * * `change_v1` - Change V1
 * * `discovery` - Discovery
 */
export type DetectionModeEnumApi = (typeof DetectionModeEnumApi)[keyof typeof DetectionModeEnumApi]

export const DetectionModeEnumApi = {
    ChangeV1: 'change_v1',
    Discovery: 'discovery',
} as const

/**
 * * `conservative` - Conservative
 * * `balanced` - Balanced
 * * `sensitive` - Sensitive
 * * `custom` - Custom
 */
export type SensitivityEnumApi = (typeof SensitivityEnumApi)[keyof typeof SensitivityEnumApi]

export const SensitivityEnumApi = {
    Conservative: 'conservative',
    Balanced: 'balanced',
    Sensitive: 'sensitive',
    Custom: 'custom',
} as const

export interface PulseSubscriptionApi {
    readonly id: string
    /** Whether Pulse runs scans for this team. */
    enabled?: boolean
    /** Scan cadence (weekly or daily).
     *
     * * `weekly` - Weekly
     * * `daily` - Daily */
    frequency?: PulseSubscriptionFrequencyEnumApi
    /** Detection algorithm. Only 'change_v1' is available in v1.
     *
     * * `change_v1` - Change V1
     * * `discovery` - Discovery */
    detection_mode?: DetectionModeEnumApi
    /** Preset that derives thresholds, or 'custom' to use the raw knobs. Gates only the deterministic metric scan — anomalies surfaced by the AI scout bypass these thresholds.
     *
     * * `conservative` - Conservative
     * * `balanced` - Balanced
     * * `sensitive` - Sensitive
     * * `custom` - Custom */
    sensitivity?: SensitivityEnumApi
    /**
     * Primary gate: minimum absolute fractional change to flag (0.0-1.0).
     * @minimum 0
     * @maximum 1
     */
    min_change_pct?: number
    /**
     * Number of completed weeks used to compute the baseline median.
     * @minimum 3
     * @maximum 52
     */
    baseline_weeks?: number
    /**
     * Maximum findings surfaced per digest.
     * @minimum 1
     * @maximum 50
     */
    max_findings?: number
    /**
     * Secondary informational threshold for the robust z-score. Never a sole trigger.
     * @minimum 0.1
     * @maximum 10
     */
    robust_z_threshold?: number
    /**
     * When Pulse last completed a scan for this team.
     * @nullable
     */
    readonly last_scan_at: string | null
    /**
     * When the next scan is scheduled.
     * @nullable
     */
    readonly next_scan_at: string | null
    readonly created_at: string
}

export interface PaginatedPulseSubscriptionListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: PulseSubscriptionApi[]
}

export interface PatchedPulseSubscriptionApi {
    readonly id?: string
    /** Whether Pulse runs scans for this team. */
    enabled?: boolean
    /** Scan cadence (weekly or daily).
     *
     * * `weekly` - Weekly
     * * `daily` - Daily */
    frequency?: PulseSubscriptionFrequencyEnumApi
    /** Detection algorithm. Only 'change_v1' is available in v1.
     *
     * * `change_v1` - Change V1
     * * `discovery` - Discovery */
    detection_mode?: DetectionModeEnumApi
    /** Preset that derives thresholds, or 'custom' to use the raw knobs. Gates only the deterministic metric scan — anomalies surfaced by the AI scout bypass these thresholds.
     *
     * * `conservative` - Conservative
     * * `balanced` - Balanced
     * * `sensitive` - Sensitive
     * * `custom` - Custom */
    sensitivity?: SensitivityEnumApi
    /**
     * Primary gate: minimum absolute fractional change to flag (0.0-1.0).
     * @minimum 0
     * @maximum 1
     */
    min_change_pct?: number
    /**
     * Number of completed weeks used to compute the baseline median.
     * @minimum 3
     * @maximum 52
     */
    baseline_weeks?: number
    /**
     * Maximum findings surfaced per digest.
     * @minimum 1
     * @maximum 50
     */
    max_findings?: number
    /**
     * Secondary informational threshold for the robust z-score. Never a sole trigger.
     * @minimum 0.1
     * @maximum 10
     */
    robust_z_threshold?: number
    /**
     * When Pulse last completed a scan for this team.
     * @nullable
     */
    readonly last_scan_at?: string | null
    /**
     * When the next scan is scheduled.
     * @nullable
     */
    readonly next_scan_at?: string | null
    readonly created_at?: string
}

/**
 * A single metric Pulse is currently watching (read-only transparency).
 */
export interface PulseWatchedCandidateApi {
    /** Where the candidate came from (dashboard_tile, recent_insight, top_event). */
    source: string
    /**
     * Underlying insight/event id, if any.
     * @nullable
     */
    source_id: string | null
    /** Human-readable metric name. */
    label: string
    /** TrendsQuery-shaped dict Pulse re-evaluates. */
    query: unknown
}

export interface PaginatedPulseWatchedCandidateListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: PulseWatchedCandidateApi[]
}

export type PulseDigestsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type PulseFindingsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type PulseSubscriptionsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
