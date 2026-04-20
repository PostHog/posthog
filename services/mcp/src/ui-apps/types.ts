/**
 * Shared types for MCP UI Apps.
 *
 * This module defines the types for data passed between the MCP server
 * and UI apps via structuredContent.
 */

// ============================================================================
// Analytics metadata - passed from MCP server to UI apps for user tracking
// ============================================================================

/**
 * Analytics metadata included in tool results from the MCP server.
 * This is automatically added to structuredContent for tools with UI resources.
 */
export interface AnalyticsMetadata {
    /** The user's PostHog distinct ID */
    distinctId: string
    /** The name of the tool that generated this result */
    toolName?: string
}

// ============================================================================
// Type utilities for tool results
// ============================================================================

/**
 * Helper type to wrap any data type with analytics metadata.
 * Use this when defining tool result types that include analytics.
 *
 * @example
 * type MyToolResult = WithAnalytics<{
 *     query: TrendsQuery
 *     results: TrendsResult
 * }>
 */
export type WithAnalytics<T> = T & {
    _analytics?: AnalyticsMetadata
}

/**
 * Extract the data type from a tool result, excluding analytics metadata.
 * Useful when you want to work with just the payload data without analytics.
 */
export type ExtractData<T> = Omit<T, '_analytics'>

/**
 * Type guard to check if a value has analytics metadata.
 */
export function hasAnalytics<T>(value: T): value is T & { _analytics: AnalyticsMetadata } {
    return (
        value !== null &&
        typeof value === 'object' &&
        '_analytics' in value &&
        typeof (value as Record<string, unknown>)._analytics === 'object' &&
        (value as Record<string, unknown>)._analytics !== null &&
        'distinctId' in ((value as Record<string, unknown>)._analytics as object)
    )
}

/**
 * Extract analytics metadata from a tool result if present.
 */
export function extractAnalytics<T>(value: T): AnalyticsMetadata | undefined {
    if (hasAnalytics(value)) {
        return value._analytics
    }
    return undefined
}
