import { env } from 'cloudflare:workers'
import { PostHog } from 'posthog-node'

let _client: PostHog | undefined

export enum AnalyticsEvent {
    MCP_INIT = 'mcp init',
    MCP_PROJECT_SWITCHED = 'mcp project switched',
    MCP_ORGANIZATION_SWITCHED = 'mcp organization switched',
    MCP_TOOL_CALL = 'mcp_tool_call', // matching mcpcat
    MCP_FEEDBACK_SUBMITTED = 'mcp feedback submitted',
}

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

export const getPostHogClient = (): PostHog => {
    if (!_client) {
        _client = new PostHog(env.POSTHOG_ANALYTICS_API_KEY, {
            disabled: !env.POSTHOG_ANALYTICS_API_KEY || !env.POSTHOG_ANALYTICS_HOST, // Disable if the API key or host is not set
            host: env.POSTHOG_ANALYTICS_HOST,
            flushAt: 1,
            flushInterval: 0,
        })
    }

    return _client
}

export async function isFeatureFlagEnabled(flagKey: string, distinctId: string): Promise<boolean> {
    try {
        const client = getPostHogClient()
        const result = await client.isFeatureEnabled(flagKey, distinctId)
        return result === true
    } catch {
        return false
    }
}

/**
 * Evaluate multiple feature flags in parallel for the given user.
 * Returns a map of flag key → boolean.
 */
export async function evaluateFeatureFlags(flagKeys: string[], distinctId: string): Promise<Record<string, boolean>> {
    if (flagKeys.length === 0) {
        return {}
    }

    const results = await Promise.all(
        flagKeys.map(async (key) => {
            const enabled = await isFeatureFlagEnabled(key, distinctId)
            return [key, enabled] as const
        })
    )

    return Object.fromEntries(results)
}
