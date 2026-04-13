import z from 'zod'

import generatedToolDefinitionsJson from '../../schema/generated-tool-definitions.json'
import toolDefinitionsV2Json from '../../schema/tool-definitions-v2.json'
import toolDefinitionsJson from '../../schema/tool-definitions.json'

/**
 * Feature flag configuration for conditional tool availability.
 * String form: flag key — tool is enabled when flag is true.
 * Object form: { key, invert } — tool is enabled when flag matches expected state.
 */
export const FeatureFlagConfigSchema = z.union([
    z.string(),
    z.object({
        key: z.string(),
        invert: z.boolean().optional(),
    }),
])

export type FeatureFlagConfig = z.infer<typeof FeatureFlagConfigSchema>

export const ToolDefinitionSchema = z.object({
    description: z.string(),
    category: z.string(),
    feature: z.string(),
    summary: z.string(),
    title: z.string(),
    required_scopes: z.array(z.string()),
    new_mcp: z.boolean().optional(),
    requires_ai_consent: z.boolean().optional(),
    /** Feature flag that controls tool availability at runtime. */
    feature_flag: FeatureFlagConfigSchema.optional(),
    annotations: z.object({
        destructiveHint: z.boolean(),
        idempotentHint: z.boolean(),
        openWorldHint: z.boolean(),
        readOnlyHint: z.boolean(),
    }),
})

export type ToolDefinition = z.infer<typeof ToolDefinitionSchema>

export type ToolDefinitions = Record<string, ToolDefinition>

const toolDefinitionsSchema = z.record(z.string(), ToolDefinitionSchema)

let _toolDefinitionsV1: ToolDefinitions | undefined = undefined
let _toolDefinitionsV2: ToolDefinitions | undefined = undefined
let _generatedToolDefinitions: ToolDefinitions | undefined = undefined

function getGeneratedToolDefinitions(): ToolDefinitions {
    if (!_generatedToolDefinitions) {
        _generatedToolDefinitions = toolDefinitionsSchema.parse(generatedToolDefinitionsJson)
    }
    return _generatedToolDefinitions
}

export function getToolDefinitions(version?: number): ToolDefinitions {
    const generated = getGeneratedToolDefinitions()

    if (version === 2) {
        if (!_toolDefinitionsV2) {
            const base = toolDefinitionsSchema.parse(toolDefinitionsJson)
            const new_tools = toolDefinitionsSchema.parse(toolDefinitionsV2Json)
            _toolDefinitionsV2 = { ...new_tools, ...base }
        }
        return { ..._toolDefinitionsV2, ...generated }
    }

    if (!_toolDefinitionsV1) {
        _toolDefinitionsV1 = toolDefinitionsSchema.parse(toolDefinitionsJson)
    }
    return { ..._toolDefinitionsV1, ...generated }
}

export function getToolDefinition(toolName: string, version?: number): ToolDefinition {
    const toolDefinitions = getToolDefinitions(version)

    const definition = toolDefinitions[toolName]

    if (!definition) {
        throw new Error(`Tool definition not found for: ${toolName}`)
    }

    return definition
}

export interface ToolFilterOptions {
    features?: string[] | undefined
    tools?: string[] | undefined
    version?: number | undefined
    excludeTools?: string[] | undefined
    readOnly?: boolean | undefined
    aiConsentGiven?: boolean | undefined
    /**
     * Evaluated feature flags for the current user. Keys are flag keys, values are
     * the flag result (boolean or string for multivariate flags). When provided,
     * tools with feature_flag config are filtered based on their flag evaluation.
     */
    evaluatedFlags?: Record<string, boolean | string> | undefined
}

function normalizeFeatureName(name: string): string {
    return name.replace(/-/g, '_')
}

/**
 * Check if a tool should be enabled based on its feature flag configuration
 * and the evaluated flags for the current user.
 */
function isToolEnabledByFeatureFlag(
    featureFlagConfig: FeatureFlagConfig | undefined,
    evaluatedFlags: Record<string, boolean | string> | undefined
): boolean {
    // No feature flag config means the tool is always enabled
    if (!featureFlagConfig) {
        return true
    }

    // If we don't have evaluated flags, skip tools with feature flag requirements
    // (they'll be filtered out until flags are available)
    if (!evaluatedFlags) {
        return false
    }

    // Parse the feature flag config
    const flagKey = typeof featureFlagConfig === 'string' ? featureFlagConfig : featureFlagConfig.key
    const invert = typeof featureFlagConfig === 'object' && featureFlagConfig.invert === true

    // Get the evaluated flag value
    const flagValue = evaluatedFlags[flagKey]

    // Determine if the flag is "on" (truthy for boolean, or any non-empty string for multivariate)
    const flagIsOn = flagValue === true || (typeof flagValue === 'string' && flagValue !== '')

    // Apply invert logic: if invert is true, enable when flag is off
    return invert ? !flagIsOn : flagIsOn
}

export function getToolsForFeatures(options?: ToolFilterOptions): string[] {
    const { features, tools, version, readOnly, aiConsentGiven, evaluatedFlags } = options || {}
    const toolDefinitions = getToolDefinitions(version)

    let entries = Object.entries(toolDefinitions)

    // Filter out tools that are not supported in new MCP
    if (version === 2) {
        entries = entries.filter(([_, definition]) => definition.new_mcp !== false)
    }

    // Filter by features and/or tools allowlist (OR union).
    // When both are provided, a tool is included if it matches a feature category OR is in the tools list.
    // Normalize hyphens to underscores so that both "error-tracking" and "error_tracking" match.
    const hasFeatures = features && features.length > 0
    const hasTools = tools && tools.length > 0
    if (hasFeatures || hasTools) {
        const normalizedFeatures = hasFeatures ? new Set(features.map(normalizeFeatureName)) : null
        const allowedTools = hasTools ? new Set(tools) : null

        entries = entries.filter(([toolName, definition]) => {
            const matchesFeature = normalizedFeatures
                ? definition.feature && normalizedFeatures.has(normalizeFeatureName(definition.feature))
                : false
            const matchesTool = allowedTools ? allowedTools.has(toolName) : false
            return matchesFeature || matchesTool
        })
    }

    // In read-only mode, only expose tools annotated as read-only
    if (readOnly) {
        entries = entries.filter(([_, definition]) => definition.annotations.readOnlyHint === true)
    }

    // When AI consent is not given or not yet fetched, exclude tools that require it
    if (!aiConsentGiven) {
        entries = entries.filter(([_, definition]) => !definition.requires_ai_consent)
    }

    // Filter by feature flag configuration
    // Tools with feature_flag config are only included if the flag evaluates appropriately
    entries = entries.filter(([_, definition]) => isToolEnabledByFeatureFlag(definition.feature_flag, evaluatedFlags))

    return entries.map(([toolName, _]) => toolName)
}
