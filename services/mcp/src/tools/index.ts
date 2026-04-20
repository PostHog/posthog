import { hasScopes } from '@/lib/api'

// Debug
import debugMcpUiApps from './debug/debugMcpUiApps'
// Documentation
import searchDocs from './documentation/searchDocs'
// Experiments (hand-written — CRUD + lifecycle are codegen in generated/experiments.ts)
import getExperimentResults from './experiments/getResults'
// Generated tools (from definitions/*.yaml)
import { GENERATED_TOOL_MAP } from './generated'
// Insights
import queryInsight from './insights/query'
// LLM Analytics
import getLLMCosts from './llmAnalytics/getLLMCosts'
// Organizations
import setActiveOrganization from './organizations/setActive'
// PostHog AI tools
import {
    executeSql,
    externalDataSourcesDbSchema,
    externalDataSourcesJobs,
    readDataSchema,
    readDataWarehouseSchema,
} from './posthogAiTools'
// Projects
import eventDefinitions from './projects/eventDefinitions'
import getProjects from './projects/getProjects'
import getProperties from './projects/propertyDefinitions'
import setActiveProject from './projects/setActive'
import updateEventDefinition from './projects/updateEventDefinition'
// Query
import generateHogQLFromQuestion from './query/generateHogQLFromQuestion'
import queryRun from './query/run'
// Search
import entitySearch from './search/entitySearch'
// Misc
import {
    type ToolFilterOptions,
    getToolsForFeatures as getFilteredToolNames,
    getToolDefinition,
} from './toolDefinitions'
// Toolsets (progressive disclosure meta-tool)
import toolsetsMetaTool from './toolsets/manage'
import type { Context, Tool, ToolBase, ZodObjectAny } from './types'

// Map of tool names to tool factory functions
export const TOOL_MAP: Record<string, () => ToolBase<ZodObjectAny>> = {
    // Organizations
    'switch-organization': setActiveOrganization,

    // Projects
    'projects-get': getProjects,
    'switch-project': setActiveProject,
    'event-definitions-list': eventDefinitions,
    'event-definition-update': updateEventDefinition,
    'properties-list': getProperties,

    // Documentation - handled separately due to env check
    // "docs-search": searchDocs,

    // Experiments (results is hand-written; CRUD + lifecycle are codegen)
    'experiment-results-get': getExperimentResults,

    // Insights
    'insight-query': queryInsight,

    // Queries
    'query-generate-hogql-from-question': generateHogQLFromQuestion,
    'query-run': queryRun,

    // LLM Analytics
    'get-llm-total-costs-for-project': getLLMCosts,

    // Search
    'entity-search': entitySearch,

    // Debug
    'debug-mcp-ui-apps': debugMcpUiApps,

    // PostHog AI tools
    'execute-sql': executeSql,
    'read-data-schema': readDataSchema,
    'read-data-warehouse-schema': readDataWarehouseSchema,

    // Data warehouse (custom handlers for non-standard request shapes)
    'external-data-sources-db-schema': externalDataSourcesDbSchema,
    'external-data-sources-jobs': externalDataSourcesJobs,

    // Meta (progressive disclosure)
    toolsets: toolsetsMetaTool,
}

export const getToolsFromContext = async (
    context: Context,
    options?: ToolFilterOptions
): Promise<Tool<ZodObjectAny>[]> => {
    // Check org AI consent to gate tools that use LLMs internally (cached in StateManager)
    const aiConsentGiven = await context.stateManager.getAiConsentGiven()

    // Progressive disclosure: merge session-enabled toolsets from cache with
    // any toolsets pre-enabled via the ?toolsets=a,b query param.
    let enabledToolsetsForFilter: string[] | undefined
    if (options?.progressive) {
        const sessionEnabled = ((await context.cache.get('enabledToolsets' as any)) ?? []) as string[]
        const fromQuery = options?.enabledToolsets ?? []
        enabledToolsetsForFilter = Array.from(new Set([...sessionEnabled, ...fromQuery]))
    }

    const effectiveOptions: ToolFilterOptions = {
        ...options,
        ...(aiConsentGiven !== undefined ? { aiConsentGiven } : {}),
        ...(enabledToolsetsForFilter !== undefined ? { enabledToolsets: enabledToolsetsForFilter } : {}),
    }
    const effectiveMap = { ...TOOL_MAP, ...GENERATED_TOOL_MAP }
    // The toolsets meta-tool only exists in progressive mode — skip it in default mode so
    // the default tool surface is unchanged.
    const baseExcludes = options?.excludeTools ?? []
    const excludeTools = options?.progressive ? baseExcludes : [...baseExcludes, 'toolsets']
    const allowedToolNames = getFilteredToolNames(effectiveOptions).filter((name) => !excludeTools.includes(name))
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

    // Filter tools by mcpVersion — when set, the tool is exclusive to that version
    const effectiveVersion = options?.version ?? 1
    const filteredBases = toolBases.filter((tb) => tb.mcpVersion === undefined || tb.mcpVersion === effectiveVersion)

    const tools: Tool<ZodObjectAny>[] = filteredBases.map((toolBase) => {
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
