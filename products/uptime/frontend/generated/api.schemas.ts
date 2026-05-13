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

/**
 * * `success` - SUCCESS
 * `failure` - FAILURE
 */
export type OutcomeEnumApi = (typeof OutcomeEnumApi)[keyof typeof OutcomeEnumApi]

export const OutcomeEnumApi = {
    Success: 'success',
    Failure: 'failure',
} as const

export interface PingDTOApi {
    monitor_id: string
    timestamp: string
    latency_ms: number
    /** @nullable */
    status_code: number | null
    outcome: OutcomeEnumApi
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
