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
 * Debug app for testing MCP Apps SDK integration.
 * Used by: debug-mcp-ui-apps
 * Displays SDK events, tool result data, and Mosaic component showcase.
 */
export const DEBUG_RESOURCE_URI = 'ui://posthog/debug.html'

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

/**
 * Experiment detail visualization.
 * Used by: experiment-get, experiment-create, experiment-update
 */
export const EXPERIMENT_RESOURCE_URI = 'ui://posthog/experiment.html'

/**
 * Experiment list visualization.
 * Used by: experiment-get-all
 */
export const EXPERIMENT_LIST_RESOURCE_URI = 'ui://posthog/experiment-list.html'

/**
 * Experiment results visualization.
 * Used by: experiment-results-get
 */
export const EXPERIMENT_RESULTS_RESOURCE_URI = 'ui://posthog/experiment-results.html'

/**

 * Feature flag detail visualization.
 * Used by: feature-flag-get-definition, create-feature-flag, update-feature-flag
 * Shows flag status, release conditions, variants, and property filters.
 */
export const FEATURE_FLAG_RESOURCE_URI = 'ui://posthog/feature-flag.html'

/**
 * Feature flag list visualization.
 * Used by: feature-flag-get-all
 * Shows a data table of all feature flags with status, tags, and dates.
 */
export const FEATURE_FLAG_LIST_RESOURCE_URI = 'ui://posthog/feature-flag-list.html'

/**

 * LLM costs visualization.
 * Used by: get-llm-total-costs-for-project
 */
export const LLM_COSTS_RESOURCE_URI = 'ui://posthog/llm-costs.html'

/**
 * Query results visualization.
 * Used by: query-run, insight-query
 * Shows trends, funnels, tables, and other query result types.
 */
export const QUERY_RESULTS_RESOURCE_URI = 'ui://posthog/query-results.html'

/**
 * Survey detail visualization.
 * Used by: survey-get, survey-create, survey-update
 */
export const SURVEY_RESOURCE_URI = 'ui://posthog/survey.html'

/**
 * Survey list visualization.
 * Used by: surveys-get-all
 */
export const SURVEY_LIST_RESOURCE_URI = 'ui://posthog/survey-list.html'

/**
 * Survey stats visualization.
 * Used by: survey-stats
 */
export const SURVEY_STATS_RESOURCE_URI = 'ui://posthog/survey-stats.html'

/**
 * Survey global stats visualization.
 * Used by: surveys-global-stats
 */
export const SURVEY_GLOBAL_STATS_RESOURCE_URI = 'ui://posthog/survey-global-stats.html'

/**

 * Workflow detail visualization.
 * Used by: workflows-get
 */
export const WORKFLOW_RESOURCE_URI = 'ui://posthog/workflow.html'

/**
 * Workflow list visualization.
 * Used by: workflows-list
 */
export const WORKFLOW_LIST_RESOURCE_URI = 'ui://posthog/workflow-list.html'
