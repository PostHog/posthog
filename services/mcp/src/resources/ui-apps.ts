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

// UI app HTML is loaded lazily via dynamic import() instead of static imports
// at module scope. This avoids ~12.5MB of HTML strings being parsed during
// Worker startup, which would exceed Cloudflare's 1-second CPU startup limit.

const UI_APPS: Array<{
    name: string
    uri: string
    description: string
    importHtml: () => Promise<{ default: string }>
}> = [
    // Core
    {
        name: 'MCP Apps Debug',
        uri: DEBUG_RESOURCE_URI,
        description: 'Debug app for testing MCP Apps SDK integration',
        importHtml: () => import('../../ui-apps-dist/src/ui-apps/apps/debug/index.html'),
    },
    {
        name: 'Query Results',
        uri: QUERY_RESULTS_RESOURCE_URI,
        description: 'Interactive visualization for PostHog query results',
        importHtml: () => import('../../ui-apps-dist/src/ui-apps/apps/query-results/index.html'),
    },
    // Actions
    {
        name: 'Action',
        uri: ACTION_RESOURCE_URI,
        description: 'Action detail view',
        importHtml: () => import('../../ui-apps-dist/src/ui-apps/apps/action/index.html'),
    },
    {
        name: 'Action list',
        uri: ACTION_LIST_RESOURCE_URI,
        description: 'Action list view',
        importHtml: () => import('../../ui-apps-dist/src/ui-apps/apps/action-list/index.html'),
    },
    // Cohorts
    {
        name: 'Cohort',
        uri: COHORT_RESOURCE_URI,
        description: 'Cohort detail view',
        importHtml: () => import('../../ui-apps-dist/src/ui-apps/apps/cohort/index.html'),
    },
    {
        name: 'Cohort list',
        uri: COHORT_LIST_RESOURCE_URI,
        description: 'Cohort list view',
        importHtml: () => import('../../ui-apps-dist/src/ui-apps/apps/cohort-list/index.html'),
    },
    // Error tracking
    {
        name: 'Error details',
        uri: ERROR_DETAILS_RESOURCE_URI,
        description: 'Error details with stack traces',
        importHtml: () => import('../../ui-apps-dist/src/ui-apps/apps/error-details/index.html'),
    },
    {
        name: 'Error issue',
        uri: ERROR_ISSUE_RESOURCE_URI,
        description: 'Error tracking issue detail view',
        importHtml: () => import('../../ui-apps-dist/src/ui-apps/apps/error-issue/index.html'),
    },
    {
        name: 'Error issue list',
        uri: ERROR_ISSUE_LIST_RESOURCE_URI,
        description: 'Error tracking issue list view',
        importHtml: () => import('../../ui-apps-dist/src/ui-apps/apps/error-issue-list/index.html'),
    },
    // Experiments
    {
        name: 'Experiment',
        uri: EXPERIMENT_RESOURCE_URI,
        description: 'Experiment detail view',
        importHtml: () => import('../../ui-apps-dist/src/ui-apps/apps/experiment/index.html'),
    },
    {
        name: 'Experiment list',
        uri: EXPERIMENT_LIST_RESOURCE_URI,
        description: 'Experiment list view',
        importHtml: () => import('../../ui-apps-dist/src/ui-apps/apps/experiment-list/index.html'),
    },
    {
        name: 'Experiment results',
        uri: EXPERIMENT_RESULTS_RESOURCE_URI,
        description: 'Experiment results visualization',
        importHtml: () => import('../../ui-apps-dist/src/ui-apps/apps/experiment-results/index.html'),
    },
    // Feature flags
    {
        name: 'Feature flag',
        uri: FEATURE_FLAG_RESOURCE_URI,
        description: 'Feature flag detail view',
        importHtml: () => import('../../ui-apps-dist/src/ui-apps/apps/feature-flag/index.html'),
    },
    {
        name: 'Feature flag list',
        uri: FEATURE_FLAG_LIST_RESOURCE_URI,
        description: 'Feature flag list view',
        importHtml: () => import('../../ui-apps-dist/src/ui-apps/apps/feature-flag-list/index.html'),
    },
    // LLM analytics
    {
        name: 'LLM costs',
        uri: LLM_COSTS_RESOURCE_URI,
        description: 'LLM costs breakdown by model',
        importHtml: () => import('../../ui-apps-dist/src/ui-apps/apps/llm-costs/index.html'),
    },
    // Surveys
    {
        name: 'Survey',
        uri: SURVEY_RESOURCE_URI,
        description: 'Survey detail view',
        importHtml: () => import('../../ui-apps-dist/src/ui-apps/apps/survey/index.html'),
    },
    {
        name: 'Survey list',
        uri: SURVEY_LIST_RESOURCE_URI,
        description: 'Survey list view',
        importHtml: () => import('../../ui-apps-dist/src/ui-apps/apps/survey-list/index.html'),
    },
    {
        name: 'Survey stats',
        uri: SURVEY_STATS_RESOURCE_URI,
        description: 'Survey statistics view',
        importHtml: () => import('../../ui-apps-dist/src/ui-apps/apps/survey-stats/index.html'),
    },
    {
        name: 'Survey global stats',
        uri: SURVEY_GLOBAL_STATS_RESOURCE_URI,
        description: 'Survey global statistics view',
        importHtml: () => import('../../ui-apps-dist/src/ui-apps/apps/survey-global-stats/index.html'),
    },
    // Workflows
    {
        name: 'Workflow',
        uri: WORKFLOW_RESOURCE_URI,
        description: 'Workflow detail view',
        importHtml: () => import('../../ui-apps-dist/src/ui-apps/apps/workflow/index.html'),
    },
    {
        name: 'Workflow list',
        uri: WORKFLOW_LIST_RESOURCE_URI,
        description: 'Workflow list view',
        importHtml: () => import('../../ui-apps-dist/src/ui-apps/apps/workflow-list/index.html'),
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
    importHtml: () => Promise<{ default: string }>
}

function registerApp(
    server: McpServer,
    context: Context,
    { name, uri, description, importHtml }: RegisterAppParams
): void {
    const analyticsBaseUrl = context.env.POSTHOG_MCP_APPS_ANALYTICS_BASE_URL
    const uiMetadata: McpUiResourceMeta = {}
    if (analyticsBaseUrl) {
        uiMetadata.csp = {
            connectDomains: [analyticsBaseUrl],
            resourceDomains: [analyticsBaseUrl],
        }
    }

    server.registerResource(name, uri, { mimeType: RESOURCE_MIME_TYPE, description }, async (uri) => {
        const { default: html } = await importHtml()

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
