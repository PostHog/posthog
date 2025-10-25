import z from 'zod'
import toolDefinitionsJson from '../../../schema/tool-definitions.json'

export const ToolDefinitionSchema = z.object({
    description: z.string(),
    category: z.string(),
    feature: z.string(),
    summary: z.string(),
    title: z.string(),
    required_scopes: z.array(z.string()),
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

export function getToolsForFeatures(features?: string[]): string[] {
    const toolDefinitions = getToolDefinitions()

    if (!features || features.length === 0) {
        return Object.keys(toolDefinitions)
    }

    return Object.entries(toolDefinitions)
        .filter(([_, definition]) => definition.feature && features.includes(definition.feature))
        .map(([toolName, _]) => toolName)
}
