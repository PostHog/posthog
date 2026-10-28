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
 * * `GET` - GET
 * * `HEAD` - HEAD
 */
export type UptimeMonitorMethodEnumApi = (typeof UptimeMonitorMethodEnumApi)[keyof typeof UptimeMonitorMethodEnumApi]

export const UptimeMonitorMethodEnumApi = {
    Get: 'GET',
    Head: 'HEAD',
} as const

export interface UptimeMonitorApi {
    /** Unique identifier of the monitor. */
    id: string
    /** Project the monitor belongs to. */
    team_id: number
    /** Display name for the monitor. */
    name: string
    /** The http or https URL to check. */
    url: string
    /** HTTP method used for each check.
     *
     * * `GET` - GET
     * * `HEAD` - HEAD */
    method: UptimeMonitorMethodEnumApi
    /** Seconds between checks, a whole number of minutes from 60 to 86400. */
    interval_seconds: number
    /** Seconds to wait for a response before the check fails, from 1 to 10. */
    timeout_seconds: number
    /** Whether checks run for this monitor. */
    enabled: boolean
    /** When the monitor was created. */
    created_at: string
    /** When the monitor was last changed. */
    updated_at: string
}

export interface PaginatedUptimeMonitorListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: UptimeMonitorApi[]
}

export interface CreateUptimeMonitorInputApi {
    /**
     * The http or https URL to check.
     * @maxLength 2048
     */
    url: string
    /**
     * Display name for the monitor.
     * @maxLength 255
     */
    name: string
    /** HTTP method used for each check.
     *
     * * `GET` - GET
     * * `HEAD` - HEAD */
    method?: UptimeMonitorMethodEnumApi
    /**
     * Seconds between checks, a whole number of minutes from 60 to 86400.
     * @minimum 60
     * @maximum 86400
     */
    interval_seconds?: number
    /**
     * Seconds to wait for a response before the check fails, from 1 to 10.
     * @minimum 1
     * @maximum 10
     */
    timeout_seconds?: number
    /** Whether checks run for this monitor. */
    enabled?: boolean
}

export interface PatchedUpdateUptimeMonitorInputApi {
    /**
     * The http or https URL to check.
     * @maxLength 2048
     */
    url?: string
    /**
     * Display name for the monitor.
     * @maxLength 255
     */
    name?: string
    /** HTTP method used for each check.
     *
     * * `GET` - GET
     * * `HEAD` - HEAD */
    method?: UptimeMonitorMethodEnumApi
    /**
     * Seconds between checks, a whole number of minutes from 60 to 86400.
     * @minimum 60
     * @maximum 86400
     */
    interval_seconds?: number
    /**
     * Seconds to wait for a response before the check fails, from 1 to 10.
     * @minimum 1
     * @maximum 10
     */
    timeout_seconds?: number
    /** Whether checks run for this monitor. */
    enabled?: boolean
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
