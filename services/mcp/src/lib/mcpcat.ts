import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { env } from 'cloudflare:workers'
import { track } from 'mcpcat'

/** Provider interface for resolving user/session identity. */
export type McpCatIdentityProvider = {
    getDistinctId: () => Promise<string>
    getSessionUuid: () => Promise<string | undefined>
    getMcpClientName: () => string | undefined
    getMcpClientVersion: () => string | undefined
    getMcpProtocolVersion: () => string | undefined
    getRegion: () => string | undefined
    getOrganizationId: () => string | undefined
    getProjectId: () => string | undefined
    getClientUserAgent: () => string | undefined
    getVersion: () => number | undefined
}

export function redactSensitiveInformation(text: string): string {
    return text.replace(/Bearer\s?[\w\-.]+/g, '<redacted>')
}

export async function initMcpCatObservability(server: McpServer, identity: McpCatIdentityProvider): Promise<void> {
    // MCPCat initialization must never block MCP server startup
    // and we don't even need to do anything if the API key or host is not set
    // This is properly set in production where we care about analytics
    const posthogApiKey = env.POSTHOG_ANALYTICS_API_KEY
    const posthogHost = env.POSTHOG_ANALYTICS_HOST
    if (!posthogApiKey || !posthogHost) {
        return
    }

    // Calculate these only once and include with every single event
    const eventProperties: Record<string, unknown> = {
        ai_product: 'mcp',
        mcp_version: identity.getVersion(),
        client_user_agent: identity.getClientUserAgent(),
        mcp_client_name: identity.getMcpClientName(),
        mcp_client_version: identity.getMcpClientVersion(),
        mcp_protocol_version: identity.getMcpProtocolVersion(),
        mcp_region: identity.getRegion(),
    }

    // For tags, we need to override MCPcat's default $session_id and $ai_session_id with our own
    // PostHog session UUID. $session_id drives Session Replay; $ai_session_id is what LLM Analytics
    // groups traces by — without overriding it, MCPcat's exporter falls back to `mcpcat_<ksuid>`.
    // We can't just do this with a single object because the type returned must be `Record<string, string>`,
    // so we need some shenanigans here.
    const sessionUuid = await identity.getSessionUuid()
    const eventTags: Record<string, string> = {}
    if (sessionUuid) {
        eventTags.$session_id = sessionUuid
        eventTags.$ai_session_id = sessionUuid
    }

    // Compute the distinct ID only once and include with every single event
    const distinctId = await identity.getDistinctId()
    const identifyResult = { userId: distinctId }

    try {
        // If the MCP_CAT_PROJECT_ID is not set, use null. This will disable sending events to MCPcat.
        // For production, we'll set this to the correct project ID.
        track(server, env.MCP_CAT_PROJECT_ID ?? null, {
            enableReportMissing: false,
            enableToolCallContext: false,
            enableTracing: true, // Tracks tools and usage patterns
            identify: async () => identifyResult,
            eventTags: () => eventTags,
            eventProperties: () => eventProperties,
            redactSensitiveInformation: (text) => Promise.resolve(redactSensitiveInformation(text)),
            exporters: {
                posthog: {
                    type: 'posthog',
                    apiKey: posthogApiKey,
                    host: posthogHost,
                    enableAITracing: true,
                },
            },
        })
    } catch {
        // MCPCat initialization must never block MCP server startup
    }
}
