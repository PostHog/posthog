import { hasScopes } from '@/lib/api'

// Dashboards
import addInsightToDashboard from './dashboards/addInsight'
import createDashboard from './dashboards/create'
import deleteDashboard from './dashboards/delete'
import getDashboard from './dashboards/get'
import getAllDashboards from './dashboards/getAll'
import reorderDashboardTiles from './dashboards/reorderTiles'
import updateDashboard from './dashboards/update'
// Debug
import debugMcpUiApps from './debug/debugMcpUiApps'
// Documentation
import searchDocs from './documentation/searchDocs'
// Error Tracking
import errorDetails from './errorTracking/errorDetails'
import listErrors from './errorTracking/listErrors'
import updateIssueStatus from './errorTracking/updateIssueStatus'
// Experiments
import createExperiment from './experiments/create'
import deleteExperiment from './experiments/delete'
import getExperiment from './experiments/get'
import getAllExperiments from './experiments/getAll'
import getExperimentResults from './experiments/getResults'
import updateExperiment from './experiments/update'
// Feature Flags
import createFeatureFlag from './featureFlags/create'
import deleteFeatureFlag from './featureFlags/delete'
import getAllFeatureFlags from './featureFlags/getAll'
import getFeatureFlagDefinition from './featureFlags/getDefinition'
import updateFeatureFlag from './featureFlags/update'
// Generated tools (from definitions/*.yaml)
import { GENERATED_TOOL_MAP } from './generated'
// Insights
import createInsight from './insights/create'
import deleteInsight from './insights/delete'
import getInsight from './insights/get'
import getAllInsights from './insights/getAll'
import queryInsight from './insights/query'
import updateInsight from './insights/update'
// LLM Analytics
import evaluationCreate from './llmAnalytics/evaluations/create'
import evaluationDelete from './llmAnalytics/evaluations/delete'
import evaluationGet from './llmAnalytics/evaluations/get'
import evaluationsGet from './llmAnalytics/evaluations/getAll'
import evaluationRun from './llmAnalytics/evaluations/run'
import evaluationUpdate from './llmAnalytics/evaluations/update'
import getLLMCosts from './llmAnalytics/getLLMCosts'
import logsListAttributes from './logs/listAttributes'
import logsListAttributeValues from './logs/listAttributeValues'
// Logs
import logsQuery from './logs/query'
// Organizations
import getOrganizationDetails from './organizations/getDetails'
import getOrganizations from './organizations/getOrganizations'
import setActiveOrganization from './organizations/setActive'
// PostHog AI tools
import { executeSql, readDataSchema, readDataWarehouseSchema } from './posthogAiTools'
// Projects
import eventDefinitions from './projects/eventDefinitions'
import getProjects from './projects/getProjects'
import getProperties from './projects/propertyDefinitions'
import setActiveProject from './projects/setActive'
import updateEventDefinition from './projects/updateEventDefinition'
// Prompts
import createPrompt from './prompts/create'
import getPrompt from './prompts/get'
import listPrompts from './prompts/list'
import updatePrompt from './prompts/update'
// Query
import generateHogQLFromQuestion from './query/generateHogQLFromQuestion'
import queryRun from './query/run'
// Search
import entitySearch from './search/entitySearch'
// Surveys
import createSurvey from './surveys/create'
import deleteSurvey from './surveys/delete'
import getSurvey from './surveys/get'
import getAllSurveys from './surveys/getAll'
import surveysGlobalStats from './surveys/global-stats'
import surveyStats from './surveys/stats'
import updateSurvey from './surveys/update'
// Misc
import {
    type ToolFilterOptions,
    getToolsForFeatures as getFilteredToolNames,
    getToolDefinition,
} from './toolDefinitions'
import type { Context, Tool, ToolBase, ZodObjectAny } from './types'

// Map of tool names to tool factory functions
const TOOL_MAP: Record<string, () => ToolBase<ZodObjectAny>> = {
    // Feature Flags
    'feature-flag-get-definition': getFeatureFlagDefinition,
    'feature-flag-get-all': getAllFeatureFlags,
    'create-feature-flag': createFeatureFlag,
    'update-feature-flag': updateFeatureFlag,
    'delete-feature-flag': deleteFeatureFlag,

    // Organizations
    'organizations-get': getOrganizations,
    'switch-organization': setActiveOrganization,
    'organization-details-get': getOrganizationDetails,

    // Projects
    'projects-get': getProjects,
    'switch-project': setActiveProject,
    'event-definitions-list': eventDefinitions,
    'event-definition-update': updateEventDefinition,
    'properties-list': getProperties,

    // Documentation - handled separately due to env check
    // "docs-search": searchDocs,

    // Error Tracking
    'list-errors': listErrors,
    'error-details': errorDetails,
    'update-issue-status': updateIssueStatus,

    // Logs
    'logs-query': logsQuery,
    'logs-list-attributes': logsListAttributes,
    'logs-list-attribute-values': logsListAttributeValues,

    // Experiments
    'experiment-get-all': getAllExperiments,
    'experiment-get': getExperiment,
    'experiment-results-get': getExperimentResults,
    'experiment-create': createExperiment,
    'experiment-delete': deleteExperiment,
    'experiment-update': updateExperiment,

    // Insights
    'insights-get-all': getAllInsights,
    'insight-get': getInsight,
    'insight-create-from-query': createInsight,
    'insight-update': updateInsight,
    'insight-delete': deleteInsight,
    'insight-query': queryInsight,

    // Queries
    'query-generate-hogql-from-question': generateHogQLFromQuestion,
    'query-run': queryRun,

    // Dashboards
    'dashboards-get-all': getAllDashboards,
    'dashboard-get': getDashboard,
    'dashboard-create': createDashboard,
    'dashboard-update': updateDashboard,
    'dashboard-delete': deleteDashboard,
    'dashboard-reorder-tiles': reorderDashboardTiles,
    'add-insight-to-dashboard': addInsightToDashboard,

    // LLM Analytics
    'get-llm-total-costs-for-project': getLLMCosts,
    'evaluations-get': evaluationsGet,
    'evaluation-get': evaluationGet,
    'evaluation-create': evaluationCreate,
    'evaluation-update': evaluationUpdate,
    'evaluation-delete': evaluationDelete,
    'evaluation-run': evaluationRun,

    // Surveys
    'surveys-get-all': getAllSurveys,
    'survey-get': getSurvey,
    'survey-create': createSurvey,
    'survey-update': updateSurvey,
    'survey-delete': deleteSurvey,
    'surveys-global-stats': surveysGlobalStats,
    'survey-stats': surveyStats,

    // Search
    'entity-search': entitySearch,

    // Debug
    'debug-mcp-ui-apps': debugMcpUiApps,

    // Prompts
    'prompt-list': listPrompts,
    'prompt-get': getPrompt,
    'prompt-create': createPrompt,
    'prompt-update': updatePrompt,

    // PostHog AI tools
    'execute-sql': executeSql,
    'read-data-schema': readDataSchema,
    'read-data-warehouse-schema': readDataWarehouseSchema,
}

export const getToolsFromContext = async (
    context: Context,
    options?: ToolFilterOptions
): Promise<Tool<ZodObjectAny>[]> => {
    const effectiveMap = { ...TOOL_MAP, ...GENERATED_TOOL_MAP }
    const excludeTools = options?.excludeTools ?? []
    const allowedToolNames = getFilteredToolNames(options).filter((name) => !excludeTools.includes(name))
    const toolBases: ToolBase<ZodObjectAny>[] = []

    for (const toolName of allowedToolNames) {
        // Special handling for docs-search which requires API key
        if (toolName === 'docs-search' && context.env.INKEEP_API_KEY) {
            toolBases.push(searchDocs())
        } else {
            const toolFactory = effectiveMap[toolName]
            if (toolFactory) {
                toolBases.push(toolFactory())
            }
        }
    }

    const tools: Tool<ZodObjectAny>[] = toolBases.map((toolBase) => {
        const definition = getToolDefinition(toolBase.name, options?.version)
        return {
            ...toolBase,
            title: definition.title,
            description: definition.description,
            scopes: definition.required_scopes ?? [],
            annotations: definition.annotations,
        }
    })

    const apiKey = await context.stateManager.getApiKey()
    const scopes = apiKey?.scopes ?? []

    return tools.filter((tool) => hasScopes(scopes, tool.scopes))
}
