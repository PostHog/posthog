// AUTO-GENERATED from products/marketing_analytics/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/marketing_analytics/api'
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

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'marketing-analytics-conversion-goals': marketingAnalyticsConversionGoals,
    'marketing-analytics-create-conversion-goal': marketingAnalyticsCreateConversionGoal,
    'marketing-analytics-data-sources': marketingAnalyticsDataSources,
    'marketing-analytics-delete-conversion-goal': marketingAnalyticsDeleteConversionGoal,
    'marketing-analytics-diagnose': marketingAnalyticsDiagnose,
    'marketing-analytics-explain-conversion-goal': marketingAnalyticsExplainConversionGoal,
    'marketing-analytics-suggest-conversion-goals': marketingAnalyticsSuggestConversionGoals,
    'marketing-analytics-suggest-utm-mappings': marketingAnalyticsSuggestUtmMappings,
    'marketing-analytics-update-conversion-goal': marketingAnalyticsUpdateConversionGoal,
    'marketing-analytics-utm-audit': marketingAnalyticsUtmAudit,
}
