// AUTO-GENERATED from products/marketing_analytics/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/marketing_analytics/api'
import { createQueryWrapper } from '@/tools/query-wrapper-factory'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const MarketingAnalyticsConversionGoalsSchema = () => z.object({})

const marketingAnalyticsConversionGoals = (): ToolBase<
    ReturnType<typeof MarketingAnalyticsConversionGoalsSchema>,
    Schemas.ConversionGoalsListResponse
> => ({
    name: 'marketing-analytics-conversion-goals',
    schema: MarketingAnalyticsConversionGoalsSchema(),
    handler: async (context: Context, _params: z.infer<ReturnType<typeof MarketingAnalyticsConversionGoalsSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ConversionGoalsListResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/marketing_analytics/conversion_goals/`,
        })
        return result
    },
})

const MarketingAnalyticsConversionRecommendationsSchema = () => z.object({})

const marketingAnalyticsConversionRecommendations = (): ToolBase<
    ReturnType<typeof MarketingAnalyticsConversionRecommendationsSchema>,
    Schemas.ConversionRecommendationState
> => ({
    name: 'marketing-analytics-conversion-recommendations',
    schema: MarketingAnalyticsConversionRecommendationsSchema(),
    handler: async (
        context: Context,
        _params: z.infer<ReturnType<typeof MarketingAnalyticsConversionRecommendationsSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ConversionRecommendationState>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/marketing_analytics/conversion_recommendations/`,
        })
        return result
    },
})

const MarketingAnalyticsCreateConversionGoalSchema = () => {
    const MarketingAnalyticsConversionGoalsCreateCreateBody =
        orvalSchemas.MarketingAnalyticsConversionGoalsCreateCreateBody()
    return MarketingAnalyticsConversionGoalsCreateCreateBody
}

const marketingAnalyticsCreateConversionGoal = (): ToolBase<
    ReturnType<typeof MarketingAnalyticsCreateConversionGoalSchema>,
    Schemas.ConversionGoalWriteResponse
> => ({
    name: 'marketing-analytics-create-conversion-goal',
    schema: MarketingAnalyticsCreateConversionGoalSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof MarketingAnalyticsCreateConversionGoalSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.goal !== undefined) {
            body['goal'] = params.goal
        }
        const result = await context.api.request<Schemas.ConversionGoalWriteResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/marketing_analytics/conversion_goals/create/`,
            body,
        })
        return result
    },
})

const MarketingAnalyticsDataSourcesSchema = () => {
    const MarketingAnalyticsDataSourcesRetrieveQueryParams =
        orvalSchemas.MarketingAnalyticsDataSourcesRetrieveQueryParams()
    return MarketingAnalyticsDataSourcesRetrieveQueryParams
}

const marketingAnalyticsDataSources = (): ToolBase<
    ReturnType<typeof MarketingAnalyticsDataSourcesSchema>,
    Schemas.DataSourceHealthResponse
> => ({
    name: 'marketing-analytics-data-sources',
    schema: MarketingAnalyticsDataSourcesSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof MarketingAnalyticsDataSourcesSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.DataSourceHealthResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/marketing_analytics/data_sources/`,
            query: {
                source_type: params.source_type,
            },
        })
        return result
    },
})

const MarketingAnalyticsDeleteConversionGoalSchema = () => {
    const MarketingAnalyticsConversionGoalsDeleteDestroyParams =
        orvalSchemas.MarketingAnalyticsConversionGoalsDeleteDestroyParams()
    return MarketingAnalyticsConversionGoalsDeleteDestroyParams.omit({ project_id: true })
}

const marketingAnalyticsDeleteConversionGoal = (): ToolBase<
    ReturnType<typeof MarketingAnalyticsDeleteConversionGoalSchema>,
    Schemas.ConversionGoalWriteResponse
> => ({
    name: 'marketing-analytics-delete-conversion-goal',
    schema: MarketingAnalyticsDeleteConversionGoalSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof MarketingAnalyticsDeleteConversionGoalSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ConversionGoalWriteResponse>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/marketing_analytics/conversion_goals/${encodeURIComponent(String(params.conversion_goal_id))}/delete/`,
        })
        return result
    },
})

const MarketingAnalyticsDiagnoseSchema = () => {
    const MarketingAnalyticsDiagnoseRetrieveQueryParams = orvalSchemas.MarketingAnalyticsDiagnoseRetrieveQueryParams()
    return MarketingAnalyticsDiagnoseRetrieveQueryParams
}

const marketingAnalyticsDiagnose = (): ToolBase<
    ReturnType<typeof MarketingAnalyticsDiagnoseSchema>,
    Schemas.MarketingDiagnosticResponse
> => ({
    name: 'marketing-analytics-diagnose',
    schema: MarketingAnalyticsDiagnoseSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof MarketingAnalyticsDiagnoseSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.MarketingDiagnosticResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/marketing_analytics/diagnose/`,
            query: {
                attribution_lookback_days: params.attribution_lookback_days,
                include_conversion_goals: params.include_conversion_goals,
                source_type: params.source_type,
            },
        })
        return result
    },
})

const MarketingAnalyticsExplainConversionGoalSchema = () => {
    const MarketingAnalyticsExplainConversionGoalRetrieveQueryParams =
        orvalSchemas.MarketingAnalyticsExplainConversionGoalRetrieveQueryParams()
    return MarketingAnalyticsExplainConversionGoalRetrieveQueryParams
}

const marketingAnalyticsExplainConversionGoal = (): ToolBase<
    ReturnType<typeof MarketingAnalyticsExplainConversionGoalSchema>,
    Schemas.GoalExplanation
> => ({
    name: 'marketing-analytics-explain-conversion-goal',
    schema: MarketingAnalyticsExplainConversionGoalSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof MarketingAnalyticsExplainConversionGoalSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.GoalExplanation>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/marketing_analytics/explain_conversion_goal/`,
            query: {
                conversion_goal_id: params.conversion_goal_id,
                date_from: params.date_from,
                date_to: params.date_to,
            },
        })
        return result
    },
})

const MarketingAnalyticsSetupPlanSchema = () => {
    const MarketingAnalyticsSetupPlanRetrieveQueryParams = orvalSchemas.MarketingAnalyticsSetupPlanRetrieveQueryParams()
    return MarketingAnalyticsSetupPlanRetrieveQueryParams
}

const marketingAnalyticsSetupPlan = (): ToolBase<
    ReturnType<typeof MarketingAnalyticsSetupPlanSchema>,
    Schemas.SetupPlanResponse
> => ({
    name: 'marketing-analytics-setup-plan',
    schema: MarketingAnalyticsSetupPlanSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof MarketingAnalyticsSetupPlanSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SetupPlanResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/marketing_analytics/setup_plan/`,
            query: {
                date_from: params.date_from,
                refresh: params.refresh,
            },
        })
        return result
    },
})

const MarketingAnalyticsStartConversionRecommendationsSchema = () => {
    const MarketingAnalyticsConversionRecommendationsStartCreateBody =
        orvalSchemas.MarketingAnalyticsConversionRecommendationsStartCreateBody()
    return MarketingAnalyticsConversionRecommendationsStartCreateBody
}

const marketingAnalyticsStartConversionRecommendations = (): ToolBase<
    ReturnType<typeof MarketingAnalyticsStartConversionRecommendationsSchema>,
    Schemas.ConversionRecommendationState
> => ({
    name: 'marketing-analytics-start-conversion-recommendations',
    schema: MarketingAnalyticsStartConversionRecommendationsSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof MarketingAnalyticsStartConversionRecommendationsSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.refresh !== undefined) {
            body['refresh'] = params.refresh
        }
        const result = await context.api.request<Schemas.ConversionRecommendationState>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/marketing_analytics/conversion_recommendations/start/`,
            body,
        })
        return result
    },
})

const MarketingAnalyticsSuggestConversionGoalsSchema = () => {
    const MarketingAnalyticsSuggestConversionGoalsRetrieveQueryParams =
        orvalSchemas.MarketingAnalyticsSuggestConversionGoalsRetrieveQueryParams()
    return MarketingAnalyticsSuggestConversionGoalsRetrieveQueryParams
}

const marketingAnalyticsSuggestConversionGoals = (): ToolBase<
    ReturnType<typeof MarketingAnalyticsSuggestConversionGoalsSchema>,
    Schemas.EventSuggestionsResponse
> => ({
    name: 'marketing-analytics-suggest-conversion-goals',
    schema: MarketingAnalyticsSuggestConversionGoalsSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof MarketingAnalyticsSuggestConversionGoalsSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.EventSuggestionsResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/marketing_analytics/suggest_conversion_goals/`,
            query: {
                min_count: params.min_count,
                top_n: params.top_n,
            },
        })
        return result
    },
})

const MarketingAnalyticsSuggestUtmMappingsSchema = () => {
    const MarketingAnalyticsSuggestUtmMappingsRetrieveQueryParams =
        orvalSchemas.MarketingAnalyticsSuggestUtmMappingsRetrieveQueryParams()
    return MarketingAnalyticsSuggestUtmMappingsRetrieveQueryParams
}

const marketingAnalyticsSuggestUtmMappings = (): ToolBase<
    ReturnType<typeof MarketingAnalyticsSuggestUtmMappingsSchema>,
    Schemas.UtmMappingSuggestionsResponse
> => ({
    name: 'marketing-analytics-suggest-utm-mappings',
    schema: MarketingAnalyticsSuggestUtmMappingsSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof MarketingAnalyticsSuggestUtmMappingsSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.UtmMappingSuggestionsResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/marketing_analytics/suggest_utm_mappings/`,
            query: {
                lookback_days: params.lookback_days,
                min_event_count: params.min_event_count,
            },
        })
        return result
    },
})

const MarketingAnalyticsUpdateConversionGoalSchema = () => {
    const MarketingAnalyticsConversionGoalsUpdatePartialUpdateBody =
        orvalSchemas.MarketingAnalyticsConversionGoalsUpdatePartialUpdateBody()
    const MarketingAnalyticsConversionGoalsUpdatePartialUpdateParams =
        orvalSchemas.MarketingAnalyticsConversionGoalsUpdatePartialUpdateParams()
    return MarketingAnalyticsConversionGoalsUpdatePartialUpdateParams.omit({ project_id: true }).extend(
        MarketingAnalyticsConversionGoalsUpdatePartialUpdateBody.shape
    )
}

const marketingAnalyticsUpdateConversionGoal = (): ToolBase<
    ReturnType<typeof MarketingAnalyticsUpdateConversionGoalSchema>,
    Schemas.ConversionGoalWriteResponse
> => ({
    name: 'marketing-analytics-update-conversion-goal',
    schema: MarketingAnalyticsUpdateConversionGoalSchema(),
    handler: async (
        context: Context,
        params: z.infer<ReturnType<typeof MarketingAnalyticsUpdateConversionGoalSchema>>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.goal !== undefined) {
            body['goal'] = params.goal
        }
        const result = await context.api.request<Schemas.ConversionGoalWriteResponse>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/marketing_analytics/conversion_goals/${encodeURIComponent(String(params.conversion_goal_id))}/update/`,
            body,
        })
        return result
    },
})

const MarketingAnalyticsUtmAuditSchema = () => {
    const MarketingAnalyticsUtmAuditRetrieveQueryParams = orvalSchemas.MarketingAnalyticsUtmAuditRetrieveQueryParams()
    return MarketingAnalyticsUtmAuditRetrieveQueryParams
}

const marketingAnalyticsUtmAudit = (): ToolBase<
    ReturnType<typeof MarketingAnalyticsUtmAuditSchema>,
    Schemas.UtmAuditResponse
> => ({
    name: 'marketing-analytics-utm-audit',
    schema: MarketingAnalyticsUtmAuditSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof MarketingAnalyticsUtmAuditSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.UtmAuditResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/marketing_analytics/utm_audit/`,
            query: {
                date_from: params.date_from,
                date_to: params.date_to,
            },
        })
        return result
    },
})

// --- Query wrapper schemas from schema.json ---

const DateRange = z.object({
    date_from: z
        .string()
        .nullable()
        .describe(
            'Start of the date range. Accepts ISO 8601 timestamps (e.g., 2024-01-15T00:00:00Z) or relative formats: -7d (7 days ago), -2w (2 weeks ago), -1m (1 month ago),\n-1h (1 hour ago), -1mStart (start of last month), -1yStart (start of last year).'
        )
        .optional(),
    date_to: z
        .string()
        .nullable()
        .describe(
            'End of the date range. Same format as date_from. Omit or null for "now". A calendar day without a time (2024-01-15) is inclusive: it rounds to the last moment of that day in the project timezone, unless explicitDate is set.'
        )
        .optional(),
    daysOfWeek: z
        .union([
            z.array(
                z.union([
                    z.literal(1),
                    z.literal(2),
                    z.literal(3),
                    z.literal(4),
                    z.literal(5),
                    z.literal(6),
                    z.literal(7),
                ])
            ),
            z.null(),
        ])
        .describe(
            'Restrict the query to events occurring on these ISO days of week (1=Monday to 7=Sunday), evaluated in the project timezone. Omit or empty for all days. Only applied by insight queries.'
        )
        .optional(),
    excludeIncompletePeriods: z.coerce
        .boolean()
        .nullable()
        .describe(
            'Exclude the current, still-collecting period by clipping date_to to the end of the last complete interval (evaluated in the project timezone). No-op when the range contains no complete interval. Only applied by insight queries.'
        )
        .default(false)
        .optional(),
    explicitDate: z.coerce
        .boolean()
        .nullable()
        .describe(
            'Whether the date_from and date_to should be used verbatim. Disables rounding to the start and end of period.'
        )
        .default(false)
        .optional(),
})

const QueryLogTags = z.object({
    name: z.string().describe('Name of the query, preferably unique. For example web_analytics_vitals').optional(),
    presetId: z
        .string()
        .describe('Short id of the saved Web analytics filter preset this query was run under, if any.')
        .optional(),
    productKey: z
        .string()
        .describe(
            "Product responsible for this query. Use string, there's no need to churn the Schema when we add a new product *"
        )
        .optional(),
    scene: z
        .string()
        .describe(
            "Scene where this query is shown in the UI. Use string, there's no need to churn the Schema when we add a new Scene *"
        )
        .optional(),
})

const MarketingAnalyticsRecommendationsQuery = z.object({
    dateRange: DateRange.optional(),
    kind: z.literal('MarketingAnalyticsRecommendationsQuery').default('MarketingAnalyticsRecommendationsQuery'),
    tags: QueryLogTags.optional(),
    version: z.coerce.number().describe('version of the node, used for schema migrations').optional(),
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'marketing-analytics-conversion-goals': marketingAnalyticsConversionGoals,
    'marketing-analytics-conversion-recommendations': marketingAnalyticsConversionRecommendations,
    'marketing-analytics-create-conversion-goal': marketingAnalyticsCreateConversionGoal,
    'marketing-analytics-data-sources': marketingAnalyticsDataSources,
    'marketing-analytics-delete-conversion-goal': marketingAnalyticsDeleteConversionGoal,
    'marketing-analytics-diagnose': marketingAnalyticsDiagnose,
    'marketing-analytics-explain-conversion-goal': marketingAnalyticsExplainConversionGoal,
    'marketing-analytics-setup-plan': marketingAnalyticsSetupPlan,
    'marketing-analytics-start-conversion-recommendations': marketingAnalyticsStartConversionRecommendations,
    'marketing-analytics-suggest-conversion-goals': marketingAnalyticsSuggestConversionGoals,
    'marketing-analytics-suggest-utm-mappings': marketingAnalyticsSuggestUtmMappings,
    'marketing-analytics-update-conversion-goal': marketingAnalyticsUpdateConversionGoal,
    'marketing-analytics-utm-audit': marketingAnalyticsUtmAudit,
    'query-marketing-recommendations': createQueryWrapper({
        name: 'query-marketing-recommendations',
        schema: MarketingAnalyticsRecommendationsQuery,
        kind: 'MarketingAnalyticsRecommendationsQuery',
        outputFormat: 'json',
        urlPrefix: '/marketing',
    }),
}
