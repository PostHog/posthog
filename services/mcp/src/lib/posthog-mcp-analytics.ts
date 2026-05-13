import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { env } from 'cloudflare:workers'

import { type McpCatIdentityProvider, redactSensitiveInformation } from '@/lib/mcpcat'

export type PostHogMcpAnalyticsIdentityProvider = McpCatIdentityProvider

export type PostHogMcpAnalyticsOptions = {
    contextEnabled: boolean
    // Gate `get_more_tools` registration on non-single-exec mode. With the full
    // tool roster registered, a missing-tool report maps to a real gap in the
    // catalog. In single-exec mode the wrapper handles every call, so the
    // signal has nothing to map to and the extra slot is just noise.
    reportMissingEnabled: boolean
}

export type PostHogMcpAnalyticsInitResult =
    | {
          action: 'initialized'
          contextEnabled: boolean
          tracingEnabled: true
          aiTracingEnabled: true
          reportMissingEnabled: boolean
      }
    | {
          action: 'skipped'
          reason: 'missing_config'
          hasApiKey: boolean
          hasHost: boolean
      }
    | {
          action: 'failed'
          errorName: string
          errorMessage: string
      }

// `$ai_session_id` is set in `buildEventProperties` rather than here. The
// upstream mcpcat exporter (which `@posthog/mcp-analytics` mirrors) only
// sets `$ai_session_id` on `$ai_span` events with a hardcoded
// `mcpcat_<ksuid>` default, and our `eventTags` override silently fails to
// win the spread on both `mcp_tool_call` and `$ai_span`. Using
// `eventProperties` instead lands the value on every event type, because
// `event.properties` is spread last in both `buildCaptureEvent` and
// `buildAISpanEvent`.
async function buildEventTags(
    identity: PostHogMcpAnalyticsIdentityProvider,
    sessionUuidFallback: string
): Promise<Record<string, string>> {
    const sessionUuid = (await identity.getSessionUuid()) ?? sessionUuidFallback

    // #region debug log (H2 fix verification - post-fix)
    fetch('http://127.0.0.1:7874/ingest/938e5110-8a29-4ce6-ab7e-fdcb908d6c91', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Debug-Session-Id': '6c81f2' },
        body: JSON.stringify({
            sessionId: '6c81f2',
            runId: 'post-fix',
            hypothesisId: 'A',
            location: 'posthog-mcp-analytics.ts:buildEventTags:return',
            message: 'buildEventTags fired (post-fix)',
            data: { sessionUuid_len: sessionUuid.length, used_fallback: !(await identity.getSessionUuid()) },
            timestamp: Date.now(),
        }),
    }).catch(() => {})
    // #endregion

    return {
        $session_id: sessionUuid,
    }
}

async function buildEventProperties(
    identity: PostHogMcpAnalyticsIdentityProvider,
    sessionUuidFallback: string
): Promise<Record<string, unknown>> {
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

    const groups = {
        ...(analyticsContext?.organizationId ? { organization: analyticsContext.organizationId } : {}),
        ...(analyticsContext?.projectUuid ? { project: analyticsContext.projectUuid } : {}),
    }

    const result: Record<string, unknown> = {
        // Set here (not in `buildEventTags`) so it lands on `mcp_tool_call`
        // and other non-AI event types — see comment on `buildEventTags`.
        ...(sessionUuid ? { $ai_session_id: sessionUuid } : {}),
        $ai_product: 'mcp',
        $mcp_version: mcpVersion,
        $mcp_client_user_agent: clientUserAgent,
        $mcp_client_name: mcpClientName,
        $mcp_client_version: mcpClientVersion,
        $mcp_protocol_version: mcpProtocolVersion,
        $mcp_region: mcpRegion,
        $mcp_organization_id: analyticsContext?.organizationId,
        $mcp_project_id: analyticsContext?.projectId,
        $mcp_project_uuid: analyticsContext?.projectUuid,
        $mcp_project_name: analyticsContext?.projectName,
        $mcp_oauth_client_name: oauthClientName,
        $mcp_read_only: readOnly,
        $mcp_transport: transport,
        $mcp_consumer: mcpConsumer,
        $mcp_mode: mcpMode,
        ...(Object.keys(groups).length > 0 ? { $groups: groups } : {}),
    }

    // #region debug log (H2 fix verification - post-fix)
    fetch('http://127.0.0.1:7874/ingest/938e5110-8a29-4ce6-ab7e-fdcb908d6c91', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Debug-Session-Id': '6c81f2' },
        body: JSON.stringify({
            sessionId: '6c81f2',
            runId: 'post-fix',
            hypothesisId: 'A',
            location: 'posthog-mcp-analytics.ts:buildEventProperties:return',
            message: 'buildEventProperties fired (post-fix)',
            data: {
                has_sessionUuid: !!sessionUuid,
                sessionUuid_len: sessionUuid ? String(sessionUuid).length : 0,
                returns_ai_session_id: '$ai_session_id' in result,
                result_ai_session_id_present: result.$ai_session_id !== undefined,
                mcp_client_name: mcpClientName ?? null,
                key_count: Object.keys(result).length,
                used_fallback: !sessionUuidRaw,
            },
            timestamp: Date.now(),
        }),
    }).catch(() => {})
    // #endregion

    return result
}

export async function initPostHogMcpAnalytics(
    server: McpServer,
    identity: PostHogMcpAnalyticsIdentityProvider,
    options: PostHogMcpAnalyticsOptions = { contextEnabled: false, reportMissingEnabled: false }
): Promise<PostHogMcpAnalyticsInitResult> {
    const posthogApiKey = env.POSTHOG_ANALYTICS_API_KEY
    const posthogHost = env.POSTHOG_ANALYTICS_HOST
    if (!posthogApiKey || !posthogHost) {
        return {
            action: 'skipped',
            reason: 'missing_config',
            hasApiKey: !!posthogApiKey,
            hasHost: !!posthogHost,
        }
    }

    try {
        const { track } = await import('@posthog/mcp-analytics')
        const distinctId = await identity.getDistinctId()
        const identifyResult = { userId: distinctId }

        // Stable per-MCP-session fallback UUID. `identity.getSessionUuid()` returns
        // undefined for clients that don't pass `?sessionId=...` in the URL (most
        // streamable-http MCP clients like cursor-vscode, claude-code via mcp-remote
        // do not). Without this fallback our `$ai_session_id` override would silently
        // drop on every event, leaving the library's hardcoded prefixed default
        // (`posthog_mcp_analytics_<ksuid>`) for `$ai_span` and nothing on `mcp_tool_call`.
        const sessionUuidFallback = crypto.randomUUID()

        track(server, {
            apiKey: posthogApiKey,
            context: options.contextEnabled,
            enableAITracing: true,
            enableTracing: true,
            host: posthogHost,
            identify: async () => identifyResult,
            posthogOptions: {
                flushAt: 1,
                flushInterval: 0,
                host: posthogHost,
            },
            reportMissing: options.reportMissingEnabled,
            eventTags: async () => buildEventTags(identity, sessionUuidFallback),
            eventProperties: async () => buildEventProperties(identity, sessionUuidFallback),
            redactSensitiveInformation: (text) => Promise.resolve(redactSensitiveInformation(text)),
        })

        return {
            action: 'initialized',
            contextEnabled: options.contextEnabled,
            tracingEnabled: true,
            aiTracingEnabled: true,
            reportMissingEnabled: options.reportMissingEnabled,
        }
    } catch (error) {
        return {
            action: 'failed',
            errorName: error instanceof Error ? error.name : 'UnknownError',
            errorMessage: error instanceof Error ? error.message : String(error),
        }
    }
}
