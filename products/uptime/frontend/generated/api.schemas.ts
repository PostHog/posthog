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

/**
 * * `up` - up
 * * `down` - down
 * * `no_data` - no_data
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
 * * `failure` - FAILURE
 */
export type PingOutcomeApi = (typeof PingOutcomeApi)[keyof typeof PingOutcomeApi]

export const PingOutcomeApi = {
    Success: 'success',
    Failure: 'failure',
} as const

/**
 * * `up` - up
 * * `degraded` - degraded
 * * `down` - down
 * * `no_data` - no_data
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
     * New HTTP(S) URL to ping.
     * @maxLength 2048
     */
    url?: string
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

export interface PingDTOApi {
    monitor_id: string
    timestamp: string
    latency_ms: number
    /** @nullable */
    status_code: number | null
    outcome: PingOutcomeApi
}

export type UptimeMonitorsOutagesListParams = {
    /**
     * Look-back window in days. Defaults to 7.
     */
    days?: number
}
