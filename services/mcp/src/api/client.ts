import { createParser } from 'eventsource-parser'
import { z } from 'zod'

import { getUserAgent } from '@/lib/constants'
import {
    ErrorCode,
    parseRetryAfterSeconds,
    PostHogApiError,
    PostHogPermissionError,
    PostHogRateLimitError,
    PostHogValidationError,
} from '@/lib/errors'
import { getSearchParamsFromRecord } from '@/lib/utils.js'
import type {
    ApiEventDefinition,
    ApiOAuthIntrospection,
    ApiPropertyDefinition,
    ApiRedactedPersonalApiKey,
    ApiUser,
} from '@/schema/api'
import type {
    Experiment,
    ExperimentExposureQuery,
    ExperimentExposureQueryResponse,
    ResolvedMetricEntry,
} from '@/schema/experiments'
import { buildMetricEntries, ExperimentExposureQuerySchema } from '@/schema/experiments'
import { isShortId } from '@/tools/insights/utils'

import type { Schemas } from './generated.js'

// Outbound 429 retry policy. The API is the source of truth for rate limits
// (per-scope, with per-team overrides), so we honor its Retry-After signal and
// fall back to jittered exponential backoff when the header is missing or
// invalid. The total wait budget bounds how long a throttled tool call can
// hold the MCP client's request open across all retries combined.
const RATE_LIMIT_MAX_RETRIES = 3
const RATE_LIMIT_BASE_BACKOFF_MS = 2000
const RATE_LIMIT_TOTAL_WAIT_BUDGET_MS = 30_000

// Outbound transient-5xx retry policy for idempotent reads. When the backend is
// momentarily unavailable — e.g. `ClickHouseAtCapacity` surfaces as a 503 — a
// short backoff-and-retry turns most of these blips into a successful response
// instead of a hard, agent-visible tool failure. Scoped to 502/503/504 (a bad
// gateway, capacity, or gateway timeout are transient; a bare 500 is usually a
// real bug not worth replaying) and only applied to GETs, since replaying a
// mutation that may have partially applied is unsafe. Shares the same wall-clock
// wait budget as the 429 path so a single call can't hold the request open
// indefinitely by bouncing between throttling and transient failures.
const TRANSIENT_SERVER_ERROR_STATUSES = new Set([502, 503, 504])
const TRANSIENT_SERVER_ERROR_MAX_RETRIES = 2
const TRANSIENT_SERVER_ERROR_BASE_BACKOFF_MS = 1000

// Default overall timeout for an SSE stream (wall-clock cap from connect to close).
// Sized to comfortably cover the slowest known caller (session summarization, ~5 min
// average) with headroom for cold-cache LLM calls.
const SSE_DEFAULT_TIMEOUT_MS = 10 * 60 * 1000

// Per-read inactivity timeout: if no chunk (not even a keepalive comment) arrives
// within this window, the server is assumed dead. Must comfortably exceed the
// server-side keepalive interval — kept in sync with `SSE_KEEPALIVE_INTERVAL = 15s`
// in `ee/api/session_summaries.py`. If you change one, check the other.
const SSE_READ_TIMEOUT_MS = 30_000

export interface GroupType {
    group_type: string
    group_type_index: number
    name_singular: string | null
    name_plural: string | null
}

// Global search types
export const SearchableEntitySchema = z.enum([
    'insight',
    'dashboard',
    'experiment',
    'feature_flag',
    'notebook',
    'action',
    'cohort',
    'event_definition',
    'survey',
])
export type SearchableEntity = z.infer<typeof SearchableEntitySchema>

export interface SearchResult {
    type: string
    result_id: string
    extra_fields: Record<string, unknown>
    rank?: number
}

export interface SearchResponse {
    results: SearchResult[]
    counts?: Record<string, number | null>
}

export type Result<T, E = Error> = { success: true; data: T } | { success: false; error: E }

export interface DataWarehouseSyncWarning {
    table_name: string
    schema_name: string
    source_type: string
    status: string
    message: string
}

export interface QueryEndpointResponse {
    results: unknown
    columns?: unknown
    formatted_results?: string
    // null (not just absent) when the query response carries no warnings — the backend
    // serializes the field explicitly rather than omitting it.
    warnings?: DataWarehouseSyncWarning[] | null
}

export interface ApiConfig {
    apiToken: string
    baseUrl: string
    /**
     * Public-facing base URL used when building links the user clicks (e.g. `_posthogUrl`).
     * Defaults to `baseUrl` when unset or empty. Distinct from `baseUrl` so deployments can route
     * API traffic over a cluster-internal hostname while still rendering public links
     * (e.g. https://us.posthog.com) in tool responses.
     */
    publicBaseUrl?: string | undefined
    clientUserAgent?: string | undefined
    mcpClientName?: string | undefined
    mcpClientVersion?: string | undefined
    mcpProtocolVersion?: string | undefined
    mcpConsumer?: string | undefined
    oauthClientName?: string | undefined
    mcpSessionId?: string | undefined
    mcpConversationId?: string | undefined
    /**
     * Sandbox-provisioned task id (from the inbound `x-posthog-task-id` MCP header). Forwarded
     * to the PostHog API as `X-PostHog-Task-Id` on every call so writes can be attributed to
     * the agent's task; the API validates it against the token's team.
     */
    taskId?: string | undefined
}

type Endpoint = Record<string, any>

export class ApiClient {
    public config: ApiConfig
    public baseUrl: string
    public publicBaseUrl: string

    constructor(config: ApiConfig) {
        this.config = config
        this.baseUrl = config.baseUrl
        // `||` (not `??`) so an empty string — e.g. the Workers vitest config sets
        // env vars to '' — falls back to baseUrl instead of yielding relative links.
        this.publicBaseUrl = config.publicBaseUrl || config.baseUrl
    }

    getProjectBaseUrl(projectId: string): string {
        if (projectId === '@current') {
            return this.publicBaseUrl
        }

        return `${this.publicBaseUrl}/project/${projectId}`
    }

    private async fetch(url: string, options?: RequestInit): Promise<Response> {
        const defaultHeaders: HeadersInit = {
            Authorization: `Bearer ${this.config.apiToken}`,
            'User-Agent': getUserAgent({ clientUserAgent: this.config.clientUserAgent }),
            ...(this.config.clientUserAgent
                ? {
                      // Forward the originating client's User-Agent as a custom header so the
                      // PostHog API can attach it to analytics events for MCP source attribution.
                      'x-posthog-mcp-user-agent': this.config.clientUserAgent,
                  }
                : {}),
            // Forward MCP clientInfo fields from the initialize request so the
            // PostHog API can attach them to analytics events.
            ...(this.config.mcpClientName ? { 'x-posthog-mcp-client-name': this.config.mcpClientName } : {}),
            ...(this.config.mcpClientVersion ? { 'x-posthog-mcp-client-version': this.config.mcpClientVersion } : {}),
            ...(this.config.mcpProtocolVersion
                ? { 'x-posthog-mcp-protocol-version': this.config.mcpProtocolVersion }
                : {}),
            ...(this.config.mcpConsumer ? { 'x-posthog-mcp-consumer': this.config.mcpConsumer } : {}),
            ...(this.config.oauthClientName ? { 'x-posthog-mcp-oauth-client-name': this.config.oauthClientName } : {}),
            // Forward MCP session and conversation ids so backend logs and OTLP
            // spans for downstream API hops can correlate with the same MCP context
            // the events carry. This is attribute-based correlation only — we do
            // not forward `traceparent` (the Worker emits no OTLP today), so the
            // Django-rooted span is not a child of any Worker-side span.
            ...(this.config.mcpSessionId ? { 'x-posthog-mcp-session-id': this.config.mcpSessionId } : {}),
            ...(this.config.mcpConversationId
                ? { 'x-posthog-mcp-conversation-id': this.config.mcpConversationId }
                : {}),
            // Forward the sandbox task id so API writes are attributed to the agent's task.
            ...(this.config.taskId ? { 'X-PostHog-Task-Id': this.config.taskId } : {}),
            'X-PostHog-Client': 'mcp',
        }
        if (options?.body) {
            defaultHeaders['Content-Type'] = 'application/json'
        }
        return fetch(url, {
            ...options,
            headers: {
                ...defaultHeaders,
                ...options?.headers,
            },
        })
    }

    /**
     * Generic HTTP request with auth.
     * Used by generated tool handlers to avoid duplicating endpoint-specific methods.
     */
    async request<T = unknown>(opts: {
        method: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
        path: string
        body?: Record<string, unknown>
        query?: Record<string, unknown>
        headers?: Record<string, string>
        responseType?: 'json' | 'text'
    }): Promise<T> {
        const searchParams = new URLSearchParams()
        if (opts.query) {
            for (const [k, v] of Object.entries(opts.query)) {
                if (v === undefined || v === null) {
                    continue
                }
                if (Array.isArray(v) && v.length === 0) {
                    continue
                }
                // JSON-stringify objects and arrays so backends that use json.loads() on query params work correctly
                if (typeof v === 'object') {
                    searchParams.append(k, JSON.stringify(v))
                } else {
                    searchParams.append(k, String(v))
                }
            }
        }
        const qs = searchParams.toString()
        const url = `${this.baseUrl}${opts.path}${qs ? `?${qs}` : ''}`

        const fetchOptions: RequestInit = {
            method: opts.method,
            ...(opts.body ? { body: JSON.stringify(opts.body) } : {}),
            ...(opts.headers ? { headers: opts.headers } : {}),
        }

        if (opts.responseType === 'text') {
            const response = await this.fetch(url, fetchOptions)
            if (!response.ok) {
                const errorText = await response.text()
                throw new PostHogApiError({
                    status: response.status,
                    statusText: response.statusText,
                    body: errorText,
                    url,
                    method: opts.method,
                })
            }
            return (await response.text()) as T
        }

        const result = await this.fetchJson<T>(url, fetchOptions)

        if (!result.success) {
            // Re-throw the original error instance so callers can instanceof-check
            // typed errors (e.g. PostHogPermissionError) that fetchJson throws.
            throw result.error
        }
        return result.data as T
    }

    /**
     * Open a Server-Sent Events (text/event-stream) connection and invoke `onEvent`
     * for each parsed event. Resolves when the server closes the stream, throws on
     * HTTP error, missing body, per-read inactivity, or overall stream timeout.
     *
     * Used by tools that consume long-running streaming endpoints (e.g. session
     * summarization) where a synchronous request would exceed gateway timeouts.
     */
    async requestSSE<T = unknown>(opts: {
        method: 'GET' | 'POST'
        path: string
        body?: Record<string, unknown>
        onEvent: (event: string, data: T) => void
        timeoutMs?: number
    }): Promise<void> {
        const url = `${this.baseUrl}${opts.path}`
        const fetchOptions: RequestInit = {
            method: opts.method,
            ...(opts.body ? { body: JSON.stringify(opts.body) } : {}),
            headers: {
                Accept: 'text/event-stream',
            },
        }

        const response = await this.fetch(url, fetchOptions)

        if (!response.ok) {
            const errorText = await response.text()
            throw new Error(
                `SSE request failed:\nURL: ${opts.method} ${url}\nStatus Code: ${response.status} (${response.statusText})\nError Message: ${errorText}`
            )
        }

        if (!response.body) {
            throw new Error(`SSE response has no body: ${opts.method} ${url}`)
        }

        const timeoutMs = opts.timeoutMs ?? SSE_DEFAULT_TIMEOUT_MS
        const readTimeoutMs = SSE_READ_TIMEOUT_MS
        const startTime = Date.now()
        const reader = response.body.getReader()
        const decoder = new TextDecoder()

        const parser = createParser({
            onEvent: ({ event, data }) => {
                const eventType = event ?? 'message'
                try {
                    const parsed = JSON.parse(data) as T
                    opts.onEvent(eventType, parsed)
                } catch {
                    // Non-JSON data, pass as-is
                    opts.onEvent(eventType, data as T)
                }
            },
        })

        try {
            while (true) {
                if (Date.now() - startTime > timeoutMs) {
                    throw new Error(`SSE stream timed out after ${timeoutMs}ms`)
                }

                let readTimeoutId: ReturnType<typeof setTimeout>
                const readResult = await Promise.race([
                    reader.read(),
                    new Promise<never>((_, reject) => {
                        readTimeoutId = setTimeout(
                            () => reject(new Error(`SSE read timed out — no data received for ${readTimeoutMs}ms`)),
                            readTimeoutMs
                        )
                    }),
                ])
                clearTimeout(readTimeoutId!)
                const { done, value } = readResult
                if (done) {
                    break
                }

                parser.feed(decoder.decode(value, { stream: true }))
            }
        } finally {
            await reader.cancel()
            reader.releaseLock()
        }
    }

    private async fetchJson<T>(url: string, options?: RequestInit): Promise<Result<T>> {
        const method = options?.method ?? 'GET'
        let waitBudgetMs = RATE_LIMIT_TOTAL_WAIT_BUDGET_MS
        // Replaying a mutation that may have partially applied server-side is
        // unsafe, so transient-5xx retries are gated to idempotent reads.
        const canRetryServerError = method === 'GET'
        let rateLimitRetries = 0
        let serverErrorRetries = 0

        // Overall loop guard: the initial attempt plus every retry either policy
        // could grant. Per-policy counters below decide when each stops; this
        // bound only keeps the loop finite (and lets TypeScript see a terminal
        // return after it).
        const maxAttempts = 1 + RATE_LIMIT_MAX_RETRIES + TRANSIENT_SERVER_ERROR_MAX_RETRIES

        for (let attempt = 0; attempt < maxAttempts; attempt++) {
            try {
                const response = await this.fetch(url, options)

                if (response.status === 429) {
                    const retryAfterSeconds = parseRetryAfterSeconds(response.headers.get('Retry-After'))
                    const rateLimitFailure = async (): Promise<Result<T>> => ({
                        success: false,
                        error: new PostHogRateLimitError({
                            body: await response.text(),
                            url,
                            method,
                            retryAfterSeconds,
                        }),
                    })

                    if (rateLimitRetries >= RATE_LIMIT_MAX_RETRIES) {
                        console.error(`[API] Rate limit (429) retries exhausted on ${method} ${url}`)
                        return rateLimitFailure()
                    }

                    // DRF rejects throttled requests before the view executes,
                    // so retrying is safe for mutations too.
                    const backoffMs = RATE_LIMIT_BASE_BACKOFF_MS * 2 ** rateLimitRetries
                    const delayMs =
                        retryAfterSeconds !== null
                            ? retryAfterSeconds * 1000
                            : // Equal jitter so concurrent 429s don't retry in lockstep.
                              backoffMs / 2 + Math.random() * (backoffMs / 2)

                    if (delayMs > waitBudgetMs) {
                        console.warn(
                            `[API] Rate limited (429) on ${method} ${url}. Requested wait of ${Math.round(delayMs / 1000)}s exceeds the remaining ${Math.round(waitBudgetMs / 1000)}s retry budget; not retrying.`
                        )
                        return rateLimitFailure()
                    }

                    waitBudgetMs -= delayMs
                    rateLimitRetries++
                    console.warn(
                        `[API] Rate limited (429) on ${method} ${url}. Retrying in ${Math.round(delayMs)}ms (attempt ${rateLimitRetries}/${RATE_LIMIT_MAX_RETRIES})`
                    )
                    await new Promise((resolve) => setTimeout(resolve, delayMs))
                    continue
                }

                // Transient 5xx on an idempotent read: back off and retry, else
                // fall through to the standard error path below (which throws a
                // PostHogApiError, preserving 5xx visibility once retries or the
                // shared wait budget are exhausted).
                if (canRetryServerError && TRANSIENT_SERVER_ERROR_STATUSES.has(response.status)) {
                    if (serverErrorRetries < TRANSIENT_SERVER_ERROR_MAX_RETRIES) {
                        const retryAfterSeconds = parseRetryAfterSeconds(response.headers.get('Retry-After'))
                        const backoffMs = TRANSIENT_SERVER_ERROR_BASE_BACKOFF_MS * 2 ** serverErrorRetries
                        const delayMs =
                            retryAfterSeconds !== null
                                ? retryAfterSeconds * 1000
                                : // Equal jitter so concurrent failures don't retry in lockstep.
                                  backoffMs / 2 + Math.random() * (backoffMs / 2)

                        if (delayMs <= waitBudgetMs) {
                            waitBudgetMs -= delayMs
                            serverErrorRetries++
                            console.warn(
                                `[API] Transient server error (${response.status}) on ${method} ${url}. Retrying in ${Math.round(delayMs)}ms (attempt ${serverErrorRetries}/${TRANSIENT_SERVER_ERROR_MAX_RETRIES})`
                            )
                            await new Promise((resolve) => setTimeout(resolve, delayMs))
                            continue
                        }
                        console.warn(
                            `[API] Transient server error (${response.status}) on ${method} ${url}. Requested wait of ${Math.round(delayMs / 1000)}s exceeds the remaining ${Math.round(waitBudgetMs / 1000)}s retry budget; not retrying.`
                        )
                    }
                }

                if (!response.ok) {
                    if (response.status === 401) {
                        throw new Error(ErrorCode.INVALID_API_KEY)
                    }

                    const errorText = await response.text()

                    let errorData: any
                    try {
                        errorData = JSON.parse(errorText)
                    } catch {
                        errorData = { detail: errorText }
                    }

                    if (response.status === 403 && errorData?.code === 'permission_denied') {
                        const scopeMatch = /required scope ['"]([^'"]+)['"]/.exec(errorData.detail || '')
                        const missingScope = scopeMatch?.[1]
                        // Warn, not error: PostHogPermissionError is thrown and handled by callers,
                        // and a missing scope is a user-config issue rather than a service bug.
                        console.warn(
                            `[API] Permission denied on ${method} ${url}: ${errorData.detail || 'unknown'}${missingScope ? ` (missing scope: ${missingScope})` : ''}`
                        )
                        throw new PostHogPermissionError({
                            detail: errorData.detail || 'permission denied',
                            missingScope,
                            url,
                            method,
                        })
                    }

                    if (errorData.type === 'validation_error') {
                        const detail = errorData.detail || errorData.code || 'unknown'
                        const attrLog = errorData.attr ? ` (field: ${errorData.attr})` : ''
                        console.error(`[API] Validation error on ${method} ${url}: ${detail}${attrLog}`)
                        throw new PostHogValidationError({
                            detail,
                            attr: errorData.attr ?? undefined,
                            code: errorData.code ?? undefined,
                            extra: (errorData.extra ?? undefined) as Record<string, unknown> | undefined,
                            url,
                            method,
                        })
                    }

                    if (response.status === 404) {
                        const experimentMatch = /\/experiments\/(\d+)/.exec(url)
                        if (experimentMatch) {
                            const experimentId = experimentMatch[1]
                            console.error(`[API] Experiment ${experimentId} not found on ${method} ${url}`)
                            throw new Error(
                                `Experiment ${experimentId} not found in this project. ` +
                                    `If the id is correct, the experiment may belong to a different project — ` +
                                    `call experiment-list to see experiments accessible with your current API key and project, or switch-project first.`
                            )
                        }
                    }

                    console.error(`[API] Request failed on ${method} ${url}: ${response.status} ${response.statusText}`)
                    throw new PostHogApiError({
                        status: response.status,
                        statusText: response.statusText,
                        body: errorText,
                        url,
                        method,
                    })
                }

                const rawText = await response.text()
                if (!rawText) {
                    return { success: true, data: {} as T }
                }

                try {
                    const rawData = JSON.parse(rawText)
                    return { success: true, data: rawData as T }
                } catch {
                    return { success: true, data: rawText as T }
                }
            } catch (error) {
                return { success: false, error: error as Error }
            }
        }

        // Unreachable: the final attempt always returns above, but TypeScript
        // can't prove the loop is exhaustive.
        return { success: false, error: new Error('Unexpected retry state') }
    }

    organizations(): Endpoint {
        return {
            list: async (): Promise<Result<Schemas.OrganizationBasic[]>> => {
                const result = await this.fetchJson<{ results: Schemas.OrganizationBasic[] }>(
                    `${this.baseUrl}/api/organizations/`
                )

                if (result.success) {
                    return { success: true, data: result.data.results }
                }
                return result
            },

            get: async ({ orgId }: { orgId: string }): Promise<Result<Schemas.OrganizationBasic>> => {
                return this.fetchJson<Schemas.OrganizationBasic>(`${this.baseUrl}/api/organizations/${orgId}/`)
            },

            projects: ({ orgId }: { orgId: string }) => {
                return {
                    list: async (): Promise<Result<Schemas.ProjectBackwardCompat[]>> => {
                        const result = await this.fetchJson<{ results: Schemas.ProjectBackwardCompat[] }>(
                            `${this.baseUrl}/api/organizations/${orgId}/projects/`
                        )

                        if (result.success) {
                            return { success: true, data: result.data.results }
                        }
                        return result
                    },
                }
            },
        }
    }

    apiKeys(): Endpoint {
        return {
            current: async (): Promise<Result<ApiRedactedPersonalApiKey>> => {
                return this.fetchJson<ApiRedactedPersonalApiKey>(`${this.baseUrl}/api/personal_api_keys/@current`)
            },
        }
    }

    oauth(): Endpoint {
        return {
            introspect: async ({ token }: { token: string }): Promise<Result<ApiOAuthIntrospection>> => {
                return this.fetchJson<ApiOAuthIntrospection>(`${this.baseUrl}/oauth/introspect`, {
                    method: 'POST',
                    body: JSON.stringify({ token }),
                    headers: {
                        'Content-Type': 'application/json',
                        Authorization: `Bearer ${token}`,
                    },
                })
            },
        }
    }

    projects(): Endpoint {
        return {
            get: async ({ projectId }: { projectId: string }): Promise<Result<Schemas.ProjectBackwardCompat>> => {
                return this.fetchJson<Schemas.ProjectBackwardCompat>(`${this.baseUrl}/api/projects/${projectId}/`)
            },

            propertyDefinitions: async ({
                projectId,
                eventNames,
                excludeCoreProperties,
                filterByEventNames,
                isFeatureFlag,
                limit,
                offset,
                type,
            }: {
                projectId: string
                eventNames?: string[] | undefined
                excludeCoreProperties?: boolean
                filterByEventNames?: boolean
                isFeatureFlag?: boolean
                limit?: number
                offset?: number
                type?: 'event' | 'person'
            }): Promise<Result<ApiPropertyDefinition[]>> => {
                try {
                    const params = {
                        event_names: eventNames?.length ? JSON.stringify(eventNames) : undefined,
                        exclude_core_properties: excludeCoreProperties,
                        filter_by_event_names: filterByEventNames,
                        is_feature_flag: isFeatureFlag,
                        limit: limit ?? 50,
                        offset: offset ?? 0,
                        type: type ?? 'event',
                        exclude_hidden: true,
                    }

                    const searchParams = getSearchParamsFromRecord(params)

                    const url = `${this.baseUrl}/api/projects/${projectId}/property_definitions/?${searchParams}`

                    const response = await this.fetch(url)

                    if (!response.ok) {
                        throw new Error(`Failed to fetch property definitions: ${response.statusText}`)
                    }

                    const data = (await response.json()) as { results: ApiPropertyDefinition[] }

                    const propertyDefinitionsWithoutHidden = data.results.filter((def) => !def.hidden)

                    return { success: true, data: propertyDefinitionsWithoutHidden }
                } catch (error) {
                    return { success: false, error: error as Error }
                }
            },

            eventDefinitions: async ({
                projectId,
                search,
                limit,
                offset,
            }: {
                projectId: string
                search?: string | undefined
                limit?: number
                offset?: number
            }): Promise<Result<ApiEventDefinition[]>> => {
                try {
                    const searchParams = getSearchParamsFromRecord({
                        search,
                        limit: limit ?? 50,
                        offset: offset ?? 0,
                    })

                    const requestUrl = `${this.baseUrl}/api/projects/${projectId}/event_definitions/?${searchParams}`

                    const response = await this.fetch(requestUrl)

                    if (!response.ok) {
                        throw new Error(`Failed to fetch event definitions: ${response.statusText}`)
                    }

                    const data = (await response.json()) as { results: ApiEventDefinition[] }

                    return { success: true, data: data.results }
                } catch (error) {
                    return { success: false, error: error as Error }
                }
            },

            updateEventDefinition: async ({
                projectId,
                eventName,
                data,
            }: {
                projectId: string
                eventName: string
                data: {
                    description?: string
                    tags?: string[]
                    verified?: boolean
                    hidden?: boolean
                }
            }): Promise<Result<ApiEventDefinition>> => {
                try {
                    // Fetching the event definition by name to get its ID
                    const searchParams = new URLSearchParams({ name: eventName })
                    const findUrl = `${this.baseUrl}/api/projects/${projectId}/event_definitions/by_name/?${searchParams}`

                    const findResponse = await this.fetch(findUrl)

                    if (findResponse.status === 404) {
                        return {
                            success: false,
                            error: new Error(`Event definition not found: ${eventName}`),
                        }
                    }

                    if (!findResponse.ok) {
                        throw new Error(`Failed to find event definition: ${findResponse.statusText}`)
                    }

                    const eventDef = (await findResponse.json()) as ApiEventDefinition

                    // Updating the event definition by ID
                    const updateUrl = `${this.baseUrl}/api/projects/${projectId}/event_definitions/${eventDef.id}/`

                    const updateResponse = await this.fetch(updateUrl, {
                        method: 'PATCH',
                        body: JSON.stringify(data),
                    })

                    if (!updateResponse.ok) {
                        throw new Error(`Failed to update event definition: ${updateResponse.statusText}`)
                    }

                    const responseData = (await updateResponse.json()) as ApiEventDefinition

                    return { success: true, data: responseData }
                } catch (error) {
                    return { success: false, error: error as Error }
                }
            },
        }
    }

    experiments({ projectId }: { projectId: string }): Endpoint {
        return {
            get: async ({ experimentId }: { experimentId: number }): Promise<Result<Experiment>> => {
                return this.fetchJson<Experiment>(
                    `${this.baseUrl}/api/projects/${projectId}/experiments/${experimentId}/`
                )
            },

            getExposures: async ({
                experimentId,
                refresh = false,
            }: {
                experimentId: number
                refresh: boolean
            }): Promise<
                Result<{
                    exposures: ExperimentExposureQueryResponse
                }>
            > => {
                /**
                 * we have to get the experiment details first. There's no guarantee
                 * that the user has queried for the experiment details before.
                 */
                const experimentDetails = await this.experiments({ projectId }).get({
                    experimentId,
                })
                if (!experimentDetails.success) {
                    return experimentDetails
                }

                const experiment = experimentDetails.data

                /**
                 * Validate that the experiment has started
                 */
                if (!experiment.start_date) {
                    return {
                        success: false,
                        error: new Error(
                            `Experiment "${experiment.name}" has not started yet. Exposure data is only available for started experiments.`
                        ),
                    }
                }

                /**
                 * create the exposure query
                 */
                const exposureQuery: ExperimentExposureQuery = {
                    kind: 'ExperimentExposureQuery',
                    experiment_id: experimentId,
                    experiment_name: experiment.name,
                    exposure_criteria: experiment.exposure_criteria,
                    feature_flag: experiment.feature_flag ?? undefined,
                    start_date: experiment.start_date,
                    end_date: experiment.end_date,
                    holdout: experiment.holdout,
                }

                // Validate against existing ExperimentExposureQuerySchema
                const validated = ExperimentExposureQuerySchema.parse(exposureQuery)

                // The API expects a QueryRequest object with the query wrapped
                const queryRequest: any = {
                    query: validated,
                    ...(refresh ? { refresh: 'blocking' } : {}),
                }

                const result = await this.fetchJson<ExperimentExposureQueryResponse>(
                    `${this.baseUrl}/api/environments/${projectId}/query/`,
                    {
                        method: 'POST',
                        body: JSON.stringify(queryRequest),
                    }
                )

                if (!result.success) {
                    return result
                }

                return {
                    success: true,
                    data: {
                        exposures: result.data,
                    },
                }
            },

            getMetricResults: async ({
                experimentId,
                refresh = false,
            }: {
                experimentId: number
                refresh?: boolean
            }): Promise<
                Result<{
                    experiment: Experiment
                    primaryMetricEntries: ResolvedMetricEntry[]
                    secondaryMetricEntries: ResolvedMetricEntry[]
                    primaryMetricsResults: any[]
                    secondaryMetricsResults: any[]
                    exposures: ExperimentExposureQueryResponse
                }>
            > => {
                /**
                 * we have to get the experiment details first. There's no guarantee
                 * that the user has queried for the experiment details before.
                 */
                const experimentDetails = await this.experiments({ projectId }).get({
                    experimentId,
                })

                if (!experimentDetails.success) {
                    return experimentDetails
                }

                const experiment = experimentDetails.data

                /**
                 * Validate that the experiment has started
                 */
                if (!experiment.start_date) {
                    return {
                        success: false,
                        error: new Error(
                            `Experiment "${experiment.name}" has not started yet. Results are only available for started experiments.`
                        ),
                    }
                }

                /**
                 * let's get the experiment exposure details to get the full
                 * picture of the resutls.
                 */
                const experimentExposure = await this.experiments({ projectId }).getExposures({
                    experimentId,
                    refresh,
                })
                if (!experimentExposure.success) {
                    return experimentExposure
                }

                const { exposures } = experimentExposure.data

                // Build the per-position metric entries. Each entry knows whether the metric
                // was defined inline on the experiment or attached via a shared saved metric, so
                // the result row can be self-describing to MCP callers.
                const primaryMetricEntries = buildMetricEntries(experiment, 'primary')
                const secondaryMetricEntries = buildMetricEntries(experiment, 'secondary')

                // Execute queries for primary metrics
                const primaryResults = await Promise.all(
                    primaryMetricEntries.map(async ({ metric }) => {
                        try {
                            const queryBody = {
                                kind: 'ExperimentQuery',
                                metric,
                                experiment_id: experimentId,
                            }

                            const queryRequest = {
                                query: queryBody,
                                ...(refresh ? { refresh: 'blocking' } : {}),
                            }

                            const result = await this.fetchJson<unknown>(
                                `${this.baseUrl}/api/environments/${projectId}/query/`,
                                {
                                    method: 'POST',
                                    body: JSON.stringify(queryRequest),
                                }
                            )

                            return result.success ? result.data : null
                        } catch {
                            return null
                        }
                    })
                )

                // Execute queries for secondary metrics
                const secondaryResults = await Promise.all(
                    secondaryMetricEntries.map(async ({ metric }) => {
                        try {
                            const queryBody = {
                                kind: 'ExperimentQuery',
                                metric,
                                experiment_id: experimentId,
                            }

                            const queryRequest = {
                                query: queryBody,
                                ...(refresh ? { refresh: 'blocking' } : {}),
                            }

                            const result = await this.fetchJson<unknown>(
                                `${this.baseUrl}/api/environments/${projectId}/query/`,
                                {
                                    method: 'POST',
                                    body: JSON.stringify(queryRequest),
                                }
                            )

                            return result.success ? result.data : null
                        } catch {
                            return null
                        }
                    })
                )

                return {
                    success: true,
                    data: {
                        experiment,
                        primaryMetricEntries,
                        secondaryMetricEntries,
                        primaryMetricsResults: primaryResults,
                        secondaryMetricsResults: secondaryResults,
                        exposures,
                    },
                }
            },
        }
    }

    insights({ projectId }: { projectId: string }): Endpoint {
        return {
            get: async ({
                insightId,
                variables_override,
                filters_override,
            }: {
                insightId: string
                variables_override?: string
                filters_override?: string
            }): Promise<Result<Schemas.Insight>> => {
                const params = new URLSearchParams()
                if (variables_override) {
                    params.set('variables_override', variables_override)
                }
                if (filters_override) {
                    params.set('filters_override', filters_override)
                }

                // Check if insightId is a short_id (8 character alphanumeric string)
                // Note: This won't work when we start creating insight id's with 8 digits. (We're at 7 currently)
                if (isShortId(insightId)) {
                    // The list endpoint accepts ?short_id=... and runs the same
                    // InsightSerializer.to_representation, which applies
                    // variables_override / filters_override from query_params. So
                    // short_id resolution + override application happen in one hop.
                    params.set('short_id', insightId)
                    const url = `${this.baseUrl}/api/projects/${projectId}/insights/?${params}`

                    const result = await this.fetchJson<{ results: Schemas.Insight[] }>(url)

                    if (!result.success) {
                        return result
                    }

                    const insights = result.data.results
                    const insight = insights[0]

                    if (insights.length === 0 || !insight) {
                        return {
                            success: false,
                            error: new Error(`No insight found with short_id: ${insightId}`),
                        }
                    }

                    return { success: true, data: insight }
                }

                const queryString = params.toString() ? `?${params}` : ''
                return this.fetchJson<Schemas.Insight>(
                    `${this.baseUrl}/api/projects/${projectId}/insights/${insightId}/${queryString}`
                )
            },

            create: async ({ data }: { data: Record<string, any> }): Promise<Result<Schemas.Insight>> => {
                return this.fetchJson<Schemas.Insight>(`${this.baseUrl}/api/projects/${projectId}/insights/`, {
                    method: 'POST',
                    body: JSON.stringify({ ...data, saved: true }),
                })
            },

            update: async ({ insightId, data }: { insightId: number; data: any }): Promise<Result<Schemas.Insight>> => {
                return this.fetchJson<Schemas.Insight>(
                    `${this.baseUrl}/api/projects/${projectId}/insights/${insightId}/`,
                    {
                        method: 'PATCH',
                        body: JSON.stringify(data),
                    }
                )
            },

            delete: async ({
                insightId,
            }: {
                insightId: number
            }): Promise<Result<{ success: boolean; message: string }>> => {
                try {
                    const response = await this.fetch(
                        `${this.baseUrl}/api/projects/${projectId}/insights/${insightId}/`,
                        {
                            method: 'PATCH',
                            body: JSON.stringify({ deleted: true }),
                        }
                    )

                    if (!response.ok) {
                        throw new Error(`Failed to delete insight: ${response.statusText}`)
                    }

                    return {
                        success: true,
                        data: {
                            success: true,
                            message: 'Insight deleted successfully',
                        },
                    }
                } catch (error) {
                    return { success: false, error: error as Error }
                }
            },

            list: async ({ params }: { params?: Record<string, any> } = {}): Promise<
                Result<Array<Schemas.Insight>>
            > => {
                try {
                    const qs = new URLSearchParams()
                    if (params?.limit !== undefined) {
                        qs.set('limit', String(params.limit))
                    }
                    if (params?.offset !== undefined) {
                        qs.set('offset', String(params.offset))
                    }
                    if (params?.search) {
                        qs.set('search', params.search)
                    }
                    const qStr = qs.toString()
                    const result = await this.fetchJson<{ results: Schemas.Insight[] }>(
                        `${this.baseUrl}/api/projects/${projectId}/insights/${qStr ? `?${qStr}` : ''}`
                    )
                    if (!result.success) {
                        throw result.error
                    }
                    return { success: true, data: result.data.results }
                } catch (error) {
                    return { success: false, error: error as Error }
                }
            },

            query: async ({ query }: { query: Record<string, any> }): Promise<Result<QueryEndpointResponse>> => {
                const url = `${this.baseUrl}/api/environments/${projectId}/query/`

                return this.fetchJson<QueryEndpointResponse>(url, {
                    method: 'POST',
                    body: JSON.stringify({ query }),
                })
            },

            validate: async ({
                query,
                language,
                connectionId,
            }: {
                query: string
                language: 'hogQL' | 'hogQLExpr' | 'hog' | 'hogTemplate'
                connectionId?: string
            }): Promise<
                Result<{
                    isValid: boolean
                    query: string
                    errors: Array<{ message: string; start?: number | null; end?: number | null; fix?: string | null }>
                    warnings: Array<{
                        message: string
                        start?: number | null
                        end?: number | null
                        fix?: string | null
                    }>
                    notices: Array<{ message: string; start?: number | null; end?: number | null; fix?: string | null }>
                    table_names: string[]
                    ch_table_names?: string[] | null
                }>
            > => {
                const url = `${this.baseUrl}/api/environments/${projectId}/query/`
                const queryBody: Record<string, unknown> = { kind: 'HogQLMetadata', language, query }
                if (connectionId) {
                    queryBody.connectionId = connectionId
                }
                return this.fetchJson(url, {
                    method: 'POST',
                    body: JSON.stringify({ query: queryBody }),
                })
            },

            sqlInsight: async ({ query }: { query: string }): Promise<Result<any[]>> => {
                const requestBody = {
                    query: query,
                    insight_type: 'sql',
                }

                const result = await this.fetchJson<unknown[]>(
                    `${this.baseUrl}/api/environments/${projectId}/max_tools/create_and_query_insight/`,
                    {
                        method: 'POST',
                        body: JSON.stringify(requestBody),
                    }
                )

                if (result.success) {
                    // Ack messages don't add anything useful so let's just keep them out
                    const filteredData = result.data.filter(
                        (item: any) => !(item?.type === 'message' && item?.data?.type === 'ack')
                    )

                    return {
                        success: true,
                        data: filteredData,
                    }
                }

                return result
            },
        }
    }

    query({ projectId }: { projectId: string }): Endpoint {
        const queryUrl = `${this.baseUrl}/api/environments/${projectId}/query/`

        // Bridge assistant-facing schema shape to the query API shape.
        // The LLM emits `filterGroup` as a flat array; the API expects a nested PropertyGroupFilter.
        const normalizeQuery = (query: Record<string, unknown>): Record<string, unknown> => {
            const normalized = { ...query }
            if (Array.isArray(normalized.filterGroup)) {
                if (normalized.filterGroup.length > 0) {
                    normalized.filterGroup = {
                        type: 'AND',
                        values: [{ type: 'AND', values: normalized.filterGroup }],
                    }
                } else {
                    delete normalized.filterGroup
                }
            }
            return normalized
        }

        const runActorsQuery = async (
            query: Record<string, unknown>,
            select: readonly string[],
            orderBy: readonly string[] = []
        ): Promise<{
            query: Record<string, unknown>
            results: { columns: string[]; results: any[][] }
            hasMore: boolean
            offset: number
        }> => {
            const normalized = normalizeQuery(query)
            const includeRecordings = Boolean(normalized.includeRecordings)
            const finalSelect = includeRecordings ? [...select, 'matched_recordings'] : [...select]

            const wrappedQuery = {
                kind: 'ActorsQuery',
                source: normalized,
                select: finalSelect,
                orderBy: [...orderBy],
                limit: 100,
            }

            const response = await this.request<{
                results: any[][]
                hasMore?: boolean
                offset?: number
            }>({
                method: 'POST',
                path: `/api/environments/${projectId}/query/`,
                body: { query: wrappedQuery },
            })

            const baseUrl = this.getProjectBaseUrl(projectId)

            // `actor`/`person` → 3 columns, `matched_recordings` → recordings, everything else passes through.
            // Retention projects `person`, which carries the same actor shape as `actor`.
            const columns: string[] = []
            for (const field of finalSelect) {
                if (field === 'actor' || field === 'person') {
                    columns.push('distinct_id', 'email', 'name')
                } else if (field === 'matched_recordings') {
                    columns.push('recordings')
                } else {
                    columns.push(field)
                }
            }

            const results = (response.results ?? []).map((row) => {
                const cells: any[] = []
                for (let i = 0; i < finalSelect.length; i++) {
                    const field = finalSelect[i]
                    const cell = row[i]
                    if (field === 'actor' || field === 'person') {
                        const props = cell?.properties ?? {}
                        cells.push(cell?.distinct_ids?.[0] ?? null, props.email, props.name)
                    } else if (field === 'matched_recordings') {
                        const links = (cell ?? [])
                            .map((r: any) => r.session_id)
                            .filter(Boolean)
                            .map((sessionId: string) => `${baseUrl}/replay/${sessionId}`)
                        cells.push(links)
                    } else {
                        cells.push(cell)
                    }
                }
                return cells
            })

            return {
                query: wrappedQuery,
                results: { columns, results },
                hasMore: response.hasMore ?? false,
                offset: response.offset ?? 0,
            }
        }

        return {
            execute: async ({ queryBody }: { queryBody: any }): Promise<Result<{ results: any[] }>> => {
                return this.fetchJson<{ results: unknown[] }>(queryUrl, {
                    method: 'POST',
                    body: JSON.stringify({ query: queryBody }),
                })
            },

            runQuery: async ({
                query,
            }: {
                query: Record<string, unknown>
            }): Promise<{ results: unknown; formatted_results?: string }> => {
                return this.request<{ results: unknown; formatted_results?: string }>({
                    method: 'POST',
                    path: `/api/environments/${projectId}/query/`,
                    body: { query: normalizeQuery(query) },
                })
            },

            trendsActors: async ({ query }: { query: Record<string, unknown> }) =>
                runActorsQuery(query, ['actor', 'event_count'], ['event_count DESC', 'actor_id DESC']),

            lifecycleActors: async ({ query }: { query: Record<string, unknown> }) => runActorsQuery(query, ['actor']),

            pathsActors: async ({ query }: { query: Record<string, unknown> }) =>
                runActorsQuery(query, ['actor', 'event_count'], ['event_count DESC', 'actor_id DESC']),

            retentionActors: async ({ query }: { query: Record<string, unknown> }) => {
                // Columns are `person` + one per return interval: prefix = period (day/week/…), count =
                // custom-bracket count + 1, else totalIntervals. Mirrors the frontend retentionToActorsQuery.
                const filter = ((query.source as Record<string, unknown>)?.retentionFilter ?? {}) as Record<
                    string,
                    unknown
                >
                const period = typeof filter.period === 'string' ? filter.period.toLowerCase() : 'day'
                const brackets = filter.retentionCustomBrackets as number[] | undefined
                const count = brackets?.length ? brackets.length + 1 : (filter.totalIntervals as number) || 7
                // The schema codegen doesn't propagate `@minimum`/`@maximum` on integer fields (only array
                // `@maxItems`, which already bounds `retentionCustomBrackets`), so `totalIntervals` can't be
                // capped in the generated zod — enforce it here instead. The limit matches the app's
                // retention UI (period count capped at 31; totalIntervals adds the acquisition interval → 32).
                // TODO: drop this guard once the schema generator supports integer min/max.
                const MAX_RETENTION_INTERVALS = 32
                if (count > MAX_RETENTION_INTERVALS) {
                    throw new Error(
                        `Retention query requests ${count} intervals; the maximum is ${MAX_RETENTION_INTERVALS}.`
                    )
                }

                const select = ['person', ...Array.from({ length: count }, (_, i) => `${period}_${i}`)]
                return runActorsQuery(query, select, ['length(appearances) DESC', 'actor_id'])
            },

            // Stickiness drills into one bar (`day` = active-interval count). The runner projects only
            // `actor_id` with no `matching_events`, so there is no recordings column — same as lifecycle.
            stickinessActors: async ({ query }: { query: Record<string, unknown> }) => runActorsQuery(query, ['actor']),

            // Funnel actors project `actor` (+ `matched_recordings` when `includeRecordings`, handled
            // by runActorsQuery). The query carries the step/trends-dropoff selectors on the inner
            // FunnelsActorsQuery; ordering is backend-determined, so orderBy stays empty.
            funnelActors: async ({ query }: { query: Record<string, unknown> }) => runActorsQuery(query, ['actor']),
        }
    }

    users(): Endpoint {
        return {
            me: async (): Promise<Result<ApiUser>> => {
                const result = await this.fetchJson<ApiUser>(`${this.baseUrl}/api/users/@me/`)

                if (!result.success) {
                    return result
                }

                return {
                    success: true,
                    data: result.data,
                }
            },
        }
    }

    /**
     * Global search across PostHog entities
     */
    search({ projectId }: { projectId: string }): Endpoint {
        return {
            /**
             * Search for entities by query string
             * @param query - Search query (searches name/description fields)
             * @param entities - Array of entity types to search (defaults to all if not specified)
             */
            query: async ({
                query,
                entities,
            }: {
                query: string
                entities?: SearchableEntity[]
            }): Promise<Result<SearchResponse>> => {
                const searchParams = new URLSearchParams()

                if (query) {
                    searchParams.append('q', query)
                }

                if (entities && entities.length > 0) {
                    for (const entity of entities) {
                        searchParams.append('entities', entity)
                    }
                }

                const url = `${this.baseUrl}/api/projects/${projectId}/search/${searchParams.toString() ? `?${searchParams}` : ''}`

                return this.fetchJson<SearchResponse>(url)
            },
        }
    }

    async getGroupTypes(projectId: string): Promise<GroupType[]> {
        const result = await this.fetchJson<GroupType[]>(`${this.baseUrl}/api/projects/${projectId}/groups_types/`)
        if (!result.success) {
            throw new Error(result.error.message)
        }
        return result.data
    }
}
