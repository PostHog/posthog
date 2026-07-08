// AUTO-GENERATED from products/marketing_analytics/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
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
    'marketing-analytics-data-sources': marketingAnalyticsDataSources,
    'marketing-analytics-diagnose': marketingAnalyticsDiagnose,
    'marketing-analytics-explain-conversion-goal': marketingAnalyticsExplainConversionGoal,
    'marketing-analytics-suggest-conversion-goals': marketingAnalyticsSuggestConversionGoals,
    'marketing-analytics-suggest-utm-mappings': marketingAnalyticsSuggestUtmMappings,
    'marketing-analytics-utm-audit': marketingAnalyticsUtmAudit,
}
