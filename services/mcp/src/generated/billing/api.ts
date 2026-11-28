/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 13 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * The billing API at /api/organizations/:organization_id/billing/, which names the organization instead of
 * following the user's current project.
 *
 * It shares that prefix with OrganizationBillingViewSet, which serves usage, spend and their exports at the same
 * paths in its own shapes, so this viewset leaves those reads to it.
 */
export const BillingOrganizationListParams = () => zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

export const BillingOrganizationListQueryParams = () => zod.object({
    include_forecasting: zod.boolean().nullish().describe('Whether to include usage forecasting.'),
    organization_id: zod.string().optional().describe('Explicit organization to refresh after payment.'),
})

/**
 * Read billing state for an organization: subscription, products, features and usage.
 *
 * The schema attributes every operation here to the billing product. Without that the route
 * puts them under organizations, and the MCP tool scaffold, which matches by product, drops
 * the billing tools that name them.
 * @summary Get the features the organization's plans include
 */
export const BillingFeaturesRetrieveParams = () => zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

/**
 * Read billing state for an organization: subscription, products, features and usage.
 *
 * The schema attributes every operation here to the billing product. Without that the route
 * puts them under organizations, and the MCP tool scaffold, which matches by product, drops
 * the billing tools that name them.
 * @summary Get the forecast for the rest of the billing period
 */
export const BillingForecastRetrieveParams = () => zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

/**
 * Read billing state for an organization: subscription, products, features and usage.
 *
 * The schema attributes every operation here to the billing product. Without that the route
 * puts them under organizations, and the MCP tool scaffold, which matches by product, drops
 * the billing tools that name them.
 * @summary Get the organization's spend limits
 */
export const BillingLimitsRetrieveParams = () => zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

/**
 * Read billing state for an organization: subscription, products, features and usage.
 *
 * The schema attributes every operation here to the billing product. Without that the route
 * puts them under organizations, and the MCP tool scaffold, which matches by product, drops
 * the billing tools that name them.
 * @summary Get one product
 */
export const BillingProductsRetrieveParams = () => zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
    product_key: zod.string().describe("The product's key."),
})

export const billingProductsRetrieveQueryIncludePlansDefault = false

export const BillingProductsRetrieveQueryParams = () => zod.object({
    include_plans: zod
        .boolean()
        .default(billingProductsRetrieveQueryIncludePlansDefault)
        .describe('Add the `plans` list to each product and add-on. Most of the payload.'),
})

/**
 * Read billing state for an organization: subscription, products, features and usage.
 *
 * The schema attributes every operation here to the billing product. Without that the route
 * puts them under organizations, and the MCP tool scaffold, which matches by product, drops
 * the billing tools that name them.
 * @summary Get every product in summary
 */
export const BillingProductsSummaryRetrieveParams = () => zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

/**
 * Every project the organization has reported usage for, deleted ones included, so a caller knows which ids a project breakdown or a team_ids filter can name. Below full billing access the list is the projects the caller can see.
 * @summary List the projects with usage
 */
export const BillingProjectListParams = () => zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

/**
 * Read billing state for an organization: subscription, products, features and usage.
 *
 * The schema attributes every operation here to the billing product. Without that the route
 * puts them under organizations, and the MCP tool scaffold, which matches by product, drops
 * the billing tools that name them.
 * @summary Get spend so far this billing period
 */
export const BillingSpendSummaryRetrieveParams = () => zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

/**
 * Read billing state for an organization: subscription, products, features and usage.
 *
 * The schema attributes every operation here to the billing product. Without that the route
 * puts them under organizations, and the MCP tool scaffold, which matches by product, drops
 * the billing tools that name them.
 * @summary Spend over time
 */
export const BillingSpendTimeseriesRetrieveParams = () => zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

export const billingSpendTimeseriesRetrieveQueryCursorMax = 512

export const billingSpendTimeseriesRetrieveQueryLimitMax = 1000

export const billingSpendTimeseriesRetrieveQueryTopProjectsMax = 200

export const BillingSpendTimeseriesRetrieveQueryParams = () => zod.object({
    breakdowns: zod
        .string()
        .nullish()
        .describe(
            'JSON-encoded array of breakdown dimensions. Valid values are \"type\" and \"team\", for example [\"type\",\"team\"]. Omit for a single aggregate series.'
        ),
    cursor: zod
        .string()
        .max(billingSpendTimeseriesRetrieveQueryCursorMax)
        .nullish()
        .describe("The cursor from a previous page's `next` link. Opaque. Ignored without `limit`."),
    end_date: zod
        .string()
        .nullish()
        .describe(
            'End date (YYYY-MM-DD, UTC), inclusive. Defaults to yesterday if both dates are omitted, or today if only start_date is provided.'
        ),
    interval: zod.string().nullish(),
    limit: zod
        .number()
        .min(1)
        .max(billingSpendTimeseriesRetrieveQueryLimitMax)
        .nullish()
        .describe(
            'Series per page, ranked by total, with a `next` link for the page after. Requires a project breakdown and is ignored without one. Omit it to get every series at once.'
        ),
    start_date: zod
        .string()
        .nullish()
        .describe(
            'Start date (YYYY-MM-DD, UTC), or \"all\" for 2020-01-01. If both dates are omitted, defaults to 30 days ago.'
        ),
    team_ids: zod
        .string()
        .nullish()
        .describe(
            'JSON-encoded array of numeric team\/project IDs to filter on, for example [1,2]. Omit for all projects available to the caller. Full billing-access callers can read all organization projects; member read-only callers are limited to visible projects and any project scope on their token.'
        ),
    top_projects: zod
        .number()
        .min(1)
        .max(billingSpendTimeseriesRetrieveQueryTopProjectsMax)
        .nullish()
        .describe(
            "With a project breakdown, return only this many highest-usage projects and fold the rest into a single 'all other projects' series, so the totals still reconcile. Omit it to get every project."
        ),
    usage_types: zod
        .string()
        .nullish()
        .describe(
            'JSON-encoded array of usage type identifiers to filter on. Valid values: event_count_in_period, exceptions_captured_in_period, recording_count_in_period, rows_synced_in_period, free_historical_rows_synced_in_period, survey_responses_count_in_period, mobile_recording_count_in_period, mobile_billable_recording_count_in_period, billable_feature_flag_requests_count_in_period, enhanced_persons_event_count_in_period, ai_event_count_in_period, cdp_billable_invocations_in_period, rows_exported_in_period, ai_credits_used_in_period, signals_credits_used_in_period, signals_spend_credits_used_in_period, posthog_code_credits_used_in_period, posthog_code_token_credits_used_in_period, sandbox_compute_credits_used_in_period, sandbox_compute_cpu_millicore_seconds_in_period, sandbox_compute_memory_mib_seconds_in_period, workflow_emails_sent_in_period, workflow_billable_invocations_in_period, logs_and_traces_mb_in_period, logs_mb_in_period, apm_tracing_mb_in_period, logs_retention_30d_mb_in_period, logs_retention_mb_days_in_period, replay_vision_credits_used_in_period, data_pipelines, group_analytics. E.g. [\"event_count_in_period\",\"recording_count_in_period\"]. Omit for all types.'
        ),
})

/**
 * Read billing state for an organization: subscription, products, features and usage.
 *
 * The schema attributes every operation here to the billing product. Without that the route
 * puts them under organizations, and the MCP tool scaffold, which matches by product, drops
 * the billing tools that name them.
 * @summary Get the organization's subscription
 */
export const BillingSubscriptionRetrieveParams = () => zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

/**
 * Read billing state for an organization: subscription, products, features and usage.
 *
 * The schema attributes every operation here to the billing product. Without that the route
 * puts them under organizations, and the MCP tool scaffold, which matches by product, drops
 * the billing tools that name them.
 * @summary Get usage so far this billing period
 */
export const BillingUsageSummaryRetrieveParams = () => zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

/**
 * What any member may know about usage: per product and add-on, the limit in effect,
 * whether usage is over or approaching it, and whether the resource is being limited right
 * now. The counts themselves are on `usage` and need usage read access.
 * @summary Get usage against limits, without the counts
 */
export const BillingUsageStatusRetrieveParams = () => zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

/**
 * Read billing state for an organization: subscription, products, features and usage.
 *
 * The schema attributes every operation here to the billing product. Without that the route
 * puts them under organizations, and the MCP tool scaffold, which matches by product, drops
 * the billing tools that name them.
 * @summary Usage over time
 */
export const BillingUsageTimeseriesRetrieveParams = () => zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

export const billingUsageTimeseriesRetrieveQueryCursorMax = 512

export const billingUsageTimeseriesRetrieveQueryLimitMax = 1000

export const billingUsageTimeseriesRetrieveQueryTopProjectsMax = 200

export const BillingUsageTimeseriesRetrieveQueryParams = () => zod.object({
    breakdowns: zod
        .string()
        .nullish()
        .describe(
            'JSON-encoded array of breakdown dimensions. Omit it for one series across the whole organization. Pass `[\"type\"]` for a series per product. Pass `[\"type\",\"team\"]` for a series per product per project. To break usage down by project, pass `\"type\"` with `\"team\"`: billing counts usage per product, and the counts do not add up across products.'
        ),
    cursor: zod
        .string()
        .max(billingUsageTimeseriesRetrieveQueryCursorMax)
        .nullish()
        .describe("The cursor from a previous page's `next` link. Opaque. Ignored without `limit`."),
    end_date: zod
        .string()
        .nullish()
        .describe(
            'End date (YYYY-MM-DD, UTC), inclusive. Defaults to yesterday if both dates are omitted, or today if only start_date is provided.'
        ),
    interval: zod.string().nullish(),
    limit: zod
        .number()
        .min(1)
        .max(billingUsageTimeseriesRetrieveQueryLimitMax)
        .nullish()
        .describe(
            'Series per page, ranked by total, with a `next` link for the page after. Requires a project breakdown and is ignored without one. Omit it to get every series at once.'
        ),
    start_date: zod
        .string()
        .nullish()
        .describe(
            'Start date (YYYY-MM-DD, UTC), or \"all\" for 2020-01-01. If both dates are omitted, defaults to 30 days ago.'
        ),
    team_ids: zod
        .string()
        .nullish()
        .describe(
            'JSON-encoded array of numeric team\/project IDs to filter on, for example [1,2]. Omit for all projects available to the caller. Full billing-access callers can read all organization projects; member read-only callers are limited to visible projects and any project scope on their token.'
        ),
    top_projects: zod
        .number()
        .min(1)
        .max(billingUsageTimeseriesRetrieveQueryTopProjectsMax)
        .nullish()
        .describe(
            "With a project breakdown, return only this many highest-usage projects and fold the rest into a single 'all other projects' series, so the totals still reconcile. Omit it to get every project."
        ),
    usage_types: zod
        .string()
        .nullish()
        .describe(
            'JSON-encoded array of usage type identifiers to filter on. Valid values: event_count_in_period, exceptions_captured_in_period, recording_count_in_period, rows_synced_in_period, free_historical_rows_synced_in_period, survey_responses_count_in_period, mobile_recording_count_in_period, mobile_billable_recording_count_in_period, billable_feature_flag_requests_count_in_period, enhanced_persons_event_count_in_period, ai_event_count_in_period, cdp_billable_invocations_in_period, rows_exported_in_period, ai_credits_used_in_period, signals_credits_used_in_period, signals_spend_credits_used_in_period, posthog_code_credits_used_in_period, posthog_code_token_credits_used_in_period, sandbox_compute_credits_used_in_period, sandbox_compute_cpu_millicore_seconds_in_period, sandbox_compute_memory_mib_seconds_in_period, workflow_emails_sent_in_period, workflow_billable_invocations_in_period, logs_and_traces_mb_in_period, logs_mb_in_period, apm_tracing_mb_in_period, logs_retention_30d_mb_in_period, logs_retention_mb_days_in_period, replay_vision_credits_used_in_period, data_pipelines, group_analytics. E.g. [\"event_count_in_period\",\"recording_count_in_period\"]. Omit for all types.'
        ),
})
