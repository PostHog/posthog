import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'

import { env } from '@/lib/env'

import { getPostHogClient } from './client'

export enum AnalyticsEvent {
    MCP_INIT = 'mcp init',
    MCP_PROJECT_SWITCHED = 'mcp project switched',
    MCP_ORGANIZATION_SWITCHED = 'mcp organization switched',
    MCP_TOOL_CALL = 'mcp_tool_call', // matching @posthog/mcp-analytics
    MCP_FEEDBACK_SUBMITTED = 'mcp feedback submitted',
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

// Provider interface for resolving user/session identity and workspace context.
export type IdentityProvider = {
    getDistinctId: () => Promise<string>
    getMcpClientName: () => Promise<string | undefined>
    getMcpClientVersion: () => Promise<string | undefined>
    getMcpProtocolVersion: () => Promise<string | undefined>
    // Per-request `x-anthropic-client` value. Distinct from `mcpClientName`:
    // tracks the live inner client on pooled MCP transports.
    getMcpVendorClient: () => Promise<string | undefined>
    getRegion: () => Promise<string | undefined>
    getAnalyticsContext: () => Promise<MCPAnalyticsContext | undefined>
    getClientUserAgent: () => Promise<string | undefined>
    getOAuthClientName: () => Promise<string | undefined>
    getReadOnly: () => Promise<boolean | undefined>
    getTransport: () => Promise<string | undefined>
    getMcpConsumer: () => Promise<string | undefined>
    getMcpMode: () => Promise<string | undefined>
    // PostHog-side session UUID. Resolved from the wrapper-app `?sessionId=`
    // query hint via `SessionManager.getSessionUuid()` and used as `$session_id`
    // / `$ai_session_id` to drive Session Replay and AI observability grouping.
    // Only set when a wrapping consumer app supplied the hint.
    getSessionUuid: () => Promise<string | undefined>
    // Streamable-HTTP transport session id from the inbound `Mcp-Session-Id`
    // header. Distinct from `getSessionUuid()` above: this one is minted by
    // the MCP server per the protocol spec and is available on (almost) every
    // request, whereas `getSessionUuid()` only resolves when a wrapper app
    // also supplied a `?sessionId=` hint. Emitted on events as `mcp_session_id`.
    getMcpSessionId: () => Promise<string | undefined>
    // Agent-echoed conversation id from `@posthog/mcp-analytics` PR #14
    // (`enableConversationId: true`). Persists across transport reconnects.
    // Sourced from tool-call arguments by the SDK; we scaffold the property
    // here so it lands on events once the SDK is bumped. Returns undefined
    // until that wiring is in place.
    getMcpConversationId: () => Promise<string | undefined>
}

type McpAnalyticsOptions = {
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

export type McpAnalyticsInitResult =
    | {
          action: 'initialized'
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

async function buildEventTags(identity: IdentityProvider): Promise<Record<string, string>> {
    const sessionUuid = await identity.getSessionUuid()
    if (!sessionUuid) {
        return {}
    }

    return {
        $session_id: sessionUuid,
        $ai_session_id: sessionUuid,
    }
}

export async function buildEventProperties(identity: IdentityProvider): Promise<Record<string, unknown>> {
    const [
        clientUserAgent,
        mcpClientName,
        mcpClientVersion,
        mcpProtocolVersion,
        mcpVendorClient,
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
        identity.getClientUserAgent(),
        identity.getMcpClientName(),
        identity.getMcpClientVersion(),
        identity.getMcpProtocolVersion(),
        identity.getMcpVendorClient(),
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
        $mcp_version: MCP_ANALYTICS_VERSION,
        $mcp_client_user_agent: clientUserAgent,
        $mcp_client_name: mcpClientName,
        $mcp_client_version: mcpClientVersion,
        mcp_vendor_client: mcpVendorClient,
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

export function redactSensitiveInformation(text: string): string {
    return text.replace(/Bearer\s?[\w\-.]+/g, '<redacted>')
}

export async function initMcpAnalytics(
    server: McpServer,
    identity: IdentityProvider,
    options: McpAnalyticsOptions = { contextEnabled: false, reportMissingEnabled: false }
): Promise<McpAnalyticsInitResult> {
    const { POSTHOG_ANALYTICS_API_KEY: posthogApiKey, POSTHOG_ANALYTICS_HOST: posthogHost } = env
    if (!posthogApiKey || !posthogHost) {
        return {
            action: 'skipped',
            reason: 'missing_config',
            hasApiKey: !!posthogApiKey,
            hasHost: !!posthogHost,
        }
    }

    try {
        const { track } = await import('@posthog/mcp-analytics') // Import only if needed
        const distinctId = await identity.getDistinctId()

        track(server, {
            posthogClient: getPostHogClient(),
            context: options.contextEnabled,
            enableAITracing: true,
            enableConversationId: false,
            enableTracing: true,
            identify: { userId: distinctId },
            reportMissing: options.reportMissingEnabled,
            eventTags: () => buildEventTags(identity),
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

        return { action: 'initialized' }
    } catch (error) {
        return {
            action: 'failed',
            errorName: error instanceof Error ? error.name : 'UnknownError',
            errorMessage: error instanceof Error ? error.message : String(error),
        }
    }
}
