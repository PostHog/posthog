/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface MonitorDTOApi {
    id: string
    name: string
    url: string
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
     * HTTP(S) URL to ping every 5 minutes.
     * @maxLength 2048
     */
    url: string
}

export interface PatchedUpdateMonitorApi {
    /**
     * New human-readable name of the monitor.
     * @maxLength 255
     */
    name?: string
    /**
     * New HTTP(S) URL to ping every 5 minutes.
     * @maxLength 2048
     */
    url?: string
}

/**
 * * `success` - SUCCESS
 * `failure` - FAILURE
 */
export type PingOutcomeApi = (typeof PingOutcomeApi)[keyof typeof PingOutcomeApi]

export const PingOutcomeApi = {
    Success: 'success',
    Failure: 'failure',
} as const

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
     * HTTP(S) URL to ping every 5 minutes.
     * @maxLength 2048
     */
    url: string
}

export interface BulkCreateMonitorApi {
    /** List of monitors to create. All-or-nothing: created atomically. */
    monitors: BulkCreateMonitorItemApi[]
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
    url: string
    created_at: string
    status: MonitorSummaryDTOStatusEnumApi
    /** @nullable */
    uptime_30d: number | null
    /** @nullable */
    avg_latency_24h_ms: number | null
    /** @nullable */
    last_ping_at: string | null
    last_ping_outcome: PingOutcomeApi | null
    daily_buckets: DailyBucketDTOApi[]
}

export interface PaginatedMonitorSummaryDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: MonitorSummaryDTOApi[]
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
