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

    // Stable per-MCP-session fallback UUID. `identity.getSessionUuid()` returns
    // undefined for clients that don't pass `?sessionId=...` in the URL — see the
    // matching note in `posthog-mcp-analytics.ts`.
    const sessionUuidFallback = crypto.randomUUID()

    try {
        // If the MCP_CAT_PROJECT_ID is not set, use null. This will disable sending events to MCPcat.
        // For production, we'll set this to the correct project ID.
        track(server, env.MCP_CAT_PROJECT_ID ?? null, {
            enableReportMissing: false,
            enableToolCallContext: false,
            enableTracing: true, // Tracks tools and usage patterns
            identify: async () => identifyResult,
            // mcpcat's eventTags pipeline silently drops our `$ai_session_id` override (it
            // works for `$session_id` only because mcpcat itself sets `$session_id` via
            // `toUUIDv7(event.sessionId)` and the call-site value happens to match ours).
            // For `$ai_session_id` we set it via `eventProperties` below — that spreads
            // LAST in both `buildCaptureEvent` and `buildAISpanEvent` inside mcpcat, winning
            // collisions against the hardcoded `mcpcat_<ksuid>` default for `$ai_span` and
            // adding the property on event types where it would otherwise be unset
            // (`mcp_tool_call`, `mcp_initialize`, `mcp_tools_list`).
            eventTags: async () => {
                const sessionUuid = (await identity.getSessionUuid()) ?? sessionUuidFallback
                return {
                    $session_id: sessionUuid,
                }
            },
            // Recomputed per event so workspace switches (via `switch-project` / `switch-organization`)
            // are reflected on subsequent events without a reinit.
            eventProperties: async () => {
                const [
                    sessionUuidRaw,
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
                    identity.getSessionUuid(),
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

                const sessionUuid = sessionUuidRaw ?? sessionUuidFallback

                // `$groups` is the raw event-payload key; mcpcat doesn't expose a typed
                // `groups` option, so we set it directly alongside the other properties.
                const groups = {
                    ...(analyticsContext?.organizationId ? { organization: analyticsContext.organizationId } : {}),
                    ...(analyticsContext?.projectUuid ? { project: analyticsContext.projectUuid } : {}),
                }

                const result: Record<string, unknown> = {
                    // Set here (not in `eventTags`) so it actually lands on `mcp_tool_call`
                    // and other non-AI event types — see the comment on `eventTags` above.
                    ...(sessionUuid ? { $ai_session_id: sessionUuid } : {}),
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

                // #region debug log (H2 fix verification - post-fix)
                fetch('http://127.0.0.1:7874/ingest/938e5110-8a29-4ce6-ab7e-fdcb908d6c91', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-Debug-Session-Id': '6c81f2' },
                    body: JSON.stringify({
                        sessionId: '6c81f2',
                        runId: 'post-fix',
                        hypothesisId: 'C',
                        location: 'mcpcat.ts:eventProperties:return',
                        message: 'mcpcat eventProperties fired (post-fix)',
                        data: {
                            has_sessionUuid: !!sessionUuid,
                            sessionUuid_len: sessionUuid ? String(sessionUuid).length : 0,
                            returns_ai_session_id: '$ai_session_id' in result,
                            mcp_client_name: mcpClientName ?? null,
                            used_fallback: !sessionUuidRaw,
                        },
                        timestamp: Date.now(),
                    }),
                }).catch(() => {})
                // #endregion

                return result
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
