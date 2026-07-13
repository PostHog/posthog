import { stringify as stringifyYaml } from 'yaml'
import { z } from 'zod'

import { markExecPayload, buildToolResultPayload, estimateResponseTokens } from '@/lib/build-tool-result'
import { isPostHogCodeConsumer } from '@/lib/client-detection'
import { ToolInputValidationError } from '@/lib/errors'
import { estimateTokens } from '@/lib/estimate-tokens'
import { formatResponse } from '@/lib/response'

import type { CodeExecutionDiscovery, CodeExecutionRuntime, ExecApplyStatus, ExecRunStatus } from './code-exec/runtime'
import { EXECUTE_SQL_TOOL_NAME } from './posthogAiTools/executeSql'
import { TOKEN_CHAR_LIMIT, listAvailablePaths, resolveSchemaPath, summarizeSchema } from './schema-utils'
import { isRegexPattern, searchToolsRanked, searchToolsRegex } from './tool-search'
import type { ScopeGatedTool } from './toolDefinitions'
import {
    POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY,
    POSTHOG_META_KEY,
    type Context,
    type Tool,
    type ZodObjectAny,
} from './types'

/** Upper bound on a `search` regex pattern — keeps a pathological pattern from
 *  forcing catastrophic backtracking against tool metadata. */
const MAX_SEARCH_PATTERN_LENGTH = 400

/** Ranked (plain-word) search can match loosely on a common token like
 *  "create"; cap the returned names so a vague query can't dump the catalog. */
const MAX_RANKED_SEARCH_RESULTS = 25

export type ExecSchema = ReturnType<typeof makeExecSchema>

export interface ExecInnerCallProperties {
    duration_ms: number
    success: boolean
    output_format: 'json' | 'text' | 'structured'
    error_message?: string
    /** Input rejected by the tool's schema before dispatch — no handler ran. */
    validation_error?: boolean
    /**
     * Estimated input/output tokens for the inner tool call. Carried so single-exec
     * mode attributes token usage to the real tool rather than the `exec` wrapper.
     */
    input_tokens?: number
    output_tokens?: number
    input?: Record<string, unknown>
}

export type ExecInnerCallTracker = (toolName: string, properties: ExecInnerCallProperties) => void

/**
 * Verb-dimension analytics update (spec §4.6 Phase 0): the dispatcher reports
 * the verb as soon as it parses, then run/apply add their structured outcome.
 * Consumers accumulate updates and stamp them onto the `$mcp_tool_call` event
 * as `$mcp_exec_*` properties.
 */
export interface ExecVerbMetaUpdate {
    verb?: string
    runStatus?: ExecRunStatus | ExecApplyStatus
    planMutations?: number
    fastPath?: boolean
    /** True exactly when a legacy verb dispatched under the active code-first surface. */
    deprecatedVerb?: boolean
}

export type ExecVerbTracker = (update: ExecVerbMetaUpdate) => void

export interface ExecToolOptions {
    requireDestructiveConfirmation?: boolean
    /**
     * Client is an inline-exec UI-app host that renders MCP UI apps on the exec
     * response (Claude Code, Cowork). Gets the same UI-app payload treatment as the
     * PostHog Code consumer: structuredContent suppressed toward the model, app data
     * re-homed onto `_meta`. Computed from the client profile at the call site.
     */
    isInlineExecUiHost?: boolean
    /**
     * Static-artifact half of the code-execution surface (spec §4.4), backing
     * `types`, the code-first aliases, and the `sql` gate. Wired whenever the
     * `mcp-code-execution` flag is on — it needs only the generated discovery
     * index, never an executor. Absent (flag off), the verbs read as unknown
     * commands, exactly as before.
     */
    codeExecutionDiscovery?: CodeExecutionDiscovery
    /**
     * Stateful half (`run` / `apply`), wired wherever the flag is on — even
     * without a sandbox executor it serves call-shaped scripts through the
     * fast path (spec §4.2). When absent (discovery-only sessions, e.g. the
     * keyless CLI catalog) both verbs stay unknown commands and the advertised
     * roster carries the discovery-only subset instead of failing midway
     * (spec §4.4).
     */
    codeExecutionRuntime?: CodeExecutionRuntime
    /**
     * Code-first surface (the `mcp-code-first` flag, spec §4.3): legacy verbs go
     * hidden with deprecation footers and `info`/`schema`/`search` alias to the
     * `types` renderings. Inert unless `codeExecutionDiscovery` is wired (the
     * aliases resolve through the discovery index) AND the runtime can execute
     * scripts — the same conjunction that selects the code-first instruction
     * arm, so dispatch behavior and served instructions can never disagree
     * (a footer steering to `run <multi-line script>` on a fast-path-only
     * server would recommend scripts that server rejects).
     */
    codeFirst?: boolean
    /** Verb-dimension analytics sink (spec §4.6 Phase 0); absent means no verb tracking. */
    trackVerb?: ExecVerbTracker
}

/**
 * Closed verb allowlist for `$mcp_exec_verb`. The raw verb is agent-controlled
 * input — normalizing anything else to `unknown` keeps the event property's
 * cardinality bounded.
 */
const EXEC_VERBS = new Set(['tools', 'search', 'info', 'schema', 'call', 'types', 'run', 'apply', 'sql'])

/** The pre-code-exec verbs that become a hidden compatibility layer under code-first (spec §4.3). */
const LEGACY_VERBS = new Set(['tools', 'search', 'info', 'schema', 'call'])

/** Footer for legacy discovery verbs whose modern equivalent is `types` (spec §4.3). */
const TYPES_DEPRECATION_FOOTER =
    'Deprecated command — use `types <query | TypeName | domain.method | domain>` for SDK discovery instead.'

function normalizeExecVerb(verb: string): string {
    return EXEC_VERBS.has(verb) ? verb : 'unknown'
}

/**
 * Normalized `$mcp_exec_verb` for a raw exec command string — callers that
 * build their analytics properties by hand (the CLI) share the dispatcher's
 * allowlist instead of re-deriving it.
 */
export function parseExecVerb(command: string): string {
    return normalizeExecVerb(parseCommand(command).verb)
}

/** Which code-execution halves this session actually has (spec §4.4). */
interface CodeExecutionAvailability {
    /** Discovery half wired — `types` (and `sql`) dispatch. */
    types: boolean
    /** Executor-backed half wired — `run`/`apply` dispatch. */
    runApply: boolean
}

function unknownCommandError(verb: string, opts: CodeExecutionAvailability & { codeFirst: boolean }): Error {
    // The roster mirrors what the dispatcher below actually accepts: a server
    // without an executor advertises `types`/`sql` but never `run`/`apply`.
    // Under code-first the legacy verbs still dispatch but disappear from the
    // advertised roster (spec §4.3 hidden compatibility layer).
    const verbs = opts.codeFirst
        ? ['types', ...(opts.runApply ? ['run', 'apply'] : []), 'sql']
        : [
              'tools',
              'search',
              'info',
              'schema',
              'call',
              ...(opts.types ? ['types'] : []),
              ...(opts.runApply ? ['run', 'apply'] : []),
              ...(opts.types || opts.runApply ? ['sql'] : []),
          ]
    return new Error(`Unknown command: "${verb}". Supported commands: ${verbs.join(', ')}`)
}

/**
 * Kept short on purpose: the description lands inside the serialized
 * `inputSchema`, which claude.ai's registry silently caps at ~16K chars.
 */
export const SCRIPT_PARAM_DESCRIPTION =
    'TypeScript source for `run` — avoids JSON-string escaping inside `command`. When set, `command` must be exactly "run".'

function makeExecSchema(
    commandReference: string
): z.ZodObject<{ command: z.ZodString; script: z.ZodOptional<z.ZodString> }> {
    return z.object({
        command: z.string().describe(commandReference),
        script: z.string().optional().describe(SCRIPT_PARAM_DESCRIPTION),
    })
}

function parseCommand(input: string): { verb: string; rest: string } {
    const trimmed = input.trim()
    // Split on any whitespace, not just a space — a multi-line `run <script>`
    // command may put a newline right after the verb.
    const idx = trimmed.search(/\s/)
    if (idx === -1) {
        return { verb: trimmed, rest: '' }
    }
    return { verb: trimmed.slice(0, idx), rest: trimmed.slice(idx + 1).trim() }
}

function parseCallFlags(input: string): { forceJson: boolean; confirmed: boolean; rest: string } {
    let rest = input.trim()
    let forceJson = false
    let confirmed = false

    while (rest) {
        const parsed = parseCommand(rest)
        if (parsed.verb === '--json') {
            forceJson = true
            rest = parsed.rest
            continue
        }
        if (parsed.verb === '--confirm') {
            confirmed = true
            rest = parsed.rest
            continue
        }
        break
    }

    return { forceJson, confirmed, rest }
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
    const callArgs = parseCallFlags(rest).rest
    if (!callArgs) {
        return
    }
    const innerName = parseCommand(callArgs).verb
    return innerName || undefined
}

// Resolves the inner tool an `exec` call targets: given a request, return the
// inner tool's { name, description } when the agent invoked it via
// `call <tool> ...`, or undefined otherwise. Lives here (alongside
// parseExecCallInnerToolName) so callers and tests share one factory.
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

// Tools that were removed from the MCP server — or flag-gated out of the active
// catalog. When the model attempts to call one that isn't present, surface a
// targeted redirect to the replacement instead of dumping the full tool catalog.
// Keep the redirect text editorial — schemas don't carry "use X instead"
// guidance. A redirect only fires when the tool is absent, so an entry for a
// conditionally-gated tool is inert whenever that tool is registered.
const DEPRECATED_TOOL_REDIRECTS: Record<string, (allTools: Tool<ZodObjectAny>[]) => string> = {
    // Removed in favor of SQL-based schema discovery via `system.information_schema.*`.
    'read-data-warehouse-schema': () =>
        'Tool "read-data-warehouse-schema" was removed in favor of SQL-based schema discovery. Use "execute-sql" against `system.information_schema.*` (`tables`, `columns`, `relationships`, `data_types`) — it scales to large catalogs and supports filtering/search (e.g. `WHERE description ILIKE \'%...%\'`). Consult the `querying-posthog-data` skill for patterns.',
    'entity-search': () =>
        'Tool "entity-search" was removed. Use "execute-sql" to search PostHog data via HogQL. Consult the `querying-posthog-data` skill for system-table patterns (system.insights, system.dashboards, system.cohorts, ...).',
    'event-definitions-list': () =>
        'Tool "event-definitions-list" was removed. Use "read-data-schema" with input { "query": { "kind": "events" } } to list event definitions.',
    'properties-list': () =>
        'Tool "properties-list" was removed. Use "read-data-schema": { "query": { "kind": "event_properties", "event_name": "..." } } for event properties, or { "kind": "entity_properties", "entity": "person" | "session" | "group/<n>" } for entity properties.',
    'property-definitions': () =>
        'Tool "property-definitions" was removed. Use "read-data-schema" with the appropriate kind: "event_properties", "entity_properties", or "action_properties" — see its info schema for required fields.',
    'query-generate-hogql-from-question': () =>
        'Tool "query-generate-hogql-from-question" was removed. Write the HogQL yourself and run it via "execute-sql". Consult the `querying-posthog-data` skill for HogQL patterns.',
    'query-run': (allTools) => {
        const queryTools = allTools
            .filter((t) => t.name.startsWith('query-'))
            .map((t) => `- ${t.name}: ${t.description.split('\n')[0]}`)
            .join('\n')
        return `Tool "query-run" was removed. Pick the typed query tool that matches your intent, or use "execute-sql" for arbitrary HogQL. Available query-* tools:\n${queryTools}`
    },
}

/** Turns a Zod validation failure into a short, field-named message the model
 *  can act on. Without it, a missing/`undefined` path segment slips through to
 *  the HTTP layer and the API returns a generic 404 that reads as "entity does
 *  not exist" — steering recovery toward re-checking the ID rather than the
 *  malformed parameter.
 *
 *  Callers must `safeParse(input, { reportInput: true })` so `issue.input`
 *  distinguishes a missing required field from a present-but-wrong one (the
 *  key is absent without the option, and the check degrades to the wrong-type
 *  message). `reportInput` embeds raw input values in the ZodError, including
 *  its `.message` — keep the error local; never log or capture it. */
export function formatInputValidationError(toolName: string, error: z.ZodError): string {
    const parts = error.issues.map((issue) => {
        const path = issue.path.map(String).join('.')
        if (issue.code === 'invalid_type') {
            if ('input' in issue && issue.input === undefined) {
                return `missing required parameter: ${path}`
            }
            return `parameter "${path}" must be of type ${issue.expected}`
        }
        if (issue.code === 'unrecognized_keys') {
            return `unexpected ${issue.keys.length > 1 ? 'properties' : 'property'}: ${issue.keys.join(', ')}`
        }
        return path ? `parameter "${path}": ${issue.message}` : issue.message
    })
    return `Invalid input for "${toolName}": ${[...new Set(parts)].join('; ')}`
}

/** Whether the tool's input schema declares an `output_format` field. */
function schemaHasOutputFormat(schema: ZodObjectAny): boolean {
    return schema instanceof z.ZodObject && 'output_format' in schema.shape
}

/**
 * Exec mode owns output encoding through the `--json` call flag, so tools must
 * not also advertise their `output_format` input — an agent passing
 * `output_format: "json"` would make the handler skip the server-side formatter
 * only for exec to TOON-encode the raw result anyway. `call` folds the flag back
 * into the field for tools that have it (see the `call` verb), so hiding it here
 * loses no capability.
 */
function stripOutputFormatProperty(jsonSchema: Record<string, unknown>): Record<string, unknown> {
    const properties = jsonSchema.properties as Record<string, unknown> | undefined
    if (!properties || !('output_format' in properties)) {
        return jsonSchema
    }
    const { output_format: _omitted, ...rest } = properties
    return { ...jsonSchema, properties: rest }
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

export interface DispatchInnerToolOptions {
    tool: Tool<ZodObjectAny>
    context: Context
    input: Record<string, unknown>
    forceJson?: boolean
    mcpConsumer: string | undefined
    isInlineExecUiHost: boolean
    trackInnerCall?: ExecInnerCallTracker
    /** Force the text branch even when the tool has a UI app — plan/apply receipts embed the output as text. */
    suppressUiPayload?: boolean
}

/**
 * Shared dispatch pipeline behind the `call` verb, the code-execution fast
 * path, and the `sql` verb: output-format folding, schema validation, handler
 * dispatch with timing, UI-app payload handling, and TOON/JSON serialization.
 * The fast path's contract is that a call-shaped `run` script behaves
 * byte-identically to `call`, so all three verbs must share this body.
 */
export async function dispatchInnerTool(options: DispatchInnerToolOptions): Promise<unknown> {
    const { tool, context, trackInnerCall } = options
    let input = { ...options.input }

    // `output_format` is hidden from exec-mode schemas — `--json` owns output
    // encoding. Honor a stray `output_format: "json"` as `--json` instead of
    // letting the handler skip the formatter only for the result to be
    // TOON-encoded anyway.
    let strayOutputFormat: unknown
    if ('output_format' in input) {
        ;({ output_format: strayOutputFormat, ...input } = input)
    }
    const useJson =
        options.forceJson === true ||
        strayOutputFormat === 'json' ||
        tool._meta?.[POSTHOG_META_KEY]?.outputFormat === 'json'
    // Fold the flag back into the tool's own `output_format` field when it has
    // one: formatter-toggle tools then skip the server-side formatter (clean raw
    // JSON, no `__formatted_results_override` duplication), and tools where the
    // field is a real backend param (dashboard-insights-run) keep full function.
    if (useJson && schemaHasOutputFormat(tool.schema)) {
        input.output_format = 'json'
    }

    // Same validation gate as the non-exec MCP path (`tool-executor.ts`) —
    // otherwise bad input reaches the HTTP layer and builds URLs like
    // `.../actions/undefined/`, a misleading 404 that hides the offending
    // field. Dispatch the parsed output so coerced values and defaults apply.
    const validation = tool.schema.safeParse(input, { reportInput: true })
    if (!validation.success) {
        const message = formatInputValidationError(tool.name, validation.error)
        trackInnerCall?.(tool.name, {
            duration_ms: 0,
            success: false,
            output_format: useJson ? 'json' : 'text',
            error_message: message,
            validation_error: true,
        })
        // Typed so the executor's catch skips exception capture and
        // classifies it as `validation`, not `internal`.
        throw new ToolInputValidationError(message)
    }
    input = validation.data as Record<string, unknown>

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
            input,
        })
        throw err
    }
    const durationMs = Date.now() - startedAt

    // If the inner tool has a UI app attached AND the caller self-identifies as
    // PostHog Code (the UI-apps host), emit a full `CallToolResult` payload
    // carrying `structuredContent` + `_meta.ui.resourceUri`. Clients only see
    // the `exec` tool registered in single-exec mode, so the UI metadata has to
    // ride on the per-call response. Gated on the consumer because other
    // single-exec callers (direct Claude Code, cline, Slack- and posthog_ai-launched
    // runs, etc.) don't render UI apps — they should see plain text.
    const isInlineUiAppHost = isPostHogCodeConsumer(options.mcpConsumer) || options.isInlineExecUiHost === true
    if (tool._meta?.ui?.resourceUri && isInlineUiAppHost && options.suppressUiPayload !== true) {
        const isStringResult = typeof result === 'string'
        const distinctId = isStringResult ? undefined : await context.getDistinctId()
        const payload = markExecPayload(
            buildToolResultPayload({
                handlerResult: result,
                toolMeta: tool._meta,
                toolName: tool.name,
                params: useJson ? { ...input, output_format: 'json' } : input,
                // Inline-exec UI-app hosts (PostHog Code, Claude Code, Cowork)
                // surface `structuredContent` to the model in preference to the
                // text content, which would bury the compact formatted table
                // under the raw JSON. Always re-home the UI app's data onto
                // `_meta` (see APP_DATA_META_KEY) so the model reads the optimized
                // table (or the TOON text when unformatted) and the chart still renders.
                forceUiDataToMeta: true,
                distinctId,
                includeUiResponseMeta: true,
            })
        )
        trackInnerCall?.(tool.name, {
            duration_ms: durationMs,
            success: true,
            output_format: 'structured',
            input_tokens: estimateTokens(input),
            output_tokens: estimateResponseTokens(payload),
            input,
        })
        return payload
    }

    // Serialize once so the token estimate measures the exact text
    // returned to the client, not the raw object.
    let outputText: string
    if (useJson) {
        outputText = JSON.stringify(result)
    } else {
        // Optimized mode: when the handler attached a backend-formatted table
        // via `__formatted_results_override`, return ONLY that string. The raw
        // `results`/`_posthogUrl` payload would otherwise duplicate the table
        // and crowd it out — buildToolResultPayload makes the same choice for
        // the non-exec path, this keeps exec consistent.
        const formattedOverride =
            result !== null && typeof result === 'object'
                ? (result as Record<string, unknown>)[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]
                : undefined
        outputText = typeof formattedOverride === 'string' ? formattedOverride : formatResponse(result)
    }
    trackInnerCall?.(tool.name, {
        duration_ms: durationMs,
        success: true,
        output_format: useJson ? 'json' : 'text',
        input_tokens: estimateTokens(input),
        output_tokens: estimateTokens(outputText),
        input,
    })
    return outputText
}

export function createExecTool(
    allTools: Tool<ZodObjectAny>[],
    context: Context | undefined,
    toolDescription: string,
    commandReference: string,
    mcpConsumer: string | undefined,
    trackInnerCall?: ExecInnerCallTracker,
    scopeGatedTools: ScopeGatedTool[] = [],
    options: ExecToolOptions = {}
): Tool<ExecSchema> {
    const ExecSchema = makeExecSchema(commandReference)

    return {
        name: 'exec',
        title: 'PostHog analytics, dashboards, insights, feature flags & more',
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
            const discovery = options.codeExecutionDiscovery
            const runtime = options.codeExecutionRuntime
            const availability: CodeExecutionAvailability = {
                types: discovery !== undefined,
                runApply: runtime !== undefined,
            }
            // Code-first is inert without discovery (its aliases and footers
            // resolve through the discovery index) and without full script
            // execution: the instructions formatter serves the legacy arm
            // wherever the sandbox is absent, so activating code-first dispatch
            // there would contradict the prompt the agent is reading.
            const codeFirstDiscovery =
                options.codeFirst === true && runtime?.canExecuteScripts === true ? discovery : undefined
            const codeFirst = codeFirstDiscovery !== undefined
            // Report the verb before dispatch so usage errors, unknown commands,
            // and thrown handler errors still carry `$mcp_exec_verb`.
            options.trackVerb?.({
                verb: normalizeExecVerb(verb),
                deprecatedVerb: codeFirst && LEGACY_VERBS.has(verb),
            })

            const script = params.script?.trim()
            if (script && (verb !== 'run' || rest !== '')) {
                throw new Error(
                    'The `script` parameter carries the TypeScript source for `run` — when it is set, `command` must be exactly "run" with no inline source.'
                )
            }

            // One-line deprecation footer on legacy-verb responses under
            // code-first, naming the exact modern equivalent (spec §4.3).
            const withDeprecationFooter = (output: string, footer: string): string =>
                codeFirst ? `${output}\n\n${footer}` : output

            switch (verb) {
                case 'tools': {
                    return withDeprecationFooter(JSON.stringify(allTools.map((t) => t.name)), TYPES_DEPRECATION_FOOTER)
                }

                case 'search': {
                    if (!rest) {
                        throw new Error('Usage: search <words or regex_pattern>')
                    }
                    if (codeFirstDiscovery) {
                        // Alias to the `types` rendering (spec §4.3): the discovery
                        // index is the code-first search surface.
                        return [
                            `Deprecated: \`search\` — use \`types ${rest}\` instead. Showing its results:`,
                            await codeFirstDiscovery.types(rest),
                        ].join('\n')
                    }
                    // Bound the user-supplied pattern length to limit the blast
                    // radius of a pathological (catastrophic-backtracking) regex.
                    if (rest.length > MAX_SEARCH_PATTERN_LENGTH) {
                        throw new Error(
                            `Search pattern too long (${rest.length} chars, max ${MAX_SEARCH_PATTERN_LENGTH}). Use a shorter, more targeted pattern.`
                        )
                    }

                    // Route by pattern shape: a pattern with regex metacharacters
                    // (e.g. `query-`, `feature-flag`) keeps the original regex
                    // predicate; plain words — including multi-word, natural-
                    // language queries — use forgiving token ranking.
                    let matches: string[]
                    let gatedMatches: ScopeGatedTool[]
                    let truncatedFrom = 0
                    if (isRegexPattern(rest)) {
                        try {
                            matches = searchToolsRegex(allTools, rest).map((t) => t.name)
                            gatedMatches = searchToolsRegex(scopeGatedTools, rest)
                        } catch {
                            throw new Error(`Invalid regex pattern: "${rest}"`)
                        }
                    } else {
                        const ranked = searchToolsRanked(allTools, rest)
                        truncatedFrom = ranked.length > MAX_RANKED_SEARCH_RESULTS ? ranked.length : 0
                        matches = ranked.slice(0, MAX_RANKED_SEARCH_RESULTS).map((r) => r.name)
                        // Preserve ranked order for gated matches too, then map
                        // each name back to its ScopeGatedTool (for missingScopes).
                        const gatedByName = new Map(scopeGatedTools.map((t) => [t.name, t]))
                        gatedMatches = searchToolsRanked(scopeGatedTools, rest)
                            .map((r) => gatedByName.get(r.name))
                            .filter((t): t is ScopeGatedTool => t !== undefined)
                    }

                    if (gatedMatches.length > 0) {
                        const requiredScopes = [...new Set(gatedMatches.flatMap((t) => t.missingScopes))].sort()
                        return JSON.stringify({
                            matches,
                            scope_gated_matches: gatedMatches.map((t) => ({
                                name: t.name,
                                missing_scopes: t.missingScopes,
                            })),
                            hint:
                                `These tools also match but are hidden because the API key is missing the ` +
                                `required scope(s): ${requiredScopes.join(', ')}. The user needs to re-authenticate the MCP or connector, if the harness supports OAuth, or add the scopes to the personal API key to use these tools.`,
                        })
                    }
                    if (matches.length === 0) {
                        return JSON.stringify({
                            matches: [],
                            hint: `No tools matched "${rest}". Run "tools" to see all available tool names.`,
                        })
                    }
                    if (truncatedFrom > 0) {
                        return JSON.stringify({
                            matches,
                            truncated: true,
                            hint: `Showing the top ${MAX_RANKED_SEARCH_RESULTS} of ${truncatedFrom} matches, ranked by relevance. Use a more specific query to narrow the results.`,
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
                    if (codeFirstDiscovery) {
                        const methodId = await codeFirstDiscovery.methodIdForTool(infoArgs)
                        if (methodId) {
                            return [
                                `Deprecated: \`info\` — use \`types ${methodId}\` instead. Showing its output:`,
                                await codeFirstDiscovery.types(methodId),
                            ].join('\n')
                        }
                        // No SDK counterpart (e.g. SSE-backed tools) — legacy
                        // rendering below, with the footer still pointing at `types`.
                    }
                    const tool = findTool(allTools, infoArgs)
                    const fullSchema = stripOutputFormatProperty(z.toJSONSchema(tool.schema) as Record<string, unknown>)
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
                        return withDeprecationFooter(fullOutput, TYPES_DEPRECATION_FOOTER)
                    }

                    // Schema too large — return summary with drill-down hints.
                    // Each complex field's `hint` carries the imperative to run
                    // `schema` before populating it, so no separate directive is
                    // needed here.
                    const summary = summarizeSchema(fullSchema as Record<string, unknown>, tool.name)
                    return withDeprecationFooter(serialize(topShape, summary), TYPES_DEPRECATION_FOOTER)
                }

                case 'schema': {
                    if (!rest) {
                        throw new Error('Usage: schema <tool_name> [field_path]')
                    }
                    const { verb: schemaToolName, rest: fieldPath } = parseCommand(rest)
                    if (codeFirstDiscovery) {
                        const methodId = await codeFirstDiscovery.methodIdForTool(schemaToolName)
                        if (methodId) {
                            const pathNote = fieldPath
                                ? ' Drill-down paths are ignored — follow the named types instead.'
                                : ''
                            return [
                                `Deprecated: \`schema\` — use \`types ${methodId}\` instead.${pathNote} Showing its output:`,
                                await codeFirstDiscovery.types(methodId),
                            ].join('\n')
                        }
                    }
                    const schemaTool = findTool(allTools, schemaToolName)
                    const fullJsonSchema = stripOutputFormatProperty(
                        z.toJSONSchema(schemaTool.schema) as Record<string, unknown>
                    )

                    if (!fieldPath) {
                        // The bare `schema <tool>` view is always a summary. Any
                        // field that still needs drilling carries the imperative
                        // in its own `hint`, so the summary stands on its own.
                        return withDeprecationFooter(
                            JSON.stringify(summarizeSchema(fullJsonSchema, schemaToolName)),
                            TYPES_DEPRECATION_FOOTER
                        )
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
                        return withDeprecationFooter(serialized, TYPES_DEPRECATION_FOOTER)
                    }

                    // Field schema too large — return a summary instead. The
                    // summary's complex sub-fields carry the drill-down `hint`,
                    // so the response shape stays the same as the inline case
                    // (`{ field, schema }`) — no separate top-level note.
                    return withDeprecationFooter(
                        JSON.stringify({
                            field: fieldPath,
                            schema: summarizeSchema(resolved as Record<string, unknown>, schemaToolName, fieldPath),
                        }),
                        TYPES_DEPRECATION_FOOTER
                    )
                }

                case 'call': {
                    if (!rest) {
                        throw new Error('Usage: call [--json] [--confirm] <tool_name> <json_input>')
                    }
                    if (!context) {
                        throw new Error('Cannot call PostHog tools without an API context')
                    }
                    const { forceJson, confirmed, rest: callArgs } = parseCallFlags(rest)
                    if (!callArgs) {
                        throw new Error('Usage: call [--json] [--confirm] <tool_name> <json_input>')
                    }
                    const { verb: toolName, rest: jsonBody } = parseCommand(callArgs)
                    const tool = findTool(allTools, toolName)
                    if (options.requireDestructiveConfirmation && tool.annotations.destructiveHint && !confirmed) {
                        throw new Error(
                            `Tool "${tool.name}" is destructive. Re-run with "call --confirm ${tool.name} ..." after verifying the target IDs. Use "info ${tool.name}" to inspect the tool first.`
                        )
                    }
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

                    const result = await dispatchInnerTool({
                        tool,
                        context,
                        input,
                        forceJson,
                        mcpConsumer,
                        isInlineExecUiHost: options.isInlineExecUiHost === true,
                        trackInnerCall,
                    })
                    // UI-app payloads are objects — a footer can't ride on them.
                    if (!codeFirstDiscovery || typeof result !== 'string') {
                        return result
                    }
                    const methodId = await codeFirstDiscovery.methodIdForTool(tool.name)
                    // In-context teaching (spec §4.3): the footer carries the exact
                    // `run` equivalent, with the JSON input as the literal argument.
                    const footer = methodId
                        ? `Deprecated: \`call\` — the code-first equivalent: run import { client } from '@posthog/sdk'; export default await client.${methodId}(${JSON.stringify(input)})`
                        : 'Deprecated: `call` — prefer `run <typescript source>`; this tool has no SDK method yet, so `call` keeps working for it.'
                    return `${result}\n\n${footer}`
                }

                case 'types': {
                    if (!discovery) {
                        throw unknownCommandError(verb, { ...availability, codeFirst })
                    }
                    if (!rest) {
                        throw new Error('Usage: types <query | TypeName... | domain.method | domain>')
                    }
                    return discovery.types(rest)
                }

                case 'run': {
                    if (!runtime) {
                        // No runtime wired (discovery-only session, e.g. the
                        // keyless CLI catalog): run/apply are not in the
                        // advertised roster, so an attempt reads as unknown —
                        // the error's roster is the redirect.
                        throw unknownCommandError(verb, { ...availability, codeFirst })
                    }
                    const source = rest || script || ''
                    if (!source) {
                        throw new Error(
                            'Usage: run <typescript source> — or pass the source via the `script` parameter with command "run"'
                        )
                    }
                    const outcome = await runtime.run(source)
                    options.trackVerb?.({
                        runStatus: outcome.meta.status,
                        fastPath: outcome.meta.fastPath,
                        ...(outcome.meta.planMutations !== undefined
                            ? { planMutations: outcome.meta.planMutations }
                            : {}),
                    })
                    return outcome.output
                }

                case 'apply': {
                    if (!runtime) {
                        throw unknownCommandError(verb, { ...availability, codeFirst })
                    }
                    if (!rest) {
                        throw new Error('Usage: apply <plan-id>')
                    }
                    const outcome = await runtime.apply(rest)
                    options.trackVerb?.({ runStatus: outcome.meta.status })
                    return outcome.output
                }

                case 'sql': {
                    // Available whenever the code-execution surface is on — the verb is
                    // sugar for a fast-pathed `client.query.sql(...)` (spec §4.3) whose
                    // dispatch needs neither half, so an executor-less server keeps it.
                    if (!discovery && !runtime) {
                        throw unknownCommandError(verb, { ...availability, codeFirst })
                    }
                    if (!rest) {
                        throw new Error('Usage: sql <hogql>')
                    }
                    if (!context) {
                        throw new Error('Cannot call PostHog tools without an API context')
                    }
                    const tool = findTool(allTools, EXECUTE_SQL_TOOL_NAME)
                    return dispatchInnerTool({
                        tool,
                        context,
                        input: { query: rest },
                        mcpConsumer,
                        isInlineExecUiHost: options.isInlineExecUiHost === true,
                        trackInnerCall,
                    })
                }

                default:
                    throw unknownCommandError(verb, { ...availability, codeFirst })
            }
        },
    }
}
