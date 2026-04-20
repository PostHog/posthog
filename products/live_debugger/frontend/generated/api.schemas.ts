/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface LiveDebuggerBreakpointApi {
    readonly id: string
    /** @nullable */
    repository?: string | null
    filename: string
    /**
     * @minimum 0
     * @maximum 2147483647
     */
    line_number: number
    enabled?: boolean
    /** @nullable */
    condition?: string | null
    readonly created_at: string
    readonly updated_at: string
}

export interface PaginatedLiveDebuggerBreakpointListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: LiveDebuggerBreakpointApi[]
}

/**
 * Schema for a single active breakpoint
 */
export interface ActiveBreakpointApi {
    /** Unique identifier for the breakpoint */
    id: string
    /**
     * Repository identifier (e.g., 'PostHog/posthog')
     * @nullable
     */
    repository?: string | null
    /** File path where the breakpoint is set */
    filename: string
    /** Line number of the breakpoint */
    line_number: number
    /** Whether the breakpoint is enabled */
    enabled: boolean
    /**
     * Optional condition for the breakpoint
     * @nullable
     */
    condition?: string | null
}

/**
 * Response schema for active breakpoints endpoint
 */
export interface ActiveBreakpointsResponseApi {
    /** List of active breakpoints */
    breakpoints: ActiveBreakpointApi[]
}

/**
 * Local variables at the time of the hit
 */
export type BreakpointHitApiVariables = { [key: string]: unknown }

/**
 * Schema for a single breakpoint hit event
 */
export interface BreakpointHitApi {
    /** Unique identifier for the hit event */
    id: string
    /** Line number where the breakpoint was hit */
    lineNumber: number
    /** Name of the function where breakpoint was hit */
    functionName: string
    /** When the breakpoint was hit */
    timestamp: string
    /** Local variables at the time of the hit */
    variables: BreakpointHitApiVariables
    /** Stack trace at the time of the hit */
    stackTrace: unknown[]
    /** ID of the breakpoint that was hit */
    breakpoint_id: string
    /** Filename where the breakpoint was hit */
    filename: string
}

/**
 * Response schema for breakpoint hits endpoint
 */
export interface BreakpointHitsResponseApi {
    /** List of breakpoint hit events */
    results: BreakpointHitApi[]
    /** Number of results returned */
    count: number
    /** Whether there are more results available */
    has_more: boolean
}

export type LiveDebuggerBreakpointsListParams = {
    filename?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    repository?: string
}

export type LiveDebuggerBreakpointsActiveRetrieveParams = {
    /**
     * Only return enabled breakpoints
     */
    enabled?: boolean
    /**
     * Filter breakpoints for a specific file
     */
    filename?: string
    /**
     * Filter breakpoints for a specific repository (e.g., 'PostHog/posthog')
     */
    repository?: string
}

export type LiveDebuggerBreakpointsBreakpointHitsRetrieveParams = {
    /**
     * Filter hits for specific breakpoints (repeat parameter for multiple IDs, e.g., ?breakpoint_ids=uuid1&breakpoint_ids=uuid2)
     */
    breakpoint_ids?: string
    /**
     * Number of hits to return (default: 100, max: 1000)
     */
    limit?: number
    /**
     * Pagination offset for retrieving additional results (default: 0)
     */
    offset?: number
}
