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

const MarketingAnalyticsConversionGoalsRetrieveSchema = z.object({})

const marketingAnalyticsConversionGoalsRetrieve = (): ToolBase<
    typeof MarketingAnalyticsConversionGoalsRetrieveSchema,
    Schemas.ConversionGoalsListResponse
> => ({
    name: 'marketing-analytics-conversion-goals-retrieve',
    schema: MarketingAnalyticsConversionGoalsRetrieveSchema,
    // eslint-disable-next-line no-unused-vars
    handler: async (context: Context, params: z.infer<typeof MarketingAnalyticsConversionGoalsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ConversionGoalsListResponse>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/marketing_analytics/conversion_goals/`,
        })
        return result
    },
})

const MarketingAnalyticsDataSourcesRetrieveSchema = MarketingAnalyticsDataSourcesRetrieveQueryParams

const marketingAnalyticsDataSourcesRetrieve = (): ToolBase<
    typeof MarketingAnalyticsDataSourcesRetrieveSchema,
    Schemas.DataSourceHealthResponse
> => ({
    name: 'marketing-analytics-data-sources-retrieve',
    schema: MarketingAnalyticsDataSourcesRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof MarketingAnalyticsDataSourcesRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.DataSourceHealthResponse>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/marketing_analytics/data_sources/`,
            query: {
                source_type: params.source_type,
            },
        })
        return result
    },
})

const MarketingAnalyticsDiagnoseRetrieveSchema = MarketingAnalyticsDiagnoseRetrieveQueryParams

const marketingAnalyticsDiagnoseRetrieve = (): ToolBase<
    typeof MarketingAnalyticsDiagnoseRetrieveSchema,
    Schemas.MarketingDiagnosticResponse
> => ({
    name: 'marketing-analytics-diagnose-retrieve',
    schema: MarketingAnalyticsDiagnoseRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof MarketingAnalyticsDiagnoseRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.MarketingDiagnosticResponse>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/marketing_analytics/diagnose/`,
            query: {
                attribution_lookback_days: params.attribution_lookback_days,
                include_conversion_goals: params.include_conversion_goals,
                source_type: params.source_type,
            },
        })
        return result
    },
})

const MarketingAnalyticsExplainConversionGoalRetrieveSchema = MarketingAnalyticsExplainConversionGoalRetrieveQueryParams

const marketingAnalyticsExplainConversionGoalRetrieve = (): ToolBase<
    typeof MarketingAnalyticsExplainConversionGoalRetrieveSchema,
    Schemas.GoalExplanation
> => ({
    name: 'marketing-analytics-explain-conversion-goal-retrieve',
    schema: MarketingAnalyticsExplainConversionGoalRetrieveSchema,
    handler: async (
        context: Context,
        params: z.infer<typeof MarketingAnalyticsExplainConversionGoalRetrieveSchema>
    ) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.GoalExplanation>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/marketing_analytics/explain_conversion_goal/`,
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
            path: `/api/environments/${encodeURIComponent(String(projectId))}/marketing_analytics/suggest_conversion_goals/`,
            query: {
                min_count: params.min_count,
                top_n: params.top_n,
            },
        })
        return result
    },
})

const MarketingAnalyticsSuggestUtmMappingsRetrieveSchema = MarketingAnalyticsSuggestUtmMappingsRetrieveQueryParams

const marketingAnalyticsSuggestUtmMappingsRetrieve = (): ToolBase<
    typeof MarketingAnalyticsSuggestUtmMappingsRetrieveSchema,
    Schemas.UtmMappingSuggestionsResponse
> => ({
    name: 'marketing-analytics-suggest-utm-mappings-retrieve',
    schema: MarketingAnalyticsSuggestUtmMappingsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof MarketingAnalyticsSuggestUtmMappingsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.UtmMappingSuggestionsResponse>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/marketing_analytics/suggest_utm_mappings/`,
            query: {
                lookback_days: params.lookback_days,
                min_event_count: params.min_event_count,
            },
        })
        return result
    },
})

const MarketingAnalyticsUtmAuditRetrieveSchema = MarketingAnalyticsUtmAuditRetrieveQueryParams

const marketingAnalyticsUtmAuditRetrieve = (): ToolBase<
    typeof MarketingAnalyticsUtmAuditRetrieveSchema,
    Schemas.UtmAuditResponse
> => ({
    name: 'marketing-analytics-utm-audit-retrieve',
    schema: MarketingAnalyticsUtmAuditRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof MarketingAnalyticsUtmAuditRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.UtmAuditResponse>({
            method: 'GET',
            path: `/api/environments/${encodeURIComponent(String(projectId))}/marketing_analytics/utm_audit/`,
            query: {
                date_from: params.date_from,
                date_to: params.date_to,
            },
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'marketing-analytics-conversion-goals-retrieve': marketingAnalyticsConversionGoalsRetrieve,
    'marketing-analytics-data-sources-retrieve': marketingAnalyticsDataSourcesRetrieve,
    'marketing-analytics-diagnose-retrieve': marketingAnalyticsDiagnoseRetrieve,
    'marketing-analytics-explain-conversion-goal-retrieve': marketingAnalyticsExplainConversionGoalRetrieve,
    'marketing-analytics-suggest-conversion-goals': marketingAnalyticsSuggestConversionGoals,
    'marketing-analytics-suggest-utm-mappings-retrieve': marketingAnalyticsSuggestUtmMappingsRetrieve,
    'marketing-analytics-utm-audit-retrieve': marketingAnalyticsUtmAuditRetrieve,
}
