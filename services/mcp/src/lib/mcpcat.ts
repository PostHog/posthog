import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { track } from 'mcpcat'

import { POSTHOG_API_KEY, POSTHOG_HOST } from './analytics'
import { CUSTOM_API_BASE_URL } from './constants'

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

export function initMcpCatObservability(server: McpServer, identity: McpCatIdentityProvider): void {
    // MCPcat analytics is only for PostHog Cloud, not self-hosted instances
    if (CUSTOM_API_BASE_URL) {
        return
    }

    try {
        track(server, null, {
            enableReportMissing: false,
            enableToolCallContext: false,
            enableTracing: true,
            identify: async () => {
                try {
                    const distinctId = await identity.getDistinctId()
                    const region = identity.getRegion()
                    const organizationId = identity.getOrganizationId()
                    const projectId = identity.getProjectId()
                    return {
                        userId: distinctId,
                        userData: {
                            ...(region ? { region } : {}),
                            ...(organizationId ? { organization_id: organizationId } : {}),
                            ...(projectId ? { project_id: projectId } : {}),
                        },
                    }
                } catch {
                    return null
                }
            },
            eventTags: async () => {
                const tags: Record<string, string> = {}
                // Override MCPcat's default $session_id with our own PostHog session UUID.
                // To use MCPcat's built-in session ID logic instead, remove this override.
                const sessionUuid = await identity.getSessionUuid()
                if (sessionUuid) {
                    tags.$session_id = sessionUuid
                }
                const clientName = identity.getMcpClientName()
                if (clientName) {
                    tags.mcp_client_name = clientName
                }
                const clientVersion = identity.getMcpClientVersion()
                if (clientVersion) {
                    tags.mcp_client_version = clientVersion
                }
                const protocolVersion = identity.getMcpProtocolVersion()
                if (protocolVersion) {
                    tags.mcp_protocol_version = protocolVersion
                }
                const region = identity.getRegion()
                if (region) {
                    tags.region = region
                }
                const organizationId = identity.getOrganizationId()
                if (organizationId) {
                    tags.organization_id = organizationId
                }
                const projectId = identity.getProjectId()
                if (projectId) {
                    tags.project_id = projectId
                }
                return tags
            },
            eventProperties: () => {
                const props: Record<string, unknown> = {}
                const version = identity.getVersion()
                if (version != null) {
                    props.mcp_version = version
                }
                const userAgent = identity.getClientUserAgent()
                if (userAgent) {
                    props.client_user_agent = userAgent
                }
                return props
            },
            exporters: {
                posthog: {
                    type: 'posthog',
                    apiKey: POSTHOG_API_KEY,
                    host: POSTHOG_HOST,
                    enableAITracing: true,
                },
            },
        })
    } catch {
        // MCPCat initialization must never block MCP server startup
    }
}
