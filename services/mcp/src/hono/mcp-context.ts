import type { RequestProperties } from '@/lib/request-properties'
import type { McpMode } from '@/lib/utils'

export type MCPClientContext = Pick<
    RequestProperties,
    'mcpClientName' | 'mcpClientVersion' | 'mcpProtocolVersion' | 'mcpConsumer' | 'mcpVendorClient'
> & {
    mode?: McpMode | undefined
}

export type MCPRequestContext = MCPClientContext &
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
    >

export type MCPSessionContext = MCPClientContext

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
        mcp_session_mode: sessionContext.mode,
        mcp_session_vendor_client: sessionContext.mcpVendorClient,
    }
}

export function getEffectiveMCPClientContext(
    requestContext: MCPRequestContext,
    sessionContext: MCPSessionContext | null
): MCPClientContext {
    return sessionContext ?? requestContext
}
