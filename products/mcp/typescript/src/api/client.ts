import { ErrorCode } from '@/lib/errors'
import { withPagination } from '@/lib/utils/api'
import { getSearchParamsFromRecord } from '@/lib/utils/helper-functions'
import {
    type ApiEventDefinition,
    ApiEventDefinitionSchema,
    type ApiPropertyDefinition,
    ApiPropertyDefinitionSchema,
    type ApiRedactedPersonalApiKey,
    ApiRedactedPersonalApiKeySchema,
    type ApiUser,
    ApiUserSchema,
} from '@/schema/api'
import {
    type CreateDashboardInput,
    CreateDashboardInputSchema,
    type ListDashboardsData,
    ListDashboardsSchema,
    type SimpleDashboard,
    SimpleDashboardSchema,
} from '@/schema/dashboards'
import type {
    Experiment,
    ExperimentExposureQuery,
    ExperimentExposureQueryResponse,
    ExperimentUpdateApiPayload,
} from '@/schema/experiments'
import {
    ExperimentCreatePayloadSchema,
    ExperimentExposureQueryResponseSchema,
    ExperimentExposureQuerySchema,
    ExperimentSchema,
    ExperimentUpdateApiPayloadSchema,
} from '@/schema/experiments'
import {
    type CreateFeatureFlagInput,
    CreateFeatureFlagInputSchema,
    type FeatureFlag,
    FeatureFlagSchema,
    type UpdateFeatureFlagInput,
    UpdateFeatureFlagInputSchema,
} from '@/schema/flags'
import {
    type CreateInsightInput,
    CreateInsightInputSchema,
    type ListInsightsData,
    type SimpleInsight,
    SimpleInsightSchema,
} from '@/schema/insights'
import { type Organization, OrganizationSchema } from '@/schema/orgs'
import { type Project, ProjectSchema } from '@/schema/projects'
import type { ExperimentCreateSchema } from '@/schema/tool-inputs'
import { isShortId } from '@/tools/insights/utils'
import { z } from 'zod'
import type {
    CreateSurveyInput,
    GetSurveySpecificStatsInput,
    GetSurveyStatsInput,
    ListSurveysInput,
    SurveyListItemOutput,
    SurveyOutput,
    SurveyResponseStatsOutput,
    UpdateSurveyInput,
} from '../schema/surveys.js'
import {
    CreateSurveyInputSchema,
    GetSurveySpecificStatsInputSchema,
    GetSurveyStatsInputSchema,
    ListSurveysInputSchema,
    SurveyListItemOutputSchema,
    SurveyOutputSchema,
    SurveyResponseStatsOutputSchema,
    UpdateSurveyInputSchema,
} from '../schema/surveys.js'
import { buildApiFetcher } from './fetcher'
import { type Schemas, createApiClient } from './generated'

export type Result<T, E = Error> = { success: true; data: T } | { success: false; error: E }

export interface ApiConfig {
    apiToken: string
    baseUrl: string
}
export class ApiClient {
    private config: ApiConfig
    private baseUrl: string
    // NOTE: The OpenAPI schema for the generated client is not always accurate
    public generated: ReturnType<typeof createApiClient>

    constructor(config: ApiConfig) {
        this.config = config
        this.baseUrl = config.baseUrl

        this.generated = createApiClient(buildApiFetcher(this.config), this.baseUrl)
    }
    private buildHeaders() {
        return {
            Authorization: `Bearer ${this.config.apiToken}`,
            'Content-Type': 'application/json',
        }
    }

    getProjectBaseUrl(projectId: string) {
        if (projectId === '@current') {
            return this.baseUrl
        }

        return `${this.baseUrl}/project/${projectId}`
    }

    private async fetchWithSchema<T>(
        url: string,
        schema: z.ZodType<T>,
        options?: RequestInit
    ): Promise<Result<T>> {
        try {
            const response = await fetch(url, {
                ...options,
                headers: {
                    ...this.buildHeaders(),
                    ...options?.headers,
                },
            })

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
                    throw new Error(`Validation error: ${errorData.code}`)
                }

                throw new Error(
                    `Request failed:\nStatus Code: ${response.status} (${response.statusText})\nError Message: ${errorText}`
                )
            }

            const rawData = await response.json()
            const parseResult = schema.safeParse(rawData)

            if (!parseResult.success) {
                throw new Error(`Response validation failed: ${parseResult.error.message}`)
            }

            return { success: true, data: parseResult.data }
        } catch (error) {
            return { success: false, error: error as Error }
        }
    }

    organizations() {
        return {
            list: async (): Promise<Result<Organization[]>> => {
                const responseSchema = z.object({
                    results: z.array(OrganizationSchema),
                })

                const result = await this.fetchWithSchema(
                    `${this.baseUrl}/api/organizations/`,
                    responseSchema
                )

                if (result.success) {
                    return { success: true, data: result.data.results }
                }
                return result
            },

            get: async ({ orgId }: { orgId: string }): Promise<Result<Organization>> => {
                return this.fetchWithSchema(
                    `${this.baseUrl}/api/organizations/${orgId}/`,
                    OrganizationSchema
                )
            },

            projects: ({ orgId }: { orgId: string }) => {
                return {
                    list: async (): Promise<Result<Project[]>> => {
                        const responseSchema = z.object({
                            results: z.array(ProjectSchema),
                        })

                        const result = await this.fetchWithSchema(
                            `${this.baseUrl}/api/organizations/${orgId}/projects/`,
                            responseSchema
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

    apiKeys() {
        return {
            current: async (): Promise<Result<ApiRedactedPersonalApiKey>> => {
                return this.fetchWithSchema(
                    `${this.baseUrl}/api/personal_api_keys/@current`,
                    ApiRedactedPersonalApiKeySchema
                )
            },
        }
    }

    projects() {
        return {
            get: async ({ projectId }: { projectId: string }): Promise<Result<Project>> => {
                return this.fetchWithSchema(
                    `${this.baseUrl}/api/projects/${projectId}/`,
                    ProjectSchema
                )
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
                        limit: limit ?? 100,
                        offset: offset ?? 0,
                        type: type ?? 'event',
                        exclude_hidden: true,
                    }

                    const searchParams = getSearchParamsFromRecord(params)

                    const url = `${this.baseUrl}/api/projects/${projectId}/property_definitions/${
                        searchParams.toString() ? `?${searchParams}` : ''
                    }`

                    const propertyDefinitions = await withPagination(
                        url,
                        this.config.apiToken,
                        ApiPropertyDefinitionSchema
                    )

                    const propertyDefinitionsWithoutHidden = propertyDefinitions.filter(
                        (def) => !def.hidden
                    )

                    return { success: true, data: propertyDefinitionsWithoutHidden }
                } catch (error) {
                    return { success: false, error: error as Error }
                }
            },

            eventDefinitions: async ({
                projectId,
                search,
            }: {
                projectId: string
                search?: string | undefined
            }): Promise<Result<ApiEventDefinition[]>> => {
                try {
                    const searchParams = getSearchParamsFromRecord({ search })

                    const requestUrl = `${this.baseUrl}/api/projects/${projectId}/event_definitions/${searchParams.toString() ? `?${searchParams}` : ''}`

                    const eventDefinitions = await withPagination(
                        requestUrl,
                        this.config.apiToken,
                        ApiEventDefinitionSchema
                    )

                    return { success: true, data: eventDefinitions }
                } catch (error) {
                    return { success: false, error: error as Error }
                }
            },
        }
    }

    experiments({ projectId }: { projectId: string }) {
        return {
            list: async (): Promise<Result<Experiment[]>> => {
                try {
                    const response = await withPagination(
                        `${this.baseUrl}/api/projects/${projectId}/experiments/`,
                        this.config.apiToken,
                        ExperimentSchema
                    )

                    return { success: true, data: response }
                } catch (error) {
                    return { success: false, error: error as Error }
                }
            },

            get: async ({
                experimentId,
            }: {
                experimentId: number
            }): Promise<Result<Experiment>> => {
                return this.fetchWithSchema(
                    `${this.baseUrl}/api/projects/${projectId}/experiments/${experimentId}/`,
                    ExperimentSchema
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
                    feature_flag: experiment.feature_flag as FeatureFlag,
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

                const result = await this.fetchWithSchema(
                    `${this.baseUrl}/api/environments/${projectId}/query/`,
                    ExperimentExposureQueryResponseSchema,
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
                    .filter(({ metadata }) => metadata.type === 'primary')
                    .map(({ query }) => query)
                const allPrimaryMetrics = [...(experiment.metrics || []), ...sharedPrimaryMetrics]

                const sharedSecondaryMetrics = (experiment.saved_metrics || [])
                    .filter(({ metadata }) => metadata.type === 'secondary')
                    .map(({ query }) => query)
                const allSecondaryMetrics = [
                    ...(experiment.metrics_secondary || []),
                    ...sharedSecondaryMetrics,
                ]

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

                            const result = await this.fetchWithSchema(
                                `${this.baseUrl}/api/environments/${projectId}/query/`,
                                z.any(),
                                {
                                    method: 'POST',
                                    body: JSON.stringify(queryRequest),
                                }
                            )

                            return result.success ? result.data : null
                        } catch (error) {
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

                            const result = await this.fetchWithSchema(
                                `${this.baseUrl}/api/environments/${projectId}/query/`,
                                z.any(),
                                {
                                    method: 'POST',
                                    body: JSON.stringify(queryRequest),
                                }
                            )

                            return result.success ? result.data : null
                        } catch (error) {
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

            create: async (
                experimentData: z.infer<typeof ExperimentCreateSchema>
            ): Promise<Result<Experiment>> => {
                // Transform agent input to API payload
                const createBody = ExperimentCreatePayloadSchema.parse(experimentData)

                return this.fetchWithSchema(
                    `${this.baseUrl}/api/projects/${projectId}/experiments/`,
                    ExperimentSchema,
                    {
                        method: 'POST',
                        body: JSON.stringify(createBody),
                    }
                )
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

                    return this.fetchWithSchema(
                        `${this.baseUrl}/api/projects/${projectId}/experiments/${experimentId}/`,
                        ExperimentSchema,
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
                    const deleteResponse = await fetch(
                        `${this.baseUrl}/api/projects/${projectId}/experiments/${experimentId}/`,
                        {
                            method: 'PATCH',
                            headers: this.buildHeaders(),
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

    featureFlags({ projectId }: { projectId: string }) {
        return {
            list: async (): Promise<
                Result<Array<{ id: number; key: string; name: string; active: boolean }>>
            > => {
                try {
                    const schema = FeatureFlagSchema.pick({
                        id: true,
                        key: true,
                        name: true,
                        active: true,
                    })

                    const response = await withPagination(
                        `${this.baseUrl}/api/projects/${projectId}/feature_flags/`,
                        this.config.apiToken,
                        schema
                    )

                    return {
                        success: true,
                        data: response as Array<{
                            id: number
                            key: string
                            name: string
                            active: boolean
                        }>,
                    }
                } catch (error) {
                    return { success: false, error: error as Error }
                }
            },

            get: async ({
                flagId,
            }: {
                flagId: string | number
            }): Promise<
                Result<{
                    id: number
                    key: string
                    name: string
                    active: boolean
                    description?: string | null | undefined
                }>
            > => {
                return this.fetchWithSchema(
                    `${this.baseUrl}/api/projects/${projectId}/feature_flags/${flagId}/`,
                    FeatureFlagSchema
                )
            },

            findByKey: async ({
                key,
            }: {
                key: string
            }): Promise<
                Result<{ id: number; key: string; name: string; active: boolean } | undefined>
            > => {
                const listResult = await this.featureFlags({ projectId }).list()

                if (!listResult.success) {
                    return { success: false, error: listResult.error }
                }

                const found = listResult.data.find((f) => f.key === key)

                if (!found) {
                    return { success: true, data: undefined }
                }

                const flagResult = await this.featureFlags({ projectId }).get({ flagId: found.id })

                if (!flagResult.success) {
                    return { success: false, error: flagResult.error }
                }

                return { success: true, data: flagResult.data }
            },

            create: async ({
                data,
            }: {
                data: CreateFeatureFlagInput
            }): Promise<Result<{ id: number; key: string; name: string; active: boolean }>> => {
                const validatedInput = CreateFeatureFlagInputSchema.parse(data)

                const body = {
                    key: validatedInput.key,
                    name: validatedInput.name,
                    description: validatedInput.description,
                    active: validatedInput.active,
                    filters: validatedInput.filters,
                }

                return this.fetchWithSchema(
                    `${this.baseUrl}/api/projects/${projectId}/feature_flags/`,
                    FeatureFlagSchema,
                    {
                        method: 'POST',
                        body: JSON.stringify(body),
                    }
                )
            },

            update: async ({
                key,
                data,
            }: {
                key: string
                data: UpdateFeatureFlagInput
            }): Promise<Result<{ id: number; key: string; name: string; active: boolean }>> => {
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

                return this.fetchWithSchema(
                    `${this.baseUrl}/api/projects/${projectId}/feature_flags/${findResult.data.id}/`,
                    FeatureFlagSchema,
                    {
                        method: 'PATCH',
                        body: JSON.stringify(body),
                    }
                )
            },

            delete: async ({
                flagId,
            }: {
                flagId: number
            }): Promise<Result<{ success: boolean; message: string }>> => {
                try {
                    const response = await fetch(
                        `${this.baseUrl}/api/projects/${projectId}/feature_flags/${flagId}/`,
                        {
                            method: 'PATCH',
                            headers: this.buildHeaders(),
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

    insights({ projectId }: { projectId: string }) {
        return {
            list: async ({ params }: { params?: ListInsightsData } = {}): Promise<
                Result<Array<Schemas.Insight>>
            > => {
                try {
                    const response = await this.generated.get(
                        '/api/projects/{project_id}/insights/',
                        {
                            path: { project_id: projectId },
                            query: params
                                ? {
                                      limit: params.limit,
                                      offset: params.offset,
                                      //@ts-expect-error search is not implemented as a query parameter
                                      search: params.search,
                                  }
                                : {},
                        }
                    )

                    return { success: true, data: response.results }
                } catch (error) {
                    return { success: false, error: error as Error }
                }
            },

            create: async ({
                data,
            }: {
                data: CreateInsightInput
            }): Promise<Result<SimpleInsight>> => {
                const validatedInput = CreateInsightInputSchema.parse(data)

                return this.fetchWithSchema(
                    `${this.baseUrl}/api/projects/${projectId}/insights/`,
                    SimpleInsightSchema,
                    {
                        method: 'POST',
                        body: JSON.stringify(validatedInput),
                    }
                )
            },

            get: async ({ insightId }: { insightId: string }): Promise<Result<SimpleInsight>> => {
                // Check if insightId is a short_id (8 character alphanumeric string)
                // Note: This won't work when we start creating insight id's with 8 digits. (We're at 7 currently)
                if (isShortId(insightId)) {
                    const searchParams = new URLSearchParams({ short_id: insightId })
                    const url = `${this.baseUrl}/api/projects/${projectId}/insights/?${searchParams}`

                    const responseSchema = z.object({
                        results: z.array(SimpleInsightSchema),
                    })

                    const result = await this.fetchWithSchema(url, responseSchema)

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

                return this.fetchWithSchema(
                    `${this.baseUrl}/api/projects/${projectId}/insights/${insightId}/`,
                    SimpleInsightSchema
                )
            },

            update: async ({
                insightId,
                data,
            }: {
                insightId: number
                data: any
            }): Promise<Result<SimpleInsight>> => {
                return this.fetchWithSchema(
                    `${this.baseUrl}/api/projects/${projectId}/insights/${insightId}/`,
                    SimpleInsightSchema,
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
                    const response = await fetch(
                        `${this.baseUrl}/api/projects/${projectId}/insights/${insightId}/`,
                        {
                            method: 'PATCH',
                            headers: this.buildHeaders(),
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

                const queryResponseSchema = z.object({
                    results: z.any(),
                })

                return this.fetchWithSchema(url, queryResponseSchema, {
                    method: 'POST',
                    body: JSON.stringify({ query }),
                })
            },

            sqlInsight: async ({ query }: { query: string }): Promise<Result<any[]>> => {
                const requestBody = {
                    query: query,
                    insight_type: 'sql',
                }

                const sqlResponseSchema = z.array(z.any())

                const result = await this.fetchWithSchema(
                    `${this.baseUrl}/api/environments/${projectId}/max_tools/create_and_query_insight/`,
                    sqlResponseSchema,
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

    dashboards({ projectId }: { projectId: string }) {
        return {
            list: async ({ params }: { params?: ListDashboardsData } = {}): Promise<
                Result<
                    Array<{
                        id: number
                        name: string
                        description?: string | null | undefined
                    }>
                >
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

                const simpleDashboardSchema = z.object({
                    id: z.number(),
                    name: z.string(),
                    description: z.string().nullish(),
                })

                const responseSchema = z.object({
                    results: z.array(simpleDashboardSchema),
                })

                const result = await this.fetchWithSchema(url, responseSchema)

                if (result.success) {
                    return { success: true, data: result.data.results }
                }

                return result
            },

            get: async ({
                dashboardId,
            }: {
                dashboardId: number
            }): Promise<Result<SimpleDashboard>> => {
                return this.fetchWithSchema(
                    `${this.baseUrl}/api/projects/${projectId}/dashboards/${dashboardId}/`,
                    SimpleDashboardSchema
                )
            },

            create: async ({
                data,
            }: {
                data: CreateDashboardInput
            }): Promise<Result<{ id: number; name: string }>> => {
                const validatedInput = CreateDashboardInputSchema.parse(data)

                const createResponseSchema = z.object({
                    id: z.number(),
                    name: z.string(),
                })

                return this.fetchWithSchema(
                    `${this.baseUrl}/api/projects/${projectId}/dashboards/`,
                    createResponseSchema,
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
            }): Promise<Result<{ id: number; name: string }>> => {
                const updateResponseSchema = z.object({
                    id: z.number(),
                    name: z.string(),
                })

                return this.fetchWithSchema(
                    `${this.baseUrl}/api/projects/${projectId}/dashboards/${dashboardId}/`,
                    updateResponseSchema,
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
                    const response = await fetch(
                        `${this.baseUrl}/api/projects/${projectId}/dashboards/${dashboardId}/`,
                        {
                            method: 'PATCH',
                            headers: this.buildHeaders(),
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
                return this.fetchWithSchema(
                    `${this.baseUrl}/api/projects/${projectId}/insights/${data.insightId}/`,
                    z.any(),
                    {
                        method: 'PATCH',
                        body: JSON.stringify({ dashboards: [data.dashboardId] }),
                    }
                )
            },
        }
    }

    query({ projectId }: { projectId: string }) {
        return {
            execute: async ({
                queryBody,
            }: {
                queryBody: any
            }): Promise<Result<{ results: any[] }>> => {
                const responseSchema = z.object({
                    results: z.array(z.any()),
                })

                return this.fetchWithSchema(
                    `${this.baseUrl}/api/environments/${projectId}/query/`,
                    responseSchema,
                    {
                        method: 'POST',
                        body: JSON.stringify({ query: queryBody }),
                    }
                )
            },
        }
    }

    users() {
        return {
            me: async (): Promise<Result<ApiUser>> => {
                const result = await this.fetchWithSchema(
                    `${this.baseUrl}/api/users/@me/`,
                    ApiUserSchema
                )

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

    surveys({ projectId }: { projectId: string }) {
        return {
            list: async ({ params }: { params?: ListSurveysInput } = {}): Promise<
                Result<Array<SurveyListItemOutput>>
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

                const responseSchema = z.object({
                    results: z.array(SurveyListItemOutputSchema),
                })

                const result = await this.fetchWithSchema(url, responseSchema)

                if (result.success) {
                    return { success: true, data: result.data.results }
                }

                return result
            },

            get: async ({ surveyId }: { surveyId: string }): Promise<Result<SurveyOutput>> => {
                return this.fetchWithSchema(
                    `${this.baseUrl}/api/projects/${projectId}/surveys/${surveyId}/`,
                    SurveyOutputSchema
                )
            },

            create: async ({
                data,
            }: {
                data: CreateSurveyInput
            }): Promise<Result<SurveyOutput>> => {
                const validatedInput = CreateSurveyInputSchema.parse(data)

                return this.fetchWithSchema(
                    `${this.baseUrl}/api/projects/${projectId}/surveys/`,
                    SurveyOutputSchema,
                    {
                        method: 'POST',
                        body: JSON.stringify(validatedInput),
                    }
                )
            },

            update: async ({
                surveyId,
                data,
            }: {
                surveyId: string
                data: UpdateSurveyInput
            }): Promise<Result<SurveyOutput>> => {
                const validatedInput = UpdateSurveyInputSchema.parse(data)

                return this.fetchWithSchema(
                    `${this.baseUrl}/api/projects/${projectId}/surveys/${surveyId}/`,
                    SurveyOutputSchema,
                    {
                        method: 'PATCH',
                        body: JSON.stringify(validatedInput),
                    }
                )
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
                        headers: this.buildHeaders(),
                    }

                    if (softDelete) {
                        fetchOptions.body = JSON.stringify({ archived: true })
                    }

                    const response = await fetch(
                        `${this.baseUrl}/api/projects/${projectId}/surveys/${surveyId}/`,
                        fetchOptions
                    )

                    if (!response.ok) {
                        throw new Error(
                            `Failed to ${softDelete ? 'archive' : 'delete'} survey: ${response.statusText}`
                        )
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

                return this.fetchWithSchema(url, SurveyResponseStatsOutputSchema)
            },

            stats: async (
                params: GetSurveySpecificStatsInput
            ): Promise<Result<SurveyResponseStatsOutput>> => {
                const validatedParams = GetSurveySpecificStatsInputSchema.parse(params)

                const searchParams = getSearchParamsFromRecord(validatedParams)

                const url = `${this.baseUrl}/api/projects/${projectId}/surveys/${validatedParams.survey_id}/stats/${searchParams.toString() ? `?${searchParams}` : ''}`

                return this.fetchWithSchema(url, SurveyResponseStatsOutputSchema)
            },
        }
    }
}
