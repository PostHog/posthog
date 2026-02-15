import z from 'zod'

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

export function getToolDefinitions(version?: number): ToolDefinitions {
    if (version === 2) {
        if (!_toolDefinitionsV2) {
            const base = toolDefinitionsSchema.parse(toolDefinitionsJson)
            const new_tools = toolDefinitionsSchema.parse(toolDefinitionsV2Json)
            _toolDefinitionsV2 = { ...new_tools, ...base }
        }
        return _toolDefinitionsV2
    }

    if (!_toolDefinitionsV1) {
        _toolDefinitionsV1 = toolDefinitionsSchema.parse(toolDefinitionsJson)
    }
    return _toolDefinitionsV1
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
    version?: number | undefined
}

export function getToolsForFeatures(options?: ToolFilterOptions): string[] {
    const { features, version } = options || {}
    const toolDefinitions = getToolDefinitions(version)

    let entries = Object.entries(toolDefinitions)

    // Filter out tools that are not supported in new MCP
    if (version === 2) {
        entries = entries.filter(([_, definition]) => definition.new_mcp !== false)
    }

    // Filter by features if provided
    if (features && features.length > 0) {
        entries = entries.filter(([_, definition]) => definition.feature && features.includes(definition.feature))
    }

    return entries.map(([toolName, _]) => toolName)
}
