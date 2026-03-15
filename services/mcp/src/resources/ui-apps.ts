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
import experimentListHtml from '../../ui-apps-dist/src/ui-apps/apps/experiment-list/index.html'
import experimentResultsHtml from '../../ui-apps-dist/src/ui-apps/apps/experiment-results/index.html'
import experimentHtml from '../../ui-apps-dist/src/ui-apps/apps/experiment/index.html'
import featureFlagListHtml from '../../ui-apps-dist/src/ui-apps/apps/feature-flag-list/index.html'
import featureFlagHtml from '../../ui-apps-dist/src/ui-apps/apps/feature-flag/index.html'
import llmCostsHtml from '../../ui-apps-dist/src/ui-apps/apps/llm-costs/index.html'
import queryResultsHtml from '../../ui-apps-dist/src/ui-apps/apps/query-results/index.html'
import surveyGlobalStatsHtml from '../../ui-apps-dist/src/ui-apps/apps/survey-global-stats/index.html'
import surveyListHtml from '../../ui-apps-dist/src/ui-apps/apps/survey-list/index.html'
import surveyStatsHtml from '../../ui-apps-dist/src/ui-apps/apps/survey-stats/index.html'
import surveyHtml from '../../ui-apps-dist/src/ui-apps/apps/survey/index.html'
import workflowListHtml from '../../ui-apps-dist/src/ui-apps/apps/workflow-list/index.html'
import workflowHtml from '../../ui-apps-dist/src/ui-apps/apps/workflow/index.html'

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
    // Experiments
    {
        name: 'Experiment',
        uri: EXPERIMENT_RESOURCE_URI,
        description: 'Experiment detail view',
        html: experimentHtml,
    },
    {
        name: 'Experiment list',
        uri: EXPERIMENT_LIST_RESOURCE_URI,
        description: 'Experiment list view',
        html: experimentListHtml,
    },
    {
        name: 'Experiment results',
        uri: EXPERIMENT_RESULTS_RESOURCE_URI,
        description: 'Experiment results visualization',
        html: experimentResultsHtml,
    },
    // Feature flags
    {
        name: 'Feature flag',
        uri: FEATURE_FLAG_RESOURCE_URI,
        description: 'Feature flag detail view',
        html: featureFlagHtml,
    },
    {
        name: 'Feature flag list',
        uri: FEATURE_FLAG_LIST_RESOURCE_URI,
        description: 'Feature flag list view',
        html: featureFlagListHtml,
    },
    // LLM analytics
    {
        name: 'LLM costs',
        uri: LLM_COSTS_RESOURCE_URI,
        description: 'LLM costs breakdown by model',
        html: llmCostsHtml,
    },
    // Surveys
    { name: 'Survey', uri: SURVEY_RESOURCE_URI, description: 'Survey detail view', html: surveyHtml },
    { name: 'Survey list', uri: SURVEY_LIST_RESOURCE_URI, description: 'Survey list view', html: surveyListHtml },
    {
        name: 'Survey stats',
        uri: SURVEY_STATS_RESOURCE_URI,
        description: 'Survey statistics view',
        html: surveyStatsHtml,
    },
    {
        name: 'Survey global stats',
        uri: SURVEY_GLOBAL_STATS_RESOURCE_URI,
        description: 'Survey global statistics view',
        html: surveyGlobalStatsHtml,
    },
    // Workflows
    { name: 'Workflow', uri: WORKFLOW_RESOURCE_URI, description: 'Workflow detail view', html: workflowHtml },
    {
        name: 'Workflow list',
        uri: WORKFLOW_LIST_RESOURCE_URI,
        description: 'Workflow list view',
        html: workflowListHtml,
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
