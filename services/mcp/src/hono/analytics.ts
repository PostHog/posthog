import { randomUUID } from 'node:crypto'

import type { MCPAnalyticsIntentSource } from '@posthog/mcp-analytics'

import type { McpAuthFailure } from '@/lib/auth-errors'
import { classifyAuthMethod } from '@/lib/auth-method'
import { MCP_ANALYTICS_SOURCE, MCP_SERVER_NAME, MCP_SERVER_VERSION } from '@/lib/constants'
import { resolveEventSource } from '@/lib/event-source'
import { gatewayServerSlug, isGatewayToolName, THIRD_PARTY_TOOL_CATEGORY } from '@/lib/gateway-tools'
import { getPostHogClient } from '@/lib/posthog'
import {
    buildMCPAnalyticsGroups,
    buildMCPContextProperties,
    MCP_ANALYTICS_VERSION,
    type MCPAnalyticsContext,
} from '@/lib/posthog/analytics'
import type { RequestProperties } from '@/lib/request-properties'
import { EXECUTE_SQL_TOOL_NAME } from '@/tools/posthogAiTools/executeSql'
import { MAX_CAPTURED_DESCRIPTION_LENGTH, getToolCategory, getToolDescription } from '@/tools/toolDefinitions'

import { buildMCPSessionAnalyticsProperties, getEffectiveMCPClientIdentity } from './mcp-context'
import type { ResolvedState } from './request-state-resolver'

function buildBaseProperties(
    state: ResolvedState,
    analyticsContext: MCPAnalyticsContext | undefined
): {
    properties: Record<string, unknown>
    groups: Record<string, string>
} {
    const groups = analyticsContext ? buildMCPAnalyticsGroups(analyticsContext) : {}
    const requestContext = state.requestContext
    // Live-first per-field: `clientInfo` only arrives on `initialize`, so a mid-session
    // `tools/call` has no live client identity of its own. Falls back to the
    // session-pinned value per field (not swapping in the whole session object) so a
    // live value from a concurrent request on the same server always wins. See
    // `getEffectiveMCPClientIdentity` for why this must differ from
    // `getEffectiveMCPClientContext`.
    const clientIdentity = getEffectiveMCPClientIdentity(requestContext, state.sessionContext)

    const properties: Record<string, unknown> = {
        $ai_product: 'mcp',
        // The same property `posthog/event_usage.py` stamps on product events, so an MCP call
        // and the API work it causes land in one breakdown. Distinct from `$mcp_source`, which
        // names the emitting SDK rather than the surface.
        source: resolveEventSource({
            mcpConsumer: clientIdentity.mcpConsumer,
            clientUserAgent: requestContext.clientUserAgent,
            apiKeyScopes: state.apiKeyScopes,
            oauthClientId: state.oauthClientId,
        }),
        $mcp_source: MCP_ANALYTICS_SOURCE,
        $mcp_server_name: MCP_SERVER_NAME,
        $mcp_server_version: MCP_SERVER_VERSION,
        $mcp_version: MCP_ANALYTICS_VERSION,
        $mcp_client_name: clientIdentity.mcpClientName,
        $mcp_client_version: clientIdentity.mcpClientVersion,
        $mcp_client_user_agent: requestContext.clientUserAgent,
        $mcp_protocol_version: clientIdentity.mcpProtocolVersion,
        $mcp_transport: requestContext.transport,
        $mcp_session_id: requestContext.mcpSessionId,
        $mcp_conversation_id: requestContext.mcpConversationId,
        $mcp_consumer: clientIdentity.mcpConsumer,
        $mcp_mode: requestContext.mode,
        $mcp_region: requestContext.region,
        $mcp_auth_method: requestContext.authMethod,
        ...(analyticsContext
            ? {
                  $mcp_organization_id: analyticsContext.organizationId,
                  $mcp_project_id: analyticsContext.projectId,
                  $mcp_project_uuid: analyticsContext.projectUuid,
                  $mcp_project_name: analyticsContext.projectName,
                  ...buildMCPContextProperties(analyticsContext),
              }
            : {}),
        mcp_runtime: 'hono',
        mcp_vendor_client: clientIdentity.mcpVendorClient,
        ...buildMCPSessionAnalyticsProperties(state.sessionContext),
    }
    return { properties, groups }
}

export async function trackInitEvent(state: ResolvedState): Promise<void> {
    try {
        const analyticsContext = await state.reqCtx.safelyGetAnalyticsContext(state.context)
        const requestContext = state.requestContext
        const initDurationMs = requestContext.requestStartTime
            ? Date.now() - requestContext.requestStartTime
            : undefined
        const sessionUuid = await state.reqCtx.getEffectiveSessionUuid(requestContext)

        const { properties, groups } = buildBaseProperties(state, analyticsContext)

        // Emits `$mcp_initialize`. The SDK maps `durationMs` → `$mcp_duration_ms`
        // and `sessionId` → `$session_id`; everything else rides on `properties`.
        getPostHogClient().captureInitialize({
            distinctId: state.distinctId,
            groups,
            durationMs: initDurationMs ?? 0,
            ...(sessionUuid ? { sessionId: sessionUuid } : {}),
            properties: {
                ...properties,
                $mcp_is_error: false,
                tool_count: state.allTools.length,
                has_organization_id: !!requestContext.organizationId,
                has_project_id: !!requestContext.projectId,
                read_only: !!requestContext.readOnly,
                via_sse_redirect: !!requestContext.viaSseRedirect,
            },
        })
    } catch {
        // never break the request for analytics
    }
}

export interface ToolCallIntentMeta {
    /** The agent's stated intent (the injected `context` arg) → `$mcp_intent`. */
    intent?: string
    /** Where it came from → `$mcp_intent_source`. */
    intentSource?: MCPAnalyticsIntentSource
}

export async function trackToolCall(
    toolName: string,
    durationMs: number,
    isError: boolean,
    state: ResolvedState,
    extraProperties?: Record<string, unknown>,
    intentMeta?: ToolCallIntentMeta,
    servedDescription?: string
): Promise<void> {
    try {
        const analyticsContext = await state.reqCtx.safelyGetAnalyticsContext(state.context)
        const requestContext = state.requestContext
        const sessionUuid = await state.reqCtx.getEffectiveSessionUuid(requestContext)

        const { properties, groups } = buildBaseProperties(state, analyticsContext)

        // The producer stamps the tool's category so the dashboard groups by it verbatim
        // (it never maps tool→category itself). Omitted when unknown (e.g. the `exec`
        // wrapper), which the dashboard buckets as "Uncategorized".
        // A proxied third-party tool has no catalog entry, so without the fallback every
        // gateway call would land uncategorized and drop out of category-sliced views.
        const gatewayServer = gatewayServerSlug(toolName)
        const toolCategory = getToolCategory(toolName) ?? (gatewayServer ? THIRD_PARTY_TOOL_CATEGORY : undefined)
        // The description the agent saw when it picked this tool, clipped. Powers the
        // tool-detail Descriptions table and description-vs-intent fit in MCP
        // analytics. Callers pass servedDescription when the advertised text differs
        // from the catalog (execute-sql's is formatted per request); otherwise the
        // catalog text is what was served. Inner exec calls reach here with the
        // resolved inner tool name, so the fallback lands on the inner tool's own
        // description.
        const toolDescription = servedDescription
            ? servedDescription.slice(0, MAX_CAPTURED_DESCRIPTION_LENGTH)
            : getToolDescription(toolName)

        // Emits `$mcp_tool_call` (+ `$mcp_is_error`). The SDK maps `toolName` →
        // `$mcp_tool_name`, `durationMs` → `$mcp_duration_ms`, `isError` →
        // `$mcp_is_error`, `intent` → `$mcp_intent`, and `sessionId` →
        // `$session_id`. `$exception` fan-out is disabled on the client, so an
        // errored call stays a single event.
        getPostHogClient().captureToolCall({
            toolName,
            durationMs,
            isError,
            distinctId: state.distinctId,
            groups,
            ...(sessionUuid ? { sessionId: sessionUuid } : {}),
            ...(intentMeta?.intent ? { intent: intentMeta.intent } : {}),
            ...(intentMeta?.intentSource ? { intentSource: intentMeta.intentSource } : {}),
            properties: {
                ...properties,
                tool_name: toolName,
                ...(toolCategory ? { $mcp_tool_category: toolCategory } : {}),
                ...(toolDescription ? { $mcp_tool_description: toolDescription } : {}),
                // Which vendor ran the tool, so "who do people actually call" is a
                // breakdown rather than a string split over `tool_name` in HogQL.
                ...(gatewayServer ? { mcp_gateway_server: gatewayServer } : {}),
                ...extraProperties,
            },
        })
    } catch {
        // never break the request for analytics
    }
}

export interface ExecuteSqlGenerationMeta {
    durationMs: number
    isError: boolean
    errorMessage?: string
}

/**
 * Manually captures an `$ai_generation` per `execute-sql` call — the client's LLM
 * authored the query; this server is the observer that sees intent and output
 * together. Lands in LLM analytics, where online evaluations (LLM judge / Hog) can
 * score it for anti-patterns on live traffic. `$ai_trace_id` is the MCP session
 * uuid, so a session's queries group into one trace.
 */
export async function trackExecuteSqlGeneration(
    toolName: string,
    args: unknown,
    state: ResolvedState,
    meta: ExecuteSqlGenerationMeta,
    intentMeta?: ToolCallIntentMeta
): Promise<void> {
    if (toolName !== EXECUTE_SQL_TOOL_NAME) {
        return
    }
    const query = (args as { query?: unknown } | null | undefined)?.query
    if (typeof query !== 'string' || query.length === 0) {
        return
    }
    try {
        const analyticsContext = await state.reqCtx.safelyGetAnalyticsContext(state.context)
        const sessionUuid = await state.reqCtx.getEffectiveSessionUuid(state.requestContext)
        const { properties, groups } = buildBaseProperties(state, analyticsContext)

        getPostHogClient().capture({
            distinctId: state.distinctId,
            event: '$ai_generation',
            groups,
            properties: {
                ...properties,
                ...(sessionUuid ? { $session_id: sessionUuid } : {}),
                $ai_trace_id: sessionUuid ?? randomUUID(),
                $ai_span_name: EXECUTE_SQL_TOOL_NAME,
                $ai_input: [{ role: 'user', content: intentMeta?.intent ?? '' }],
                $ai_output_choices: [{ role: 'assistant', content: query }],
                $ai_latency: meta.durationMs / 1000,
                $ai_is_error: meta.isError,
                ...(meta.errorMessage ? { $ai_error: meta.errorMessage } : {}),
            },
        })
    } catch {
        // never break the request for analytics
    }
}

const METADATA_QUERY_MARKER = 'information_schema'
const MAX_SPAN_STATE_LENGTH = 30_000

export interface ToolSpanMeta {
    durationMs: number
    isError: boolean
    errorMessage?: string
    input?: unknown
    output?: unknown
}

// Comments and single-quoted string literals can carry the metadata marker
// without the query actually reading a metadata relation, so they're stripped
// before the check — otherwise a data query like `... WHERE 'information_schema'
// != ''` would be mis-tagged as metadata and its result captured.
function stripSqlCommentsAndLiterals(query: string): string {
    return query
        .replace(/--[^\n]*/g, ' ')
        .replace(/\/\*[\s\S]*?\*\//g, ' ')
        .replace(/'(?:''|[^'])*'/g, ' ')
}

function isMetadataQuery(query: string): boolean {
    return stripSqlCommentsAndLiterals(query).toLowerCase().includes(METADATA_QUERY_MARKER)
}

function shouldCaptureToolSpan(toolName: string, input: unknown): boolean {
    // A proxied third-party tool's args and result are the vendor's content — an issue
    // body, a support ticket, a CRM record — passing through our gateway on its way
    // somewhere else. Key-based redaction only catches credential-shaped fields, so
    // capturing these would put arbitrary customer content in analytics to serve
    // evaluations that target PostHog's own tools. `$mcp_tool_call` still records that
    // the call happened, with its server, duration and outcome.
    if (isGatewayToolName(toolName)) {
        return false
    }
    // execute-sql can't be captured wholesale: its payload is the query result,
    // which is the bulk of MCP response volume. Metadata queries are the
    // exception, because their results are small and describe what the agent
    // learned about the workspace before writing its next query, which is the
    // context an evaluation needs to judge that query.
    if (toolName !== EXECUTE_SQL_TOOL_NAME) {
        return true
    }
    const query = (input as { query?: unknown } | null | undefined)?.query
    return typeof query === 'string' && isMetadataQuery(query)
}

const REDACTED_VALUE = '[redacted]'

// Capturing every tool's raw args would land credentials in telemetry: tools
// like user-settings-update carry `password`/`current_password`, warehouse
// sources carry `client_secret`, and hog-function inputs carry `secret` values.
// Match errs toward redaction — an over-redacted eval field is harmless, a
// leaked credential is not.
//
// Enumerating credential prefixes missed most of them: our own warehouse sources
// name their secret `api_token`, `database_token`, `consumer_key`,
// `signing_key`, and a dozen more, none of which the prefix list matched. The
// trailing-segment rule catches that whole shape. Plural `*_tokens` stays out on
// purpose — it is LLM token counts and Adjust's `app_tokens` app ids, never a
// secret. `connection_string` gets its own name: Postgres, MSSQL, Redshift,
// Snowflake and friends all accept one as an alternative to discrete
// host/user/password fields, and it carries the credentials inline
// (`postgres://user:pass@host/db`) — MongoDB's source has no other field for them.
// `certificate` covers Temporal Cloud's `client_certificate`: the source config
// itself marks it `secret: true` even though the name reads as public key
// material, and a client cert is namespace-identifying enough to keep out of
// telemetry too. `server_client_root_ca` stays unmatched on purpose — it is
// the CA the client uses to verify the *server*, public key material with no
// private half, marked `secret: true` only because the UI groups it with the
// real credentials.
//
// `app_id`/`api_id` and the trailing `username` case cover sources whose
// credential is an identifier rather than a token: Open Exchange Rates'
// `app_id` and Veracode's `api_id` are the whole usable credential, and
// Pipeliner generates its `username` alongside `password` as one half of a
// one-time API key pair (`secret: true` on the source config), unlike every
// other source's plain login `username`. Aircall's `api_id` and
// AppsFlyer/AppSignal/Churnkey's `app_id` are not credentials — they select
// which account or app an already-redacted token applies to — but the
// pattern can't tell those apart by name, and over-redacting a non-secret
// identifier is harmless where under-redacting a credential is not.
const SENSITIVE_KEY_PATTERN =
    /password|passwd|passphrase|secret|credential|certificate|private[_-]?key|access[_-]?key|api[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token|session[_-]?token|authorization|bearer|keypair|key[_-]?file|token[_-]?request|connection[_-]?string|app[_-]?id|api[_-]?id|(^|[_-])(token|key|keys|username)$/i

function redactSecrets(value: unknown): unknown {
    if (Array.isArray(value)) {
        return value.map(redactSecrets)
    }
    if (value !== null && typeof value === 'object') {
        return Object.fromEntries(
            Object.entries(value).map(([key, val]) => [
                key,
                SENSITIVE_KEY_PATTERN.test(key) ? REDACTED_VALUE : redactSecrets(val),
            ])
        )
    }
    return value
}

function serializeSpanState(value: unknown): string | undefined {
    if (value === undefined) {
        return undefined
    }
    try {
        const redacted = redactSecrets(value)
        const serialized = typeof redacted === 'string' ? redacted : JSON.stringify(redacted)
        return serialized?.slice(0, MAX_SPAN_STATE_LENGTH)
    } catch {
        return undefined
    }
}

/**
 * Captures an `$ai_span` for a tool call, joining the same MCP-session trace as
 * the execute-sql `$ai_generation` events. Trace-target online evaluations then
 * see a call's args AND result, neither of which `$mcp_tool_call` carries.
 *
 * Every tool is captured by default. `execute-sql` is the one exception: its
 * payload is the query result and it serves the bulk of MCP volume, so only its
 * metadata queries are captured (see {@link shouldCaptureToolSpan}).
 */
export async function trackToolSpan(toolName: string, state: ResolvedState, meta: ToolSpanMeta): Promise<void> {
    try {
        if (!shouldCaptureToolSpan(toolName, meta.input)) {
            return
        }
        const analyticsContext = await state.reqCtx.safelyGetAnalyticsContext(state.context)
        const sessionUuid = await state.reqCtx.getEffectiveSessionUuid(state.requestContext)
        const { properties, groups } = buildBaseProperties(state, analyticsContext)
        const toolCategory = getToolCategory(toolName)
        const inputState = serializeSpanState(meta.input)
        const outputState = serializeSpanState(meta.output)

        getPostHogClient().capture({
            distinctId: state.distinctId,
            event: '$ai_span',
            groups,
            properties: {
                ...properties,
                ...(sessionUuid ? { $session_id: sessionUuid } : {}),
                $ai_trace_id: sessionUuid ?? randomUUID(),
                $ai_span_name: toolName,
                ...(toolCategory ? { $mcp_tool_category: toolCategory } : {}),
                ...(inputState !== undefined ? { $ai_input_state: inputState } : {}),
                ...(outputState !== undefined ? { $ai_output_state: outputState } : {}),
                $ai_latency: meta.durationMs / 1000,
                $ai_is_error: meta.isError,
                ...(meta.errorMessage ? { $ai_error: meta.errorMessage } : {}),
            },
        })
    } catch {
        // never break the request for analytics
    }
}

/**
 * Emits `$mcp_auth_failed` for a request the PostHog API refused. These requests die
 * before `RequestStateResolver.resolve` returns, so they never reach
 * `trackInitEvent`/`trackToolCall` and are otherwise invisible in analytics — a
 * connector stuck in an authorize loop looks like a gap in the data rather than a
 * failure. Keyed on `userHash` (a hash of the bearer token, never the token itself)
 * so affected credentials can be counted without identifying anyone.
 *
 * Only PostHog's own server emits this; no SDK does. It reuses the canonical `$mcp_*`
 * client-identity fields so one query can group it and real MCP traffic by the same
 * dimensions.
 */
export function trackAuthFailure(props: RequestProperties, failure: McpAuthFailure): void {
    try {
        getPostHogClient().capture({
            distinctId: props.userHash,
            event: '$mcp_auth_failed',
            properties: {
                $ai_product: 'mcp',
                // Resolved without scopes — the request never authenticated, so nothing can
                // vouch for a declared consumer and anything unproven lands as `mcp`.
                source: resolveEventSource({
                    mcpConsumer: props.mcpConsumer,
                    clientUserAgent: props.clientUserAgent,
                }),
                $mcp_source: MCP_ANALYTICS_SOURCE,
                $mcp_server_name: MCP_SERVER_NAME,
                $mcp_server_version: MCP_SERVER_VERSION,
                $mcp_version: MCP_ANALYTICS_VERSION,
                $mcp_client_name: props.mcpClientName,
                $mcp_client_version: props.mcpClientVersion,
                $mcp_client_user_agent: props.clientUserAgent,
                $mcp_protocol_version: props.mcpProtocolVersion,
                $mcp_transport: props.transport,
                $mcp_session_id: props.mcpSessionId,
                $mcp_conversation_id: props.mcpConversationId,
                $mcp_consumer: props.mcpConsumer,
                $mcp_mode: props.mode,
                $mcp_region: props.region,
                $mcp_auth_method: classifyAuthMethod(props.apiToken),
                mcp_runtime: 'hono',
                mcp_vendor_client: props.mcpVendorClient,
                $mcp_auth_failure_reason: failure.reason,
                ...(failure.status ? { $mcp_auth_status: failure.status } : {}),
                ...(failure.missingScope ? { $mcp_missing_scope: failure.missingScope } : {}),
                has_organization_id: !!props.organizationId,
                has_project_id: !!props.projectId,
            },
        })
    } catch {
        // never break the request for analytics
    }
}

export async function trackToolsList(toolNames: string[], state: ResolvedState): Promise<void> {
    try {
        const analyticsContext = await state.reqCtx.safelyGetAnalyticsContext(state.context)
        const requestContext = state.requestContext
        const sessionUuid = await state.reqCtx.getEffectiveSessionUuid(requestContext)

        const { properties, groups } = buildBaseProperties(state, analyticsContext)

        // The SDK maps `toolNames` → `$mcp_listed_tool_names`, which powers
        // "advertised but never called" analysis.
        getPostHogClient().captureToolsList({
            toolNames,
            distinctId: state.distinctId,
            groups,
            ...(sessionUuid ? { sessionId: sessionUuid } : {}),
            properties: {
                ...properties,
                tool_count: toolNames.length,
            },
        })
    } catch {
        // never break the request for analytics
    }
}
