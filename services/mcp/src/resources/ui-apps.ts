import { McpUiResourceMeta } from '@modelcontextprotocol/ext-apps'
import { RESOURCE_MIME_TYPE } from '@modelcontextprotocol/ext-apps/server'
import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'

import type { Context } from '@/tools/types'

import {
    ACTION_LIST_RESOURCE_URI,
    ACTION_RESOURCE_URI,
    COHORT_LIST_RESOURCE_URI,
    COHORT_RESOURCE_URI,
    DEBUG_RESOURCE_URI,
    ERROR_DETAILS_RESOURCE_URI,
    ERROR_ISSUE_LIST_RESOURCE_URI,
    ERROR_ISSUE_RESOURCE_URI,
    QUERY_RESULTS_RESOURCE_URI,
} from './ui-apps-constants'

// Import bundled HTML at build time (wrangler Text rule)
// Each UI app has its own HTML file in ui-apps-dist/src/ui-apps/apps/<name>/
import actionListHtml from '../../ui-apps-dist/src/ui-apps/apps/action-list/index.html'
import actionHtml from '../../ui-apps-dist/src/ui-apps/apps/action/index.html'
import cohortListHtml from '../../ui-apps-dist/src/ui-apps/apps/cohort-list/index.html'
import cohortHtml from '../../ui-apps-dist/src/ui-apps/apps/cohort/index.html'
import debugHtml from '../../ui-apps-dist/src/ui-apps/apps/debug/index.html'
import errorDetailsHtml from '../../ui-apps-dist/src/ui-apps/apps/error-details/index.html'
import errorIssueListHtml from '../../ui-apps-dist/src/ui-apps/apps/error-issue-list/index.html'
import errorIssueHtml from '../../ui-apps-dist/src/ui-apps/apps/error-issue/index.html'
import queryResultsHtml from '../../ui-apps-dist/src/ui-apps/apps/query-results/index.html'

const UI_APPS: Array<{ name: string; uri: string; description: string; html: string }> = [
    // Core
    {
        name: 'MCP Apps Debug',
        uri: DEBUG_RESOURCE_URI,
        description: 'Debug app for testing MCP Apps SDK integration',
        html: debugHtml,
    },
    {
        name: 'Query Results',
        uri: QUERY_RESULTS_RESOURCE_URI,
        description: 'Interactive visualization for PostHog query results',
        html: queryResultsHtml,
    },
    // Actions
    { name: 'Action', uri: ACTION_RESOURCE_URI, description: 'Action detail view', html: actionHtml },
    { name: 'Action list', uri: ACTION_LIST_RESOURCE_URI, description: 'Action list view', html: actionListHtml },
    // Cohorts
    { name: 'Cohort', uri: COHORT_RESOURCE_URI, description: 'Cohort detail view', html: cohortHtml },
    { name: 'Cohort list', uri: COHORT_LIST_RESOURCE_URI, description: 'Cohort list view', html: cohortListHtml },
    // Error tracking
    {
        name: 'Error details',
        uri: ERROR_DETAILS_RESOURCE_URI,
        description: 'Error details with stack traces',
        html: errorDetailsHtml,
    },
    {
        name: 'Error issue',
        uri: ERROR_ISSUE_RESOURCE_URI,
        description: 'Error tracking issue detail view',
        html: errorIssueHtml,
    },
    {
        name: 'Error issue list',
        uri: ERROR_ISSUE_LIST_RESOURCE_URI,
        description: 'Error tracking issue list view',
        html: errorIssueListHtml,
    },
]

/**
 * Registers UI app resources with the MCP server.
 * These resources provide interactive visualizations for tool results
 * in MCP clients that support ext-apps (like Claude Desktop).
 *
 * Each tool type can have its own visualization registered here.
 */
export async function registerUiAppResources(server: McpServer, context: Context): Promise<void> {
    for (const app of UI_APPS) {
        registerApp(server, context, app)
    }
}

interface RegisterAppParams {
    name: string
    uri: string
    description: string
    html: string
}

function registerApp(server: McpServer, context: Context, { name, uri, description, html }: RegisterAppParams): void {
    const analyticsBaseUrl = context.env.POSTHOG_MCP_APPS_ANALYTICS_BASE_URL
    const uiMetadata: McpUiResourceMeta = {}
    if (analyticsBaseUrl) {
        uiMetadata.csp = {
            connectDomains: [analyticsBaseUrl],
            resourceDomains: [analyticsBaseUrl],
        }
    }

    server.registerResource(name, uri, { description: description }, async (uri) => {
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
