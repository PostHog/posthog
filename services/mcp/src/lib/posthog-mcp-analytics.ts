import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'

import { env } from '@/lib/env'
import { type McpCatIdentityProvider, redactSensitiveInformation } from '@/lib/mcpcat'

export type PostHogMcpAnalyticsIdentityProvider = McpCatIdentityProvider

export type PostHogMcpAnalyticsOptions = {
    contextEnabled: boolean
    // Gate `get_more_tools` registration on non-single-exec mode. With the full
    // tool roster registered, a missing-tool report maps to a real gap in the
    // catalog. In single-exec mode the wrapper handles every call, so the
    // signal has nothing to map to and the extra slot is just noise.
    reportMissingEnabled: boolean
    // In single-exec mode, every event's `$mcp_tool_name` is `exec` — the real
    // tool the LLM was invoking lives inside `arguments.command`. This callback
    // lets the caller resolve that inner tool's name + description from the
    // request so they can be surfaced as `$mcp_exec_tool_call_name` /
    // `$mcp_exec_tool_call_description`. Returns undefined when the request
    // isn't an exec call or the inner tool isn't recognized. Type accepts
    // `| undefined` explicitly so callers can pass the value through
    // unconditionally under `exactOptionalPropertyTypes: true`.
    resolveExecInnerToolCall?: ((request: unknown) => { name: string; description: string } | undefined) | undefined
    // In single-exec mode the SDK's $mcp_listed_tool_names on mcp_tools_list
    // collapses to just the dispatcher's name (`exec`) because that's the
    // only tool the server actually advertises over MCP. Passing the full
    // inner-tool catalog here lets us attach the inner names on tools/list
    // events as $mcp_exec_inner_tool_names so dashboards can compute the
    // "advertised but never called" diff against $mcp_exec_tool_call_name
    // from mcp_tool_call events.
    execInnerToolNames?: readonly string[] | undefined
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

async function buildEventTags(identity: PostHogMcpAnalyticsIdentityProvider): Promise<Record<string, string>> {
    const sessionUuid = await identity.getSessionUuid()
    if (!sessionUuid) {
        return {}
    }

    return {
        $session_id: sessionUuid,
        $ai_session_id: sessionUuid,
    }
}

async function buildEventProperties(identity: PostHogMcpAnalyticsIdentityProvider): Promise<Record<string, unknown>> {
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
        mcpSessionId,
        mcpConversationId,
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
        identity.getMcpSessionId(),
        identity.getMcpConversationId(),
    ])

    const groups = {
        ...(analyticsContext?.organizationId ? { organization: analyticsContext.organizationId } : {}),
        ...(analyticsContext?.projectUuid ? { project: analyticsContext.projectUuid } : {}),
    }

    return {
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
        $mcp_session_id: mcpSessionId,
        $mcp_conversation_id: mcpConversationId,
        ...(Object.keys(groups).length > 0 ? { $groups: groups } : {}),
    }
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

        track(server, {
            apiKey: posthogApiKey,
            context: options.contextEnabled,
            enableAITracing: true,
            enableConversationId: true,
            enableTracing: true,
            host: posthogHost,
            identify: async () => identifyResult,
            posthogOptions: {
                flushAt: 1,
                flushInterval: 0,
                host: posthogHost,
            },
            reportMissing: options.reportMissingEnabled,
            eventTags: async () => buildEventTags(identity),
            eventProperties: async (request) => {
                const base = await buildEventProperties(identity)
                const innerToolCall = options.resolveExecInnerToolCall?.(request)
                const isListToolsRequest =
                    (request as { method?: unknown })?.method === 'tools/list' &&
                    !!options.execInnerToolNames &&
                    options.execInnerToolNames.length > 0
                return {
                    ...base,
                    ...(innerToolCall
                        ? {
                              $mcp_exec_tool_call_name: innerToolCall.name,
                              $mcp_exec_tool_call_description: innerToolCall.description,
                          }
                        : {}),
                    ...(isListToolsRequest
                        ? { $mcp_exec_inner_tool_names: [...(options.execInnerToolNames ?? [])] }
                        : {}),
                }
            },
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
