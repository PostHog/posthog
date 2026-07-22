// AUTO-GENERATED from products/marketing_analytics/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    MarketingAnalyticsConversionGoalsCreateCreateBody,
    MarketingAnalyticsConversionGoalsDeleteDestroyParams,
    MarketingAnalyticsConversionGoalsUpdatePartialUpdateBody,
    MarketingAnalyticsConversionGoalsUpdatePartialUpdateParams,
    MarketingAnalyticsDataSourcesRetrieveQueryParams,
    MarketingAnalyticsDiagnoseRetrieveQueryParams,
    MarketingAnalyticsExplainConversionGoalRetrieveQueryParams,
    MarketingAnalyticsSuggestConversionGoalsRetrieveQueryParams,
    MarketingAnalyticsSuggestUtmMappingsRetrieveQueryParams,
    MarketingAnalyticsUtmAuditRetrieveQueryParams,
} from '@/generated/marketing_analytics/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const MarketingAnalyticsConversionGoalsSchema = z.object({})

const marketingAnalyticsConversionGoals = (): ToolBase<
    typeof MarketingAnalyticsConversionGoalsSchema,
    Schemas.ConversionGoalsListResponse
> => ({
    name: 'marketing-analytics-conversion-goals',
    schema: MarketingAnalyticsConversionGoalsSchema,
    // eslint-disable-next-line no-unused-vars
    handler: async (context: Context, params: z.infer<typeof MarketingAnalyticsConversionGoalsSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ConversionGoalsListResponse>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/marketing_analytics/conversion_goals/`,
        })
        return result
    },
})

const MarketingAnalyticsCreateConversionGoalSchema = MarketingAnalyticsConversionGoalsCreateCreateBody

const marketingAnalyticsCreateConversionGoal = (): ToolBase<
    typeof MarketingAnalyticsCreateConversionGoalSchema,
    Schemas.ConversionGoalWriteResponse
> => ({
    name: 'marketing-analytics-create-conversion-goal',
    schema: MarketingAnalyticsCreateConversionGoalSchema,
    handler: async (context: Context, params: z.infer<typeof MarketingAnalyticsCreateConversionGoalSchema>) => {
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

const MarketingAnalyticsDataSourcesSchema = MarketingAnalyticsDataSourcesRetrieveQueryParams

const marketingAnalyticsDataSources = (): ToolBase<
    typeof MarketingAnalyticsDataSourcesSchema,
    Schemas.DataSourceHealthResponse
> => ({
    name: 'marketing-analytics-data-sources',
    schema: MarketingAnalyticsDataSourcesSchema,
    handler: async (context: Context, params: z.infer<typeof MarketingAnalyticsDataSourcesSchema>) => {
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

const MarketingAnalyticsDeleteConversionGoalSchema = MarketingAnalyticsConversionGoalsDeleteDestroyParams.omit({
    project_id: true,
})

const marketingAnalyticsDeleteConversionGoal = (): ToolBase<
    typeof MarketingAnalyticsDeleteConversionGoalSchema,
    Schemas.ConversionGoalWriteResponse
> => ({
    name: 'marketing-analytics-delete-conversion-goal',
    schema: MarketingAnalyticsDeleteConversionGoalSchema,
    handler: async (context: Context, params: z.infer<typeof MarketingAnalyticsDeleteConversionGoalSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ConversionGoalWriteResponse>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/marketing_analytics/conversion_goals/${encodeURIComponent(String(params.conversion_goal_id))}/delete/`,
        })
        return result
    },
})

const MarketingAnalyticsDiagnoseSchema = MarketingAnalyticsDiagnoseRetrieveQueryParams

const marketingAnalyticsDiagnose = (): ToolBase<
    typeof MarketingAnalyticsDiagnoseSchema,
    Schemas.MarketingDiagnosticResponse
> => ({
    name: 'marketing-analytics-diagnose',
    schema: MarketingAnalyticsDiagnoseSchema,
    handler: async (context: Context, params: z.infer<typeof MarketingAnalyticsDiagnoseSchema>) => {
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

const MarketingAnalyticsExplainConversionGoalSchema = MarketingAnalyticsExplainConversionGoalRetrieveQueryParams

const marketingAnalyticsExplainConversionGoal = (): ToolBase<
    typeof MarketingAnalyticsExplainConversionGoalSchema,
    Schemas.GoalExplanation
> => ({
    name: 'marketing-analytics-explain-conversion-goal',
    schema: MarketingAnalyticsExplainConversionGoalSchema,
    handler: async (context: Context, params: z.infer<typeof MarketingAnalyticsExplainConversionGoalSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.GoalExplanation>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/marketing_analytics/explain_conversion_goal/`,
            query: {
                date_from: params.date_from,
                date_to: params.date_to,
                goal_id: params.goal_id,
            },
        })
        return result
    },
})

const MarketingAnalyticsSuggestConversionGoalsSchema = MarketingAnalyticsSuggestConversionGoalsRetrieveQueryParams

const marketingAnalyticsSuggestConversionGoals = (): ToolBase<
    typeof MarketingAnalyticsSuggestConversionGoalsSchema,
    Schemas.EventSuggestionsResponse
> => ({
    name: 'marketing-analytics-suggest-conversion-goals',
    schema: MarketingAnalyticsSuggestConversionGoalsSchema,
    handler: async (context: Context, params: z.infer<typeof MarketingAnalyticsSuggestConversionGoalsSchema>) => {
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

const MarketingAnalyticsSuggestUtmMappingsSchema = MarketingAnalyticsSuggestUtmMappingsRetrieveQueryParams

const marketingAnalyticsSuggestUtmMappings = (): ToolBase<
    typeof MarketingAnalyticsSuggestUtmMappingsSchema,
    Schemas.UtmMappingSuggestionsResponse
> => ({
    name: 'marketing-analytics-suggest-utm-mappings',
    schema: MarketingAnalyticsSuggestUtmMappingsSchema,
    handler: async (context: Context, params: z.infer<typeof MarketingAnalyticsSuggestUtmMappingsSchema>) => {
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

const MarketingAnalyticsUpdateConversionGoalSchema = MarketingAnalyticsConversionGoalsUpdatePartialUpdateParams.omit({
    project_id: true,
}).extend(MarketingAnalyticsConversionGoalsUpdatePartialUpdateBody.shape)

const marketingAnalyticsUpdateConversionGoal = (): ToolBase<
    typeof MarketingAnalyticsUpdateConversionGoalSchema,
    Schemas.ConversionGoalWriteResponse
> => ({
    name: 'marketing-analytics-update-conversion-goal',
    schema: MarketingAnalyticsUpdateConversionGoalSchema,
    handler: async (context: Context, params: z.infer<typeof MarketingAnalyticsUpdateConversionGoalSchema>) => {
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

const MarketingAnalyticsUtmAuditSchema = MarketingAnalyticsUtmAuditRetrieveQueryParams

const marketingAnalyticsUtmAudit = (): ToolBase<typeof MarketingAnalyticsUtmAuditSchema, Schemas.UtmAuditResponse> => ({
    name: 'marketing-analytics-utm-audit',
    schema: MarketingAnalyticsUtmAuditSchema,
    handler: async (context: Context, params: z.infer<typeof MarketingAnalyticsUtmAuditSchema>) => {
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
