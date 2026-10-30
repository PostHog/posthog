export enum AnalyticsEvent {
    MCP_PROJECT_SWITCHED = 'mcp project switched',
    MCP_ORGANIZATION_SWITCHED = 'mcp organization switched',
    MCP_TOOL_CALL = '$mcp_tool_call',
    MCP_FEEDBACK_SUBMITTED = 'mcp feedback submitted',
}

// Emitted as `$mcp_version` / `mcp_version` on analytics events. The MCP server
// no longer branches on a request version (v2 fully rolled out); this constant
// keeps the property stable for dashboards that already filter on it.
export const MCP_ANALYTICS_VERSION = 2

// Matches the truncation the MCP analytics queries apply to `$mcp_error_type`.
const MAX_ERROR_TOKEN_LENGTH = 200

export type MCPAnalyticsContext = {
    organizationId?: string
    projectId?: string
    projectUuid?: string
    projectName?: string
    /** The project's `ingested_event`; absent when the project could not be read. */
    projectHasData?: boolean
}

/**
 * Build PostHog `$groups` from resolved workspace context. Uses `projectUuid`
 * (not the numeric team id) as the `project` group key to match the convention
 * in `posthog/event_usage.py` so MCP events join with the rest of the product
 * in group-level analytics.
 */
export const buildMCPAnalyticsGroups = ({
    organizationId,
    projectUuid,
}: MCPAnalyticsContext): Record<string, string> => ({
    ...(organizationId ? { organization: organizationId } : {}),
    ...(projectUuid ? { project: projectUuid } : {}),
})

/**
 * Convert the workspace context (camelCase) into snake_case event properties.
 * Single source of truth for this mapping — every callsite that would otherwise
 * hand-roll `{ organization_id, project_id, project_uuid, project_name }` should
 * go through this helper so adding a field is a one-touch change.
 *
 * `prefix` is used to emit `previous_*` properties on context-switch events.
 */
export const buildMCPContextProperties = (
    ctx: MCPAnalyticsContext,
    { prefix = '' }: { prefix?: string } = {}
): Record<string, string | boolean> => ({
    ...(ctx.organizationId ? { [`${prefix}organization_id`]: ctx.organizationId } : {}),
    ...(ctx.projectId ? { [`${prefix}project_id`]: ctx.projectId } : {}),
    ...(ctx.projectUuid ? { [`${prefix}project_uuid`]: ctx.projectUuid } : {}),
    ...(ctx.projectName ? { [`${prefix}project_name`]: ctx.projectName } : {}),
    ...(ctx.projectHasData !== undefined ? { [`${prefix}mcp_project_has_data`]: ctx.projectHasData } : {}),
})

/**
 * Backend error codes and DRF field paths come from server code, never caller
 * values, but they cross a network boundary. Strip control characters and cap
 * the length so a malformed body can't pollute the property.
 */
export function sanitizeErrorToken(token: string): string | undefined {
    const sanitized = token
        .replace(/[\x00-\x1f\x7f]/g, '')
        .trim()
        .slice(0, MAX_ERROR_TOKEN_LENGTH)
    return sanitized || undefined
}
