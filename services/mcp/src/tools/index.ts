import { hasScopes } from '@/lib/api'

// Agent platform (hand-written — CRUD is codegen in generated/agent_platform.ts)
import resolveResource from './agentPlatform/resolveResource'
// AI observability
import getLLMCosts from './aiObservability/getLLMCosts'
// Debug
import debugMcpUiApps from './debug/debugMcpUiApps'
// Experiments (hand-written — CRUD + lifecycle are codegen in generated/experiments.ts)
import getExperimentResults from './experiments/getResults'
import experimentListDeprecated from './experiments/listDeprecated'
// Feedback
import submitFeedback from './feedback/submit'
// Generated tools (from definitions/*.yaml)
import { GENERATED_TOOL_MAP } from './generated'
// Insights
import queryInsight from './insights/query'
// Links (utility — builds canonical app URLs from the frontend's route table)
import generateAppUrl from './links/generate-app-url'
// Notebooks (edit is hand-written — generated CRUD lives in generated/notebooks.ts)
import notebookEdit from './notebooks/edit'
// Organizations
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
// Projects
import getProjects from './projects/getProjects'
import setActiveProject from './projects/setActive'
import updateEventDefinition from './projects/updateEventDefinition'
// Replay
import sessionRecordingSummarize from './replay/sessionRecordingSummarize'
// Skills (deprecation aliases for the llma-skill-* → skill-* rename)
import { SKILL_DEPRECATED_ALIASES } from './skills/deprecatedAliases'
// Misc
import {
    type ToolFilterOptions,
    getToolsForFeatures as getFilteredToolNames,
    getToolDefinition,
} from './toolDefinitions'
import type { Context, Tool, ToolBase, ZodObjectAny } from './types'
// Workflows (batch — orchestration over existing REST endpoints with a blast-radius guard)
import { workflowsBlastRadius, workflowsRunBatch, workflowsScheduleCreate } from './workflows/batch'
// Workflows (lifecycle — CRUD lives in generated/workflows.ts). workflows-disable is intentionally
// not registered: editing active workflows is blocked, and exposing disable invited a
// disable→edit→enable workaround. The factory stays in lifecycle.ts for easy re-enable.
import { workflowsArchive, workflowsEnable } from './workflows/lifecycle'

// Map of tool names to tool factory functions
export const TOOL_MAP: Record<string, () => ToolBase<ZodObjectAny>> = {
    // Organizations
    'switch-organization': setActiveOrganization,

    // Projects
    'projects-get': getProjects,
    'switch-project': setActiveProject,
    'event-definition-update': updateEventDefinition,

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

    // Notebooks
    'notebook-edit': notebookEdit,

    // Debug
    'debug-mcp-ui-apps': debugMcpUiApps,

    // Feedback
    'agent-feedback': submitFeedback,

    // Agent platform (read-only playbook resolver — CRUD lives in generated/agent_platform.ts)
    'agent-resolve-resource': resolveResource,

    // PostHog AI tools
    [EXECUTE_SQL_TOOL_NAME]: executeSql,
    'read-data-schema': readDataSchema,

    // Replay
    'session-recording-summarize': sessionRecordingSummarize,

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

    // Skills — deprecated llma-skill-* aliases forwarding to the renamed skill-* tools.
    ...SKILL_DEPRECATED_ALIASES,
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

    return tools.filter((tool) => hasScopes(scopes, tool.scopes))
}
