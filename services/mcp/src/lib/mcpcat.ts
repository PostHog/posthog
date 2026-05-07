import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { env } from 'cloudflare:workers'
import { track } from 'mcpcat'

import type { MCPAnalyticsContext } from '@/lib/analytics'

/** Provider interface for resolving user/session identity and workspace context. */
export type McpCatIdentityProvider = {
    getDistinctId: () => Promise<string>
    getSessionUuid: () => Promise<string | undefined>
    getMcpClientName: () => Promise<string | undefined>
    getMcpClientVersion: () => Promise<string | undefined>
    getMcpProtocolVersion: () => Promise<string | undefined>
    getRegion: () => Promise<string | undefined>
    getAnalyticsContext: () => Promise<MCPAnalyticsContext | undefined>
    getClientUserAgent: () => Promise<string | undefined>
    getMcpVersion: () => Promise<number | undefined>
    getOAuthClientName: () => Promise<string | undefined>
    getReadOnly: () => Promise<boolean | undefined>
    getTransport: () => Promise<string | undefined>
    getMcpConsumer: () => Promise<string | undefined>
    getMcpMode: () => Promise<string | undefined>
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
            // For tags, we need to override MCPcat's default $session_id and $ai_session_id with our
            // own PostHog session UUID. $session_id drives Session Replay; $ai_session_id is what
            // LLM Analytics groups traces by — without overriding it, MCPcat's exporter falls back
            // to `mcpcat_<ksuid>`. Recomputed per event so a late-bound session UUID is picked up.
            eventTags: async () => {
                const sessionUuid = await identity.getSessionUuid()
                if (!sessionUuid) {
                    return {}
                }

                return {
                    $session_id: sessionUuid,
                    $ai_session_id: sessionUuid,
                }
            },
            // Recomputed per event so workspace switches (via `switch-project` / `switch-organization`)
            // are reflected on subsequent events without a reinit.
            eventProperties: async () => {
                const [
                    mcpVersion,
                    clientUserAgent,
                    mcpClientName,
                    mcpClientVersion,
                    mcpProtocolVersion,
                    mcpRegion,
                    analyticsContext,
                    oauthClientName,
                    readOnly,
                    transport,
                    mcpConsumer,
                    mcpMode,
                ] = await Promise.all([
                    identity.getMcpVersion(),
                    identity.getClientUserAgent(),
                    identity.getMcpClientName(),
                    identity.getMcpClientVersion(),
                    identity.getMcpProtocolVersion(),
                    identity.getRegion(),
                    identity.getAnalyticsContext(),
                    identity.getOAuthClientName(),
                    identity.getReadOnly(),
                    identity.getTransport(),
                    identity.getMcpConsumer(),
                    identity.getMcpMode(),
                ])

                // `$groups` is the raw event-payload key; mcpcat doesn't expose a typed
                // `groups` option, so we set it directly alongside the other properties.
                const groups = {
                    ...(analyticsContext?.organizationId ? { organization: analyticsContext.organizationId } : {}),
                    ...(analyticsContext?.projectUuid ? { project: analyticsContext.projectUuid } : {}),
                }

                return {
                    ai_product: 'mcp',
                    mcp_version: mcpVersion,
                    client_user_agent: clientUserAgent,
                    mcp_client_name: mcpClientName,
                    mcp_client_version: mcpClientVersion,
                    mcp_protocol_version: mcpProtocolVersion,
                    mcp_region: mcpRegion,
                    organization_id: analyticsContext?.organizationId,
                    project_id: analyticsContext?.projectId,
                    project_uuid: analyticsContext?.projectUuid,
                    project_name: analyticsContext?.projectName,
                    mcp_oauth_client_name: oauthClientName,
                    read_only: readOnly,
                    mcp_transport: transport,
                    mcp_consumer: mcpConsumer,
                    mcp_mode: mcpMode,
                    ...(Object.keys(groups).length > 0 ? { $groups: groups } : {}),
                }
            },
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
