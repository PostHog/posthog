/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface IncidentDTOApi {
    id: string
    monitor_id: string
    name: string
    description: string
    started_at: string
    /** @nullable */
    resolved_at: string | null
    resolution_note: string
    created_at: string
    updated_at: string
}

export interface PaginatedIncidentDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: IncidentDTOApi[]
}

export interface CreateIncidentApi {
    /** ID of the monitor this incident is attached to. */
    monitor_id: string
    /**
     * Short, human-readable incident title.
     * @maxLength 255
     */
    name: string
    /** Longer description of the incident, shown publicly. */
    description?: string
    /** When the incident started. Defaults to the time the incident was created. */
    started_at?: string
    /**
     * When the incident was resolved. Omit or null for an ongoing incident.
     * @nullable
     */
    resolved_at?: string | null
    /** Resolution note. Required when resolved_at is set. */
    resolution_note?: string
}

export interface PatchedUpdateIncidentApi {
    /**
     * Updated incident title.
     * @maxLength 255
     */
    name?: string
    /** Updated description of the incident. */
    description?: string
    /** Updated start time of the incident. */
    started_at?: string
    /**
     * When the incident was resolved. Null means the incident is still ongoing.
     * @nullable
     */
    resolved_at?: string | null
    /** Note explaining how the incident was resolved. */
    resolution_note?: string
}

export interface ResolveIncidentApi {
    /** Required note explaining how the incident was resolved. Shown on the public status page. */
    resolution_note: string
}

/**
 * * `auto` - auto
 * `manual` - manual
 */
export type MonitorModeApi = (typeof MonitorModeApi)[keyof typeof MonitorModeApi]

export const MonitorModeApi = {
    Auto: 'auto',
    Manual: 'manual',
} as const

export interface MonitorDTOApi {
    id: string
    name: string
    /** @nullable */
    url: string | null
    mode: MonitorModeApi
    created_at: string
}

export interface PaginatedMonitorDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: MonitorDTOApi[]
}

export interface CreateMonitorApi {
    /**
     * Human-readable name of the monitor.
     * @maxLength 255
     */
    name: string
    /**
     * HTTP(S) URL to ping (every minute in auto mode). Required when mode='auto', optional when mode='manual'.
     * @maxLength 2048
     * @nullable
     */
    url?: string | null
    /** Monitor tracking mode. 'auto' (default) means PostHog pings the URL on a recurring schedule and computes uptime / latency from the pings. 'manual' means uptime is assumed 100% until you declare an incident on the monitor — useful for tracking internal services or third-party dependencies without a public health endpoint.

  * `auto` - auto
  * `manual` - manual */
    mode?: MonitorModeApi
}

/**
 * * `up` - up
 * `down` - down
 * `no_data` - no_data
 */
export type MonitorSummaryDTOStatusEnumApi =
    (typeof MonitorSummaryDTOStatusEnumApi)[keyof typeof MonitorSummaryDTOStatusEnumApi]

export const MonitorSummaryDTOStatusEnumApi = {
    Up: 'up',
    Down: 'down',
    NoData: 'no_data',
} as const

/**
 * * `success` - SUCCESS
 * `failure` - FAILURE
 */
export type PingOutcomeApi = (typeof PingOutcomeApi)[keyof typeof PingOutcomeApi]

export const PingOutcomeApi = {
    Success: 'success',
    Failure: 'failure',
} as const

/**
 * * `up` - up
 * `degraded` - degraded
 * `down` - down
 * `no_data` - no_data
 */
export type DailyBucketDTOStatusEnumApi = (typeof DailyBucketDTOStatusEnumApi)[keyof typeof DailyBucketDTOStatusEnumApi]

export const DailyBucketDTOStatusEnumApi = {
    Up: 'up',
    Degraded: 'degraded',
    Down: 'down',
    NoData: 'no_data',
} as const

export interface DailyBucketDTOApi {
    date: string
    total: number
    failed: number
    status: DailyBucketDTOStatusEnumApi
}

export interface MonitorSummaryDTOApi {
    id: string
    name: string
    /** @nullable */
    url: string | null
    mode: MonitorModeApi
    created_at: string
    status: MonitorSummaryDTOStatusEnumApi
    /** @nullable */
    uptime_90d: number | null
    /** @nullable */
    avg_latency_24h_ms: number | null
    /** @nullable */
    last_ping_at: string | null
    last_ping_outcome: PingOutcomeApi | null
    daily_buckets: DailyBucketDTOApi[]
}

export interface PatchedUpdateMonitorApi {
    /**
     * New human-readable name of the monitor.
     * @maxLength 255
     */
    name?: string
    /**
     * New HTTP(S) URL. Required when the resulting mode is 'auto'.
     * @maxLength 2048
     * @nullable
     */
    url?: string | null
    /** Monitor tracking mode. 'auto' (default) means PostHog pings the URL on a recurring schedule and computes uptime / latency from the pings. 'manual' means uptime is assumed 100% until you declare an incident on the monitor — useful for tracking internal services or third-party dependencies without a public health endpoint.

  * `auto` - auto
  * `manual` - manual */
    mode?: MonitorModeApi
}

export interface OutageDTOApi {
    monitor_id: string
    started_at: string
    /** @nullable */
    resolved_at: string | null
    fail_count: number
    /** @nullable */
    last_status_code: number | null
}

export interface PaginatedOutageDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: OutageDTOApi[]
}

export interface PingDTOApi {
    monitor_id: string
    timestamp: string
    latency_ms: number
    /** @nullable */
    status_code: number | null
    outcome: PingOutcomeApi
}

export interface PaginatedPingDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: PingDTOApi[]
}

export interface BulkCreateMonitorItemApi {
    /**
     * Human-readable name of the monitor.
     * @maxLength 255
     */
    name: string
    /**
     * HTTP(S) URL to ping every minute.
     * @maxLength 2048
     */
    url: string
}

export interface BulkCreateMonitorApi {
    /** List of monitors to create. All-or-nothing: created atomically. */
    monitors: BulkCreateMonitorItemApi[]
}

export interface ReorderMonitorsApi {
    /** Monitor IDs in their desired display order. Position 0 renders first. */
    ordered_ids: string[]
}

export interface SuggestedUrlDTOApi {
    url: string
    host: string
    event_count: number
    unique_paths: number
    last_seen: string
}

export interface PaginatedSuggestedUrlDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: SuggestedUrlDTOApi[]
}

export interface PaginatedMonitorSummaryDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: MonitorSummaryDTOApi[]
}

export interface StatusPageDTOApi {
    id: string
    title: string
    slug: string
    monitor_ids: string[]
    is_published: boolean
    /** @nullable */
    published_at: string | null
    created_at: string
    updated_at: string
}

export interface PaginatedStatusPageDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: StatusPageDTOApi[]
}

export interface PatchedUpdateStatusPageApi {
    /**
     * Human-readable title of the status page, shown publicly above the monitor list.
     * @maxLength 255
     */
    title?: string
    /**
     * URL slug used in the public URL /status/<slug>. Must be globally unique.
     * @maxLength 64
     */
    slug?: string
    /** Ordered list of monitor IDs to display on this status page. Order is preserved. */
    monitor_ids?: string[]
}

export type UptimeIncidentsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * When provided, only incidents for this monitor are returned.
     */
    monitor_id?: string
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type UptimeMonitorsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type UptimeMonitorsOutagesListParams = {
    /**
     * Look-back window in days. Defaults to 7.
     */
    days?: number
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type UptimeMonitorsPingsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type UptimeMonitorsBulkCreateCreateParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type UptimeMonitorsSuggestedUrlsListParams = {
    /**
     * Look-back window in days. Defaults to 30.
     */
    days?: number
    /**
     * Maximum number of suggestions to return. Defaults to 20.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type UptimeMonitorsSummaryListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type UptimeStatusPagesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
