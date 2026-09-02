import { classifyAuthMethod, type McpAuthMethod } from '@/lib/auth-method'
import type { RequestProperties } from '@/lib/request-properties'
import type { McpMode } from '@/lib/utils'

export interface MCPClientContext extends Pick<
    RequestProperties,
    'mcpClientName' | 'mcpClientVersion' | 'mcpProtocolVersion' | 'mcpConsumer' | 'mcpVendorClient'
> {}

export interface MCPRequestContext
    extends
        MCPClientContext,
        Pick<
            RequestProperties,
            | 'sessionId'
            | 'organizationId'
            | 'projectId'
            | 'readOnly'
            | 'viaSseRedirect'
            | 'requestStartTime'
            | 'clientUserAgent'
            | 'transport'
            | 'mcpSessionId'
            | 'mcpConversationId'
            | 'region'
        > {
    mode?: McpMode | undefined
    authMethod: McpAuthMethod
}

// Identical shape to MCPClientContext but tracked separately to mark values
// pinned to the MCP session id rather than the live request.
export interface MCPSessionContext extends MCPClientContext {}

export function buildMCPRequestContext(props: RequestProperties): MCPRequestContext {
    return {
        sessionId: props.sessionId,
        organizationId: props.organizationId,
        projectId: props.projectId,
        readOnly: props.readOnly,
        viaSseRedirect: props.viaSseRedirect,
        requestStartTime: props.requestStartTime,
        clientUserAgent: props.clientUserAgent,
        mcpClientName: props.mcpClientName,
        mcpClientVersion: props.mcpClientVersion,
        mcpProtocolVersion: props.mcpProtocolVersion,
        transport: props.transport,
        mcpSessionId: props.mcpSessionId,
        mcpConversationId: props.mcpConversationId,
        mcpConsumer: props.mcpConsumer,
        mode: props.mode,
        region: props.region,
        mcpVendorClient: props.mcpVendorClient,
        authMethod: classifyAuthMethod(props.apiToken),
    }
}

export function buildMCPSessionAnalyticsProperties(sessionContext: MCPSessionContext | null): Record<string, unknown> {
    if (!sessionContext) {
        return {}
    }

    return {
        mcp_session_client_name: sessionContext.mcpClientName,
        mcp_session_client_version: sessionContext.mcpClientVersion,
        mcp_session_protocol_version: sessionContext.mcpProtocolVersion,
        mcp_session_consumer: sessionContext.mcpConsumer,
        mcp_session_vendor_client: sessionContext.mcpVendorClient,
    }
}

export function getEffectiveMCPClientContext(
    requestContext: MCPRequestContext,
    sessionContext: MCPSessionContext | null
): MCPClientContext {
    return sessionContext ?? requestContext
}

/**
 * Per-field live-first coalesce for the identity properties captured on every MCP
 * analytics event. `clientInfo` only arrives on the `initialize` handshake (or, for
 * stateless requests, `params._meta['io.modelcontextprotocol/clientInfo']`), so a
 * `tools/call` in the middle of a session has no live client name — without a
 * fallback, `$mcp_client_name` goes out empty on every non-initialize event.
 *
 * This must stay per-field rather than whole-object (unlike
 * `getEffectiveMCPClientContext`, which is session-first and fine for that because
 * it drives session-scoped tool behavior): a single server multiplexes concurrent
 * requests from different clients, so a live value on this request always wins
 * over a possibly-stale session-pinned one, and only a genuinely absent field falls
 * back. Mirrors the `@posthog/mcp` SDK's own capture-side precedence
 * (`packages/mcp/src/extensions/capture.ts`) and the read-path classifier's field
 * order (`mcp_harness.py`: `$mcp_client_name` before `mcp_session_client_name`).
 */
export function getEffectiveMCPClientIdentity(
    requestContext: MCPRequestContext,
    sessionContext: MCPSessionContext | null
): MCPClientContext {
    return {
        mcpClientName: requestContext.mcpClientName ?? sessionContext?.mcpClientName,
        mcpClientVersion: requestContext.mcpClientVersion ?? sessionContext?.mcpClientVersion,
        mcpProtocolVersion: requestContext.mcpProtocolVersion ?? sessionContext?.mcpProtocolVersion,
        mcpConsumer: requestContext.mcpConsumer ?? sessionContext?.mcpConsumer,
        mcpVendorClient: requestContext.mcpVendorClient ?? sessionContext?.mcpVendorClient,
    }
}
