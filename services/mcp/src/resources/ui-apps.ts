import { McpUiResourceMeta } from '@modelcontextprotocol/ext-apps'
import { RESOURCE_MIME_TYPE } from '@modelcontextprotocol/ext-apps/server'
import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'

import type { Context } from '@/tools/types'

import { type UiAppKey, UI_APPS, URI_MAP } from './ui-apps.generated'

/**
 * Wrap a tool definition with UI app metadata.
 * Works with both ToolBase and Tool (full definition with scopes/annotations).
 */
export function withUiApp<T extends { _meta?: unknown }>(appKey: UiAppKey, config: Omit<T, '_meta'>): T {
    return { ...config, _meta: { ui: { resourceUri: URI_MAP[appKey] } } } as T
}

/**
 * Build a minimal HTML stub that loads app JS+CSS from static assets.
 */
export function buildAppStubHtml(appDir: string, baseUrl: string): string {
    return `<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="stylesheet" href="${baseUrl}/ui-apps/${appDir}/styles.css">
</head><body>
<div id="root"></div>
<script src="${baseUrl}/ui-apps/${appDir}/main.js"></script>
</body></html>`
}

/**
 * Registers UI app resources with the MCP server.
 * These resources provide interactive visualizations for tool results
 * in MCP clients that support ext-apps (like Claude Desktop).
 *
 * Each tool type can have its own visualization registered here.
 */
export async function registerUiAppResources(server: McpServer, context: Context): Promise<void> {
    const baseUrl = context.env.MCP_APPS_BASE_URL
    if (!baseUrl) {
        console.warn('MCP_APPS_BASE_URL is not set — UI app resources will not be registered')
        return
    }

    for (const app of UI_APPS) {
        registerApp(server, context, app, baseUrl)
    }
}

interface RegisterAppParams {
    name: string
    uri: string
    description: string
    appDir: string
}

function registerApp(
    server: McpServer,
    context: Context,
    { name, uri, description, appDir }: RegisterAppParams,
    baseUrl: string
): void {
    const analyticsBaseUrl = context.env.POSTHOG_MCP_APPS_ANALYTICS_BASE_URL
    const uiMetadata: McpUiResourceMeta = {}

    const resourceDomains: string[] = [baseUrl]
    const connectDomains: string[] = []

    if (analyticsBaseUrl) {
        connectDomains.push(analyticsBaseUrl)
        resourceDomains.push(analyticsBaseUrl)
    }

    uiMetadata.csp = {
        connectDomains,
        resourceDomains,
    }

    const html = buildAppStubHtml(appDir, baseUrl)

    server.registerResource(name, uri, { mimeType: RESOURCE_MIME_TYPE, description }, async (uri) => {
        return {
            contents: [
                {
                    uri: uri.toString(),
                    mimeType: RESOURCE_MIME_TYPE,
                    text: html,
                    _meta: { ui: uiMetadata },
                },
            ],
        }
    })
}
