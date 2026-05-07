import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { env } from 'cloudflare:workers'

import { type McpCatIdentityProvider, redactSensitiveInformation } from '@/lib/mcpcat'

export type PostHogMcpAnalyticsIdentityProvider = McpCatIdentityProvider

export type PostHogMcpAnalyticsOptions = {
    contextEnabled: boolean
}

export type PostHogMcpAnalyticsInitResult =
    | {
          action: 'initialized'
          contextEnabled: boolean
          tracingEnabled: true
          aiTracingEnabled: true
          reportMissingEnabled: true
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
        ...(Object.keys(groups).length > 0 ? { $groups: groups } : {}),
    }
}

export async function initPostHogMcpAnalytics(
    server: McpServer,
    identity: PostHogMcpAnalyticsIdentityProvider,
    options: PostHogMcpAnalyticsOptions = { contextEnabled: false }
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
            enableTracing: true,
            host: posthogHost,
            identify: async () => identifyResult,
            posthogOptions: {
                flushAt: 1,
                flushInterval: 0,
                host: posthogHost,
            },
            reportMissing: true,
            eventTags: async () => buildEventTags(identity),
            eventProperties: async () => buildEventProperties(identity),
            redactSensitiveInformation: (text) => Promise.resolve(redactSensitiveInformation(text)),
        })

        return {
            action: 'initialized',
            contextEnabled: options.contextEnabled,
            tracingEnabled: true,
            aiTracingEnabled: true,
            reportMissingEnabled: true,
        }
    } catch (error) {
        return {
            action: 'failed',
            errorName: error instanceof Error ? error.name : 'UnknownError',
            errorMessage: error instanceof Error ? error.message : String(error),
        }
    }
}
