import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { track } from 'mcpcat'

const POSTHOG_API_KEY = 'sTMFPsFhdP1Ssg'
const POSTHOG_HOST = 'https://us.i.posthog.com'

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
    try {
        track(server, null, {
            enableReportMissing: false,
            enableToolCallContext: false,
            enableTracing: true,
            identify: async () => {
                try {
                    const distinctId = await identity.getDistinctId()
                    const sessionUuid = await identity.getSessionUuid()

                    return {
                        userId: distinctId,
                        userData: {
                            ...(sessionUuid ? { $session_id: sessionUuid } : {}),
                            ...(identity.getMcpClientName() ? { mcp_client_name: identity.getMcpClientName() } : {}),
                            ...(identity.getMcpClientVersion()
                                ? { mcp_client_version: identity.getMcpClientVersion() }
                                : {}),
                            ...(identity.getMcpProtocolVersion()
                                ? { mcp_protocol_version: identity.getMcpProtocolVersion() }
                                : {}),
                            ...(identity.getRegion() ? { region: identity.getRegion() } : {}),
                            ...(identity.getOrganizationId() ? { organization_id: identity.getOrganizationId() } : {}),
                            ...(identity.getProjectId() ? { project_id: identity.getProjectId() } : {}),
                            ...(identity.getClientUserAgent()
                                ? { client_user_agent: identity.getClientUserAgent() }
                                : {}),
                            ...(identity.getVersion() != null ? { mcp_version: identity.getVersion() } : {}),
                        },
                    }
                } catch {
                    return null
                }
            },
            exporters: {
                posthog: {
                    type: 'posthog',
                    apiKey: POSTHOG_API_KEY,
                    host: POSTHOG_HOST,
                },
            },
        })
    } catch {
        // MCPCat initialization must never block MCP server startup
    }
}
