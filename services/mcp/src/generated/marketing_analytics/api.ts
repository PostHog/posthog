/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 7 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Read the configured conversion goals for the current project — each with its kind, target, last-30d count, integrated vs non-integrated split, and a misconfiguration flag. Read-only.
 * @summary List conversion goals
 */
export const MarketingAnalyticsConversionGoalsRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Check the platform → data-warehouse side of every native marketing integration: connection state, sync recency, row counts, required-table status, and schema-mapping coverage. Read-only.
 * @summary List marketing data sources
 */
export const MarketingAnalyticsDataSourcesRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const MarketingAnalyticsDataSourcesRetrieveQueryParams = /* @__PURE__ */ zod.object({
    source_type: zod.string().nullish().describe("Optional. Restrict to one integration (e.g. 'GoogleAds')."),
})

/**
 * Aggregate data-source sync health, UTM attribution health, and conversion-goal config into a single per-integration diagnostic with recommended actions. Read-only.
 * @summary Diagnose marketing analytics
 */
export const MarketingAnalyticsDiagnoseRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const marketingAnalyticsDiagnoseRetrieveQueryAttributionLookbackDaysDefault = 7
export const marketingAnalyticsDiagnoseRetrieveQueryAttributionLookbackDaysMax = 365

export const marketingAnalyticsDiagnoseRetrieveQueryIncludeConversionGoalsDefault = true

export const MarketingAnalyticsDiagnoseRetrieveQueryParams = /* @__PURE__ */ zod.object({
    attribution_lookback_days: zod
        .number()
        .min(1)
        .max(marketingAnalyticsDiagnoseRetrieveQueryAttributionLookbackDaysMax)
        .default(marketingAnalyticsDiagnoseRetrieveQueryAttributionLookbackDaysDefault)
        .describe('Lookback window for attribution health (1-365 days); defaults to 7'),
    include_conversion_goals: zod
        .boolean()
        .default(marketingAnalyticsDiagnoseRetrieveQueryIncludeConversionGoalsDefault)
        .describe('Whether to include the conversion-goal summary in the diagnostic'),
    source_type: zod.string().nullish().describe('Optional integration filter'),
})

/**
 * Break down a single conversion goal's events over a period by event name, utm_source, and matched integration, with a small sample of events. Read-only.
 * @summary Explain a conversion goal
 */
export const MarketingAnalyticsExplainConversionGoalRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const MarketingAnalyticsExplainConversionGoalRetrieveQueryParams = /* @__PURE__ */ zod.object({
    date_from: zod.string().nullish().describe('ISO start; defaults to 30 days ago'),
    date_to: zod.string().nullish().describe('ISO end; defaults to now'),
    goal_id: zod.string().min(1).describe('Id of the conversion goal to explain (from list_conversion_goals).'),
})

/**
 * Rank existing custom events as conversion-goal candidates by volume, UTM-tag coverage, and unique users, excluding system/autocaptured events. Read-only.
 * @summary Suggest conversion goals
 */
export const MarketingAnalyticsSuggestConversionGoalsRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const marketingAnalyticsSuggestConversionGoalsRetrieveQueryMinCountDefault = 50
export const marketingAnalyticsSuggestConversionGoalsRetrieveQueryTopNDefault = 10

export const MarketingAnalyticsSuggestConversionGoalsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    min_count: zod
        .number()
        .default(marketingAnalyticsSuggestConversionGoalsRetrieveQueryMinCountDefault)
        .describe('Minimum 30d event count to be a candidate'),
    top_n: zod
        .number()
        .default(marketingAnalyticsSuggestConversionGoalsRetrieveQueryTopNDefault)
        .describe('Max candidates to return'),
})

/**
 * Detect unmatched utm_source values from recent events and propose custom_source_mappings entries, alongside the full utm_source catalogue and current mappings. Read-only.
 * @summary Suggest UTM source mappings
 */
export const MarketingAnalyticsSuggestUtmMappingsRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const marketingAnalyticsSuggestUtmMappingsRetrieveQueryLookbackDaysDefault = 90
export const marketingAnalyticsSuggestUtmMappingsRetrieveQueryLookbackDaysMax = 365

export const marketingAnalyticsSuggestUtmMappingsRetrieveQueryMinEventCountDefault = 10

export const MarketingAnalyticsSuggestUtmMappingsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    lookback_days: zod
        .number()
        .min(1)
        .max(marketingAnalyticsSuggestUtmMappingsRetrieveQueryLookbackDaysMax)
        .default(marketingAnalyticsSuggestUtmMappingsRetrieveQueryLookbackDaysDefault)
        .describe('Days of history to inspect (1-365); defaults to 90'),
    min_event_count: zod
        .number()
        .default(marketingAnalyticsSuggestUtmMappingsRetrieveQueryMinEventCountDefault)
        .describe('Only suggest for raw values with >= this many events'),
})

/**
 * Cross-reference campaigns with spend from ad platforms against pageview events with UTM parameters to identify tracking issues.
 * @summary Run UTM audit
 */
export const MarketingAnalyticsUtmAuditRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const marketingAnalyticsUtmAuditRetrieveQueryDateFromDefault = `-30d`

export const MarketingAnalyticsUtmAuditRetrieveQueryParams = /* @__PURE__ */ zod.object({
    date_from: zod
        .string()
        .min(1)
        .default(marketingAnalyticsUtmAuditRetrieveQueryDateFromDefault)
        .describe('Start date for the audit period'),
    date_to: zod.string().nullish().describe('End date for the audit period'),
})
