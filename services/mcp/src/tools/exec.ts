import { z } from 'zod'

import { formatResponse } from '@/lib/response'

import { TOKEN_CHAR_LIMIT, listAvailablePaths, resolveSchemaPath, summarizeSchema } from './schema-utils'
import { POSTHOG_META_KEY, type Context, type Tool, type ZodObjectAny } from './types'

type ExecSchema = ReturnType<typeof makeExecSchema>

function makeExecSchema(commandReference: string): z.ZodObject<{ command: z.ZodString }> {
    return z.object({
        command: z.string().describe(commandReference),
    })
}

function parseCommand(input: string): { verb: string; rest: string } {
    const trimmed = input.trim()
    const idx = trimmed.indexOf(' ')
    if (idx === -1) {
        return { verb: trimmed, rest: '' }
    }
    return { verb: trimmed.slice(0, idx), rest: trimmed.slice(idx + 1).trim() }
}

function findTool(tools: Tool<ZodObjectAny>[], name: string): Tool<ZodObjectAny> {
    const tool = tools.find((t) => t.name === name)
    if (!tool) {
        const available = tools.map((t) => t.name).join(', ')
        throw new Error(`Unknown tool: "${name}". Available tools: ${available}`)
    }
    return tool
}

export function createExecTool(
    allTools: Tool<ZodObjectAny>[],
    context: Context,
    toolDescription: string,
    commandReference: string
): Tool<ExecSchema> {
    const ExecSchema = makeExecSchema(commandReference)

    return {
        name: 'exec',
        title: 'Execute PostHog command',
        description: toolDescription,
        schema: ExecSchema,
        scopes: [],
        annotations: {
            destructiveHint: false,
            idempotentHint: false,
            openWorldHint: true,
            readOnlyHint: false,
        },
        handler: async (_context: Context, params: z.infer<ExecSchema>) => {
            const { verb, rest } = parseCommand(params.command)

            switch (verb) {
                case 'tools': {
                    return JSON.stringify(allTools.map((t) => t.name))
                }

                case 'search': {
                    if (!rest) {
                        throw new Error('Usage: search <regex_pattern>')
                    }
                    let regex: RegExp
                    try {
                        regex = new RegExp(rest, 'i')
                    } catch {
                        throw new Error(`Invalid regex pattern: "${rest}"`)
                    }
                    const matches = allTools
                        .filter((t) => regex.test(t.name) || regex.test(t.title) || regex.test(t.description))
                        .map((t) => t.name)
                    if (matches.length === 0) {
                        return JSON.stringify({
                            matches: [],
                            hint: `No tools matched "${rest}". Run "tools" to see all available tool names.`,
                        })
                    }
                    return JSON.stringify(matches)
                }

                case 'info': {
                    if (!rest) {
                        throw new Error('Usage: info <tool_name>')
                    }
                    const tool = findTool(allTools, rest)
                    const fullSchema = z.toJSONSchema(tool.schema)
                    const fullOutput = JSON.stringify({
                        name: tool.name,
                        title: tool.title,
                        description: tool.description,
                        annotations: tool.annotations,
                        inputSchema: fullSchema,
                    })

                    if (fullOutput.length <= TOKEN_CHAR_LIMIT) {
                        return fullOutput
                    }

                    // Schema too large — return summary with drill-down hints
                    return JSON.stringify({
                        name: tool.name,
                        title: tool.title,
                        description: tool.description,
                        annotations: tool.annotations,
                        inputSchema: summarizeSchema(fullSchema as Record<string, unknown>, tool.name),
                    })
                }

                case 'schema': {
                    if (!rest) {
                        throw new Error('Usage: schema <tool_name> [field_path]')
                    }
                    const { verb: schemaToolName, rest: fieldPath } = parseCommand(rest)
                    const schemaTool = findTool(allTools, schemaToolName)
                    const fullJsonSchema = z.toJSONSchema(schemaTool.schema) as Record<string, unknown>

                    if (!fieldPath) {
                        return JSON.stringify(summarizeSchema(fullJsonSchema, schemaToolName))
                    }

                    const resolved = resolveSchemaPath(fullJsonSchema, fieldPath)
                    if (!resolved) {
                        const available = listAvailablePaths(fullJsonSchema)
                        throw new Error(`Unknown path "${fieldPath}". Available: ${available.join(', ')}`)
                    }

                    const serialized = JSON.stringify({
                        field: fieldPath,
                        schema: resolved,
                    })
                    if (serialized.length <= TOKEN_CHAR_LIMIT) {
                        return serialized
                    }

                    // Field schema too large — return summary with sub-path hints
                    return JSON.stringify({
                        field: fieldPath,
                        note: `Full schema is ${Math.ceil(serialized.length / 6000)}k+ tokens. Showing summary. Drill into sub-fields for details.`,
                        schema: summarizeSchema(resolved as Record<string, unknown>, schemaToolName, fieldPath),
                    })
                }

                case 'call': {
                    if (!rest) {
                        throw new Error('Usage: call [--json] <tool_name> <json_input>')
                    }
                    const forceJson = rest.startsWith('--json ') || rest === '--json'
                    const callArgs = forceJson ? rest.slice('--json'.length).trim() : rest
                    if (!callArgs) {
                        throw new Error('Usage: call [--json] <tool_name> <json_input>')
                    }
                    const { verb: toolName, rest: jsonBody } = parseCommand(callArgs)
                    const tool = findTool(allTools, toolName)

                    let input: Record<string, unknown>
                    if (!jsonBody) {
                        input = {}
                    } else {
                        try {
                            input = JSON.parse(jsonBody) as Record<string, unknown>
                        } catch {
                            throw new Error(`Invalid JSON input: ${jsonBody}`)
                        }
                    }

                    const result = await tool.handler(context, input)
                    const useJson = forceJson || tool._meta?.[POSTHOG_META_KEY]?.responseFormat === 'json'
                    return useJson ? JSON.stringify(result) : formatResponse(result)
                }

                default:
                    throw new Error(`Unknown command: "${verb}". Supported commands: tools, search, info, schema, call`)
            }
        },
    }
}
