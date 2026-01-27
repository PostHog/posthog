import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { RESOURCE_MIME_TYPE } from '@modelcontextprotocol/ext-apps/server'

import { QUERY_VISUALIZER_RESOURCE_URI } from './ui-apps-constants'

// Import bundled HTML at build time (wrangler Text rule)
import queryVisualizerHtml from '../../ui-apps-dist/src/ui-apps/app/index.html'

/**
 * Registers UI app resources with the MCP server.
 * These resources provide interactive visualizations for query results
 * in MCP clients that support ext-apps (like Claude Desktop).
 */
export async function registerUiAppResources(server: McpServer): Promise<void> {
    server.registerResource(
        'PostHog Query Visualizer',
        QUERY_VISUALIZER_RESOURCE_URI,
        {
            mimeType: RESOURCE_MIME_TYPE,
            description: 'Interactive visualization for PostHog query results (trends, funnels, tables)',
        },
        async (uri) => ({
            contents: [
                {
                    uri: uri.toString(),
                    mimeType: RESOURCE_MIME_TYPE,
                    text: queryVisualizerHtml,
                },
            ],
        })
    )

    return Promise.resolve()
}

export { QUERY_VISUALIZER_RESOURCE_URI }
