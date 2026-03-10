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

/**

 * Action detail visualization.
 * Used by: action-get, action-create, action-update
 */
export const ACTION_RESOURCE_URI = 'ui://posthog/action.html'

/**
 * Action list visualization.
 * Used by: actions-get-all
 */
export const ACTION_LIST_RESOURCE_URI = 'ui://posthog/action-list.html'

/**

 * Cohort detail visualization.
 * Used by: cohorts-retrieve, cohorts-create, cohorts-partial-update
 */
export const COHORT_RESOURCE_URI = 'ui://posthog/cohort.html'
/**
 * Cohort list visualization.
 * Used by: cohorts-list
 */
export const COHORT_LIST_RESOURCE_URI = 'ui://posthog/cohort-list.html'

/**
 * Error details visualization with stack traces.
 * Used by: error-details
 */
export const ERROR_DETAILS_RESOURCE_URI = 'ui://posthog/error-details.html'
/**
 * Error tracking issue detail visualization.
 * Used by: error-tracking-issues-retrieve, error-tracking-issues-partial-update
 */
export const ERROR_ISSUE_RESOURCE_URI = 'ui://posthog/error-issue.html'
/**
 * Error tracking issue list visualization.
 * Used by: error-tracking-issues-list
 */
export const ERROR_ISSUE_LIST_RESOURCE_URI = 'ui://posthog/error-issue-list.html'
