import type { PostHogMCP } from '@posthog/mcp-analytics'

export enum AnalyticsEvent {
    MCP_PROJECT_SWITCHED = 'mcp project switched',
    MCP_ORGANIZATION_SWITCHED = 'mcp organization switched',
    MCP_TOOL_CALL = '$mcp_tool_call',
    MCP_FEEDBACK_SUBMITTED = 'mcp feedback submitted',
}

/**
 * The name the analytics SDK advertises its missing-capability virtual tool under.
 *
 * The SDK owns that name and does not export it, so read it back from the tool list it
 * prepares. A configured `missingCapabilityToolName` is then honored instead of assumed,
 * which keeps every dispatcher accepting exactly the name `tools/list` advertised. Takes the
 * client rather than resolving it, because the runtimes that need this hold their own.
 * Returns undefined when the SDK appends no tool, and callers then treat the name as unknown.
 */
export function missingCapabilityToolName(client: PostHogMCP): string | undefined {
    try {
        const [descriptor] = client.prepareToolList<{ name: string }>([], { reportMissing: true })
        return descriptor?.name
    } catch {
        return undefined
    }
}

// Emitted as `$mcp_version` / `mcp_version` on analytics events. The MCP server
// no longer branches on a request version (v2 fully rolled out); this constant
// keeps the property stable for dashboards that already filter on it.
export const MCP_ANALYTICS_VERSION = 2

export type MCPAnalyticsContext = {
    organizationId?: string
    projectId?: string
    projectUuid?: string
    projectName?: string
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
): Record<string, string> => ({
    ...(ctx.organizationId ? { [`${prefix}organization_id`]: ctx.organizationId } : {}),
    ...(ctx.projectId ? { [`${prefix}project_id`]: ctx.projectId } : {}),
    ...(ctx.projectUuid ? { [`${prefix}project_uuid`]: ctx.projectUuid } : {}),
    ...(ctx.projectName ? { [`${prefix}project_name`]: ctx.projectName } : {}),
})
