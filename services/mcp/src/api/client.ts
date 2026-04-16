import { z } from 'zod'

import { getUserAgent } from '@/lib/constants'
import { ErrorCode } from '@/lib/errors'
import { getSearchParamsFromRecord } from '@/lib/utils.js'
import type {
    ApiEventDefinition,
    ApiOAuthIntrospection,
    ApiPropertyDefinition,
    ApiRedactedPersonalApiKey,
    ApiUser,
} from '@/schema/api'
import type { Experiment, ExperimentExposureQuery, ExperimentExposureQueryResponse } from '@/schema/experiments'
import { ExperimentExposureQuerySchema } from '@/schema/experiments'
import { isShortId } from '@/tools/insights/utils'

import type { Schemas } from './generated.js'
import { globalRateLimiter } from './rate-limiter.js'

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

export interface ApiConfig {
    apiToken: string
    baseUrl: string
    clientUserAgent?: string | undefined
    mcpClientName?: string | undefined
    mcpClientVersion?: string | undefined
    mcpProtocolVersion?: string | undefined
    oauthClientName?: string | undefined
}

type Endpoint = Record<string, any>

export class ApiClient {
    public config: ApiConfig
    public baseUrl: string

    constructor(config: ApiConfig) {
        this.config = config
        this.baseUrl = config.baseUrl
    }

    getProjectBaseUrl(projectId: string): string {
        if (projectId === '@current') {
            return this.baseUrl
        }

        return `${this.baseUrl}/project/${projectId}`
    }

    private async fetch(url: string, options?: RequestInit): Promise<Response> {
        // TODO: should we move rate limiting from `fetchJson` to here?
        const defaultHeaders: HeadersInit = {
            Authorization: `Bearer ${this.config.apiToken}`,
            'User-Agent': getUserAgent(this.config.clientUserAgent),
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
            ...(this.config.oauthClientName ? { 'x-posthog-mcp-oauth-client-name': this.config.oauthClientName } : {}),
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
     * Generic HTTP request with auth, rate limiting, and retries.
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
                throw new Error(
                    `Request failed:\nURL: ${opts.method} ${url}\nStatus Code: ${response.status} (${response.statusText})\nError Message: ${errorText}`
                )
            }
            return (await response.text()) as T
        }

        const result = await this.fetchJson<T>(url, fetchOptions)

        if (!result.success) {
            throw new Error(result.error.message)
        }
        return result.data as T
    }

    private async fetchJson<T>(url: string, options?: RequestInit): Promise<Result<T>> {
        const maxRetries = 3
        const baseBackoffMs = 2000
        const method = options?.method ?? 'GET'

        for (let attempt = 0; attempt <= maxRetries; attempt++) {
            try {
                // Apply rate limiting before making the request
                await globalRateLimiter.throttle()

                const response = await this.fetch(url, options)

                // Handle rate limiting with exponential backoff
                if (response.status === 429) {
                    if (attempt < maxRetries) {
                        // Check for Retry-After header
                        const retryAfter = response.headers.get('Retry-After')
                        const delayMs = retryAfter
                            ? parseInt(retryAfter, 10) * 1000
                            : baseBackoffMs * Math.pow(2, attempt)

                        console.warn(
                            `[API] Rate limited (429) on ${method} ${url}. Retrying in ${delayMs}ms (attempt ${attempt + 1}/${maxRetries})`
                        )
                        await new Promise((resolve) => setTimeout(resolve, delayMs))
                        continue
                    }
                    // Max retries exceeded
                    const errorText = await response.text()
                    console.error(`[API] Rate limit exceeded after ${maxRetries} retries on ${method} ${url}`)
                    return {
                        success: false,
                        error: new Error(
                            `Rate limit exceeded after ${maxRetries} retries:\nURL: ${method} ${url}\nStatus Code: ${response.status}\nError Message: ${errorText}`
                        ),
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

                    if (errorData.type === 'validation_error') {
                        const detail = errorData.detail || errorData.code || 'unknown'
                        const attr = errorData.attr ? ` (field: ${errorData.attr})` : ''
                        console.error(`[API] Validation error on ${method} ${url}: ${detail}${attr}`)
                        throw new Error(`Validation error: ${detail}${attr}`)
                    }

                    console.error(`[API] Request failed on ${method} ${url}: ${response.status} ${response.statusText}`)
                    throw new Error(
                        `Request failed:\nURL: ${method} ${url}\nStatus Code: ${response.status} (${response.statusText})\nError Message: ${errorText}`
                    )
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
                // Only retry on rate limit errors, not other errors
                if (error instanceof Error && error.message.includes('Rate limit')) {
                    continue
                }
                return { success: false, error: error as Error }
            }
        }

        // This should never be reached, but TypeScript needs it
        return {
            success: false,
            error: new Error('Unexpected error in retry logic'),
        }
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

                // Prepare metrics queries
                const sharedPrimaryMetrics = (experiment.saved_metrics || [])
                    .filter(({ metadata }: any) => metadata.type === 'primary')
                    .map(({ query }: any) => query)
                const allPrimaryMetrics = [...(experiment.metrics || []), ...sharedPrimaryMetrics]

                const sharedSecondaryMetrics = (experiment.saved_metrics || [])
                    .filter(({ metadata }: any) => metadata.type === 'secondary')
                    .map(({ query }: any) => query)
                const allSecondaryMetrics = [...(experiment.metrics_secondary || []), ...sharedSecondaryMetrics]

                // Execute queries for primary metrics
                const primaryResults = await Promise.all(
                    allPrimaryMetrics.map(async (metric) => {
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
                    allSecondaryMetrics.map(async (metric) => {
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
            get: async ({ insightId }: { insightId: string }): Promise<Result<Schemas.Insight>> => {
                // Check if insightId is a short_id (8 character alphanumeric string)
                // Note: This won't work when we start creating insight id's with 8 digits. (We're at 7 currently)
                if (isShortId(insightId)) {
                    const searchParams = new URLSearchParams({ short_id: insightId })
                    const url = `${this.baseUrl}/api/projects/${projectId}/insights/?${searchParams}`

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

                return this.fetchJson<Schemas.Insight>(
                    `${this.baseUrl}/api/projects/${projectId}/insights/${insightId}/`
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

            query: async ({
                query,
            }: {
                query: Record<string, any>
            }): Promise<Result<{ results: unknown; columns?: unknown; formatted_results?: string }>> => {
                const url = `${this.baseUrl}/api/environments/${projectId}/query/`

                return this.fetchJson<{ results: unknown; columns?: unknown; formatted_results?: string }>(url, {
                    method: 'POST',
                    body: JSON.stringify({ query }),
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
        return {
            execute: async ({ queryBody }: { queryBody: any }): Promise<Result<{ results: any[] }>> => {
                return this.fetchJson<{ results: unknown[] }>(`${this.baseUrl}/api/environments/${projectId}/query/`, {
                    method: 'POST',
                    body: JSON.stringify({ query: queryBody }),
                })
            },
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
