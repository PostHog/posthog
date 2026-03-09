/**
 * UI App Resource URIs
 *
 * Each constant maps a tool (or group of related tools) to its UI visualization.
 * The URI format is: ui://posthog/<app-name>.html
 *
 * When adding a new UI app:
 * 1. Create a new folder in src/ui-apps/<app-name>/
 * 2. Add entry point to vite.ui-apps.config.ts
 * 3. Add constant here
 * 4. Register resource in src/resources/ui-apps.ts
 * 5. Reference from tool's _meta.ui.resourceUri
 */

/**
 * Query results visualization.
 * Used by: query-run, insight-query
 * Shows trends, funnels, tables, and other query result types.
 */
export const QUERY_RESULTS_RESOURCE_URI = 'ui://posthog/query-results.html'

/**
 * Debug app for testing MCP Apps SDK integration.
 * Used by: debug-mcp-ui-apps
 * Displays SDK events, tool result data, and Mosaic component showcase.
 */
export const DEBUG_RESOURCE_URI = 'ui://posthog/debug.html'
