import { hasScopes } from '@/lib/api'
import { filterStaffOnlyTools } from '@/lib/staff-only-tools'

// AI observability
import getLLMCosts from './aiObservability/getLLMCosts'
import parserRecipeCreate from './aiObservability/parserRecipeCreate'
import parserRecipeReference from './aiObservability/parserRecipeReference'
// Debug
import debugMcpUiApps from './debug/debugMcpUiApps'
// Experiments (hand-written — CRUD + lifecycle are codegen in generated/experiments.ts)
import getExperimentResults from './experiments/getResults'
import experimentListDeprecated from './experiments/listDeprecated'
// Feature flags (get-definition-by-key is hand-written; get-definition-by-id is codegen)
import featureFlagGetDefinitionByKey from './featureFlags/getDefinitionByKey'
// Feedback
import submitFeedback from './feedback/submit'
// Generated tools (from definitions/*.yaml)
import { GENERATED_TOOL_MAP } from './generated'
// Insights
import queryInsight from './insights/query'
// Links (utility — builds canonical app URLs from the frontend's route table)
import generateAppUrl from './links/generate-app-url'
import loopsReview from './loops/loopsReview'
// Notebooks (edit + cell tools are hand-written — generated CRUD lives in generated/notebooks.ts)
import notebookAddCell from './notebooks/addCell'
import notebookCreateMarkdown from './notebooks/createMarkdown'
import notebookDeleteCell from './notebooks/deleteCell'
import notebookEdit from './notebooks/edit'
import notebookUpdateCell from './notebooks/updateCell'
// Organizations
import getOrganizations from './organizations/getOrganizations'
import setActiveOrganization from './organizations/setActive'
// PostHog AI tools
import {
    EXECUTE_SQL_TOOL_NAME,
    executeSql,
    externalDataSourcesDbSchema,
    externalDataSourcesJobs,
    externalDataSourcesPreview,
    externalDataSyncLogs,
    readDataSchema,
} from './posthogAiTools'
// PostHog connections (run this project's tools against a connected project in another org/region)
import { createConnectionCallTool } from './posthogConnections/call'
// Projects
import createEventDefinition from './projects/createEventDefinition'
import getProjects from './projects/getProjects'
import setActiveProject from './projects/setActive'
import updateEventDefinition from './projects/updateEventDefinition'
import updatePathCleaning from './projects/updatePathCleaning'
import updatePropertyDefinition from './projects/updatePropertyDefinition'
// Replay
// Skills (deprecation aliases for the llma-skill-* → skill-* rename)
import { SKILL_DEPRECATED_ALIASES } from './skills/deprecatedAliases'
import { tasksArtifactsList, tasksCommentsList, tasksCommentsRetrieve } from './tasksContext'
// Misc
import {
    type ToolFilterOptions,
    getToolsForFeatures as getFilteredToolNames,
    getToolDefinition,
} from './toolDefinitions'
import type { Context, Tool, ToolBase, ZodObjectAny } from './types'
// Workflows (batch — orchestration over existing REST endpoints with a blast-radius guard)
import { workflowsBlastRadius, workflowsRunBatch, workflowsScheduleCreate } from './workflows/batch'
// Workflows (lifecycle — CRUD lives in generated/workflows.ts). workflows-disable is intentionally not
// registered: draft routing is gated on ACTIVE status, so disable→edit→enable lands the edit straight on
// the live row and resumes it, skipping the impact preview and signed confirm token that workflows-publish
// makes unskippable. A tool description telling the agent not to do that isn't enforcement — prompt
// injection reaching the agent would just ignore it. Register this only once edits made while disabled
// stage a draft too, or re-enabling a workflow edited while disabled requires publish confirmation.
// The factory stays in lifecycle.ts for that day.
import { workflowsArchive, workflowsEnable } from './workflows/lifecycle'

// Map of tool names to tool factory functions
export const TOOL_MAP: Record<string, () => ToolBase<ZodObjectAny>> = {
    // Organizations
    'organizations-get': getOrganizations,
    'switch-organization': setActiveOrganization,

    // Projects
    'projects-get': getProjects,
    'switch-project': setActiveProject,
    'event-definition-create': createEventDefinition,
    'event-definition-update': updateEventDefinition,
    'property-definition-update': updatePropertyDefinition,

    // Feature flags (get-definition-by-key is hand-written; get-definition by numeric id is codegen)
    'feature-flag-get-definition-by-key': featureFlagGetDefinitionByKey,

    'path-cleaning-rules-update': updatePathCleaning,

    // Experiments (results is hand-written; CRUD + lifecycle are codegen)
    'experiment-results-get': getExperimentResults,
    // Deprecated alias for experiment-list — forwards and annotates the response.
    'experiment-get-all': experimentListDeprecated,

    // Insights
    'insight-query': queryInsight,

    // Links (utility — canonical app URLs so the model never hand-builds/mis-slugs entity links)
    'generate-app-url': generateAppUrl,

    // AI observability
    'get-llm-total-costs-for-project': getLLMCosts,
    'llma-parser-recipe-create': parserRecipeCreate,
    'llma-parser-recipe-reference': parserRecipeReference,

    // Notebooks
    'notebook-edit': notebookEdit,
    'notebooks-add-cell': notebookAddCell,
    'notebooks-create-markdown': notebookCreateMarkdown,
    'notebooks-delete-cell': notebookDeleteCell,
    'notebooks-update-cell': notebookUpdateCell,

    // Debug
    'debug-mcp-ui-apps': debugMcpUiApps,
    'loops-review': loopsReview,

    // Feedback
    'agent-feedback': submitFeedback,

    // Current-task comments. The model never supplies a task id; the host-stamped MCP context does.
    'tasks-artifacts-list': tasksArtifactsList,
    'tasks-comments-list': tasksCommentsList,
    'tasks-comments-retrieve': tasksCommentsRetrieve,

    // PostHog AI tools
    [EXECUTE_SQL_TOOL_NAME]: executeSql,
    'read-data-schema': readDataSchema,

    // Replay

    // Data warehouse (custom handlers for non-standard request shapes)
    'external-data-sources-db-schema': externalDataSourcesDbSchema,
    'external-data-sources-preview-resource': externalDataSourcesPreview,
    'external-data-sources-jobs': externalDataSourcesJobs,
    'external-data-sync-logs': externalDataSyncLogs,

    // Workflows lifecycle (thin wrappers over hog_flows_partial_update so MCP gets
    // an idiomatic enable/disable/archive surface without three new REST endpoints).
    'workflows-enable': workflowsEnable,
    'workflows-archive': workflowsArchive,

    // Workflows batch (hand-rolled: blast-radius sizing + echo-back guard before fan-out,
    // composing the existing user_blast_radius / batch_jobs / schedules endpoints).
    'workflows-blast-radius': workflowsBlastRadius,
    'workflows-run-batch': workflowsRunBatch,
    'workflows-schedule-create': workflowsScheduleCreate,

    // PostHog connections — runs any other tool in this map (or a generated one) against a connected
    // project. The registry is injected rather than imported over there so the two don't form a cycle.
    'posthog-connection-call': () => createConnectionCallTool(resolveToolBase),

    // Skills — deprecated llma-skill-* aliases forwarding to the renamed skill-* tools.
    ...SKILL_DEPRECATED_ALIASES,
}

/** Build one tool by name, from the hand-written and generated registries alike. */
function resolveToolBase(name: string): ToolBase<ZodObjectAny> | undefined {
    return { ...TOOL_MAP, ...GENERATED_TOOL_MAP }[name]?.()
}

export const getToolsFromContext = async (
    context: Context,
    options?: ToolFilterOptions
): Promise<Tool<ZodObjectAny>[]> => {
    // Check org AI consent to gate tools that use LLMs internally (cached in StateManager)
    const aiConsentGiven = await context.stateManager.getAiConsentGiven()
    const effectiveOptions = aiConsentGiven !== undefined ? { ...options, aiConsentGiven } : options
    const effectiveMap = { ...TOOL_MAP, ...GENERATED_TOOL_MAP }
    const excludeTools = options?.excludeTools ?? []
    const allowedToolNames = getFilteredToolNames(effectiveOptions).filter((name) => !excludeTools.includes(name))
    const toolBases: ToolBase<ZodObjectAny>[] = []

    for (const toolName of allowedToolNames) {
        const toolFactory = effectiveMap[toolName]
        if (toolFactory) {
            toolBases.push(toolFactory())
        }
    }

    const tools: Tool<ZodObjectAny>[] = toolBases.map((toolBase) => {
        const definition = getToolDefinition(toolBase.name)
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

    const candidates = tools.filter((tool) => hasScopes(scopes, tool.scopes))

    return filterStaffOnlyTools(candidates, apiKey ?? { scopes: [] }, () => context.stateManager.getUser())
}
