import { stringify as stringifyYaml } from 'yaml'
import { z } from 'zod'

import { markExecPayload, buildToolResultPayload, estimateResponseTokens } from '@/lib/build-tool-result'
import { isPostHogCodeConsumer } from '@/lib/client-detection'
import { ExecCommandError, findRecoverableApiError, PostHogApiError, ToolInputValidationError } from '@/lib/errors'
import { estimateTokens } from '@/lib/estimate-tokens'
import { GATEWAY_TOOL_SEPARATOR, isGatewayToolName } from '@/lib/gateway-tools'
import { formatResponse } from '@/lib/response'

import type { ExecHelpCatalog } from './exec-help'
import { TOKEN_CHAR_LIMIT, listAvailablePaths, resolveSchemaPath, summarizeSchema } from './schema-utils'
import { isRegexPattern, searchToolsRanked, searchToolsRegex } from './tool-search'
import type { ScopeGatedTool } from './toolDefinitions'
import {
    POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY,
    POSTHOG_INFORMATIONAL_RESPONSE_KEY,
    POSTHOG_META_KEY,
    type Context,
    type Tool,
    type ZodObjectAny,
} from './types'

/** Upper bound on a `search` regex pattern — keeps a pathological pattern from
 *  forcing catastrophic backtracking against tool metadata. */
const MAX_SEARCH_PATTERN_LENGTH = 400

/** One line telling the agent third-party tools exist and how to find them, for the
 *  `tools` listing. Returns undefined when nothing is connected. */
async function resolveConnectedSummary(
    resolveTools: () => Promise<Tool<ZodObjectAny>[]>,
    posthogToolCount: number
): Promise<string | undefined> {
    const combined = await resolveTools()
    const extra = combined.length - posthogToolCount
    if (extra <= 0) {
        return undefined
    }
    const servers = new Set(
        combined.slice(posthogToolCount).map((tool) => tool.name.split(GATEWAY_TOOL_SEPARATOR)[0] ?? '')
    )
    return `${extra} tool${extra === 1 ? '' : 's'} from ${servers.size} connected MCP server${servers.size === 1 ? '' : 's'} (${[...servers].sort().join(', ')}) are also callable — find them with "search <what you need>".`
}

/** Ranked (plain-word) search can match loosely on a common token like
 *  "create"; cap the returned names so a vague query can't dump the catalog. */
const MAX_RANKED_SEARCH_RESULTS = 25

type ExecSchema = ReturnType<typeof makeExecSchema>

export interface ExecInnerCallProperties {
    duration_ms: number
    success: boolean
    output_format: 'json' | 'text' | 'structured'
    error_message?: string
    /**
     * HTTP status when the failure was a typed PostHog API error — value-free,
     * safe for consumers that must not forward raw error messages.
     */
    error_status?: number
    /** Input rejected by the tool's schema before dispatch — no handler ran. */
    validation_error?: boolean
    /**
     * Estimated input/output tokens for the inner tool call. Carried so single-exec
     * mode attributes token usage to the real tool rather than the `exec` wrapper.
     */
    input_tokens?: number
    output_tokens?: number
    input?: Record<string, unknown>
    /**
     * The payload returned to the client, exactly as serialized. Consumed by the
     * `$ai_span` capture for data-catalog-relevant calls, which needs the tool's
     * result (e.g. which metrics a catalog lookup returned), not just its size.
     */
    output?: unknown
}

export type ExecInnerCallTracker = (toolName: string, properties: ExecInnerCallProperties) => void

/**
 * What the agent asked `exec` to do, for the `$mcp_tool_call` event.
 *
 * `call` is already attributed to the inner tool it dispatched, so the value here is in
 * the other verbs — above all `search`, whose query is the only record of what an agent
 * looked for. A search that matches nothing is otherwise invisible, which leaves the
 * question "which capability do people reach for that we don't have" unanswerable.
 */
export interface ExecCommandMeta {
    /** The verb the agent used: `search`, `info`, `schema`, `tools`, `learn`, `call`. */
    exec_verb: string
    /** The raw search query. Already bounded to MAX_SEARCH_PATTERN_LENGTH by the handler. */
    exec_search_query?: string
    /** How many tools matched, before the response is truncated — 0 is the interesting case. */
    exec_search_match_count?: number
    /** How many of those matches came from a connected third-party server. */
    exec_search_gateway_match_count?: number
}

export type ExecCommandTracker = (meta: ExecCommandMeta) => void

export interface ExecToolOptions {
    requireDestructiveConfirmation?: boolean
    helpCatalog?: ExecHelpCatalog
    /**
     * Client is an inline-exec UI-app host that renders MCP UI apps on the exec
     * response (Claude Code, Cowork). Gets the same UI-app payload treatment as the
     * PostHog Desktop consumer: structuredContent suppressed toward the model, app data
     * re-homed onto `_meta`. Computed from the client profile at the call site.
     */
    isInlineExecUiHost?: boolean
    /**
     * Resolves the caller's third-party MCP tools (see `lib/gateway-tools.ts`). Awaited
     * lazily by the commands that need a tool roster, so a session that never reaches for
     * a connected server pays nothing for having one. Must not throw: a failing gateway
     * degrades to "no third-party tools", never to a broken `exec`.
     */
    gatewayToolsProvider?: () => Promise<Tool<ZodObjectAny>[]>
    /** Reports what the agent asked for, so non-`call` verbs stop being invisible. */
    trackCommand?: ExecCommandTracker
}

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

// Extracts the inner tool's JSON arguments from an exec `call` command, e.g.
// `call skill-get {"skill_name":"x"}` → `{ skill_name: 'x' }`. Sibling of
// parseExecCallInnerToolName, and deliberately mirrors how the `call` handler
// below reads the same command — a body-less call is `{}` there, so it is `{}`
// here. Returns undefined when no inner arguments exist to read: another verb,
// or a body that is not a JSON object. Analytics uses this because in
// single-exec mode the arguments never arrive as tool arguments, so a property
// derived only from those would miss nearly every skill read.
export function parseExecCallInnerArgs(command: string): Record<string, unknown> | undefined {
    const { verb, rest } = parseCommand(command)
    if (verb !== 'call' || !rest) {
        return
    }
    const callArgs = parseCallFlags(rest).rest
    if (!callArgs) {
        return
    }
    const { rest: jsonBody } = parseCommand(callArgs)
    if (!jsonBody) {
        return {}
    }
    try {
        const parsed: unknown = JSON.parse(jsonBody)
        // Arrays and `null` are typeof 'object'; only a plain object holds arguments.
        return parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed)
            ? (parsed as Record<string, unknown>)
            : undefined
    } catch {
        return
    }
}

/** Verbs the dispatcher grammar accepts. A verb outside this set is what the
 *  `unknown_command` rejection fires on, and is recorded as unrecognized. */
const KNOWN_EXEC_VERBS = new Set(['learn', 'tools', 'search', 'info', 'schema', 'call'])

/** Verbs whose first positional argument names a tool. */
const TOOL_TARGETING_VERBS = new Set(['info', 'schema', 'call'])

/**
 * Recorded in place of a verb or tool name the server doesn't recognize. A token
 * the grammar rejected is caller text, and bounding its charset does not make it
 * value-free — an identifier-shaped secret survives sanitization intact. This file
 * already withholds `ExecCommandError`'s message from analytics for exactly this
 * reason (it echoes the caller's tool name); the rejection reason on the event says
 * which of the two failed, so the sentinel loses only the misspelling itself.
 */
const UNRECOGNIZED_EXEC_TOKEN = 'unrecognized'

export interface ExecCommandShape {
    /** The dispatcher verb, or `unrecognized` when it isn't one we accept. */
    verb?: string
    /** The tool `info`/`schema`/`call` targeted, or `unrecognized` when the name
     *  resolves to nothing in our catalog. */
    targetTool?: string
}

/**
 * Describes an exec command for analytics: which verb ran, and which tool it
 * targeted. Both are value-free by construction — a verb from the closed grammar
 * and a tool name from our own catalog, never the caller's token (see
 * `describeValidationError` for the same constraint applied to schema rejections).
 *
 * Without this, every non-`call` verb lands in one undifferentiated `exec`
 * bucket: schema discovery is indistinguishable from tool search, and an
 * `unknown_command` rejection records no verb to diagnose. `targetTool` is what
 * links an `info <tool>` to the `call <tool>` that follows it.
 *
 * `isKnownToolName` decides whether a target resolves against the catalog this
 * connection can see; anything it rejects is recorded as
 * `UNRECOGNIZED_EXEC_TOKEN`.
 */
export function describeExecCommand(command: string, isKnownToolName: (name: string) => boolean): ExecCommandShape {
    const { verb: rawVerb, rest } = parseCommand(command)
    if (!rawVerb) {
        return {}
    }
    const verb = KNOWN_EXEC_VERBS.has(rawVerb) ? rawVerb : UNRECOGNIZED_EXEC_TOKEN
    if (!TOOL_TARGETING_VERBS.has(rawVerb) || !rest) {
        return { verb }
    }
    // The target must be parsed exactly as the dispatcher looks it up, or a
    // rejected command gets attributed to a valid tool. `call` strips its flags
    // then takes the first token; `schema` takes the first token. `info` is the
    // exception: it hands the entire remaining argument to `findTool` as an exact
    // name (after an optional `--json`), so `info execute-sql extra` looks up
    // "execute-sql extra", resolves to nothing, and records `unrecognized` — not
    // the `execute-sql` its first token would suggest.
    let target: string
    if (rawVerb === 'call') {
        target = parseCommand(parseCallFlags(rest).rest).verb
    } else if (rawVerb === 'info') {
        target = rest.replace(/^--json(\s+|$)/, '').trim()
    } else {
        target = parseCommand(rest).verb
    }
    if (!target) {
        return { verb }
    }
    return { verb, targetTool: isRecordableToolName(target, isKnownToolName) ? target : UNRECOGNIZED_EXEC_TOKEN }
}

/** Tool names we own, and can therefore record: the ones this connection can see,
 *  plus the removed ones kept only to redirect a call. A name outside both is the
 *  caller's own text. */
function isRecordableToolName(name: string, isKnownToolName: (name: string) => boolean): boolean {
    return isKnownToolName(name) || Object.prototype.hasOwnProperty.call(DEPRECATED_TOOL_REDIRECTS, name)
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
        'Tool "read-data-warehouse-schema" was removed in favor of SQL-based schema discovery. Use "execute-sql" against `system.information_schema.*` (`tables`, `columns`, `relationships`, `data_types`) — it scales to large catalogs and supports filtering/search (e.g. `WHERE description ILIKE \'%...%\'`). Consult the `querying-posthog-data` skill (a built-in local skill, when installed) for patterns.',
    'entity-search': (allTools) => {
        const base =
            'Tool "entity-search" was removed. Use "execute-sql" to search PostHog data via HogQL. Consult the `querying-posthog-data` skill (a built-in local skill, when installed) for system-table patterns (system.insights, system.dashboards, system.cohorts, ...).'
        const hasCatalog = allTools.some((t) => t.name === 'data-catalog-metric-run')
        return hasCatalog
            ? `${base} For governed business metrics, search \`system.information_schema.metrics\` instead of \`system.insights\`.`
            : base
    },
    'event-definitions-list': () =>
        'Tool "event-definitions-list" was removed. Use "read-data-schema" with input { "query": { "kind": "events" } } to list event definitions.',
    'properties-list': () =>
        'Tool "properties-list" was removed. Use "read-data-schema": { "query": { "kind": "event_properties", "event_name": "..." } } for event properties, or { "kind": "entity_properties", "entity": "person" | "session" | "group/<n>" } for entity properties.',
    'property-definitions': () =>
        'Tool "property-definitions" was removed. Use "read-data-schema" with the appropriate kind: "event_properties", "entity_properties", or "action_properties" — see its info schema for required fields.',
    'query-generate-hogql-from-question': () =>
        'Tool "query-generate-hogql-from-question" was removed. Write the HogQL yourself and run it via "execute-sql". Consult the `querying-posthog-data` skill (a built-in local skill, when installed) for HogQL patterns.',
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
        // A too-long string names the limit and the input's actual length so the
        // agent knows how much to trim (zod's default names only the limit).
        // Surfaces the LENGTH only, never the value: the message is returned to
        // the caller and recorded as the analytics error_message. `issue.input`
        // is only present under `reportInput: true`; without it, or for
        // non-string origins, fall through to zod's limit-naming default.
        if (issue.code === 'too_big' && issue.origin === 'string' && typeof issue.input === 'string') {
            return `parameter "${path}" is too long: ${issue.input.length} characters (max ${issue.maximum})`
        }
        return path ? `parameter "${path}": ${issue.message}` : issue.message
    })
    return `Invalid input for "${toolName}": ${[...new Set(parts)].join('; ')}`
}

/** Caps on what we record so a single failure can't blow up analytics cardinality. */
const MAX_VALIDATION_DESCRIPTORS = 20
const MAX_KEY_LENGTH = 64

/**
 * Issue codes where the type of the rejected value is the diagnostic signal: a
 * parameter that is absent and one that is present under the right name but the
 * wrong shape are different bugs with different fixes, and both otherwise read as
 * a bare `invalid_type`.
 */
const TYPE_REVEALING_CODES = new Set(['invalid_type', 'invalid_union'])

/**
 * Recorded in place of a path segment the schema never declared. An open record
 * (`generate-app-url`'s `params: z.record(z.string(), z.string())`) puts the
 * caller's own key in the issue path, so recording the path verbatim would carry
 * caller text into analytics. Which field held the bad value is preserved; only
 * the key inside it is masked.
 */
const UNDECLARED_PATH_SEGMENT = '*'

/** Defensive bound on the JSON Schema walk behind `declaredPropertyNames`. */
const MAX_SCHEMA_WALK_DEPTH = 20

/**
 * Joins an issue path into a descriptor, collapsing array indices to `N` and
 * masking any segment `declaredNames` doesn't cover.
 *
 * `series.0.event` and `series.1.event` describe one defect. Without the collapse
 * a malformed 50-element array yields 50 distinct descriptors that fill
 * `MAX_VALIDATION_DESCRIPTORS` with restatements of itself — and because the cap
 * truncates in schema-traversal order, it evicts genuinely different fields that
 * failed later. The dedupe is what keeps the cap meaningful.
 *
 * `declaredNames` is omitted only where every segment is ours by construction
 * (`describeApiValidationError`, whose `attr` is a serializer field name).
 */
function normalizeDescriptorPath(segments: readonly PropertyKey[], declaredNames?: ReadonlySet<string>): string {
    if (!segments.length) {
        return '(root)'
    }
    return segments
        .map((segment) => {
            if (typeof segment === 'number' || /^\d+$/.test(String(segment))) {
                return 'N'
            }
            const name = String(segment)
            if (declaredNames && !declaredNames.has(name)) {
                return UNDECLARED_PATH_SEGMENT
            }
            return name
        })
        .join('.')
        .slice(0, MAX_KEY_LENGTH)
}

const declaredPropertyNamesCache = new WeakMap<object, ReadonlySet<string>>()

/**
 * Every property name a tool's schema declares, at any depth. A path segment
 * outside this set came from an open record or a catchall, which means the caller
 * chose it.
 *
 * Read off the JSON Schema exec already generates for `info`, so this depends on
 * no Zod internals. A schema that can't be converted yields an empty set: more
 * masking than strictly needed, never less.
 */
function declaredPropertyNames(schema: z.ZodType): ReadonlySet<string> {
    const cached = declaredPropertyNamesCache.get(schema)
    if (cached) {
        return cached
    }
    const names = new Set<string>()
    try {
        collectDeclaredPropertyNames(z.toJSONSchema(schema, { io: 'input' }), names)
    } catch {
        // Telemetry must never break a tool call; an empty set only costs detail.
    }
    declaredPropertyNamesCache.set(schema, names)
    return names
}

function collectDeclaredPropertyNames(node: unknown, into: Set<string>, depth = 0): void {
    if (depth > MAX_SCHEMA_WALK_DEPTH || typeof node !== 'object' || node === null) {
        return
    }
    if (Array.isArray(node)) {
        for (const child of node) {
            collectDeclaredPropertyNames(child, into, depth + 1)
        }
        return
    }
    for (const [key, value] of Object.entries(node)) {
        // Only a `properties` map is keyed by field names. `patternProperties`,
        // `additionalProperties` and `$defs` are keyed by pattern or definition name,
        // so descend into their values without recording the keys.
        if (key === 'properties' && typeof value === 'object' && value !== null && !Array.isArray(value)) {
            for (const [name, child] of Object.entries(value)) {
                into.add(name)
                collectDeclaredPropertyNames(child, into, depth + 1)
            }
            continue
        }
        collectDeclaredPropertyNames(value, into, depth + 1)
    }
}

/** The JSON-shaped type of a rejected value — never the value, never its length. */
function describeReceivedType(value: unknown): string {
    if (value === null) {
        return 'null'
    }
    if (Array.isArray(value)) {
        return 'array'
    }
    return typeof value
}

/**
 * Builds a descriptor in the same `path:code[:received]` shape
 * `describeValidationError` emits, for a rejection that came from the PostHog API
 * rather than the local schema — so both kinds of validation failure answer one
 * query instead of requiring `$mcp_error_message` to be string-parsed.
 *
 * `attr` is one of our own serializer field names and `code` a DRF code; neither
 * carries caller input, unlike the API's free-text `detail`.
 */
export function describeApiValidationError(attr: string | undefined, code: string | undefined): string[] {
    const path = normalizeDescriptorPath((attr ?? '').split('.').filter(Boolean))
    return [`${path}:${code ?? 'unknown'}`]
}

/**
 * Derives a value-free descriptor of a validation failure for telemetry, so a
 * contract regression (agents sending a field name the schema doesn't accept) is
 * diagnosable from the `$mcp_tool_call` event alone — without ever recording the
 * request payload.
 *
 * `fields` are the offending field path + issue code, plus the received type where
 * that distinguishes the bug (e.g. `id:invalid_type:undefined` for an omitted
 * parameter vs `query:invalid_union:string` for an envelope the agent flattened).
 * `inputKeys` — the top-level keys the caller actually sent — is what surfaces an
 * unaccepted alias (e.g. `organizationId` where the schema wants `orgId`).
 *
 * Records only structural information: field names, issue codes, and the TYPE of a
 * rejected value. It never records input VALUES — the ZodError embeds those in
 * `issue.input` and in `.message` (see `formatInputValidationError`), so this reads
 * `typeof issue.input` and never the value behind it. `schema` is what keeps that
 * true of the field paths as well: a key the schema never declared belongs to the
 * caller, so it is masked rather than recorded (see `normalizeDescriptorPath`).
 */
export function describeValidationError(
    error: z.ZodError,
    input: Record<string, unknown>,
    schema: z.ZodType
): { fields: string[]; inputKeys: string[] } {
    const declaredNames = declaredPropertyNames(schema)
    const fields = [
        ...new Set(
            error.issues.map((issue) => {
                const descriptor = `${normalizeDescriptorPath(issue.path, declaredNames)}:${issue.code}`
                // `input` is only present under `safeParse(..., { reportInput: true })`;
                // without it there is no type to report, and an absent value and an
                // unreported one must not both read as `undefined`.
                if (!TYPE_REVEALING_CODES.has(issue.code) || !('input' in issue)) {
                    return descriptor
                }
                return `${descriptor}:${describeReceivedType(issue.input)}`
            })
        ),
    ].slice(0, MAX_VALIDATION_DESCRIPTORS)
    const inputKeys = Object.keys(input)
        .sort()
        .slice(0, MAX_VALIDATION_DESCRIPTORS)
        .map((key) => key.slice(0, MAX_KEY_LENGTH))
    return { fields, inputKeys }
}

/** Whether the tool's input schema declares an `output_format` field. Unwraps
 *  `z.preprocess(...)` pipes (e.g. the id-alias normalization on insight-query)
 *  to reach the underlying object schema. */
function schemaHasOutputFormat(schema: ZodObjectAny): boolean {
    let current: z.ZodType = schema
    while (current instanceof z.ZodPipe) {
        current = current.out as z.ZodType
    }
    return current instanceof z.ZodObject && 'output_format' in current.shape
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

function findTool(tools: Tool<ZodObjectAny>[], scopeGatedTools: ScopeGatedTool[], name: string): Tool<ZodObjectAny> {
    const tool = tools.find((t) => t.name === name)
    if (!tool) {
        const redirect = DEPRECATED_TOOL_REDIRECTS[name]
        if (redirect) {
            throw new ExecCommandError(redirect(tools), 'deprecated_tool')
        }
        const scopeGatedTool = scopeGatedTools.find((candidate) => candidate.name === name)
        if (scopeGatedTool) {
            throw new ExecCommandError(
                `Tool "${name}" exists, but this MCP connection is missing the required scope(s): ${scopeGatedTool.missingScopes.join(', ')}. Reconnect or reauthorize the PostHog MCP connection and approve these scopes. Logging in to PostHog in a browser does not update MCP permissions.`,
                'missing_scope'
            )
        }
        throw new ExecCommandError(
            `Unknown tool: "${name}". Run "search ${name}" to find the current tool name before claiming the capability is unavailable.`,
            'unknown_tool'
        )
    }
    return tool
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
            // Reported up front so a command that throws (unknown tool, bad regex) still
            // records what was attempted — those are the failures worth counting.
            options.trackCommand?.({ exec_verb: verb })

            let gatewayTools: Tool<ZodObjectAny>[] | undefined
            /** PostHog's tools plus any third-party tools the caller has connected.
             *  Resolved at most once per command, and only for commands that need a
             *  roster — `learn` never touches the gateway. */
            const resolveTools = async (): Promise<Tool<ZodObjectAny>[]> => {
                if (!options.gatewayToolsProvider) {
                    return allTools
                }
                if (gatewayTools === undefined) {
                    gatewayTools = await options.gatewayToolsProvider()
                }
                return gatewayTools.length > 0 ? [...allTools, ...gatewayTools] : allTools
            }

            switch (verb) {
                case 'learn': {
                    const helpCatalog = options.helpCatalog
                    if (!helpCatalog) {
                        // `learn` is only advertised when a catalog exists, so without one
                        // it's an unsupported verb rather than a misuse of a real command.
                        throw new ExecCommandError(
                            'The learning catalog is not available for this client.',
                            'unknown_command'
                        )
                    }
                    if (!rest) {
                        return JSON.stringify(helpCatalog.list())
                    }
                    const topicIds = [...new Set(rest.split(/\s+/))]
                    const entries = topicIds.map((topicId) => helpCatalog.get(topicId))
                    const unknownTopicIds = topicIds.filter((_, index) => entries[index] === undefined)
                    if (unknownTopicIds.length > 0) {
                        const available = helpCatalog
                            .list()
                            .map((item) => item.id)
                            .join(', ')
                        const unknownTopics = unknownTopicIds.map((topicId) => `"${topicId}"`).join(', ')
                        throw new ExecCommandError(
                            `Unknown learning topic${unknownTopicIds.length === 1 ? '' : 's'}: ${unknownTopics}. Available: ${available}`,
                            'unknown_learn_topic'
                        )
                    }
                    const resolvedEntries = entries.filter((entry) => entry !== undefined)
                    if (resolvedEntries.length === 1) {
                        return resolvedEntries[0]!.content
                    }
                    return resolvedEntries.map((entry) => `## ${entry.title}\n\n${entry.content}`).join('\n\n')
                }

                case 'tools': {
                    const names = allTools.map((t) => t.name)
                    const connected = await resolveConnectedSummary(resolveTools, allTools.length)
                    if (!connected) {
                        return JSON.stringify(names)
                    }
                    // Summarize rather than list: a user with several connected servers can
                    // have hundreds of third-party tools, and dumping them all here would
                    // cost more context than `search` ever does.
                    return JSON.stringify({ tools: names, connected_servers: connected })
                }

                case 'search': {
                    if (!rest) {
                        throw new ExecCommandError('Usage: search <words or regex_pattern>', 'usage')
                    }
                    // Bound the user-supplied pattern length to limit the blast
                    // radius of a pathological (catastrophic-backtracking) regex.
                    if (rest.length > MAX_SEARCH_PATTERN_LENGTH) {
                        throw new ExecCommandError(
                            `Search pattern too long (${rest.length} chars, max ${MAX_SEARCH_PATTERN_LENGTH}). Use a shorter, more targeted pattern.`,
                            'usage'
                        )
                    }

                    // Route by pattern shape: a pattern with regex metacharacters
                    // (e.g. `query-`, `feature-flag`) keeps the original regex
                    // predicate; plain words — including multi-word, natural-
                    // language queries — use forgiving token ranking.
                    const searchableTools = await resolveTools()
                    // `matches` is the page the agent sees; `matchedNames` is every match,
                    // which is what the counts report — a truncated page would make a broad
                    // query look as narrow as a precise one.
                    let matchedNames: string[]
                    let matches: string[]
                    let gatedMatches: ScopeGatedTool[]
                    let truncatedFrom = 0
                    if (isRegexPattern(rest)) {
                        try {
                            matchedNames = searchToolsRegex(searchableTools, rest).map((t) => t.name)
                            matches = matchedNames
                            gatedMatches = searchToolsRegex(scopeGatedTools, rest)
                        } catch {
                            throw new ExecCommandError(`Invalid regex pattern: "${rest}"`, 'invalid_regex')
                        }
                    } else {
                        const ranked = searchToolsRanked(searchableTools, rest)
                        truncatedFrom = ranked.length > MAX_RANKED_SEARCH_RESULTS ? ranked.length : 0
                        matchedNames = ranked.map((r) => r.name)
                        matches = matchedNames.slice(0, MAX_RANKED_SEARCH_RESULTS)
                        // Preserve ranked order for gated matches too, then map
                        // each name back to its ScopeGatedTool (for missingScopes).
                        const gatedByName = new Map(scopeGatedTools.map((t) => [t.name, t]))
                        gatedMatches = searchToolsRanked(scopeGatedTools, rest)
                            .map((r) => gatedByName.get(r.name))
                            .filter((t): t is ScopeGatedTool => t !== undefined)
                    }

                    options.trackCommand?.({
                        exec_verb: verb,
                        exec_search_query: rest,
                        exec_search_match_count: matchedNames.length,
                        exec_search_gateway_match_count: matchedNames.filter(isGatewayToolName).length,
                    })

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
                        throw new ExecCommandError('Usage: info [--json] <tool_name>', 'usage')
                    }
                    const forceJson = rest.startsWith('--json ') || rest === '--json'
                    const infoArgs = forceJson ? rest.slice('--json'.length).trim() : rest
                    if (!infoArgs) {
                        throw new ExecCommandError('Usage: info [--json] <tool_name>', 'usage')
                    }
                    const tool = findTool(await resolveTools(), scopeGatedTools, infoArgs)
                    // `io: 'input'` mirrors the advertised `tools/list` schema and the executor's
                    // validation: fields with a Zod `.default()` (e.g. a query `kind` discriminator)
                    // are optional and auto-filled. The default `io: 'output'` would list them as
                    // required, misrepresenting them as mandatory input the caller must supply.
                    const fullSchema =
                        tool.rawInputSchema ??
                        stripOutputFormatProperty(
                            z.toJSONSchema(tool.schema, { io: 'input' }) as Record<string, unknown>
                        )
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
                    // Each complex field's `hint` carries the imperative to run
                    // `schema` before populating it, so no separate directive is
                    // needed here.
                    const summary = summarizeSchema(fullSchema as Record<string, unknown>, tool.name)
                    return serialize(topShape, summary)
                }

                case 'schema': {
                    if (!rest) {
                        throw new ExecCommandError('Usage: schema <tool_name> [field_path]', 'usage')
                    }
                    const { verb: schemaToolName, rest: fieldPath } = parseCommand(rest)
                    const schemaTool = findTool(await resolveTools(), scopeGatedTools, schemaToolName)
                    // See the `info` command: `io: 'input'` keeps this in sync with the advertised
                    // schema and validation, so `.default()` fields aren't shown as required.
                    const fullJsonSchema =
                        schemaTool.rawInputSchema ??
                        stripOutputFormatProperty(
                            z.toJSONSchema(schemaTool.schema, { io: 'input' }) as Record<string, unknown>
                        )

                    if (!fieldPath) {
                        // The bare `schema <tool>` view is always a summary. Any
                        // field that still needs drilling carries the imperative
                        // in its own `hint`, so the summary stands on its own.
                        return JSON.stringify(summarizeSchema(fullJsonSchema, schemaToolName))
                    }

                    const resolved = resolveSchemaPath(fullJsonSchema, fieldPath)
                    if (!resolved) {
                        const available = listAvailablePaths(fullJsonSchema)
                        throw new ExecCommandError(
                            `Unknown path "${fieldPath}". Available: ${available.join(', ')}`,
                            'usage'
                        )
                    }

                    const serialized = JSON.stringify({
                        field: fieldPath,
                        schema: resolved,
                    })
                    if (serialized.length <= TOKEN_CHAR_LIMIT) {
                        return serialized
                    }

                    // Field schema too large — return a summary instead. The
                    // summary's complex sub-fields carry the drill-down `hint`,
                    // so the response shape stays the same as the inline case
                    // (`{ field, schema }`) — no separate top-level note.
                    return JSON.stringify({
                        field: fieldPath,
                        schema: summarizeSchema(resolved as Record<string, unknown>, schemaToolName, fieldPath),
                    })
                }

                case 'call': {
                    if (!rest) {
                        throw new ExecCommandError('Usage: call [--json] [--confirm] <tool_name> <json_input>', 'usage')
                    }
                    if (!context) {
                        // Deliberately untyped: a wiring fault, not an agent mistake, so it
                        // belongs in the `internal` bucket its siblings are kept out of.
                        throw new Error('Cannot call PostHog tools without an API context')
                    }
                    const { forceJson, confirmed, rest: callArgs } = parseCallFlags(rest)
                    if (!callArgs) {
                        throw new ExecCommandError('Usage: call [--json] [--confirm] <tool_name> <json_input>', 'usage')
                    }
                    const { verb: toolName, rest: jsonBody } = parseCommand(callArgs)
                    const tool = findTool(await resolveTools(), scopeGatedTools, toolName)
                    if (options.requireDestructiveConfirmation && tool.annotations.destructiveHint && !confirmed) {
                        throw new ExecCommandError(
                            `Tool "${tool.name}" is destructive. Re-run with "call --confirm ${tool.name} ..." after verifying the target IDs. Use "info ${tool.name}" to inspect the tool first.`,
                            'needs_confirmation'
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
                            throw new ExecCommandError(`Invalid JSON input: ${detail}`, 'invalid_json')
                        }
                    }

                    // `output_format` is hidden from exec-mode schemas — `--json` owns output
                    // encoding. Honor a stray `output_format: "json"` as `--json` instead of
                    // letting the handler skip the formatter only for the result to be
                    // TOON-encoded anyway.
                    let strayOutputFormat: unknown
                    if ('output_format' in input) {
                        ;({ output_format: strayOutputFormat, ...input } = input)
                    }
                    const useJson =
                        forceJson ||
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
                        // classifies it as `validation`, not `internal`. The value-free
                        // descriptor rides along so the errored `$mcp_tool_call` records
                        // which field/alias was rejected — without the payload.
                        throw new ToolInputValidationError(
                            message,
                            describeValidationError(validation.error, input, tool.schema)
                        )
                    }
                    input = validation.data as Record<string, unknown>

                    const startedAt = Date.now()
                    let result: unknown
                    try {
                        result = await tool.handler(context, input)
                    } catch (err) {
                        // PostHogValidationError is the API's 400 validation_error body.
                        const apiError = findRecoverableApiError(err)
                        trackInnerCall?.(tool.name, {
                            duration_ms: Date.now() - startedAt,
                            success: false,
                            output_format: useJson ? 'json' : 'text',
                            error_message: err instanceof Error ? err.message : String(err),
                            ...(apiError
                                ? { error_status: apiError instanceof PostHogApiError ? apiError.status : 400 }
                                : {}),
                            input,
                        })
                        throw err
                    }
                    const durationMs = Date.now() - startedAt
                    const formattedOverride =
                        result !== null && typeof result === 'object'
                            ? (result as Record<string, unknown>)[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]
                            : undefined
                    const isInformationalResponse =
                        result !== null &&
                        typeof result === 'object' &&
                        (result as Record<string, unknown>)[POSTHOG_INFORMATIONAL_RESPONSE_KEY] === true

                    if (useJson && isInformationalResponse && typeof formattedOverride === 'string') {
                        const outputText = JSON.stringify({ content: formattedOverride })
                        trackInnerCall?.(tool.name, {
                            duration_ms: durationMs,
                            success: true,
                            output_format: 'json',
                            input_tokens: estimateTokens(input),
                            output_tokens: estimateTokens(outputText),
                            input,
                            output: outputText,
                        })
                        return outputText
                    }

                    // If the inner tool has a UI app attached AND the caller self-identifies as
                    // PostHog Desktop (the UI-apps host), emit a full `CallToolResult` payload
                    // carrying `structuredContent` + `_meta.ui.resourceUri`. Clients only see
                    // the `exec` tool registered in single-exec mode, so the UI metadata has to
                    // ride on the per-call response. Gated on the consumer because other
                    // single-exec callers (direct Claude Code, cline, Slack- and posthog_ai-launched
                    // runs, etc.) don't render UI apps — they should see plain text.
                    const isInlineUiAppHost = isPostHogCodeConsumer(mcpConsumer) || options.isInlineExecUiHost === true
                    if (tool._meta?.ui?.resourceUri && isInlineUiAppHost) {
                        const isStringResult = typeof result === 'string'
                        const distinctId = isStringResult ? undefined : await context.getDistinctId()
                        const payload = markExecPayload(
                            buildToolResultPayload({
                                handlerResult: result,
                                toolMeta: tool._meta,
                                toolName: tool.name,
                                params: useJson ? { ...input, output_format: 'json' } : input,
                                // Inline-exec UI-app hosts (PostHog Desktop, Claude Code, Cowork)
                                // surface `structuredContent` to the model in preference to the
                                // text content, which would bury a compact formatted table under
                                // the raw JSON. When such a table exists, re-home the UI app's data
                                // onto `_meta` (see APP_DATA_META_KEY) so the model reads the compact
                                // table and the chart still renders. When there is no formatted table,
                                // the payload stays in the standard `structuredContent` field — which
                                // both the model and the app read — and the text channel carries a
                                // pointer rather than a second copy of the same rows.
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
                            output: payload,
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
                        outputText = typeof formattedOverride === 'string' ? formattedOverride : formatResponse(result)
                    }
                    trackInnerCall?.(tool.name, {
                        duration_ms: durationMs,
                        success: true,
                        output_format: useJson ? 'json' : 'text',
                        input_tokens: estimateTokens(input),
                        output_tokens: estimateTokens(outputText),
                        input,
                        output: outputText,
                    })
                    return outputText
                }

                default:
                    throw new ExecCommandError(
                        `Unknown command: "${verb}". Supported commands: ${options.helpCatalog ? 'learn, ' : ''}tools, search, info, schema, call`,
                        'unknown_command'
                    )
            }
        },
    }
}
