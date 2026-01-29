import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { RESOURCE_MIME_TYPE } from '@modelcontextprotocol/ext-apps/server'

import { QUERY_RESULTS_RESOURCE_URI, DEMO_RESOURCE_URI } from './ui-apps-constants'

// Import bundled HTML at build time (wrangler Text rule)
// Each UI app has its own HTML file in ui-apps-dist/src/ui-apps/apps/<name>/
import queryResultsHtml from '../../ui-apps-dist/src/ui-apps/apps/query-results/index.html'
import demoHtml from '../../ui-apps-dist/src/ui-apps/apps/demo/index.html'
import { Context } from '@/tools'
import { McpUiResourceMeta } from '@modelcontextprotocol/ext-apps'

/**
 * Registers UI app resources with the MCP server.
 * These resources provide interactive visualizations for tool results
 * in MCP clients that support ext-apps (like Claude Desktop).
 *
 * Each tool type can have its own visualization registered here.
 */
export async function registerUiAppResources(server: McpServer, context: Context): Promise<void> {
    registerDemoApp(server, context) // Demo app - used by demo-mcp-ui-apps tool for testing
    registerQueryResultsApp(server, context) // Query Results - used by query-run and insight-query tools
}

function registerDemoApp(server: McpServer, context: Context): void {
    registerApp(server, context, {name: 'MCP Apps Demo', uri: DEMO_RESOURCE_URI, description: 'Demo app for testing MCP Apps SDK integration - displays SDK events and tool data', html: demoHtml})
}

function registerQueryResultsApp(server: McpServer, context: Context): void {
    registerApp(server, context, {name: 'Query Results', uri: QUERY_RESULTS_RESOURCE_URI, description: 'Interactive visualization for PostHog query results (trends, funnels, tables)', html: queryResultsHtml})
}

interface RegisterAppParams {
    name: string
    uri: string
    description: string
    html: string
}

function registerApp(server: McpServer, context: Context, {name, uri, description, html}: RegisterAppParams): void {
    
    
    server.registerResource(
        name,
        uri,
        {
            mimeType: RESOURCE_MIME_TYPE,
            description: description,
            // TODO: This doesn't do anything, Claude Desktop is not respecting it and not letting us run analytics
            // I've reported this to Claude Desktop team and I'm waiting to hear back from them.
            // _meta: { ui: buildUiMetadataFrom(context) },
        },
        async (uri) => {
            return {
                contents: [
                    {
                        uri: uri.toString(),
                        mimeType: RESOURCE_MIME_TYPE,
                        text: html,
                    },
                ],
            }
        }
    )
}

function buildUiMetadataFrom(context: Context): McpUiResourceMeta {
    const posthogBaseUrl = context.env.POSTHOG_BASE_URL

    const meta: McpUiResourceMeta = {}

    if (posthogBaseUrl) {
        meta.csp = {
            connectDomains: [posthogBaseUrl],
            resourceDomains: [posthogBaseUrl],
        }
        meta.domain = posthogBaseUrl
    }

    return meta
}

// Re-export for tools to import
export { QUERY_RESULTS_RESOURCE_URI, DEMO_RESOURCE_URI }