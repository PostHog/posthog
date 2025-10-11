import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import type { Context } from '@/tools/types'
import { registerIntegrationResources } from './integration'

// Re-export ResourceUri for external consumers
export { ResourceUri } from './integration'

/**
 * Registers all PostHog resources with the MCP server
 */
export function registerResources(server: McpServer, context: Context) {
    // Register all integration-related resources
    registerIntegrationResources(server, context)
}
