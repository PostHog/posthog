/**
 * Analytics properties recording the page size and volume buckets an error
 * tracking issues list call asked for.
 *
 * `query-error-tracking-issues-list` is the most called error tracking tool, and a
 * small share of its calls return most of its output tokens. Without these
 * properties `$mcp_tool_call` cannot say whether a large page (`limit`) or many
 * volume buckets per row (`volumeResolution`) made a response large.
 *
 * Both values are bounded integers from the tool's own schema, never caller text.
 * `args` is the parsed input, so schema defaults apply and an omitted field is
 * recorded as the default the handler sent. Malformed input yields no properties
 * rather than throwing — analytics must never break a tool call.
 */

export const ERROR_TRACKING_ISSUES_LIST_TOOL = 'query-error-tracking-issues-list'

/** A whole, non-negative number — anything else did not reach the API as sent. */
function recordableCount(value: unknown): number | undefined {
    return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : undefined
}

export function errorTrackingAnalyticsProperties(toolName: string | undefined, args: unknown): Record<string, unknown> {
    if (toolName !== ERROR_TRACKING_ISSUES_LIST_TOOL) {
        return {}
    }
    if (args === null || typeof args !== 'object' || Array.isArray(args)) {
        return {}
    }
    const { limit: limitArg, volumeResolution: volumeResolutionArg } = args as Record<string, unknown>
    const limit = recordableCount(limitArg)
    const volumeResolution = recordableCount(volumeResolutionArg)
    return {
        ...(limit !== undefined ? { error_tracking_limit: limit } : {}),
        ...(volumeResolution !== undefined ? { error_tracking_volume_resolution: volumeResolution } : {}),
    }
}
