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
    EXPERIMENT_LIST_RESOURCE_URI,
    EXPERIMENT_RESOURCE_URI,
    EXPERIMENT_RESULTS_RESOURCE_URI,
    FEATURE_FLAG_LIST_RESOURCE_URI,
    FEATURE_FLAG_RESOURCE_URI,
    LLM_COSTS_RESOURCE_URI,
    QUERY_RESULTS_RESOURCE_URI,
    SURVEY_GLOBAL_STATS_RESOURCE_URI,
    SURVEY_LIST_RESOURCE_URI,
    SURVEY_RESOURCE_URI,
    SURVEY_STATS_RESOURCE_URI,
    WORKFLOW_LIST_RESOURCE_URI,
    WORKFLOW_RESOURCE_URI,
} from './ui-apps-constants'

const UI_APPS: Array<{
    name: string
    uri: string
    description: string
    appDir: string
}> = [
    // Core
    {
        name: 'MCP Apps Debug',
        uri: DEBUG_RESOURCE_URI,
        description: 'Debug app for testing MCP Apps SDK integration',
        appDir: 'debug',
    },
    {
        name: 'Query Results',
        uri: QUERY_RESULTS_RESOURCE_URI,
        description: 'Interactive visualization for PostHog query results',
        appDir: 'query-results',
    },
    // Actions
    {
        name: 'Action',
        uri: ACTION_RESOURCE_URI,
        description: 'Action detail view',
        appDir: 'action',
    },
    {
        name: 'Action list',
        uri: ACTION_LIST_RESOURCE_URI,
        description: 'Action list view',
        appDir: 'action-list',
    },
    // Cohorts
    {
        name: 'Cohort',
        uri: COHORT_RESOURCE_URI,
        description: 'Cohort detail view',
        appDir: 'cohort',
    },
    {
        name: 'Cohort list',
        uri: COHORT_LIST_RESOURCE_URI,
        description: 'Cohort list view',
        appDir: 'cohort-list',
    },
    // Error tracking
    {
        name: 'Error details',
        uri: ERROR_DETAILS_RESOURCE_URI,
        description: 'Error details with stack traces',
        appDir: 'error-details',
    },
    {
        name: 'Error issue',
        uri: ERROR_ISSUE_RESOURCE_URI,
        description: 'Error tracking issue detail view',
        appDir: 'error-issue',
    },
    {
        name: 'Error issue list',
        uri: ERROR_ISSUE_LIST_RESOURCE_URI,
        description: 'Error tracking issue list view',
        appDir: 'error-issue-list',
    },
    // Experiments
    {
        name: 'Experiment',
        uri: EXPERIMENT_RESOURCE_URI,
        description: 'Experiment detail view',
        appDir: 'experiment',
    },
    {
        name: 'Experiment list',
        uri: EXPERIMENT_LIST_RESOURCE_URI,
        description: 'Experiment list view',
        appDir: 'experiment-list',
    },
    {
        name: 'Experiment results',
        uri: EXPERIMENT_RESULTS_RESOURCE_URI,
        description: 'Experiment results visualization',
        appDir: 'experiment-results',
    },
    // Feature flags
    {
        name: 'Feature flag',
        uri: FEATURE_FLAG_RESOURCE_URI,
        description: 'Feature flag detail view',
        appDir: 'feature-flag',
    },
    {
        name: 'Feature flag list',
        uri: FEATURE_FLAG_LIST_RESOURCE_URI,
        description: 'Feature flag list view',
        appDir: 'feature-flag-list',
    },
    // LLM analytics
    {
        name: 'LLM costs',
        uri: LLM_COSTS_RESOURCE_URI,
        description: 'LLM costs breakdown by model',
        appDir: 'llm-costs',
    },
    // Surveys
    {
        name: 'Survey',
        uri: SURVEY_RESOURCE_URI,
        description: 'Survey detail view',
        appDir: 'survey',
    },
    {
        name: 'Survey list',
        uri: SURVEY_LIST_RESOURCE_URI,
        description: 'Survey list view',
        appDir: 'survey-list',
    },
    {
        name: 'Survey stats',
        uri: SURVEY_STATS_RESOURCE_URI,
        description: 'Survey statistics view',
        appDir: 'survey-stats',
    },
    {
        name: 'Survey global stats',
        uri: SURVEY_GLOBAL_STATS_RESOURCE_URI,
        description: 'Survey global statistics view',
        appDir: 'survey-global-stats',
    },
    // Workflows
    {
        name: 'Workflow',
        uri: WORKFLOW_RESOURCE_URI,
        description: 'Workflow detail view',
        appDir: 'workflow',
    },
    {
        name: 'Workflow list',
        uri: WORKFLOW_LIST_RESOURCE_URI,
        description: 'Workflow list view',
        appDir: 'workflow-list',
    },
]

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
