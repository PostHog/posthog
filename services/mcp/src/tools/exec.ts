import { stringify as stringifyYaml } from 'yaml'
import { z } from 'zod'

import { markExecPayload, buildToolResultPayload } from '@/lib/build-tool-result'
import { isPostHogCodeConsumer } from '@/lib/client-detection'
import { formatResponse } from '@/lib/response'

import { TOKEN_CHAR_LIMIT, listAvailablePaths, resolveSchemaPath, summarizeSchema } from './schema-utils'
import {
    POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY,
    POSTHOG_META_KEY,
    type Context,
    type Tool,
    type ZodObjectAny,
} from './types'

type ExecSchema = ReturnType<typeof makeExecSchema>

// Surfaced on every truncated/summarized schema view to push the model to
// keep drilling instead of guessing the shape from sibling fields or
// pre-training. Phrased as an instruction, not a description, because models
// observably treat declarative notes as advisory.
const SCHEMA_DRILLDOWN_DIRECTIVE =
    'SUMMARIZED - DO NOT GUESS. For any field you plan to populate that has a `hint`, you must run the exact `schema` command in that hint. Keep drilling until the needed path has neither a `note` nor a `hint`. Do not infer shape from names, sibling tools, or prior knowledge.'

export interface ExecInnerCallProperties {
    duration_ms: number
    success: boolean
    output_format: 'json' | 'text' | 'structured'
    error_message?: string
}

export type ExecInnerCallTracker = (toolName: string, properties: ExecInnerCallProperties) => void

function makeExecSchema(commandReference: string): z.ZodObject<{ command: z.ZodString }> {
    return z.object({
        command: z.string().describe(commandReference),
    })
}

function summaryHasHints(summary: ReturnType<typeof summarizeSchema>): boolean {
    return Object.values(summary.properties).some((p) => p.hint !== undefined)
}

function parseCommand(input: string): { verb: string; rest: string } {
    const trimmed = input.trim()
    const idx = trimmed.indexOf(' ')
    if (idx === -1) {
        return { verb: trimmed, rest: '' }
    }
    return { verb: trimmed.slice(0, idx), rest: trimmed.slice(idx + 1).trim() }
}

// Extracts the inner tool name from an exec `call` command, e.g.
// "call my-tool {...}" → "my-tool". Returns undefined for other verbs or
// malformed input. Used by analytics to surface the real tool being invoked
// in single-exec mode, where the outer call always shows as `exec`.
export function parseExecCallInnerToolName(command: string): string | undefined {
    const { verb, rest } = parseCommand(command)
    if (verb !== 'call' || !rest) {
        return
    }
    const argv = rest.startsWith('--json ') ? rest.slice('--json '.length).trim() : rest === '--json' ? '' : rest
    if (!argv) {
        return
    }
    const innerName = parseCommand(argv).verb
    return innerName || undefined
}

// Builds the resolver mcp.ts hands to initMcpAnalytics in single-exec
// mode: given a request, return the inner tool's { name, description } when
// the agent invoked it via `call <tool> ...`, or undefined otherwise. Lives
// here (alongside parseExecCallInnerToolName) so tests can import the exact
// same factory the production code uses — no copy-pasted resolver lambda.
export function createExecInnerToolCallResolver(
    allTools: ReadonlyArray<Tool<ZodObjectAny>>
): (request: unknown) => { name: string; description: string } | undefined {
    return (request: unknown) => {
        const params = (request as { params?: { name?: unknown; arguments?: { command?: unknown } } })?.params
        if (params?.name !== 'exec' || typeof params.arguments?.command !== 'string') {
            return
        }
        const innerName = parseExecCallInnerToolName(params.arguments.command)
        if (!innerName) {
            return
        }
        const tool = allTools.find((t) => t.name === innerName)
        return tool ? { name: tool.name, description: tool.description } : undefined
    }
}

// Tools removed from v2 (single-exec) MCP. When the model attempts to call one,
// surface a targeted redirect to the v2 replacement instead of dumping the full
// tool catalog. Sourced from tools marked `new_mcp: false` in
// schema/tool-definitions.json. Keep the redirect text editorial — schemas
// don't carry "use X instead" guidance.
const DEPRECATED_TOOL_REDIRECTS: Record<string, (allTools: Tool<ZodObjectAny>[]) => string> = {
    'entity-search': () =>
        'Tool "entity-search" was removed in MCP v2. Use "execute-sql" to search PostHog data via HogQL. Consult the `querying-posthog-data` skill for system-table patterns (system.insights, system.dashboards, system.cohorts, ...).',
    'event-definitions-list': () =>
        'Tool "event-definitions-list" was removed in MCP v2. Use "read-data-schema" with input { "query": { "kind": "events" } } to list event definitions.',
    'properties-list': () =>
        'Tool "properties-list" was removed in MCP v2. Use "read-data-schema": { "query": { "kind": "event_properties", "event_name": "..." } } for event properties, or { "kind": "entity_properties", "entity": "person" | "session" | "group/<n>" } for entity properties.',
    'property-definitions': () =>
        'Tool "property-definitions" was removed in MCP v2. Use "read-data-schema" with the appropriate kind: "event_properties", "entity_properties", or "action_properties" — see its info schema for required fields.',
    'query-generate-hogql-from-question': () =>
        'Tool "query-generate-hogql-from-question" was removed in MCP v2. Write the HogQL yourself and run it via "execute-sql". Consult the `querying-posthog-data` skill for HogQL patterns.',
    'query-run': (allTools) => {
        const queryTools = allTools
            .filter((t) => t.name.startsWith('query-'))
            .map((t) => `- ${t.name}: ${t.description.split('\n')[0]}`)
            .join('\n')
        return `Tool "query-run" was removed in MCP v2. Pick the typed query tool that matches your intent, or use "execute-sql" for arbitrary HogQL. Available query-* tools:\n${queryTools}`
    },
}

function findTool(tools: Tool<ZodObjectAny>[], name: string): Tool<ZodObjectAny> {
    const tool = tools.find((t) => t.name === name)
    if (!tool) {
        const redirect = DEPRECATED_TOOL_REDIRECTS[name]
        if (redirect) {
            throw new Error(redirect(tools))
        }
        const available = tools.map((t) => t.name).join(', ')
        throw new Error(`Unknown tool: "${name}". Available tools: ${available}`)
    }
    return tool
}

export function createExecTool(
    allTools: Tool<ZodObjectAny>[],
    context: Context,
    toolDescription: string,
    commandReference: string,
    mcpConsumer: string | undefined,
    trackInnerCall?: ExecInnerCallTracker
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
                        throw new Error('Usage: info [--json] <tool_name>')
                    }
                    const forceJson = rest.startsWith('--json ') || rest === '--json'
                    const infoArgs = forceJson ? rest.slice('--json'.length).trim() : rest
                    if (!infoArgs) {
                        throw new Error('Usage: info [--json] <tool_name>')
                    }
                    const tool = findTool(allTools, infoArgs)
                    const fullSchema = z.toJSONSchema(tool.schema)
                    // YAML for the top shape, but inputSchema stays as a JSON
                    // string dumped inside the YAML — JSON Schema is conventionally
                    // JSON and converting it to YAML obscures `$ref`, `oneOf`, etc.
                    const serialize = (payload: Record<string, unknown>, schema: unknown): string => {
                        if (forceJson) {
                            return JSON.stringify({ ...payload, inputSchema: schema })
                        }
                        return stringifyYaml({ ...payload, inputSchema: JSON.stringify(schema) }, { lineWidth: 0 })
                    }

                    const topShape = {
                        name: tool.name,
                        title: tool.title,
                        description: tool.description,
                        annotations: tool.annotations,
                    }
                    const fullOutput = serialize(topShape, fullSchema)

                    if (fullOutput.length <= TOKEN_CHAR_LIMIT) {
                        return fullOutput
                    }

                    // Schema too large — return summary with drill-down hints.
                    // Attach the same directive used by `schema` so agents don't
                    // treat `info` summaries as enough to construct nested fields.
                    const summary = summarizeSchema(fullSchema as Record<string, unknown>, tool.name)
                    if (summaryHasHints(summary)) {
                        return serialize({ ...topShape, note: SCHEMA_DRILLDOWN_DIRECTIVE }, summary)
                    }
                    return serialize(topShape, summary)
                }

                case 'schema': {
                    if (!rest) {
                        throw new Error('Usage: schema <tool_name> [field_path]')
                    }
                    const { verb: schemaToolName, rest: fieldPath } = parseCommand(rest)
                    const schemaTool = findTool(allTools, schemaToolName)
                    const fullJsonSchema = z.toJSONSchema(schemaTool.schema) as Record<string, unknown>

                    if (!fieldPath) {
                        const summary = summarizeSchema(fullJsonSchema, schemaToolName)
                        // The bare `schema <tool>` view is always a summary. Attach the
                        // drill-down directive whenever any property still carries a
                        // `hint` — that's the only case where the model has more work
                        // to do than what it sees.
                        if (summaryHasHints(summary)) {
                            return JSON.stringify({
                                note: SCHEMA_DRILLDOWN_DIRECTIVE,
                                schema: summary,
                            })
                        }
                        return JSON.stringify(summary)
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

                    // Field schema too large — return summary with sub-path hints.
                    // Lead with the size so the model knows why this is summarized,
                    // then the directive so it knows what to do about it.
                    const sizeK = Math.ceil(serialized.length / 6000)
                    return JSON.stringify({
                        field: fieldPath,
                        note: `Full schema for this field is ~${sizeK}k tokens — too large to inline. ${SCHEMA_DRILLDOWN_DIRECTIVE}`,
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
                        } catch (err) {
                            const detail = err instanceof Error ? err.message : String(err)
                            throw new Error(`Invalid JSON input: ${detail}`)
                        }
                    }

                    const useJson = forceJson || tool._meta?.[POSTHOG_META_KEY]?.outputFormat === 'json'
                    const startedAt = Date.now()
                    let result: unknown
                    try {
                        result = await tool.handler(context, input)
                    } catch (err) {
                        trackInnerCall?.(tool.name, {
                            duration_ms: Date.now() - startedAt,
                            success: false,
                            output_format: useJson ? 'json' : 'text',
                            error_message: err instanceof Error ? err.message : String(err),
                        })
                        throw err
                    }
                    const durationMs = Date.now() - startedAt

                    // If the inner tool has a UI app attached AND the caller self-identifies as
                    // PostHog Code (the UI-apps host), emit a full `CallToolResult` payload
                    // carrying `structuredContent` + `_meta.ui.resourceUri`. Clients only see
                    // the `exec` tool registered in single-exec mode, so the UI metadata has to
                    // ride on the per-call response. Gated on the consumer because other
                    // single-exec callers (direct Claude Code, cline, Slack-launched runs, etc.)
                    // don't render UI apps — they should see plain text.
                    if (tool._meta?.ui?.resourceUri && isPostHogCodeConsumer(mcpConsumer)) {
                        const isStringResult = typeof result === 'string'
                        const distinctId = isStringResult ? undefined : await context.getDistinctId()
                        trackInnerCall?.(tool.name, {
                            duration_ms: durationMs,
                            success: true,
                            output_format: 'structured',
                        })
                        return markExecPayload(
                            buildToolResultPayload({
                                handlerResult: result,
                                toolMeta: tool._meta,
                                toolName: tool.name,
                                params: useJson ? { ...input, output_format: 'json' } : input,
                                // Consumer is the UI-apps host; keep `structuredContent` for the UI.
                                // Passing `undefined` bypasses the coding-agent suppression in
                                // `buildToolResultPayload` because this path explicitly wants it.
                                clientName: undefined,
                                distinctId,
                                includeUiResponseMeta: true,
                            })
                        )
                    }

                    trackInnerCall?.(tool.name, {
                        duration_ms: durationMs,
                        success: true,
                        output_format: useJson ? 'json' : 'text',
                    })
                    if (useJson) {
                        return JSON.stringify(result)
                    }
                    // Optimized mode: when the handler attached a backend-formatted table
                    // via `__formatted_results_override`, return ONLY that string. The raw
                    // `results`/`_posthogUrl` payload would otherwise duplicate the table
                    // and crowd it out — buildToolResultPayload makes the same choice for
                    // the non-exec path, this keeps exec consistent.
                    if (result !== null && typeof result === 'object') {
                        const formattedOverride = (result as Record<string, unknown>)[
                            POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY
                        ]
                        if (typeof formattedOverride === 'string') {
                            return formattedOverride
                        }
                    }
                    return formatResponse(result)
                }

                default:
                    throw new Error(`Unknown command: "${verb}". Supported commands: tools, search, info, schema, call`)
            }
        },
    }
}
