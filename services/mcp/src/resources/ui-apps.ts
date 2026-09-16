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
 * Base URL the stub loads the app JS and CSS from.
 *
 * A host builds the app iframe CSP around the origin the client connected to, so a
 * stub that points anywhere else renders blank. Clients reach `mcp.posthog.com`, which
 * proxies to a regional runtime whose `MCP_APPS_BASE_URL` names the regional host, so
 * the static value disagrees with the connected origin. Every runtime serves
 * `/ui-apps/*` itself, so the connected origin always has the assets.
 *
 * `MCP_APPS_BASE_URL` stays the switch that turns UI apps on, and the fallback for an
 * origin we do not serve assets from.
 */
export function resolveUiAppsBaseUrl(
    publicOrigin: string | undefined,
    configuredBaseUrl: string | undefined
): string | undefined {
    if (!configuredBaseUrl || !publicOrigin) {
        return configuredBaseUrl
    }
    return isTrustedAppsOrigin(publicOrigin, configuredBaseUrl) ? publicOrigin : configuredBaseUrl
}

// The stub origin becomes `script-src` for the app iframe, and a client controls the
// forwarded host, so only PostHog hosts and the configured host are accepted.
function isTrustedAppsOrigin(publicOrigin: string, configuredBaseUrl: string): boolean {
    const host = hostnameOf(publicOrigin)
    if (!host) {
        return false
    }
    return host === 'posthog.com' || host.endsWith('.posthog.com') || host === hostnameOf(configuredBaseUrl)
}

function hostnameOf(url: string): string | undefined {
    try {
        return new URL(url).hostname.toLowerCase()
    } catch {
        return undefined
    }
}

export interface UiAppResourceMeta {
    [key: string]: unknown
    ui: McpUiResourceMeta
    'openai/widgetCSP': {
        connect_domains: string[]
        resource_domains: string[]
    }
}

/**
 * Build the `_meta` object for a UI app resource, declaring which domains the
 * host must allow in the app iframe's CSP.
 *
 * Declared in two formats: `ui.csp` per the MCP Apps spec (Claude), and
 * `openai/widgetCSP` for ChatGPT — ChatGPT ignores `ui.csp` and only extends
 * its iframe CSP with its own key, so without it the app assets are blocked.
 */
export function buildUiAppResourceMeta(baseUrl: string, analyticsBaseUrl: string | undefined): UiAppResourceMeta {
    const resourceDomains: string[] = [baseUrl]
    const connectDomains: string[] = []

    if (analyticsBaseUrl) {
        connectDomains.push(analyticsBaseUrl)
        resourceDomains.push(analyticsBaseUrl)
    }

    return {
        ui: { csp: { connectDomains, resourceDomains } },
        'openai/widgetCSP': {
            connect_domains: connectDomains,
            resource_domains: resourceDomains,
        },
    }
}

/**
 * Registers UI app resources with the MCP server.
 * These resources provide interactive visualizations for tool results
 * in MCP clients that support ext-apps (like Claude Desktop).
 *
 * Each tool type can have its own visualization registered here.
 */
let warnedMissingBaseUrl = false

export async function registerUiAppResources(server: McpServer, context: Context): Promise<void> {
    const baseUrl = context.env.MCP_APPS_BASE_URL
    if (!baseUrl) {
        if (!warnedMissingBaseUrl) {
            warnedMissingBaseUrl = true
            console.warn('MCP_APPS_BASE_URL is not set — UI app resources will not be registered')
        }
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
    const meta = buildUiAppResourceMeta(baseUrl, context.env.POSTHOG_MCP_APPS_ANALYTICS_BASE_URL)
    const html = buildAppStubHtml(appDir, baseUrl)

    // `_meta` goes on the registration too, so a host that builds the iframe CSP from
    // `resources/list` alone still allows the stub's script and stylesheet from `baseUrl`.
    server.registerResource(name, uri, { mimeType: RESOURCE_MIME_TYPE, description, _meta: meta }, async (uri) => {
        return {
            contents: [
                {
                    uri: uri.toString(),
                    mimeType: RESOURCE_MIME_TYPE,
                    text: html,
                    _meta: meta,
                },
            ],
        }
    })
}
