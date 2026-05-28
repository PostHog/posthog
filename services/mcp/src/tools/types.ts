import type { ElicitRequestFormParams, ElicitResult } from '@modelcontextprotocol/sdk/types.js'
import type { z } from 'zod'

import type { ApiClient, GroupType } from '@/api/client'
import type { Schemas } from '@/api/generated'
import type { ScopedCache } from '@/lib/cache/ScopedCache'
import type { AnalyticsEvent } from '@/lib/posthog/analytics'
import type { SessionManager } from '@/lib/SessionManager'
import type { StateManager } from '@/lib/StateManager'
import type { PrefixedString } from '@/lib/types'
import type { ApiRedactedPersonalApiKey, ApiUser } from '@/schema/api'

export type CloudRegion = 'us' | 'eu'

export type SessionState = {
    uuid: string
}

export type CachedUser = ApiUser
export type CachedOrg = Schemas.OrganizationBasic
export type CachedProject = Schemas.ProjectBackwardCompat

export type State = {
    projectId: string | undefined
    orgId: string | undefined
    distinctId: string | undefined
    region: CloudRegion | undefined
    apiKey: ApiRedactedPersonalApiKey | undefined
    clientName: string | undefined
    mcpClientName: string | undefined
    mcpClientVersion: string | undefined
    mcpProtocolVersion: string | undefined
} & Record<PrefixedString<'session'>, SessionState> &
    Record<PrefixedString<'groupTypes'>, GroupType[] | undefined> &
    Record<PrefixedString<'groupTypesFetchedAt'>, number | undefined> &
    Record<PrefixedString<'cachedUser'>, CachedUser | undefined> &
    Record<PrefixedString<'cachedUserFetchedAt'>, number | undefined> &
    Record<PrefixedString<'cachedOrg'>, CachedOrg | undefined> &
    Record<PrefixedString<'cachedOrgFetchedAt'>, number | undefined> &
    Record<PrefixedString<'cachedProject'>, CachedProject | undefined> &
    Record<PrefixedString<'cachedProjectFetchedAt'>, number | undefined>

export type Env = {
    /**
     * Custom API base URL for self-hosted PostHog instances.
     *
     * WARNING: In PostHog Production, this should NOT be set.
     * The code automatically handles US/EU region routing via getAuthorizationServerUrl().
     * Only set this for self-hosted PostHog deployments.
     */
    POSTHOG_API_BASE_URL: string | undefined
    /**
     * Base URL for serving MCP UI app static assets.
     * When using Workers Static Assets, this is the Worker's own public URL.
     * Example: https://mcp.posthog.com
     */
    MCP_APPS_BASE_URL: string | undefined
    /**
     * PostHog base URL for MCP Apps analytics (used for CSP and analytics ingestion).
     * For local development, set to http://localhost:8010.
     */
    POSTHOG_MCP_APPS_ANALYTICS_BASE_URL: string | undefined
    /**
     * PostHog API token for MCP Apps analytics (used for CSP and analytics ingestion).
     */
    POSTHOG_UI_APPS_TOKEN: string | undefined
    /**
     * PostHog API key for dev/self-hosted analytics.
     * Falls back to the production US key if not set.
     */
    POSTHOG_ANALYTICS_API_KEY: string | undefined
    /**
     * PostHog host for dev/self-hosted analytics.
     * Falls back to the production US host if not set.
     */
    POSTHOG_ANALYTICS_HOST: string | undefined
}

export type Context = {
    api: ApiClient
    cache: ScopedCache<State>
    env: Env
    stateManager: StateManager
    sessionManager: SessionManager
    /**
     * Resolve the current user's PostHog distinct ID. Cached by the MCP class —
     * safe to call repeatedly. Exposed on the context so tool handlers (e.g. the
     * exec wrapper) can attach `_analytics` without depending on the MCP class.
     */
    getDistinctId: () => Promise<string>
    /**
     * Capture a PostHog analytics event with the same context (mcp_client_name,
     * session id, $groups, etc.) that the MCP class attaches to its own events.
     * Best-effort — never throws and silently swallows failures so analytics
     * cannot fail a tool call. Workspace context is auto-resolved from the
     * stateManager when not provided.
     */
    trackEvent: (event: AnalyticsEvent, properties?: Record<string, unknown>) => Promise<void>
    /**
     * Request structured input from the user via the MCP client (an elicitation
     * modal). Used to gate destructive actions behind manual confirmation.
     *
     * Undefined when elicitation cannot or should not be attempted. Tool
     * authors MUST treat `context.elicit` as a capability check and fall back
     * gracefully when it's missing. Reasons for `undefined`:
     *
     * - **Runtime not wired:** runtimes other than Hono (e.g. the Workers/DO
     *   implementation) don't expose elicit at all yet.
     * - **Client didn't declare support:** the MCP spec requires the server
     *   NOT to send `elicitation/create` to a client that didn't advertise
     *   `capabilities.elicitation` at initialize. The Hono dispatcher reads
     *   the cached capability and leaves `elicit` undefined when missing —
     *   including cold-start cases where no initialize has been observed
     *   yet for this token. Fail-closed by design.
     *
     * Throws (only when invoked — i.e. when `elicit` is defined):
     * - `SessionBusTimeoutError` if no response within the deadline.
     * - `SessionBusAbortedError` if the request signal aborts.
     * - `ElicitationNotSupportedError` if the client returns a JSON-RPC error
     *   envelope at runtime (e.g. lied about capability, or supports only a
     *   mode we don't yet send). Carries the JSON-RPC error code. Tool
     *   authors should catch and fall back to a non-interactive path.
     * - `SessionBusUnhealthyError` if the bus transport or payload validation
     *   fails (structurally malformed responses, not protocol-level errors).
     *
     * NOTE: `elicit` is legacy (2025-06-18 protocol only). New code should
     * use `requestInput` below — same intent, works on both protocol versions.
     */
    elicit?: ElicitFn

    /**
     * Universal input-request seam. Works on both protocol pipelines:
     *
     * - 2025-06-18: delegates to `elicit` under the hood (pushes
     *   `elicitation/create` over SSE and awaits a reply via the session bus).
     * - 2026-07-28: throws an internal `InputRequiredSignal` that the
     *   dispatcher catches, turning into an `InputRequiredResult`. On retry,
     *   returns the corresponding entry from `inputResponses`.
     *
     * Tool authors write straight-line code:
     *
     * ```ts
     * const result = await context.requestInput({
     *     key: 'confirm',
     *     message: 'Proceed?',
     *     requestedSchema: { type: 'object', properties: {} },
     * })
     * if (result.action !== 'accept') return cancellation()
     * ```
     *
     * Undefined when no elicitation capability was negotiated. Tool authors
     * MUST treat `if (context.requestInput)` as a capability check.
     *
     * IMPORTANT (2026-07-28 only): handlers may be re-invoked multiple times
     * as the protocol round-trips. Code BEFORE a `requestInput` call runs on
     * every round; side-effects there must be idempotent. Place destructive
     * side-effects AFTER the `accept` branch.
     */
    requestInput?: RequestInputFn
}

export type ElicitFn = (
    params: ElicitRequestFormParams,
    options?: { timeoutMs?: number; signal?: AbortSignal }
) => Promise<ElicitResult>

export type RequestInputFn = (params: RequestInputParams) => Promise<ElicitResult>

export interface RequestInputParams {
    /**
     * Author-chosen identifier for this input request. Used to correlate
     * the response on retry. Stable within a single tool's logic — if a
     * handler issues two requestInput calls in sequence, they must use
     * different keys.
     */
    key: string
    /** Prompt text shown to the user. */
    message: string
    /** JSON Schema for the expected response content. Empty `properties` for action-only confirmations. */
    requestedSchema: ElicitRequestFormParams['requestedSchema']
}

export type Tool<TSchema extends z.ZodType = z.ZodType, TResult = unknown> = {
    name: string
    title: string
    description: string
    schema: TSchema
    handler: (context: Context, params: z.infer<TSchema>) => Promise<TResult>
    scopes: string[]
    annotations: {
        destructiveHint: boolean
        idempotentHint: boolean
        openWorldHint: boolean
        readOnlyHint: boolean
    }
    _meta?: ToolMeta
}

export type ToolBase<TSchema extends z.ZodType = z.ZodType, TResult = unknown> = Omit<
    Tool<TSchema, TResult>,
    'title' | 'description' | 'scopes' | 'annotations'
> & {
    _meta?: ToolMeta
    /** When set, the tool is only available in this MCP version (1 = v1 only, 2 = v2 only). */
    mcpVersion?: number
}

export type ZodObjectAny = z.ZodType<any>

export type ToolUiMeta = {
    resourceUri: string
    visibility?: ('model' | 'app')[]
}

export const POSTHOG_META_KEY = 'com.posthog.mcp' as const
export const POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY = '__formatted_results_override' as const

export type PostHogToolMeta = {
    /**
     * Output format for the tool response.
     * `'optimized'` surfaces the LLM-friendly formatter output (from `ee/hogai/context/insight/format/`)
     * via `formatted_results` when available; `'json'` returns raw JSON-stringified content. When unset,
     * the text content is TOON-encoded by default.
     */
    outputFormat?: 'optimized' | 'json'
}

export type ToolMeta = {
    // Legacy flat key for MCP Apps compatibility (ui/resourceUri)
    'ui/resourceUri'?: string
    // New non-legacy key for MCP Apps
    ui?: ToolUiMeta

    /** PostHog-specific tool metadata under a namespaced key. */
    [POSTHOG_META_KEY]?: PostHogToolMeta
}
