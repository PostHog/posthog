import z from 'zod'

import toolDefinitionsJson from '../../schema/tool-definitions.json'

export const ToolDefinitionSchema = z.object({
    description: z.string(),
    category: z.string(),
    feature: z.string(),
    summary: z.string(),
    title: z.string(),
    required_scopes: z.array(z.string()),
    new_mcp: z.boolean(),
    annotations: z.object({
        destructiveHint: z.boolean(),
        idempotentHint: z.boolean(),
        openWorldHint: z.boolean(),
        readOnlyHint: z.boolean(),
    }),
})

export type ToolDefinition = z.infer<typeof ToolDefinitionSchema>

export type ToolDefinitions = Record<string, ToolDefinition>

let _toolDefinitions: ToolDefinitions | undefined = undefined

export function getToolDefinitions(): ToolDefinitions {
    if (!_toolDefinitions) {
        _toolDefinitions = z.record(z.string(), ToolDefinitionSchema).parse(toolDefinitionsJson)
    }
    return _toolDefinitions
}

export function getToolDefinition(toolName: string): ToolDefinition {
    const toolDefinitions = getToolDefinitions()

    const definition = toolDefinitions[toolName]

    if (!definition) {
        throw new Error(`Tool definition not found for: ${toolName}`)
    }

    return definition
}

export interface ToolFilterOptions {
    features?: string[] | undefined
    newMcpOnly?: boolean | undefined
}

export function getToolsForFeatures(options?: ToolFilterOptions): string[] {
    const toolDefinitions = getToolDefinitions()
    const { features, newMcpOnly } = options || {}

    let entries = Object.entries(toolDefinitions)

    // Filter by new_mcp if requested
    if (newMcpOnly) {
        entries = entries.filter(([_, definition]) => definition.new_mcp === true)
    }

    // Filter by features if provided
    if (features && features.length > 0) {
        entries = entries.filter(([_, definition]) => definition.feature && features.includes(definition.feature))
    }

    return entries.map(([toolName, _]) => toolName)
}
