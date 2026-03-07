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
import {
    type CreateDashboardInput,
    CreateDashboardInputSchema,
    type ListDashboardsData,
    ListDashboardsSchema,
} from '@/schema/dashboards'
import type {
    Experiment,
    ExperimentExposureQuery,
    ExperimentExposureQueryResponse,
    ExperimentUpdateApiPayload,
} from '@/schema/experiments'
import {
    ExperimentCreatePayloadSchema,
    ExperimentExposureQuerySchema,
    ExperimentUpdateApiPayloadSchema,
} from '@/schema/experiments'
import {
    type CreateFeatureFlagInput,
    CreateFeatureFlagInputSchema,
    type UpdateFeatureFlagInput,
    UpdateFeatureFlagInputSchema,
} from '@/schema/flags'
import { type CreateInsightInput, CreateInsightInputSchema, type ListInsightsData } from '@/schema/insights'
import type { ExperimentCreateSchema } from '@/schema/tool-inputs'
import { isShortId } from '@/tools/insights/utils'

import type { CreateActionInput, ListActionsInput, UpdateActionInput } from '../schema/actions.js'
import type {
    LogAttribute,
    LogAttributeValue,
    LogsListAttributeValuesInput,
    LogsListAttributesInput,
    LogsQueryInput,
    LogsQueryResponse,
} from '../schema/logs.js'
import type {
    CreateSurveyInput,
    GetSurveySpecificStatsInput,
    GetSurveyStatsInput,
    ListSurveysInput,
    SurveyResponseStatsOutput,
    UpdateSurveyInput,
} from '../schema/surveys.js'
import {
    CreateSurveyInputSchema,
    GetSurveySpecificStatsInputSchema,
    GetSurveyStatsInputSchema,
    ListSurveysInputSchema,
    UpdateSurveyInputSchema,
} from '../schema/surveys.js'
import { buildApiFetcher } from './fetcher.js'
import { type Schemas, createApiClient } from './generated.js'
import { globalRateLimiter } from './rate-limiter.js'

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
}

type Endpoint = Record<string, any>

export class ApiClient {
    public config: ApiConfig
    public baseUrl: string
    // NOTE: The OpenAPI schema for the generated client is not always accurate
    public generated: ReturnType<typeof createApiClient>

    constructor(config: ApiConfig) {
        this.config = config
        this.baseUrl = config.baseUrl

        this.generated = createApiClient(buildApiFetcher(this.config), this.baseUrl)
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
        query?: Record<string, string | number | undefined>
    }): Promise<T> {
        const searchParams = new URLSearchParams()
        if (opts.query) {
            for (const [k, v] of Object.entries(opts.query)) {
                if (v !== undefined) {
                    searchParams.append(k, String(v))
                }
            }
        }
        const qs = searchParams.toString()
        const url = `${this.baseUrl}${opts.path}${qs ? `?${qs}` : ''}`

        const result = await this.fetchJson<T>(url, {
            method: opts.method,
            ...(opts.body ? { body: JSON.stringify(opts.body) } : {}),
        })

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

                    if (errorData.type === 'validation_error' && errorData.code) {
                        console.error(`[API] Validation error on ${method} ${url}: ${errorData.code}`)
                        throw new Error(`Validation error: ${errorData.code}`)
                    }

                    console.error(`[API] Request failed on ${method} ${url}: ${response.status} ${response.statusText}`)
                    throw new Error(
                        `Request failed:\nURL: ${method} ${url}\nStatus Code: ${response.status} (${response.statusText})\nError Message: ${errorText}`
                    )
                }

                const rawData = await response.json()
                return { success: true, data: rawData as T }
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
            list: async ({ params }: { params?: { limit?: number; offset?: number } } = {}): Promise<
                Result<Experiment[]>
            > => {
                try {
                    const limit = params?.limit ?? 50
                    const offset = params?.offset ?? 0

                    const response = await this.generated.get('/api/projects/{project_id}/experiments/', {
                        path: { project_id: projectId },
                        query: { limit, offset },
                    })

                    return { success: true, data: response.results as Experiment[] }
                } catch (error) {
                    return { success: false, error: error as Error }
                }
            },

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

            create: async (experimentData: z.infer<typeof ExperimentCreateSchema>): Promise<Result<Experiment>> => {
                // Transform agent input to API payload
                const createBody = ExperimentCreatePayloadSchema.parse(experimentData)

                return this.fetchJson<Experiment>(`${this.baseUrl}/api/projects/${projectId}/experiments/`, {
                    method: 'POST',
                    body: JSON.stringify(createBody),
                })
            },

            update: async ({
                experimentId,
                updateData,
            }: {
                experimentId: number
                updateData: ExperimentUpdateApiPayload
            }): Promise<Result<Experiment>> => {
                try {
                    const updateBody = ExperimentUpdateApiPayloadSchema.parse(updateData)

                    return this.fetchJson<Experiment>(
                        `${this.baseUrl}/api/projects/${projectId}/experiments/${experimentId}/`,
                        {
                            method: 'PATCH',
                            body: JSON.stringify(updateBody),
                        }
                    )
                } catch (error) {
                    return { success: false, error: new Error(`Update failed: ${error}`) }
                }
            },

            delete: async ({
                experimentId,
            }: {
                experimentId: number
            }): Promise<Result<{ success: boolean; message: string }>> => {
                try {
                    const deleteResponse = await this.fetch(
                        `${this.baseUrl}/api/projects/${projectId}/experiments/${experimentId}/`,
                        {
                            method: 'PATCH',
                            body: JSON.stringify({ deleted: true }),
                        }
                    )

                    if (deleteResponse.ok) {
                        return {
                            success: true,
                            data: { success: true, message: 'Experiment deleted successfully' },
                        }
                    }

                    return {
                        success: false,
                        error: new Error(`Delete failed with status: ${deleteResponse.status}`),
                    }
                } catch (error) {
                    return { success: false, error: new Error(`Delete failed: ${error}`) }
                }
            },
        }
    }

    featureFlags({ projectId }: { projectId: string }): Endpoint {
        return {
            list: async ({ params }: { params?: { limit?: number; offset?: number } } = {}): Promise<
                Result<Array<Pick<Schemas.FeatureFlag, 'id' | 'key' | 'name' | 'active' | 'updated_at'>>>
            > => {
                try {
                    const limit = params?.limit ?? 50
                    const offset = params?.offset ?? 0

                    const response = await this.generated.get('/api/projects/{project_id}/feature_flags/', {
                        path: { project_id: projectId },
                        query: { limit, offset },
                    })

                    return {
                        success: true,
                        data: response.results.map((f) => ({
                            id: f.id,
                            key: f.key,
                            name: f.name ?? '',
                            active: f.active ?? false,
                            updated_at: f.updated_at ?? null,
                        })),
                    }
                } catch (error) {
                    return { success: false, error: error as Error }
                }
            },

            get: async ({ flagId }: { flagId: string | number }): Promise<Result<Schemas.FeatureFlag>> => {
                return this.fetchJson<Schemas.FeatureFlag>(
                    `${this.baseUrl}/api/projects/${projectId}/feature_flags/${flagId}/`
                )
            },

            findByKey: async ({ key }: { key: string }): Promise<Result<Schemas.FeatureFlag | undefined>> => {
                const listResult = await this.featureFlags({ projectId }).list()

                if (!listResult.success) {
                    return { success: false, error: listResult.error }
                }

                const found = listResult.data.find((f: { key: string }) => f.key === key)

                if (!found) {
                    return { success: true, data: undefined }
                }

                const flagResult = await this.featureFlags({ projectId }).get({ flagId: found.id })

                if (!flagResult.success) {
                    return { success: false, error: flagResult.error }
                }

                return { success: true, data: flagResult.data }
            },

            create: async ({ data }: { data: CreateFeatureFlagInput }): Promise<Result<Schemas.FeatureFlag>> => {
                const validatedInput = CreateFeatureFlagInputSchema.parse(data)

                const body = {
                    key: validatedInput.key,
                    name: validatedInput.name,
                    description: validatedInput.description,
                    active: validatedInput.active,
                    filters: validatedInput.filters,
                }

                return this.fetchJson<Schemas.FeatureFlag>(`${this.baseUrl}/api/projects/${projectId}/feature_flags/`, {
                    method: 'POST',
                    body: JSON.stringify(body),
                })
            },

            update: async ({
                key,
                data,
            }: {
                key: string
                data: UpdateFeatureFlagInput
            }): Promise<Result<Schemas.FeatureFlag>> => {
                const validatedInput = UpdateFeatureFlagInputSchema.parse(data)
                const findResult = await this.featureFlags({ projectId }).findByKey({ key })

                if (!findResult.success) {
                    return findResult
                }

                if (!findResult.data) {
                    return {
                        success: false,
                        error: new Error(`Feature flag not found: ${key}`),
                    }
                }

                const body = {
                    key: key,
                    name: validatedInput.name,
                    description: validatedInput.description,
                    active: validatedInput.active,
                    filters: validatedInput.filters,
                }

                return this.fetchJson<Schemas.FeatureFlag>(
                    `${this.baseUrl}/api/projects/${projectId}/feature_flags/${findResult.data.id}/`,
                    {
                        method: 'PATCH',
                        body: JSON.stringify(body),
                    }
                )
            },

            delete: async ({ flagId }: { flagId: number }): Promise<Result<{ success: boolean; message: string }>> => {
                try {
                    const response = await this.fetch(
                        `${this.baseUrl}/api/projects/${projectId}/feature_flags/${flagId}/`,
                        {
                            method: 'PATCH',
                            body: JSON.stringify({ deleted: true }),
                        }
                    )

                    if (!response.ok) {
                        throw new Error(`Failed to delete feature flag: ${response.statusText}`)
                    }

                    return {
                        success: true,
                        data: {
                            success: true,
                            message: 'Feature flag deleted successfully',
                        },
                    }
                } catch (error) {
                    return { success: false, error: error as Error }
                }
            },
        }
    }

    insights({ projectId }: { projectId: string }): Endpoint {
        return {
            list: async ({ params }: { params?: ListInsightsData } = {}): Promise<Result<Array<Schemas.Insight>>> => {
                try {
                    const response = await this.generated.get('/api/projects/{project_id}/insights/', {
                        path: { project_id: projectId },
                        query: params
                            ? {
                                  limit: params.limit,
                                  offset: params.offset,
                                  //@ts-expect-error search is not implemented as a query parameter
                                  search: params.search,
                              }
                            : {},
                    })

                    return { success: true, data: response.results }
                } catch (error) {
                    return { success: false, error: error as Error }
                }
            },

            create: async ({ data }: { data: CreateInsightInput }): Promise<Result<Schemas.Insight>> => {
                const validatedInput = CreateInsightInputSchema.parse(data)

                return this.fetchJson<Schemas.Insight>(`${this.baseUrl}/api/projects/${projectId}/insights/`, {
                    method: 'POST',
                    body: JSON.stringify(validatedInput),
                })
            },

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

                return this.fetchJson<Schemas.Insight>(`${this.baseUrl}/api/projects/${projectId}/insights/${insightId}/`)
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

            query: async ({ query }: { query: Record<string, any> }): Promise<Result<any>> => {
                const url = `${this.baseUrl}/api/environments/${projectId}/query/`

                return this.fetchJson<{ results: unknown; columns: unknown }>(url, {
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

    dashboards({ projectId }: { projectId: string }): Endpoint {
        return {
            list: async ({ params }: { params?: ListDashboardsData } = {}): Promise<
                Result<Schemas.Dashboard[]>
            > => {
                const validatedParams = params ? ListDashboardsSchema.parse(params) : undefined
                const searchParams = new URLSearchParams()

                if (validatedParams?.limit) {
                    searchParams.append('limit', String(validatedParams.limit))
                }
                if (validatedParams?.offset) {
                    searchParams.append('offset', String(validatedParams.offset))
                }
                if (validatedParams?.search) {
                    searchParams.append('search', validatedParams.search)
                }

                const url = `${this.baseUrl}/api/projects/${projectId}/dashboards/${searchParams.toString() ? `?${searchParams}` : ''}`

                const result = await this.fetchJson<{
                    results: Schemas.Dashboard[]
                }>(url)

                if (result.success) {
                    return { success: true, data: result.data.results }
                }

                return result
            },

            get: async ({ dashboardId }: { dashboardId: number }): Promise<Result<Schemas.Dashboard>> => {
                return this.fetchJson<Schemas.Dashboard>(
                    `${this.baseUrl}/api/projects/${projectId}/dashboards/${dashboardId}/`
                )
            },

            create: async ({ data }: { data: CreateDashboardInput }): Promise<Result<Schemas.Dashboard>> => {
                const validatedInput = CreateDashboardInputSchema.parse(data)

                return this.fetchJson<Schemas.Dashboard>(
                    `${this.baseUrl}/api/projects/${projectId}/dashboards/`,
                    {
                        method: 'POST',
                        body: JSON.stringify(validatedInput),
                    }
                )
            },

            update: async ({
                dashboardId,
                data,
            }: {
                dashboardId: number
                data: any
            }): Promise<Result<Schemas.Dashboard>> => {
                return this.fetchJson<Schemas.Dashboard>(
                    `${this.baseUrl}/api/projects/${projectId}/dashboards/${dashboardId}/`,
                    {
                        method: 'PATCH',
                        body: JSON.stringify(data),
                    }
                )
            },

            delete: async ({
                dashboardId,
            }: {
                dashboardId: number
            }): Promise<Result<{ success: boolean; message: string }>> => {
                try {
                    const response = await this.fetch(
                        `${this.baseUrl}/api/projects/${projectId}/dashboards/${dashboardId}/`,
                        {
                            method: 'PATCH',
                            body: JSON.stringify({ deleted: true }),
                        }
                    )

                    if (!response.ok) {
                        throw new Error(`Failed to delete dashboard: ${response.statusText}`)
                    }

                    return {
                        success: true,
                        data: {
                            success: true,
                            message: 'Dashboard deleted successfully',
                        },
                    }
                } catch (error) {
                    return { success: false, error: error as Error }
                }
            },

            addInsight: async ({
                data,
            }: {
                data: { insightId: number; dashboardId: number }
            }): Promise<Result<any>> => {
                return this.fetchJson<unknown>(
                    `${this.baseUrl}/api/projects/${projectId}/insights/${data.insightId}/`,
                    {
                        method: 'PATCH',
                        body: JSON.stringify({ dashboards: [data.dashboardId] }),
                    }
                )
            },

            reorderTiles: async ({
                dashboardId,
                tileOrder,
            }: {
                dashboardId: number
                tileOrder: number[]
            }): Promise<Result<{ success: boolean; message: string; tiles: Array<{ id: number; order: number }> }>> => {
                // Calculate new layout positions based on the specified order
                // Use 2-column grid for larger layouts (sm and above), single column for xs
                const tileWidth = 6 // Half of 12-column grid
                const tileHeight = 5

                const tiles = tileOrder.map((tileId, index) => {
                    const row = Math.floor(index / 2)
                    const col = index % 2

                    return {
                        id: tileId,
                        layouts: {
                            // 2-column layout for sm and larger screens
                            sm: { x: col * tileWidth, y: row * tileHeight, w: tileWidth, h: tileHeight },
                            // Single column for xs (mobile)
                            xs: { x: 0, y: index * tileHeight, w: 6, h: tileHeight },
                        },
                    }
                })

                const result = await this.fetchJson<{
                    id: number
                    tiles: Array<{ id: number; layouts?: Record<string, unknown> | null }>
                }>(`${this.baseUrl}/api/projects/${projectId}/dashboards/${dashboardId}/`, {
                    method: 'PATCH',
                    body: JSON.stringify({ tiles }),
                })

                if (!result.success) {
                    return result
                }

                // Return a summary of the updated order
                const updatedTiles = result.data.tiles
                    .filter((tile) => tileOrder.includes(tile.id))
                    .map((tile) => ({
                        id: tile.id,
                        order: tileOrder.indexOf(tile.id),
                    }))
                    .sort((a, b) => a.order - b.order)

                return {
                    success: true,
                    data: {
                        success: true,
                        message: `Successfully reordered ${updatedTiles.length} tiles on dashboard ${dashboardId}`,
                        tiles: updatedTiles,
                    },
                }
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

    surveys({ projectId }: { projectId: string }): Endpoint {
        return {
            list: async ({ params }: { params?: ListSurveysInput } = {}): Promise<
                Result<Array<Schemas.Survey>>
            > => {
                const validatedParams = params ? ListSurveysInputSchema.parse(params) : undefined
                const searchParams = new URLSearchParams()

                if (validatedParams?.limit) {
                    searchParams.append('limit', String(validatedParams.limit))
                }
                if (validatedParams?.offset) {
                    searchParams.append('offset', String(validatedParams.offset))
                }
                if (validatedParams?.search) {
                    searchParams.append('search', validatedParams.search)
                }

                const url = `${this.baseUrl}/api/projects/${projectId}/surveys/${searchParams.toString() ? `?${searchParams}` : ''}`

                const result = await this.fetchJson<{ results: Schemas.Survey[] }>(url)

                if (result.success) {
                    return { success: true, data: result.data.results }
                }

                return result
            },

            get: async ({ surveyId }: { surveyId: string }): Promise<Result<Schemas.Survey>> => {
                return this.fetchJson<Schemas.Survey>(`${this.baseUrl}/api/projects/${projectId}/surveys/${surveyId}/`)
            },

            create: async ({ data }: { data: CreateSurveyInput }): Promise<Result<Schemas.Survey>> => {
                const validatedInput = CreateSurveyInputSchema.parse(data)

                return this.fetchJson<Schemas.Survey>(`${this.baseUrl}/api/projects/${projectId}/surveys/`, {
                    method: 'POST',
                    body: JSON.stringify(validatedInput),
                })
            },

            update: async ({
                surveyId,
                data,
            }: {
                surveyId: string
                data: UpdateSurveyInput
            }): Promise<Result<Schemas.Survey>> => {
                const validatedInput = UpdateSurveyInputSchema.parse(data)

                return this.fetchJson<Schemas.Survey>(`${this.baseUrl}/api/projects/${projectId}/surveys/${surveyId}/`, {
                    method: 'PATCH',
                    body: JSON.stringify(validatedInput),
                })
            },

            delete: async ({
                surveyId,
                softDelete = true,
            }: {
                surveyId: string
                softDelete?: boolean
            }): Promise<Result<{ success: boolean; message: string }>> => {
                try {
                    const fetchOptions: RequestInit = {
                        method: softDelete ? 'PATCH' : 'DELETE',
                    }

                    if (softDelete) {
                        fetchOptions.body = JSON.stringify({ archived: true })
                    }

                    const response = await this.fetch(
                        `${this.baseUrl}/api/projects/${projectId}/surveys/${surveyId}/`,
                        fetchOptions
                    )

                    if (!response.ok) {
                        throw new Error(`Failed to ${softDelete ? 'archive' : 'delete'} survey: ${response.statusText}`)
                    }

                    return {
                        success: true,
                        data: {
                            success: true,
                            message: `Survey ${softDelete ? 'archived' : 'deleted'} successfully`,
                        },
                    }
                } catch (error) {
                    return { success: false, error: error as Error }
                }
            },

            globalStats: async ({ params }: { params?: GetSurveyStatsInput } = {}): Promise<
                Result<SurveyResponseStatsOutput>
            > => {
                const validatedParams = GetSurveyStatsInputSchema.parse(params)

                const searchParams = getSearchParamsFromRecord(validatedParams)

                const url = `${this.baseUrl}/api/projects/${projectId}/surveys/stats/${searchParams.toString() ? `?${searchParams}` : ''}`

                return this.fetchJson<SurveyResponseStatsOutput>(url)
            },

            stats: async (params: GetSurveySpecificStatsInput): Promise<Result<SurveyResponseStatsOutput>> => {
                const validatedParams = GetSurveySpecificStatsInputSchema.parse(params)

                const searchParams = getSearchParamsFromRecord(validatedParams)

                const url = `${this.baseUrl}/api/projects/${projectId}/surveys/${validatedParams.survey_id}/stats/${searchParams.toString() ? `?${searchParams}` : ''}`

                return this.fetchJson<SurveyResponseStatsOutput>(url)
            },
        }
    }

    logs({ projectId }: { projectId: string }): Endpoint {
        return {
            query: async ({ params }: { params: LogsQueryInput }): Promise<Result<LogsQueryResponse>> => {
                const queryBody = {
                    query: {
                        dateRange: {
                            date_from: params.dateFrom,
                            date_to: params.dateTo,
                        },
                        severityLevels: params.severityLevels ?? [],
                        serviceNames: params.serviceNames ?? [],
                        searchTerm: params.searchTerm ?? null,
                        orderBy: params.orderBy ?? 'latest',
                        limit: params.limit ?? 100,
                        after: params.after ?? null,
                        filterGroup: { type: 'AND', values: [] },
                    },
                }

                return this.fetchJson<LogsQueryResponse>(`${this.baseUrl}/api/projects/${projectId}/logs/query/`, {
                    method: 'POST',
                    body: JSON.stringify(queryBody),
                })
            },

            attributes: async ({
                params,
            }: {
                params?: LogsListAttributesInput
            } = {}): Promise<Result<{ results: LogAttribute[]; count: number }>> => {
                const searchParams = getSearchParamsFromRecord({
                    search: params?.search,
                    attribute_type: params?.attributeType ?? 'log',
                    limit: params?.limit ?? 100,
                    offset: params?.offset ?? 0,
                })

                const url = `${this.baseUrl}/api/projects/${projectId}/logs/attributes/?${searchParams}`

                return this.fetchJson<{ results: LogAttribute[]; count: number }>(url)
            },

            values: async ({
                params,
            }: {
                params: LogsListAttributeValuesInput
            }): Promise<Result<LogAttributeValue[]>> => {
                const searchParams = getSearchParamsFromRecord({
                    key: params.key,
                    attribute_type: params.attributeType ?? 'log',
                    value: params.search,
                })

                const url = `${this.baseUrl}/api/projects/${projectId}/logs/values/?${searchParams}`

                const result = await this.fetchJson<{ results: LogAttributeValue[]; refreshing: boolean }>(url)
                if (!result.success) {
                    return result
                }
                return { success: true, data: result.data.results }
            },
        }
    }

    actions({ projectId }: { projectId: string }): Endpoint {
        return {
            /**
             * List all actions in the project
             */
            list: async ({ params }: { params?: ListActionsInput } = {}): Promise<Result<Array<Schemas.Action>>> => {
                const searchParams = new URLSearchParams()

                if (params?.limit) {
                    searchParams.append('limit', String(params.limit))
                }
                if (params?.offset) {
                    searchParams.append('offset', String(params.offset))
                }

                const url = `${this.baseUrl}/api/projects/${projectId}/actions/${searchParams.toString() ? `?${searchParams}` : ''}`

                const result = await this.fetchJson<{ results: Schemas.Action[] }>(url)

                if (result.success) {
                    return { success: true, data: result.data.results }
                }

                return result
            },

            /**
             * Get a single action by ID
             */
            get: async ({ actionId }: { actionId: number }): Promise<Result<Schemas.Action>> => {
                return this.fetchJson<Schemas.Action>(`${this.baseUrl}/api/projects/${projectId}/actions/${actionId}/`)
            },

            /**
             * Create a new action
             */
            create: async ({ data }: { data: CreateActionInput }): Promise<Result<Schemas.Action>> => {
                const body = {
                    name: data.name,
                    description: data.description,
                    steps: data.steps,
                    tags: data.tags,
                    post_to_slack: data.post_to_slack ?? false,
                    slack_message_format: data.slack_message_format,
                }

                return this.fetchJson<Schemas.Action>(`${this.baseUrl}/api/projects/${projectId}/actions/`, {
                    method: 'POST',
                    body: JSON.stringify(body),
                })
            },

            /**
             * Update an existing action
             */
            update: async ({
                actionId,
                data,
            }: {
                actionId: number
                data: UpdateActionInput
            }): Promise<Result<Schemas.Action>> => {
                return this.fetchJson<Schemas.Action>(
                    `${this.baseUrl}/api/projects/${projectId}/actions/${actionId}/`,
                    {
                        method: 'PATCH',
                        body: JSON.stringify(data),
                    }
                )
            },

            /**
             * Soft delete an action (sets deleted=true)
             */
            delete: async ({
                actionId,
            }: {
                actionId: number
            }): Promise<Result<{ success: boolean; message: string }>> => {
                try {
                    // First fetch the action to get its name (required by backend validation)
                    const getResponse = await this.fetch(
                        `${this.baseUrl}/api/projects/${projectId}/actions/${actionId}/`,
                        {
                            method: 'GET',
                        }
                    )

                    if (!getResponse.ok) {
                        throw new Error(`Failed to fetch action: ${getResponse.statusText}`)
                    }

                    const action = (await getResponse.json()) as { name: string }

                    const response = await this.fetch(
                        `${this.baseUrl}/api/projects/${projectId}/actions/${actionId}/`,
                        {
                            method: 'PATCH',
                            body: JSON.stringify({ name: action.name, deleted: true }),
                        }
                    )

                    if (!response.ok) {
                        throw new Error(`Failed to delete action: ${response.statusText}`)
                    }

                    return {
                        success: true,
                        data: {
                            success: true,
                            message: 'Action deleted successfully',
                        },
                    }
                } catch (error) {
                    return { success: false, error: error as Error }
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
}
