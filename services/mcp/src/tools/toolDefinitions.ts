import z from 'zod'

import generatedToolDefinitionsJson from '../../schema/generated-tool-definitions.json'
import toolDefinitionsV2Json from '../../schema/tool-definitions-v2.json'
import toolDefinitionsJson from '../../schema/tool-definitions.json'

export const ToolDefinitionSchema = z.object({
    description: z.string(),
    category: z.string(),
    feature: z.string(),
    summary: z.string(),
    title: z.string(),
    required_scopes: z.array(z.string()),
    new_mcp: z.boolean().optional(),
    requires_ai_consent: z.boolean().optional(),
    /** PostHog feature flag key that gates this tool. */
    feature_flag: z.string().optional(),
    /** How the flag gates the tool: 'enable' (default) or 'disable'. */
    feature_flag_behavior: z.enum(['enable', 'disable']).optional(),
    /** One-line selection hint surfaced in the system prompt's query tool catalog. */
    system_prompt_hint: z.string().optional(),
    /**
     * When true, the tool is exposed even when the client passes a `features`
     * or `tools` allowlist that wouldn't otherwise match. Reserved for
     * cross-cutting utility tools (e.g. feedback) that should remain
     * discoverable to every client without forcing them to opt in.
     * Other filters (readOnly, AI consent, feature flags, scopes) still apply.
     */
    always_available: z.boolean().optional(),
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
     * Map of feature flag key → evaluated boolean result.
     * Used to gate tools that declare `feature_flag` in their YAML config.
     */
    featureFlags?: Record<string, boolean> | undefined
}

/**
 * Collect all distinct feature flag keys referenced by tool definitions.
 * Used at init time to batch-evaluate flags before filtering tools.
 */
export function getRequiredFeatureFlags(version?: number): string[] {
    const toolDefinitions = getToolDefinitions(version)
    const flags = new Set<string>()
    for (const definition of Object.values(toolDefinitions)) {
        if (definition.feature_flag) {
            flags.add(definition.feature_flag)
        }
    }
    return [...flags]
}

function normalizeFeatureName(name: string): string {
    return name.replace(/-/g, '_')
}

export function getToolsForFeatures(options?: ToolFilterOptions): string[] {
    const { features, tools, version, readOnly, aiConsentGiven, featureFlags } = options || {}
    const toolDefinitions = getToolDefinitions(version)

    let entries = Object.entries(toolDefinitions)

    // Filter out tools that are not supported in new MCP
    if (version === 2) {
        entries = entries.filter(([_, definition]) => definition.new_mcp !== false)
    }

    // Filter by features and/or tools allowlist (OR union).
    // When both are provided, a tool is included if it matches a feature category OR is in the tools list.
    // Normalize hyphens to underscores so that both "error-tracking" and "error_tracking" match.
    // Tools marked `always_available` bypass this allowlist so utility tools
    // (e.g. feedback) stay discoverable for every client.
    const hasFeatures = features && features.length > 0
    const hasTools = tools && tools.length > 0
    if (hasFeatures || hasTools) {
        const normalizedFeatures = hasFeatures ? new Set(features.map(normalizeFeatureName)) : null
        const allowedTools = hasTools ? new Set(tools) : null

        entries = entries.filter(([toolName, definition]) => {
            if (definition.always_available) {
                return true
            }
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

    // Filter by feature flags — tools with a feature_flag are gated by the flag's evaluation.
    // behavior 'enable' (default): tool is included only when the flag is on.
    // behavior 'disable': tool is excluded when the flag is on.
    if (featureFlags) {
        entries = entries.filter(([_, definition]) => {
            if (!definition.feature_flag) {
                return true
            }
            const flagValue = featureFlags[definition.feature_flag]
            // If the flag wasn't evaluated (missing from the map), exclude the tool
            // for 'enable' behavior and include it for 'disable' behavior.
            const isOn = flagValue === true
            const behavior = definition.feature_flag_behavior ?? 'enable'
            return behavior === 'enable' ? isOn : !isOn
        })
    } else {
        // When no feature flags have been evaluated, exclude tools that require
        // a flag to be enabled (behavior 'enable') — they shouldn't appear by default.
        // Tools with behavior 'disable' are included since their flag hasn't fired.
        entries = entries.filter(([_, definition]) => {
            if (!definition.feature_flag) {
                return true
            }
            return (definition.feature_flag_behavior ?? 'enable') === 'disable'
        })
    }

    return entries.map(([toolName, _]) => toolName)
}
