import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import type { Context } from '@/tools/types'
import { registerIntegrationResources } from './integration'

// Re-export ResourceUri for external consumers
export { ResourceUri } from './integration'

export function registerResources(server: McpServer, context: Context) {
    registerIntegrationResources(server, context)
}
